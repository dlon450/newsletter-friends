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

## Preview Locally Without Sending

To load the current Google Sheet responses and view the rendered newsletter in a browser without emailing anyone, run:

```bash
python preview.py
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000). The preview offers both the standard and Spark/Outlook variants plus a **Reload live data** button.

Preview mode:

* binds only to your computer (`127.0.0.1`)
* reads `SHEET_ID`, `SHEET_NAME`, and `BACKGROUND_URL` from `.env`
* displays Google Drive photos through the loopback-only preview server
* does not read email credentials or recipient lists
* cannot send email
* shows the next edition number without changing `log.txt`

Press `Ctrl+C` in the terminal to stop the server. You can choose another local port with `python preview.py --port 8080`.

Running `main.py` is the production action: it advances the edition counter and sends the newsletter. Otherwise, if using this repo with GitHub Actions, you will need to add these hidden variables as secrets (Settings > Secrets and Variables > Actions > New repository secret).

## Built With
* Jinja2
* Pandas
* Python 3.8
