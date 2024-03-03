from jinja2 import Template
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from dotenv import load_dotenv
from datetime import datetime
from PIL import Image, ImageOps
from io import BytesIO
import ast
import os
import pytz
import pandas as pd
import numpy as np
import requests
import smtplib
import random

class Reminder:

    def __init__(self, sender, recipients, recipients_spark, password, sheet_id, sheet_name, form_url):
        
        self.datetime_now = datetime.now(tz=pytz.timezone(timezone))
        self.sender = sender
        self.recipients = recipients
        self.recipients_spark = recipients_spark
        self.password = password
        self.form_url = form_url

        url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={sheet_name}'.replace(" ", "%20")
        self.data_df = pd.read_csv(url).replace(np.nan, '')

    def generate_email(self):
        '''
        Generate reminder using HTML template and Jinja
        '''
        with open('reminder.html', encoding="utf8") as f:
            template = Template(f.read())
        self.email_data = {
            "subject": "🔔 NEWSLETTER REMINDER " + self.datetime_now.strftime("%m/%d") + " 🔔",
            "image_url": random.choice(
                [x for i in range(1, 4) for x in self.data_df[f"Image {i}"].to_list() if x]
                ).replace('open?', 'uc?export=view&'),
            "form_url": form_url
        }
        self.email_content = template.render(self.email_data)

    def send_email(self):
        '''
        Send email containing newsletter
        '''
        msg = MIMEMultipart()
        msg['Subject'] = self.email_data["subject"]
        msg['From'] = self.sender
        msg['To'] = self.sender
        self.image_to_byte(msg)
        msg.attach(MIMEText(self.email_content, "html"))

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp_server:
            smtp_server.ehlo()
            smtp_server.login(self.sender, self.password)
            smtp_server.sendmail(self.sender, [self.sender] + self.recipients_spark + self.recipients, msg.as_string()) # recipients are BCCed
        print("Message sent!")

    def image_to_byte(self, msg):
        image_data = ImageOps.exif_transpose(Image.open(requests.get(self.email_data["image_url"], stream=True).raw))
        if image_data.mode in ("RGBA", "P"): image_data = image_data.convert("RGB")
        quality = 100
        while True:
            byte_buffer = BytesIO()
            image_data.save(byte_buffer, format="JPEG", quality=quality)
            if byte_buffer.tell() / 1000000 > 24.5:
                quality -= 5
            else:
                break 
        image = MIMEImage(byte_buffer.getvalue())
        image.add_header('Content-ID', f"<image>")
        image.add_header('content-disposition', 'attachment', filename="🍵")
        msg.attach(image)
        
if __name__ == "__main__":

    # parameters
    timezone = "Pacific/Auckland"

    load_dotenv()
    sender = os.getenv("GMAIL_ADDRESS")
    recipients = ast.literal_eval(os.getenv("RECIPIENT"))
    recipients_spark = ast.literal_eval(os.getenv("RECIPIENT_SPARK"))
    password = os.getenv("APP_PASSWORD")
    sheet_id = os.getenv("SHEET_ID")
    sheet_name = os.getenv("SHEET_NAME")
    form_url = os.getenv("FORM_URL")
    
    # send email
    reminder = Reminder(sender, recipients, recipients_spark, password, sheet_id, sheet_name, form_url)
    reminder.generate_email()
    reminder.send_email()