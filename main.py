from jinja2 import Template
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from dotenv import load_dotenv
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
from io import BytesIO
try:
    from pillow_heif import register_heif_opener
except ImportError:
    def register_heif_opener():
        return None
import ast
import os
import pytz
import pandas as pd
import numpy as np
import requests
import smtplib
import re

class Newsletter:

    def __init__(self, first_edition_date, frequency_unit, frequency, timezone, sender, recipients, 
                 recipients_spark, password, sheet_id, sheet_name, background_url, special_edition=False, num_images=3):
        
        self.datetime_now = datetime.now(tz=pytz.timezone(timezone))
        self.sender = sender
        self.recipients = recipients
        self.recipients_spark = recipients_spark
        self.frequency = frequency
        self.first_edition_date = first_edition_date
        self.password = password
        self.time_delta = {'month': relativedelta(months=+self.frequency), 'day': timedelta(days=self.frequency)}[frequency_unit]
        self.background_url = background_url
        self.max_image_byte = 0.
        self.special_edition = special_edition
        self.num_images = num_images

        url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={sheet_name}'.replace(" ", "%20")
        data_df = pd.read_csv(url).replace(np.nan, '')
        if frequency_unit == 'month':
            self.data_df = data_df[pd.to_datetime(data_df["Timestamp"]) >= pd.to_datetime(self.datetime_now - timedelta(days=14)).date().strftime("%Y/%m/%d")]
        else:
            self.data_df = data_df[pd.to_datetime(data_df["Timestamp"]) >= pd.to_datetime(self.datetime_now - self.time_delta).date().strftime("%Y/%m/%d")]

    def generate_newsletter(self):
        '''
        Generate newsletter using HTML template and Jinja
        '''
        with open('template.html', encoding="utf8") as f:
            template = Template(f.read())

        with open('template_spark.html', encoding="utf8") as f:
            template_spark = Template(f.read())

        question = self.data_df.iloc[:, 2].to_list()
        names = self.data_df["Your Name"].to_list()
        one_good_thing = self.data_df["☀️ One Good Thing!"].to_list()
        life_updates = self.data_df["✨ Any life updates?"].to_list()
        images = [self.data_df[f"Image {i}"].to_list() for i in range(1, self.num_images + 1)]
        captions = [self.data_df[f"Caption {i}"].to_list() for i in range(1, self.num_images + 1)]
        food_spot = self.data_df['😋 Food spot of the month?'].to_list()
        confessions = self.data_df['🤫 Any interesting, funny, or embarrassing moments?'].to_list()

        has_diyl_col = "Description of a DIYL" in self.data_df.columns
        existing_diyl_rows = (
            has_diyl_col
            and any(self.data_df["Description of a DIYL"].astype(str).str.strip() != '')
        )
        looks_like_diyl_links = any("drive.google.com" in str(a) for a in question if str(a).strip())
        use_diyl_mode = existing_diyl_rows and looks_like_diyl_links

        if use_diyl_mode:
            diyl_desc = self.data_df["Description of a DIYL"].to_list()
            qa = []
            for i, (name, raw, desc) in enumerate(zip(names, question, diyl_desc)):
                raw = str(raw).strip()
                if not raw:
                    continue
                links = [x.strip() for x in raw.split(",") if x.strip()]
                if not links:
                    continue
                cid = f"questiongif{i}"
                qa.append((name, cid, str(desc), links))
            question_answers = qa
            question_mode = "diyl_gif"
        else:
            question_answers = [(name, answer) for name, answer in zip(names, question) if answer != ""]
            question_mode = "text"

        self.email_data = {
            "subject": "Chatime Newsletter 🍵",
            "question_title": self.data_df.columns[2],
            "question_answers": question_answers,
            "question_mode": question_mode,
            "life_updates": [(name, answer) for name, answer in zip(names, life_updates) if answer != ''],
            "one_good_thing": [(name, ogt) for ogt, name in zip(one_good_thing, names) if ogt != ''],
            "food_spot": [(name, fs) for fs, name in zip(food_spot, names) if fs != ''],
            "confessions": [(name, c) for c, name in zip(confessions, names) if c != ''],
            "images": [[self._drive_direct_url(images[i][j]), names[j], captions[i][j]] for j in range(len(names)) for i in range(len(images)) if images[i][j] != ''],
            "date": self.datetime_now,
            "next_date": self.datetime_now + self.time_delta,
            "edition_number": edition_number(),
            "background_url": self.background_url,
            # "special_images": [],
            # "extra_images": [],
        }

        # special edition
        if self.special_edition:
            special_edition_questions = self.data_df.columns.to_list()[13:21]
            special_edition_answers = {q: self.data_df[q].to_list() for q in special_edition_questions}
            extra_images = [self.data_df[f"Extra Image {i}"].to_list() for i in range(1, self.num_images + 1)]
            extra_image_captions = [self.data_df[f"Extra Caption {i}"].to_list() for i in range(1, self.num_images + 1)]
            self.email_data["special_edition_questions"] = special_edition_questions
            self.email_data["special_edition_answers"] = {q: [(name, answer) for name, answer in zip(names, special_edition_answers[q]) if answer != ''] for q in special_edition_questions}
            self.email_data["extra_images"] = [[extra_images[i][j].replace('open?', 'uc?export=view&'), names[j], extra_image_captions[i][j]] for j in range(len(names)) for i in range(len(extra_images)) if extra_images[i][j] != '']
            self.email_data["special_images"] = [
                ["https://drive.google.com/uc?export=view&id=1N6Y3mYt3VbrL3NrUmn7vOUbP5RPHC5gy", "portraits", "need more selfies from some of y'all"],
                ["https://drive.google.com/uc?export=view&id=1IUrWCdUdtwRD91bcKb5qdugiyzXZWHa4", "outdoor", "outdoor adventures"],
                ["https://drive.google.com/uc?export=view&id=1IsQWyY3QxgkA15EvTgPOJ1BXr8tpvRuL", "instagram1", "if we had a chatime insta..."],
                ["https://drive.google.com/uc?export=view&id=1Zv9QQ2_GVj5QKKQgwjpBllILC4v5J6Yg", "instagram2", "chatime instagram 2"],
                ["https://drive.google.com/uc?export=view&id=1pU2sp4Kk8Oy0FjV2SbFbYxYFRUEI6fzI", "instagram3", "chatime instagram 3"]
            ]

        self.max_image_byte = 25. / (1 + len(self.email_data["images"])) # + len(self.email_data["extra_images"]) + len(self.email_data["special_images"]))
        self.email_content = template.render(self.email_data)
        self.email_content_spark = template_spark.render(self.email_data)

    def send_email(self, spark=False):
        '''
        Send email containing newsletter
        '''
        msg = MIMEMultipart()
        msg['Subject'] = self.email_data["subject"] + " " + self.email_data["date"].strftime("%m/%d")
        msg['From'] = sender
        msg['To'] = sender
        if spark: 
            spark_max_image_byte = self._spark_budget_mb()
            if self.email_data.get("question_mode") == "diyl_gif":
                self._attach_question_gifs(msg, max_image_byte=spark_max_image_byte)
            self.image_to_byte(msg, max_image_byte=spark_max_image_byte)
            msg.attach(MIMEText(self.email_content_spark, "html"))
        else:
            if self.email_data.get("question_mode") == "diyl_gif":
                self._attach_question_gifs(msg)
            msg.attach(MIMEText(self.email_content, "html"))

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp_server:
            smtp_server.ehlo()
            smtp_server.login(self.sender, self.password)
            if spark:
                smtp_server.sendmail(self.sender, [sender] + self.recipients_spark, msg.as_string()) # recipients are BCCed
            else:
                smtp_server.sendmail(self.sender, [sender] + self.recipients, msg.as_string()) # recipients are BCCed
        print("Message sent!")

    def image_to_byte(self, msg, max_image_byte=None):
        target_max_image_byte = self.max_image_byte if max_image_byte is None else max_image_byte
        for i, (url, _, _) in enumerate([[self.background_url, '', '']] 
                                        + self.email_data["images"] 
                                        # + self.email_data["special_images"] 
                                        # + self.email_data["extra_images"]
            ):
            image_data = self._open_remote_image(url)
            if image_data is None:
                continue
            if image_data.mode in ("RGBA", "P"): image_data = image_data.convert("RGB")
            quality = 95
            while True:
                byte_buffer = BytesIO()
                image_data.save(byte_buffer, format="JPEG", quality=quality)
                if byte_buffer.tell() / 1000000 > target_max_image_byte:
                    quality -= 5
                    if quality <= 0:
                        break
                else:
                    break 
            image = MIMEImage(byte_buffer.getvalue())
            image.add_header('Content-ID', f"<image{i}>")
            msg.attach(image)
            print("image", i, byte_buffer.tell() / 1000000)

    def _spark_budget_mb(self):
        asset_count = 1 + len(self.email_data["images"])
        if self.email_data.get("question_mode") == "diyl_gif":
            asset_count += len(self.email_data["question_answers"])
        # ~28% overhead buffer for base64 + MIME wrappers.
        return (25.0 * 0.72) / max(asset_count, 1)

    def _drive_file_id(self, url: str):
        normalized = str(url).strip()
        match = re.search(r"[?&]id=([^&]+)", normalized) or re.search(r"/d/([^/]+)", normalized)
        if not match:
            return None
        return match.group(1)

    def _drive_url_candidates(self, url: str):
        normalized = str(url).strip()
        file_id = self._drive_file_id(normalized)
        if file_id is None:
            return [normalized]
        return [
            f"https://drive.google.com/uc?export=view&id={file_id}",
            f"https://drive.google.com/uc?export=download&id={file_id}",
            f"https://drive.google.com/thumbnail?id={file_id}&sz=w2000",
            normalized,
        ]

    def _open_remote_image(self, url):
        for candidate in self._drive_url_candidates(url):
            try:
                response = requests.get(candidate, timeout=30)
                response.raise_for_status()
                image_bytes = BytesIO(response.content)
                try:
                    return ImageOps.exif_transpose(Image.open(image_bytes))
                except UnidentifiedImageError:
                    register_heif_opener()
                    image_bytes.seek(0)
                    return ImageOps.exif_transpose(Image.open(image_bytes))
            except Exception as error:
                last_error = error
                continue
        print(f"Skipping unrecognized image URL: {url}. Last error: {last_error}")
        return None

    def _drive_direct_url(self, url: str) -> str:
        url = url.strip()
        m = re.search(r"[?&]id=([^&]+)", url) or re.search(r"/d/([^/]+)", url)
        if m:
            return f"https://drive.google.com/uc?export=view&id={m.group(1)}"
        return url

    def _build_intro_frame(self, width, height, text):
        frame = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(frame)
        font_size = max(20, min(48, width // 18))
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Helvetica.ttc", font_size)
        except Exception:
            print("Font file not found, using default bitmap font.")
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = max(0, (width - text_width) // 2)
        y = max(0, (height - text_height) // 2)
        draw.text((x, y), text, fill="black", font=font)
        return frame

    def _make_gif_bytes(self, urls, max_image_byte=None, intro_text=None):
        lanczos = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        frames = []
        for u in urls:
            im = self._open_remote_image(u)
            if im is None:
                continue
            if im.mode in ("RGBA", "P"):
                im = im.convert("RGB")
            frames.append(im)
        if not frames:
            return None

        def build_bytes(max_side, color_count, frame_step, duration_ms):
            selected = frames[::frame_step]
            if not selected:
                selected = [frames[0]]

            resized = []
            for frame in selected:
                ratio = min(max_side / frame.width, max_side / frame.height, 1.0)
                if ratio < 1.0:
                    new_size = (max(1, int(frame.width * ratio)), max(1, int(frame.height * ratio)))
                    resized_frame = frame.resize(new_size, resample=lanczos)
                else:
                    resized_frame = frame.copy()
                resized.append(resized_frame.convert("RGB"))

            width = max(frame.width for frame in resized)
            height = max(frame.height for frame in resized)
            normalized = []
            for frame in resized:
                canvas = Image.new("RGB", (width, height), "white")
                canvas.paste(frame, ((width - frame.width) // 2, (height - frame.height) // 2))
                normalized.append(canvas.convert("P", palette=Image.ADAPTIVE, colors=color_count))

            if intro_text:
                intro = self._build_intro_frame(width, height, intro_text)
                normalized.insert(0, intro.convert("P", palette=Image.ADAPTIVE, colors=color_count))

            output = BytesIO()
            normalized[0].save(
                output,
                format="GIF",
                save_all=True,
                append_images=normalized[1:],
                duration=duration_ms,
                loop=0,
                optimize=True,
                disposal=2,
            )
            return output.getvalue()

        if max_image_byte is None:
            return build_bytes(max_side=1200, color_count=128, frame_step=1, duration_ms=1200)

        max_bytes = int(max_image_byte * 1000000)
        candidates = [
            (1200, 128, 1, 1200),
            (1000, 96, 1, 1200),
            (850, 80, 1, 1000),
            (700, 64, 2, 1000),
            (560, 48, 2, 900),
            (440, 32, 3, 850),
            (340, 24, 4, 800),
        ]
        fallback = None
        for max_side, color_count, frame_step, duration_ms in candidates:
            gif_bytes = build_bytes(max_side, color_count, frame_step, duration_ms)
            fallback = gif_bytes
            if len(gif_bytes) <= max_bytes:
                return gif_bytes
        return fallback

    def _attach_question_gifs(self, msg, max_image_byte=None):
        for answer in self.email_data.get("question_answers", []):
            if len(answer) < 4:
                continue
            name = str(answer[0]).strip()
            cid = answer[1]
            links = answer[3]
            intro_text = f"Day in my life: {name}" if name else "Day in my life"
            gif_bytes = self._make_gif_bytes(
                links,
                max_image_byte=max_image_byte,
                intro_text=intro_text,
            )
            if gif_bytes is None:
                continue
            part = MIMEImage(gif_bytes, _subtype="gif")
            part.add_header("Content-ID", f"<{cid}>")
            part.add_header("Content-Disposition", "inline", filename=f"{cid}.gif")
            msg.attach(part)

def edition_number():
    '''
    Return the newsletter edition number 
    '''
    if not os.path.exists('log.txt'):
        with open('log.txt','w') as f:
            f.write('0')
    with open('log.txt','r') as f:
        st = int(f.read())
        st += 1 
    with open('log.txt','w') as f:
        f.write(str(st))
    return st

if __name__ == "__main__":

    # parameters
    first_edition_date = '2024/03/01'
    frequency_unit = 'month' #'month' or 'day'
    frequency = 1 #time between newsletters with unit `frequency_unit`
    timezone = "Pacific/Auckland"

    load_dotenv()
    sender = os.getenv("GMAIL_ADDRESS")
    recipients = ast.literal_eval(os.getenv("RECIPIENT"))
    recipients_spark = ast.literal_eval(os.getenv("RECIPIENT_SPARK"))
    password = os.getenv("APP_PASSWORD")
    sheet_id = os.getenv("SHEET_ID")
    sheet_name = os.getenv("SHEET_NAME")
    background_url = os.getenv("BACKGROUND_URL")

    # send email
    newsletter = Newsletter(first_edition_date, frequency_unit, frequency, timezone, sender, recipients, 
                            recipients_spark, password, sheet_id, sheet_name, background_url, special_edition=True)
    newsletter.generate_newsletter()
    newsletter.send_email()
    if recipients_spark:
        newsletter.send_email(spark=True)