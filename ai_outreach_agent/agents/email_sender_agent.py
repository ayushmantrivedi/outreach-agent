"""
agents/email_sender_agent.py
============================
Sends outreach emails via SMTP.

Safeguards:
  - Hard cap of `daily_email_limit` emails per day (configurable)
  - Skips companies already emailed
  - Logs every send attempt (success/failure) to PostgreSQL
  - 2-second delay between sends to avoid SMTP rate limits
"""

import os
import smtplib
import ssl
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List

import yaml
from ai_outreach_agent.utils import load_env
from loguru import logger

from ai_outreach_agent.database.db import (
    get_daily_sent_count,
    log_email,
    update_email_status,
)

load_dotenv()

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "settings.yaml")

# SMTP credentials from environment
_SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
_SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
_SMTP_USER = os.getenv("SMTP_USER", "")
_SMTP_PASS = os.getenv("SMTP_PASS", "")


def _load_config() -> dict:
    with open(_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def _build_mime_message(from_addr: str, to_addr: str, subject: str, body: str) -> MIMEMultipart:
    """Construct a MIME email message."""
    msg = MIMEMultipart("alternative")
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    # Plain text part
    msg.attach(MIMEText(body, "plain"))
    return msg


def send_single_email(
    to_address: str,
    subject: str,
    body: str,
    company_id: int,
    template_used: str = "engineering_role",
) -> bool:
    """
    Send one email and log the result to the database.

    Returns True on success, False on failure.
    """
    if not _SMTP_USER or not _SMTP_PASS:
        logger.error(
            "SMTP credentials not set. Add SMTP_USER and SMTP_PASS to your .env file."
        )
        return False

    email_id = log_email(
        company_id=company_id,
        to_address=to_address,
        subject=subject,
        body=body,
        template=template_used,
        status="pending",
    )

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(_SMTP_USER, _SMTP_PASS)
            msg = _build_mime_message(_SMTP_USER, to_address, subject, body)
            server.sendmail(_SMTP_USER, to_address, msg.as_string())

        update_email_status(email_id, status="sent")
        logger.success(f"✉️  Email sent → {to_address} | Subject: '{subject}'")
        return True

    except smtplib.SMTPRecipientsRefused as exc:
        err = f"Recipient refused: {exc}"
        update_email_status(email_id, status="failed", error_message=err)
        logger.error(f"Send failed ({to_address}): {err}")
        return False

    except smtplib.SMTPAuthenticationError as exc:
        err = f"SMTP authentication error: {exc}"
        update_email_status(email_id, status="failed", error_message=err)
        logger.error(err)
        logger.warning(
            "Gmail users: make sure you're using an App Password, not your account password. "
            "Enable 2FA first at myaccount.google.com → Security → App Passwords."
        )
        return False

    except Exception as exc:
        err = str(exc)
        update_email_status(email_id, status="failed", error_message=err)
        logger.error(f"Unexpected SMTP error ({to_address}): {err}")
        return False


def run_email_sending(emails: List[Dict]) -> Dict:
    """
    Send a batch of generated emails respecting the daily limit.

    Parameters
    ----------
    emails : list
        Output from email_generation_agent.run_email_generation().
        Each item: {'company': {...}, 'subject': str, 'body': str}

    Returns
    -------
    dict : {'sent': N, 'failed': M, 'skipped': K}
    """
    cfg = _load_config()
    daily_limit: int = int(cfg.get("daily_email_limit", 20))

    sent_today = get_daily_sent_count()
    logger.info(f"Emails sent today so far: {sent_today}/{daily_limit}")

    stats = {"sent": 0, "failed": 0, "skipped": 0}

    for item in emails:
        if sent_today + stats["sent"] >= daily_limit:
            logger.warning(
                f"Daily email limit of {daily_limit} reached. "
                f"Remaining emails will be sent tomorrow."
            )
            stats["skipped"] += len(emails) - stats["sent"] - stats["failed"] - stats["skipped"]
            break

        company = item["company"]
        to_address = company.get("contact_email")

        if not to_address:
            logger.warning(f"No email for {company.get('company_name')} — skipping.")
            stats["skipped"] += 1
            continue

        success = send_single_email(
            to_address=to_address,
            subject=item["subject"],
            body=item["body"],
            company_id=company["id"],
            template_used=cfg.get("email_template", "engineering_role"),
        )

        if success:
            stats["sent"] += 1
        else:
            stats["failed"] += 1

        # Be polite to SMTP servers
        time.sleep(2)

    logger.success(
        f"Email sending done: {stats['sent']} sent, "
        f"{stats['failed']} failed, {stats['skipped']} skipped."
    )
    return stats
