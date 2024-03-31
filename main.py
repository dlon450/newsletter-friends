from jinja2 import Template
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from dotenv import load_dotenv
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from PIL import Image, ImageOps, UnidentifiedImageError
from io import BytesIO
from pillow_heif import register_heif_opener
import ast
import os
import pytz
import pandas as pd
import numpy as np
import requests
import smtplib

class Newsletter:

    def __init__(self, first_edition_date, frequency_unit, frequency, timezone, sender, recipients, recipients_spark, password, sheet_id, sheet_name, background_url):
        
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

        url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={sheet_name}'.replace(" ", "%20")
        data_df = pd.read_csv(url).replace(np.nan, '')
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
        one_good_thing = self.data_df["One Good Thing"].to_list()
        life_updates = self.data_df["Any life updates?"].to_list()
        images = [self.data_df[f"Image {i}"].to_list() for i in range(1, 4)]
        captions = [self.data_df[f"Caption {i}"].to_list() for i in range(1, 4)]

        self.email_data = {
            "subject": "Chatime Newsletter 🍵",
            "question_title": self.data_df.columns[2],
            "question_answers": [(name, answer) for name, answer in zip(names, question) if answer != ''],
            "life_updates": [(name, answer) for name, answer in zip(names, life_updates) if answer != ''],
            "one_good_thing": [(name, ogt) for ogt, name in zip(one_good_thing, names) if ogt != ''],
            "images": [[images[i][j].replace('open?', 'uc?export=view&'), names[j], captions[i][j]] for j in range(len(names)) for i in range(len(images)) if images[i][j] != ''],
            "date": self.datetime_now,
            "next_date": self.datetime_now + self.time_delta,
            "edition_number": edition_number(),
            "background_url": self.background_url
        }
        self.max_image_byte = 25. / (len(self.email_data["images"]) + 1)
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
            self.image_to_byte(msg)
            msg.attach(MIMEText(self.email_content_spark, "html"))
        else:
            msg.attach(MIMEText(self.email_content, "html"))

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp_server:
            smtp_server.ehlo()
            smtp_server.login(self.sender, self.password)
            if spark:
                smtp_server.sendmail(self.sender, [sender] + self.recipients_spark, msg.as_string()) # recipients are BCCed
            else:
                smtp_server.sendmail(self.sender, [sender] + self.recipients, msg.as_string()) # recipients are BCCed
        print("Message sent!")

    def image_to_byte(self, msg):
        for i, (url, _, _) in enumerate([[self.background_url, '', '']] + self.email_data["images"]):
            try:
                image_data = ImageOps.exif_transpose(Image.open(requests.get(url, stream=True).raw))
            except UnidentifiedImageError:
                register_heif_opener()
                image_data = ImageOps.exif_transpose(Image.open(requests.get(url, stream=True).raw))
            if image_data.mode in ("RGBA", "P"): image_data = image_data.convert("RGB")
            quality = 95
            while True:
                byte_buffer = BytesIO()
                image_data.save(byte_buffer, format="JPEG", quality=quality)
                if byte_buffer.tell() / 1000000 > self.max_image_byte:
                    quality -= 5
                else:
                    break 
            image = MIMEImage(byte_buffer.getvalue())
            image.add_header('Content-ID', f"<image{i}>")
            msg.attach(image)
            print("image", i, byte_buffer.tell() / 1000000)
    
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
    newsletter = Newsletter(first_edition_date, frequency_unit, frequency, timezone, sender, recipients, recipients_spark, password, sheet_id, sheet_name, background_url)
    newsletter.generate_newsletter()
    # newsletter.send_email()
    if recipients_spark:
        newsletter.send_email(spark=True)