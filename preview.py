"""Local, read-only browser preview for the Chatime newsletter.

This module deliberately has no route that sends email. It loads the same
Google Sheet data as the production newsletter, renders both email variants,
and serves them only on the loopback interface.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from string import Template as StringTemplate
from typing import Dict, Optional
from urllib.parse import parse_qs, quote, unquote, urlparse

import requests
from dotenv import load_dotenv
from jinja2 import Environment, StrictUndefined

from main import Newsletter


BASE_DIR = Path(__file__).resolve().parent
LOCAL_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
VARIANTS = {
    "standard": "Standard",
    "spark": "Spark / Outlook",
}


class PreviewConfigurationError(RuntimeError):
    """Raised when the read-only preview configuration is incomplete."""


class PreviewNewsletter(Newsletter):
    """Newsletter variant with a hard stop on all email sending."""

    def send_email(self, *args, **kwargs):
        raise RuntimeError("Email sending is disabled in local preview mode.")


@dataclass(frozen=True)
class PreviewConfig:
    sheet_id: str
    sheet_name: str
    background_url: str
    first_edition_date: str = "2024/03/01"
    frequency_unit: str = "month"
    frequency: int = 1
    timezone: str = "Pacific/Auckland"
    num_images: int = 3

    @classmethod
    def from_environment(cls) -> "PreviewConfig":
        required = {
            "SHEET_ID": os.getenv("SHEET_ID", "").strip(),
            "SHEET_NAME": os.getenv("SHEET_NAME", "").strip(),
            "BACKGROUND_URL": os.getenv("BACKGROUND_URL", "").strip(),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise PreviewConfigurationError(
                "Missing preview setting(s): " + ", ".join(sorted(missing))
            )

        try:
            num_images = int(os.getenv("NEWSLETTER_NUM_IMAGES", "3"))
            frequency = int(os.getenv("NEWSLETTER_FREQUENCY", "1"))
        except ValueError as error:
            raise PreviewConfigurationError(
                "NEWSLETTER_NUM_IMAGES and NEWSLETTER_FREQUENCY must be whole numbers."
            ) from error

        return cls(
            sheet_id=required["SHEET_ID"],
            sheet_name=required["SHEET_NAME"],
            background_url=required["BACKGROUND_URL"],
            first_edition_date=os.getenv(
                "NEWSLETTER_FIRST_EDITION_DATE", "2024/03/01"
            ).strip(),
            frequency_unit=os.getenv(
                "NEWSLETTER_FREQUENCY_UNIT", "month"
            ).strip(),
            frequency=frequency,
            timezone=os.getenv(
                "NEWSLETTER_TIMEZONE", "Pacific/Auckland"
            ).strip(),
            num_images=num_images,
        )


@dataclass(frozen=True)
class PreviewSnapshot:
    standard_html: str
    spark_html: str
    loaded_at: str
    edition_number: int
    response_count: int
    question_mode: str

    def html_for(self, variant: str) -> str:
        return self.spark_html if variant == "spark" else self.standard_html


def _placeholder_image_data_uri() -> str:
    svg = """<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
