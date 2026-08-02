import os
import re
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import main
import preview


class EditionNumberTests(unittest.TestCase):
    def test_read_only_edition_does_not_change_existing_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            log_path = base_dir / "log.txt"
            log_path.write_text("26", encoding="utf8")
            before = (log_path.read_bytes(), log_path.stat().st_mtime_ns)

            with mock.patch.object(main, "BASE_DIR", base_dir):
                self.assertEqual(main.edition_number(update_log=False), 27)

            after = (log_path.read_bytes(), log_path.stat().st_mtime_ns)
            self.assertEqual(after, before)

    def test_read_only_edition_does_not_create_missing_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            log_path = base_dir / "log.txt"

            with mock.patch.object(main, "BASE_DIR", base_dir):
                self.assertEqual(main.edition_number(update_log=False), 1)

            self.assertFalse(log_path.exists())

    def test_production_edition_still_persists_increment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            log_path = base_dir / "log.txt"
            log_path.write_text("26", encoding="utf8")

            with mock.patch.object(main, "BASE_DIR", base_dir):
                self.assertEqual(main.edition_number(), 27)

            self.assertEqual(log_path.read_text(encoding="utf8"), "27")


class NewsletterDataFilterTests(unittest.TestCase):
    def test_sheet_dates_are_parsed_day_first(self):
        fixed_now = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)

        class FixedDatetime:
            @classmethod
            def now(cls, tz):
                return fixed_now.astimezone(tz)

        responses = main.pd.DataFrame(
            {
                "Timestamp": [
                    "01/08/2026 12:00:00",
                    "08/01/2026 12:00:00",
                ]
            }
        )
        with mock.patch.object(main, "datetime", FixedDatetime), mock.patch.object(
            main.pd,
            "read_csv",
            return_value=responses,
        ):
            newsletter = main.Newsletter(
                "2024/03/01",
                "month",
                1,
                "Pacific/Auckland",
                sender=None,
                recipients=[],
                recipients_spark=[],
                password=None,
                sheet_id="sheet-id",
                sheet_name="Form Responses 1",
                background_url="https://example.test/cover.jpg",
            )

        self.assertEqual(
            newsletter.data_df["Timestamp"].tolist(),
            ["01/08/2026 12:00:00"],
        )


