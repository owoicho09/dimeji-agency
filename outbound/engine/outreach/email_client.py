import smtplib
import os
import itertools
from email.mime.text import MIMEText
from email.utils import formataddr
from django.conf import settings


class SMTPManager:
    def __init__(self):
        print("Initializing SMTP rotation manager…")
        self.accounts = settings.EMAIL_ACCOUNTS
        self.pool = itertools.cycle(self.accounts)
        print(f"Loaded {len(self.accounts)} SMTP accounts")

    def send_email(self, subject, body, to_email):
        account = next(self.pool)
        print(f"Using SMTP account: {account['EMAIL_HOST_USER']}")

        REPLY_INBOX = os.getenv("REPLY_INBOX")

        # Construct MIME message
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = formataddr((account["DISPLAY_NAME"], account["EMAIL_HOST_USER"]))
        msg["To"] = to_email
        if REPLY_INBOX:
            msg["Reply-To"] = REPLY_INBOX

        try:
            print("Connecting to SMTP server...")
            with smtplib.SMTP(account["EMAIL_HOST"], account["EMAIL_PORT"]) as server:
                server.starttls()
                server.login(account["EMAIL_HOST_USER"], account["EMAIL_HOST_PASSWORD"])
                # Use send_message to preserve From + Reply-To
                server.send_message(msg)
            print(f"Email sent successfully to {to_email}")
            return account["EMAIL_HOST_USER"], True

        except Exception as e:
            print("SMTP ERROR:", e)
            return account["EMAIL_HOST_USER"], False


# Initialize SMTP client
smtp_client = SMTPManager()
