# HTML Newsletter Email for Friends
Send an HTML newsletter via email to friends. Content in newsletter is retrieved from a Google Form responses file.

## Getting Started
A Gmail account and app password is required for emails to be sent (see [here](https://support.google.com/accounts/answer/185833?hl=en) on how to set up an app password). A Google Form is also required for people to upload the content (e.g., images, question responses) that will be included in the HTML newsletter, as well as a corresponding Google Spreadsheet containing response data. The form, spreadsheet, and any related folders in Google Drive will need to be set to "Anyone can view".

When using this repo locally, you will need to set up a .env file containing email addresses, passwords, and the Google Spreadsheet corresponding to the Google Form. It should look something like this:

```
GMAIL_ADDRESS=xxx@gmail.com
GMAIL_PASSWORD=xxxxxxxxxxxx
RECIPIENT=["xxx@gmail.com", "yyy@gmail.com", ...]
SHEET_ID=xxxxxxxxxxxx
SHEET_NAME="xxx"
```

Then, run ``main.py``. Otherwise, if using this repo with GitHub Actions, you will need to add these hidden variables as secrets (Settings > Secrets and Variables > Actions > New repository secret).

## Built With
* Jinja2
* Pandas
* Python 3.8