class PreviewRenderingTests(unittest.TestCase):
    def _template_context(self):
        return {
            "question_title": "Question sentinel",
            "question_answers": [
                ("Question Name A", "Question Answer A"),
                ("Question Name B", "Question Answer B"),
            ],
            "question_mode": "text",
            "life_updates": [("Life Name", "Life Answer")],
            "one_good_thing": [("Good Name", "Good Answer")],
            "food_spot": [("Food Name", "Food Answer")],
            "confessions": [("Confession Name", "Confession Answer")],
            "images": [
                ["https://example.test/photo-a.jpg", "Photo Name A", "Photo Caption A"],
                ["https://example.test/photo-b.jpg", "Photo Name B", "Photo Caption B"],
            ],
            "date": datetime(2026, 8, 2, tzinfo=timezone.utc),
            "next_date": datetime(2026, 9, 2, tzinfo=timezone.utc),
            "edition_number": 98765,
            "background_url": "https://example.test/cover.jpg",
        }

    def _render_live_templates(self, context=None):
        newsletter = SimpleNamespace(
            email_data=context or self._template_context()
        )
        return preview._render_templates(newsletter)

    def test_config_does_not_require_email_credentials(self):
        environment = {
            "SHEET_ID": "sheet-id",
            "SHEET_NAME": "Form Responses 1",
            "BACKGROUND_URL": "https://example.test/cover.jpg",
        }
        with mock.patch.dict(os.environ, environment, clear=True):
            config = preview.PreviewConfig.from_environment()

        self.assertEqual(config.sheet_id, "sheet-id")
        self.assertEqual(config.num_images, 3)

    def test_templates_escape_sheet_content_for_browser(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            source = "<p>{{ answer }}</p>"
            (base_dir / "template.html").write_text(source, encoding="utf8")
            (base_dir / "template_spark.html").write_text(source, encoding="utf8")
            newsletter = SimpleNamespace(
                email_data={"answer": "<script>alert(1)</script>"}
            )

            with mock.patch.object(preview, "BASE_DIR", base_dir):
                rendered = preview._render_templates(newsletter)

        self.assertIn("&lt;script&gt;", rendered["standard"])
        self.assertNotIn("<script>", rendered["spark"])

    def test_refreshed_templates_preserve_all_dynamic_content(self):
        rendered = self._render_live_templates()
        sentinels = (
            "Question sentinel",
            "Question Name A",
            "Question Answer B",
            "Life Answer",
            "Good Answer",
            "Food Answer",
            "Confession Answer",
            "Photo Name A",
            "Photo Caption B",
            "Issue No. 98765",
            "Sunday, August 02",
            "Wednesday, September 02",
        )

        for variant, document in rendered.items():
            for sentinel in sentinels:
                self.assertIn(sentinel, document, msg=variant)
            self.assertNotRegex(document, r"{[{%]")
            self.assertNotIn("Issue No. XX", document)
            self.assertNotIn("sample.svg", document)

    def test_standard_and_spark_image_mappings_match_attachments(self):
        rendered = self._render_live_templates()
        pattern = r'<img\b[^>]*\bsrc="([^"]+)"'
        standard_sources = re.findall(pattern, rendered["standard"])
        spark_sources = re.findall(pattern, rendered["spark"])

        self.assertEqual(
            standard_sources,
            [
                "https://example.test/cover.jpg",
                "https://example.test/photo-a.jpg",
                "https://example.test/photo-b.jpg",
            ],
        )
        self.assertEqual(
            spark_sources,
            ["cid:image0", "cid:image1", "cid:image2"],
        )
        self.assertEqual(
            rendered["standard"].count('class="photo-card"'),
            2,
        )
        self.assertEqual(
            rendered["spark"].count('class="photo-card"'),
            2,
        )

    def test_question_names_and_responses_share_one_line(self):
        rendered = self._render_live_templates()

        for variant, document in rendered.items():
            self.assertRegex(
                document,
                r'Question Name A</span>:\s+Question Answer A',
                msg=variant,
            )
            self.assertNotRegex(
                document,
                r'Question Name A</p>\s*<p[^>]*>Question Answer A',
                msg=variant,
            )

    def test_photo_names_and_captions_use_separate_lines(self):
        rendered = self._render_live_templates()

        for variant, document in rendered.items():
            self.assertRegex(
                document,
                r'Photo Name A</p>\s*<p[^>]*>Photo Caption A',
                msg=variant,
            )
            self.assertNotRegex(
                document,
                r'Photo Name A</span>:\s+Photo Caption A',
                msg=variant,
            )

    def test_diyl_cids_and_descriptions_are_preserved(self):
        context = self._template_context()
        context["question_mode"] = "diyl_gif"
        context["question_answers"] = [
            (
                "DIYL Name",
                "questiongif7",
                "Morning & coffee\nEvening walk",
                ["https://example.test/day-1.jpg"],
            )
        ]
        context["images"] = []

        rendered = self._render_live_templates(context)

        for document in rendered.values():
            self.assertIn('src="cid:questiongif7"', document)
            self.assertIn("DIYL Name", document)
            self.assertIn("Morning &amp; coffee<br>Evening walk", document)

    def test_templates_keep_mockup_palette_type_and_uncropped_images(self):
        for filename in ("template.html", "template_spark.html"):
            source = (preview.BASE_DIR / filename).read_text(encoding="utf8")
            for color in ("#f3eee8", "#faf5f1", "#133f63", "#eee6de"):
                self.assertIn(color, source, msg=filename)
            self.assertIn("Source Serif 4", source, msg=filename)
            self.assertIn("Georgia", source, msg=filename)
            self.assertIn("@media screen and (max-width: 632px)", source)
            self.assertIn("height: auto !important", source)
            self.assertIn("width: 100% !important", source)
            self.assertNotIn("object-fit", source)
            self.assertNotIn("max-height: 560px", source)
            self.assertNotIn("max-height: 500px", source)

    def test_email_cids_are_replaced_for_browser(self):
        newsletter = SimpleNamespace(
            background_url="https://example.test/cover.jpg",
            email_data={
                "images": [
                    ["https://example.test/photo.jpg?a=1&b=2", "A", "Caption"]
                ]
            },
        )
        rendered = (
            '<img src="cid:image0"><img src="cid:image1">'
            '<img src="cid:questiongif0">'
        )
        result = preview._replace_browser_cids(
            rendered,
            newsletter,
            {"questiongif0": "data:image/gif;base64,R0lG"},
        )

        self.assertNotIn("cid:", result)
        self.assertIn("cover.jpg", result)
        self.assertIn("a=1&amp;b=2", result)
        self.assertIn("data:image/gif;base64,R0lG", result)

    def test_drive_images_use_the_local_image_route(self):
        drive_id = "1bKIKBOzyq7LjG0mKRpu2UktBLWwbnmGF"
        newsletter = SimpleNamespace(
            background_url=(
                "https://drive.google.com/uc?export=view&id=" + drive_id
            ),
            email_data={"images": [], "question_mode": "text"},
        )
        rendered = '<img src="cid:image0">'

        result = preview._replace_browser_cids(rendered, newsletter)

        self.assertIn('src="/image/{}"'.format(drive_id), result)
        self.assertNotIn("drive.google.com", result)

    def test_drive_image_fetch_is_cached(self):
        config = preview.PreviewConfig(
            sheet_id="sheet-id",
            sheet_name="Form Responses 1",
            background_url="https://example.test/cover.jpg",
        )
        state = preview.PreviewState(config)
        response = SimpleNamespace(
            content=b"jpeg-bytes",
            headers={"Content-Type": "image/jpeg; charset=binary"},
            raise_for_status=mock.Mock(),
        )
        drive_id = "1bKIKBOzyq7LjG0mKRpu2UktBLWwbnmGF"

        with mock.patch.object(preview.requests, "get", return_value=response) as get:
            first = state.get_image(drive_id)
            second = state.get_image(drive_id)

        self.assertEqual(first, ("image/jpeg", b"jpeg-bytes"))
        self.assertEqual(second, first)
        get.assert_called_once()

    def test_diyl_gif_is_generated_in_memory(self):
        newsletter = SimpleNamespace(
            email_data={
                "question_mode": "diyl_gif",
                "question_answers": [
                    ("Maya", "questiongif0", "A day", ["https://example.test/1"])
                ],
            },
            _make_gif_bytes=mock.Mock(return_value=b"GIF89a-preview"),
        )
        result = preview._question_cid_sources(newsletter)

        self.assertTrue(result["questiongif0"].startswith("data:image/gif;base64,"))
        newsletter._make_gif_bytes.assert_called_once()

    def test_build_snapshot_has_no_send_path_and_uses_read_only_edition(self):
        calls = []

        class FakeNewsletter:
            def __init__(self, *args, **kwargs):
                self.background_url = kwargs["background_url"]
                self.datetime_now = datetime(2026, 8, 1, tzinfo=timezone.utc)
                self.data_df = SimpleNamespace(index=[0, 1])

            def generate_newsletter(self, update_edition=True):
                calls.append(update_edition)
                self.email_data = {
                    "edition_number": 27,
                    "images": [
                        ["https://example.test/photo.jpg", "A", "Caption"]
                    ],
                    "question_mode": "text",
                    "question_answers": [],
                }

            def send_email(self, *args, **kwargs):
                raise AssertionError("Preview attempted to send email")

        config = preview.PreviewConfig(
            sheet_id="sheet-id",
            sheet_name="Form Responses 1",
            background_url="https://example.test/cover.jpg",
        )
        rendered = {
            "standard": '<img src="https://example.test/cover.jpg">',
            "spark": '<img src="cid:image0"><img src="cid:image1">',
        }

        with mock.patch.object(preview, "PreviewNewsletter", FakeNewsletter), mock.patch.object(
            preview, "_render_templates", return_value=rendered
        ), mock.patch.object(
            main.smtplib,
            "SMTP_SSL",
            side_effect=AssertionError("SMTP must not be opened"),
        ):
            snapshot = preview.build_snapshot(config)

        self.assertEqual(calls, [False])
        self.assertEqual(snapshot.edition_number, 27)
        self.assertNotIn("cid:", snapshot.spark_html)


class PreviewServerTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = preview.PreviewSnapshot(
            standard_html="<html><body>standard preview</body></html>",
            spark_html="<html><body>spark preview</body></html>",
            loaded_at="Friday, August 01 at 12:00 PM UTC",
            edition_number=27,
            response_count=2,
            question_mode="text",
        )

        class StaticState:
            def __init__(inner_self, snapshot):
                inner_self.snapshot = snapshot
                inner_self.calls = 0
                inner_self.image_calls = []

            def get_snapshot(inner_self, refresh=False):
                inner_self.calls += 1
                return inner_self.snapshot

            def get_image(inner_self, file_id):
                inner_self.image_calls.append(file_id)
                return ("image/png", b"preview-image")

        self.state = StaticState(self.snapshot)
        self.server = preview.LocalPreviewServer(
            (preview.LOCAL_HOST, 0),
            preview.create_handler(self.state),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = "http://{}:{}".format(
            preview.LOCAL_HOST,
            self.server.server_address[1],
        )

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_health_does_not_fetch_sheet(self):
        with urlopen(self.base_url + "/healthz") as response:
            payload = json_load(response.read())

        self.assertEqual(payload["email_sending"], "disabled")
        self.assertEqual(self.state.calls, 0)

    def test_dashboard_and_both_email_variants(self):
        with urlopen(self.base_url + "/") as response:
            dashboard = response.read().decode("utf8")
            self.assertEqual(response.headers["Cache-Control"], "no-store")

        with urlopen(self.base_url + "/email?variant=standard") as response:
            standard = response.read().decode("utf8")
            self.assertIn("script-src 'none'", response.headers["Content-Security-Policy"])

        with urlopen(self.base_url + "/email?variant=spark") as response:
            spark = response.read().decode("utf8")

        self.assertIn("Sending disabled", dashboard)
        self.assertIn("standard preview", standard)
        self.assertIn("spark preview", spark)

    def test_local_image_route(self):
        drive_id = "1bKIKBOzyq7LjG0mKRpu2UktBLWwbnmGF"
        with urlopen(self.base_url + "/image/" + drive_id) as response:
            payload = response.read()

        self.assertEqual(response.headers["Content-Type"], "image/png")
        self.assertEqual(payload, b"preview-image")
        self.assertEqual(self.state.image_calls, [drive_id])
        self.assertEqual(self.state.calls, 0)

    def test_post_is_not_allowed(self):
        request = Request(self.base_url + "/", data=b"", method="POST")
        with self.assertRaises(HTTPError) as caught:
            urlopen(request)
        self.assertEqual(caught.exception.code, HTTPStatus.METHOD_NOT_ALLOWED)

    def test_server_is_loopback_only(self):
        self.assertEqual(preview.LOCAL_HOST, "127.0.0.1")


def json_load(payload):
    import json

    return json.loads(payload.decode("utf8"))


if __name__ == "__main__":
    unittest.main()