<rect width="960" height="540" fill="#faf5f1"/>
<rect x="1" y="1" width="958" height="538" fill="none" stroke="#eee6de" stroke-width="2"/>
<text x="480" y="255" text-anchor="middle" fill="#133f63" font-family="Georgia,serif" font-size="28" font-weight="700">Preview image unavailable</text>
<text x="480" y="300" text-anchor="middle" fill="#6f6a65" font-family="Georgia,serif" font-size="18">The newsletter will skip an image it cannot load.</text>
</svg>"""
    encoded = base64.b64encode(svg.encode("utf8")).decode("ascii")
    return "data:image/svg+xml;base64," + encoded


PLACEHOLDER_IMAGE = _placeholder_image_data_uri()
PLACEHOLDER_IMAGE_BYTES = base64.b64decode(PLACEHOLDER_IMAGE.split(",", 1)[1])


def _drive_file_id(url: str) -> Optional[str]:
    normalized = html.unescape(str(url)).strip()
    match = re.search(r"[?&]id=([^&]+)", normalized) or re.search(
        r"/d/([^/]+)", normalized
    )
    if not match:
        return None
    file_id = match.group(1)
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", file_id):
        return None
    return file_id


def _proxy_drive_image_sources(rendered_html: str) -> str:
    """Use same-origin image URLs so Drive photos display in the browser."""

    def replace_source(match):
        file_id = _drive_file_id(match.group("url"))
        if not file_id:
            return match.group(0)
        return "{}{}{}".format(
            match.group("prefix"),
            "/image/" + quote(file_id, safe=""),
            match.group("quote"),
        )

    return re.sub(
        r"(?P<prefix>\bsrc\s*=\s*(?P<quote>['\"]))(?P<url>[^'\"]+)(?P=quote)",
        replace_source,
        rendered_html,
        flags=re.IGNORECASE,
    )


def _render_templates(newsletter: PreviewNewsletter) -> Dict[str, str]:
    """Render sheet content with browser-safe HTML escaping enabled."""
    environment = Environment(autoescape=True, undefined=StrictUndefined)
    rendered = {}
    for variant, filename in (
        ("standard", "template.html"),
        ("spark", "template_spark.html"),
    ):
        source = (BASE_DIR / filename).read_text(encoding="utf8")
        rendered[variant] = environment.from_string(source).render(
            newsletter.email_data
        )
    return rendered


def _question_cid_sources(newsletter: PreviewNewsletter) -> Dict[str, str]:
    sources = {}
    if newsletter.email_data.get("question_mode") != "diyl_gif":
        return sources

    for answer in newsletter.email_data.get("question_answers", []):
        if len(answer) < 4:
            continue
        name = str(answer[0]).strip()
        cid = str(answer[1])
        links = answer[3]
        intro_text = "Day in my life: " + name if name else "Day in my life"
        gif_bytes = newsletter._make_gif_bytes(
            links,
            max_image_byte=8.0,
            intro_text=intro_text,
        )
        if gif_bytes:
            encoded = base64.b64encode(gif_bytes).decode("ascii")
            sources[cid] = "data:image/gif;base64," + encoded
        else:
            sources[cid] = PLACEHOLDER_IMAGE
    return sources


def _replace_browser_cids(
    rendered_html: str,
    newsletter: PreviewNewsletter,
    question_sources: Optional[Dict[str, str]] = None,
) -> str:
    """Replace email-only CID references with browser-viewable sources."""
    image_sources = [newsletter.background_url]
    image_sources.extend(
        picture[0] for picture in newsletter.email_data.get("images", [])
    )

    def replace_image(match):
        index = int(match.group(1))
        source = image_sources[index] if index < len(image_sources) else ""
        return html.escape(source, quote=True) if source else PLACEHOLDER_IMAGE

    browser_html = re.sub(r"cid:image(\d+)", replace_image, rendered_html)

    for cid, source in (question_sources or {}).items():
        browser_html = browser_html.replace(
            "cid:" + cid,
            html.escape(source, quote=True),
        )

    # Never leave an email-only source broken in the browser preview.
    browser_html = re.sub(
        r"cid:[^\"'\s>]+",
        PLACEHOLDER_IMAGE,
        browser_html,
    )
    return _proxy_drive_image_sources(browser_html)


def build_snapshot(config: PreviewConfig) -> PreviewSnapshot:
    """Fetch live form responses and build both read-only preview variants."""
    newsletter = PreviewNewsletter(
        config.first_edition_date,
        config.frequency_unit,
        config.frequency,
        config.timezone,
        sender=None,
        recipients=[],
        recipients_spark=[],
        password=None,
        sheet_id=config.sheet_id,
        sheet_name=config.sheet_name,
        background_url=config.background_url,
        special_edition=True,
        num_images=config.num_images,
    )
    newsletter.generate_newsletter(update_edition=False)

    rendered = _render_templates(newsletter)
    question_sources = _question_cid_sources(newsletter)
    standard_html = _replace_browser_cids(
        rendered["standard"], newsletter, question_sources
    )
    spark_html = _replace_browser_cids(
        rendered["spark"], newsletter, question_sources
    )

    if "cid:" in standard_html or "cid:" in spark_html:
        raise RuntimeError("A browser-incompatible image reference remains.")

    return PreviewSnapshot(
        standard_html=standard_html,
        spark_html=spark_html,
        loaded_at=newsletter.datetime_now.strftime("%A, %B %d at %I:%M %p %Z"),
        edition_number=int(newsletter.email_data["edition_number"]),
        response_count=len(newsletter.data_df.index),
        question_mode=str(newsletter.email_data.get("question_mode", "text")),
    )


class PreviewState:
    def __init__(self, config: PreviewConfig):
        self.config = config
        self._snapshot = None
        self._lock = threading.Lock()
        self._image_cache = {}
        self._image_lock = threading.Lock()

    def get_snapshot(self, refresh: bool = False) -> PreviewSnapshot:
        with self._lock:
            if refresh or self._snapshot is None:
                self._snapshot = build_snapshot(self.config)
            return self._snapshot

    def get_image(self, file_id: str):
        """Fetch and cache one explicitly identified Google Drive image."""
        if not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", file_id):
            raise ValueError("Invalid Drive file ID")

        with self._image_lock:
            cached = self._image_cache.get(file_id)
        if cached:
            return cached

        response = requests.get(
            "https://drive.google.com/uc?export=view&id=" + file_id,
            timeout=30,
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
        if not content_type.startswith("image/"):
            raise ValueError("Drive file is not an image")
        if len(response.content) > 50 * 1024 * 1024:
            raise ValueError("Drive image is too large for the local preview")

        image = (content_type, response.content)
        with self._image_lock:
            self._image_cache[file_id] = image
        return image


def _dashboard_html(snapshot: PreviewSnapshot, variant: str) -> str:
    variant_label = VARIANTS[variant]
    buttons = []
    for value, label in VARIANTS.items():
        selected = " selected" if value == variant else ""
        buttons.append(
            '<a class="tab{}" href="/?variant={}">{}</a>'.format(
                selected,
                quote(value),
                html.escape(label),
            )
        )

    email_url = "/email?variant=" + quote(variant)
    status = (
        "Issue No. {} · {} responses · loaded {} · {} mode"
    ).format(
        snapshot.edition_number,
        snapshot.response_count,
        snapshot.loaded_at,
        snapshot.question_mode,
    )
    template = StringTemplate("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Chatime Newsletter local preview</title>
    <style>
        * { box-sizing: border-box; }
        html, body { height: 100%; margin: 0; }
        body { background: #ebe7e2; color: #17202a; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
        .toolbar { align-items: center; background: #ffffff; border-bottom: 1px solid #d9d3cc; display: flex; flex-wrap: wrap; gap: 10px 14px; min-height: 76px; padding: 12px 18px; }
        .identity { margin-right: auto; min-width: 240px; }
        .eyebrow { color: #133f63; font-size: 11px; font-weight: 800; letter-spacing: 1.3px; margin: 0 0 3px; text-transform: uppercase; }
        h1 { font-size: 17px; line-height: 1.25; margin: 0; }
        .status { color: #69635e; font-size: 12px; line-height: 1.35; margin: 3px 0 0; }
        .tabs { display: flex; gap: 6px; }
        .tab, .action { border: 1px solid #cfc8c1; border-radius: 7px; color: #133f63; font-size: 13px; font-weight: 700; padding: 8px 11px; text-decoration: none; }
        .tab.selected { background: #133f63; border-color: #133f63; color: #ffffff; }
        .action { background: #faf5f1; }
        .notice { background: #fff7dd; border-bottom: 1px solid #eadcae; color: #5c4b17; font-size: 12px; padding: 7px 18px; text-align: center; }
        iframe { background: #f3eee8; border: 0; display: block; height: calc(100vh - 107px); width: 100%; }
        @media (max-width: 720px) {
            .toolbar { align-items: flex-start; padding: 11px 12px; }
            .identity { flex-basis: 100%; }
            .tabs { order: 2; }
            .status { white-space: normal; }
            iframe { height: calc(100vh - 154px); }
        }
    </style>
</head>
<body>
    <header class="toolbar">
        <div class="identity">
            <p class="eyebrow">Local preview · Sending disabled</p>
            <h1>Chatime Newsletter — $variant_label</h1>
            <p class="status">$status</p>
        </div>
        <nav class="tabs" aria-label="Preview variant">$buttons</nav>
        <a class="action" href="/?variant=$variant&amp;refresh=1">Reload live data</a>
        <a class="action" href="$email_url" target="_blank" rel="noopener">Open email only</a>
    </header>
    <div class="notice">This page only reads the sheet. It cannot send email or advance the edition counter.</div>
    <iframe title="Rendered newsletter" src="$email_url" sandbox=""></iframe>
</body>
</html>""")
    return template.substitute(
        variant_label=html.escape(variant_label),
        status=html.escape(status),
        buttons="".join(buttons),
        variant=quote(variant),
        email_url=html.escape(email_url, quote=True),
    )


