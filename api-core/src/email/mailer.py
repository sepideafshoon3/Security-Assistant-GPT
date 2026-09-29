import logging
import os
import smtplib
from email.mime.text import MIMEText

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)

logger = logging.getLogger(__name__)


def send_verification_code(to_email: str, code: str) -> None:
    if not SMTP_HOST:
        logger.warning(
            "[dev-mode] SMTP not configured — code for %s is: %s", to_email, code
        )
        return

    msg = MIMEText(f"Your verification code is: {code}\nIt expires in 10 minutes.")
    msg["Subject"] = "Your verification code"
    msg["From"] = SMTP_FROM
    msg["To"] = to_email

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
