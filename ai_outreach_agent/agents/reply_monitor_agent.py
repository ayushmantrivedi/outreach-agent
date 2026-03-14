"""
agents/reply_monitor_agent.py
=============================
Polls the IMAP inbox every N minutes for replies to outreach emails.
On detecting a reply:
  1. Stores it in the `replies` table.
  2. Classifies it (positive / neutral / negative) via the local LLM.
  3. Flags it for Telegram notification.
"""

import email
import imaplib
import os
import time
from email.header import decode_header
from typing import Optional

import yaml
from ai_outreach_agent.utils import load_env
from loguru import logger

from ai_outreach_agent.database.db import (
    get_company_id_by_email,
    log_reply,
    get_unnotified_replies,
    mark_reply_notified,
)
from ai_outreach_agent.models.llm_interface import LLMInterface
from ai_outreach_agent.notifications.telegram_notifier import TelegramNotifier

load_env()

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "settings.yaml")
_IMAP_HOST = os.getenv("IMAP_HOST", "imap.gmail.com")
_IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
_IMAP_USER = os.getenv("IMAP_USER", "")
_IMAP_PASS = os.getenv("IMAP_PASS", "")


def _load_config() -> dict:
    with open(_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def _decode_header_value(raw: str) -> str:
    """Decode encoded email header values (e.g. =?UTF-8?B?...?=)."""
    parts = decode_header(raw)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(str(part))
    return " ".join(decoded)


def _extract_body(msg: email.message.Message) -> str:
    """Extract plain-text body from a MIME email."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if ct == "text/plain" and "attachment" not in disp:
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    return ""


def check_inbox_once(llm: Optional[LLMInterface] = None) -> int:
    """
    Connect to IMAP, fetch UNSEEN emails, classify, and store replies.

    Returns
    -------
    int
        Number of new replies processed.
    """
    if not _IMAP_USER or not _IMAP_PASS:
        logger.error("IMAP credentials not set. Add IMAP_USER and IMAP_PASS to your .env.")
        return 0

    if llm is None:
        cfg = _load_config()
        llm = LLMInterface(model=cfg.get("llm_model", "llama3"), timeout=cfg.get("ollama_timeout", 120))

    notifier = TelegramNotifier()
    processed = 0

    try:
        mail = imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT)
        mail.login(_IMAP_USER, _IMAP_PASS)
        mail.select("INBOX")

        status, data = mail.search(None, "UNSEEN")
        if status != "OK" or not data[0]:
            logger.info("IMAP: no new messages.")
            mail.logout()
            return 0

        ids = data[0].split()
        logger.info(f"IMAP: {len(ids)} unseen messages found.")

        for msg_id in ids:
            try:
                _, msg_data = mail.fetch(msg_id, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                from_addr = email.utils.parseaddr(msg.get("From", ""))[1]
                subject = _decode_header_value(msg.get("Subject", "(no subject)"))
                body = _extract_body(msg)

                # Match to a known company (if possible)
                company_id = get_company_id_by_email(from_addr)

                # Classify the reply
                classification = llm.classify_reply(body)

                reply_id = log_reply(
                    company_id=company_id,
                    from_address=from_addr,
                    subject=subject,
                    raw_message=body[:5000],
                    classification=classification,
                )

                company_name = from_addr  # fallback label
                notifier.notify_reply(company_name=company_name, subject=subject,
                                      classification=classification)
                mark_reply_notified(reply_id)
                processed += 1

                logger.success(
                    f"Reply from {from_addr} | {classification.upper()} | '{subject}'"
                )

            except Exception as exc:
                logger.error(f"Error processing message {msg_id}: {exc}")

        mail.logout()

    except imaplib.IMAP4.error as exc:
        logger.error(f"IMAP error: {exc}")
    except Exception as exc:
        logger.error(f"Unexpected error in inbox check: {exc}")

    return processed


def run_reply_monitor(interval_minutes: int = 5) -> None:
    """
    Continuously poll the inbox at `interval_minutes` intervals.
    Run this as a background service or within the Prefect pipeline.
    Press Ctrl+C to stop.
    """
    cfg = _load_config()
    interval_minutes = cfg.get("monitor_interval_minutes", interval_minutes)
    llm = LLMInterface(model=cfg.get("llm_model", "llama3"), timeout=cfg.get("ollama_timeout", 120))

    logger.info(f"Reply monitor started (polling every {interval_minutes} min). Press Ctrl+C to stop.")
    try:
        while True:
            check_inbox_once(llm=llm)
            logger.info(f"Next inbox check in {interval_minutes} minutes …")
            time.sleep(interval_minutes * 60)
    except KeyboardInterrupt:
        logger.info("Reply monitor stopped by user.")
