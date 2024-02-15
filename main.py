from jinja2 import Template
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import ast
import os
import pytz
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

class Newsletter:

    def __init__(self, first_edition_date, frequency, timezone, sender, recipients, password, sheet_id, sheet_name):
        
        self.datetime_now = datetime.now(tz=pytz.timezone(timezone))
        self.sender = sender
        self.recipients = recipients
        self.frequency = frequency
        self.first_edition_date = first_edition_date
        self.password = password

        url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={sheet_name}'.replace(" ", "%20")
        data_df = pd.read_csv(url).replace(np.nan, '')
        self.data_df = data_df[pd.to_datetime(data_df["Timestamp"]) > pd.to_datetime(self.datetime_now - timedelta(days=self.frequency)).date().strftime("%Y/%m/%d")]

    def generate_newsletter(self):
        '''
        Generate newsletter using HTML template and Jinja
        '''
        with open('template.html', encoding="utf8") as f:
            template = Template(f.read())

        question = self.data_df.iloc[:, 2].to_list()
        names = self.data_df["Your Name"].to_list()
        one_good_thing = self.data_df["One Good Thing"].to_list()
        images = [self.data_df[f"Image {i}"].to_list() for i in range(1, 4)]
        captions = [self.data_df[f"Caption {i}"].to_list() for i in range(1, 4)]

        self.email_data = {
            "subject": "Weekly Newsletter",
            "question_title": self.data_df.columns[2],
            "question_answers": [(name, answer) for name, answer in zip(names, question) if answer != ''],
            "one_good_thing": [(name, ogt) for ogt, name in zip(one_good_thing, names) if ogt != ''],
            "images": [(images[i][j].replace('open?', 'uc?export=view&'), names[j], captions[i][j]) for j in range(len(names)) for i in range(len(images)) if images[i][j] != ''],
            "date": self.datetime_now,
            "next_date": self.datetime_now + timedelta(days=self.frequency),
            "edition_number": (datetime.now() - datetime.strptime(first_edition_date, "%Y/%m/%d")).seconds // (86400 * self.frequency) + 1
        }
        self.email_content = template.render(self.email_data)

    def send_email(self):
        '''
        Send email containing newsletter
        '''
        msg = MIMEMultipart()
        msg['Subject'] = self.email_data["subject"] + " " + self.email_data["date"].strftime("%m/%d")
        msg['From'] = sender
        msg['To'] = ', '.join(recipients)
        msg.attach(MIMEText(self.email_content, "html"))
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp_server:
            smtp_server.login(self.sender, self.password)
            smtp_server.sendmail(self.sender, self.recipients, msg.as_string())
        print("Message sent!")

if __name__ == "__main__":

    # parameters
    first_edition_date = '2024/02/15'
    frequency = 1 # no. days between newsletters
    timezone = "Pacific/Auckland"

    load_dotenv()
    sender = os.getenv("GMAIL_ADDRESS")
    recipients = ast.literal_eval(os.getenv("RECIPIENT"))
    print(recipients)
    password = os.getenv("GMAIL_PASSWORD")
    sheet_id = os.getenv("SHEET_ID")
    sheet_name = os.getenv("SHEET_NAME")
    
    # send email
    newsletter = Newsletter(first_edition_date, frequency, timezone, sender, recipients, password, sheet_id, sheet_name)
    newsletter.generate_newsletter()
    newsletter.send_email()