def _error_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Newsletter preview unavailable</title>
    <style>
        body { background:#f3eee8; color:#000; font-family:Georgia,serif; margin:0; padding:40px 20px; }
        main { background:#fff; border-top:4px solid #133f63; border-radius:12px; margin:0 auto; max-width:620px; padding:32px; }
        h1 { margin-top:0; }
        p { font-size:16px; line-height:1.5; }
        a { color:#133f63; font-weight:700; }
        code { background:#faf5f1; border-radius:4px; padding:2px 5px; }
    </style>
</head>
<body>
    <main>
        <h1>Couldn’t load the live newsletter</h1>
        <p>Check <code>SHEET_ID</code>, <code>SHEET_NAME</code>, <code>BACKGROUND_URL</code>, the sheet’s sharing settings, and your network connection.</p>
        <p>No email was sent and the edition counter was not changed.</p>
        <p><a href="/?refresh=1">Try again</a></p>
    </main>
</body>
</html>"""


def create_handler(state: PreviewState):
    class PreviewRequestHandler(BaseHTTPRequestHandler):
        server_version = "ChatimePreview/1.0"

        def do_GET(self):
            self._dispatch(send_body=True)

        def do_HEAD(self):
            self._dispatch(send_body=False)

        def do_POST(self):
            self._write(
                HTTPStatus.METHOD_NOT_ALLOWED,
                "Method not allowed",
                "text/plain; charset=utf-8",
                send_body=True,
            )

        def _dispatch(self, send_body: bool):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)

            if parsed.path == "/favicon.ico":
                self._write(
                    HTTPStatus.NO_CONTENT,
                    "",
                    "text/plain; charset=utf-8",
                    send_body,
                )
                return

            if parsed.path in ("/health", "/healthz"):
                body = json.dumps(
                    {"status": "ok", "email_sending": "disabled"}
                )
                self._write(
                    HTTPStatus.OK,
                    body,
                    "application/json; charset=utf-8",
                    send_body,
                )
                return

            if parsed.path.startswith("/image/"):
                file_id = unquote(parsed.path.removeprefix("/image/"))
                if not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", file_id):
                    self._write(
                        HTTPStatus.NOT_FOUND,
                        "Not found",
                        "text/plain; charset=utf-8",
                        send_body,
                    )
                    return
                try:
                    content_type, payload = state.get_image(file_id)
                    status = HTTPStatus.OK
                except Exception as error:
                    print(
                        "Preview image unavailable: {}".format(
                            type(error).__name__
                        )
                    )
                    content_type = "image/svg+xml"
                    payload = PLACEHOLDER_IMAGE_BYTES
                    status = HTTPStatus.BAD_GATEWAY
                self._write_bytes(
                    status,
                    payload,
                    content_type,
                    send_body,
                    image_document=True,
                )
                return

            if parsed.path not in ("/", "/email"):
                self._write(
                    HTTPStatus.NOT_FOUND,
                    "Not found",
                    "text/plain; charset=utf-8",
                    send_body,
                )
                return

            variant = query.get("variant", ["standard"])[0]
            if variant not in VARIANTS:
                self._write(
                    HTTPStatus.BAD_REQUEST,
                    "Unknown preview variant",
                    "text/plain; charset=utf-8",
                    send_body,
                )
                return

            refresh = query.get("refresh", ["0"])[0] == "1"
            try:
                snapshot = state.get_snapshot(refresh=refresh)
            except Exception as error:
                print("Preview refresh failed: {}".format(type(error).__name__))
                self._write(
                    HTTPStatus.BAD_GATEWAY,
                    _error_html(),
                    "text/html; charset=utf-8",
                    send_body,
                    email_document=True,
                )
                return

            if parsed.path == "/email":
                self._write(
                    HTTPStatus.OK,
                    snapshot.html_for(variant),
                    "text/html; charset=utf-8",
                    send_body,
                    email_document=True,
                )
                return

            self._write(
                HTTPStatus.OK,
                _dashboard_html(snapshot, variant),
                "text/html; charset=utf-8",
                send_body,
            )

        def _write(
            self,
            status: HTTPStatus,
            body: str,
            content_type: str,
            send_body: bool,
            email_document: bool = False,
        ):
            payload = body.encode("utf8")
            self.send_response(status.value)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if email_document:
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'none'; img-src 'self' https: data:; "
                    "style-src 'unsafe-inline' https://fonts.googleapis.com; "
                    "font-src https://fonts.gstatic.com; script-src 'none'; "
                    "object-src 'none'; base-uri 'none'; form-action 'none'; "
                    "frame-ancestors 'self'",
                )
            else:
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; style-src 'unsafe-inline'; "
                    "img-src 'self' data:; script-src 'none'; object-src 'none'; "
                    "base-uri 'none'; form-action 'none'; frame-src 'self'",
                )
            self.end_headers()
            if send_body:
                self.wfile.write(payload)

        def _write_bytes(
            self,
            status: HTTPStatus,
            payload: bytes,
            content_type: str,
            send_body: bool,
            image_document: bool = False,
        ):
            self.send_response(status.value)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if image_document:
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'none'; sandbox",
                )
            self.end_headers()
            if send_body:
                self.wfile.write(payload)

        def log_message(self, message_format, *args):
            print("Preview: " + (message_format % args))

    return PreviewRequestHandler


class LocalPreviewServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="View the live Chatime newsletter locally without sending it."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="Local port to use (default: %(default)s).",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    load_dotenv(BASE_DIR / ".env")
    try:
        config = PreviewConfig.from_environment()
    except PreviewConfigurationError as error:
        raise SystemExit("Preview configuration error: " + str(error))

    state = PreviewState(config)
    server = LocalPreviewServer(
        (LOCAL_HOST, args.port),
        create_handler(state),
    )
    print("Chatime newsletter preview: http://{}:{}".format(LOCAL_HOST, args.port))
    print("Local preview only — email sending is disabled.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPreview stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
