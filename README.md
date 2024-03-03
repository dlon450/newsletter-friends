# HTML Newsletter Email for Friends
Send an HTML newsletter via email to friends. Content in newsletter is retrieved from a Google Form responses file.

## Getting Started
A Gmail account and app password are required for emails to be sent (see [here](https://support.google.com/accounts/answer/185833?hl=en) on how to set up an app password). A Google Form is also required for people to upload the content (e.g., images, question responses) that will be included in the HTML newsletter, as well as a corresponding Google Spreadsheet containing response data. The form, spreadsheet, and any related folders in Google Drive will need to be set to "Anyone can view".

When using this repo locally, you will need to set up a .env file containing email addresses, passwords, and the Google Spreadsheet corresponding to the Google Form. It should look something like this:

```
GMAIL_ADDRESS=sender@gmail.com
APP_PASSWORD=xxxxxxxxxxxxxxxx
RECIPIENT=["recipient1@gmail.com", "recipient2@gmail.com", ...]
RECIPIENT_SPARK=["recipient3@outlook.com", "recipient4@outlook.com", ...]
SHEET_ID=xxxxxxxxxxxxxxxx
SHEET_NAME="xxxxxxxxxxxxxxxx"
BACKGROUND_URL=xxxxxxxxxxxxxxxx
FORM_URL=xxxxxxxxxxxxxxxx
```

Then, run ``main.py``. Otherwise, if using this repo with GitHub Actions, you will need to add these hidden variables as secrets (Settings > Secrets and Variables > Actions > New repository secret).

## Built With
* Jinja2
* Pandas
* Python 3.8
