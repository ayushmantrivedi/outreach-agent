"""
notifications/telegram_notifier.py
===================================
Sends Telegram messages via the Bot API.
All notification types are centralised here.
"""

import os
from typing import Optional

import requests
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    """
    Sends structured alerts to a Telegram chat.

    Requires:
        TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in your .env file.
        Create a bot at https://t.me/BotFather
        Get your chat ID by messaging @userinfobot
    """

    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        self.token = token or _BOT_TOKEN
        self.chat_id = chat_id or _CHAT_ID

        if not self.token or not self.chat_id:
            logger.warning(
                "Telegram credentials not set. "
                "Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to your .env to enable notifications."
            )

    def _send(self, text: str) -> bool:
        """
        Send a raw message to the configured chat.
        Returns True on success, False on failure.
        """
        if not self.token or not self.chat_id:
            return False

        url = _TELEGRAM_API.format(token=self.token)
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            return True
        except Exception as exc:
            logger.error(f"Telegram send failed: {exc}")
            return False

    def notify_reply(self, company_name: str, subject: str, classification: str) -> bool:
        """Alert: a reply was received."""
        emoji = {"positive": "🎉", "neutral": "📩", "negative": "👎"}.get(classification, "📬")
        text = (
            f"{emoji} *New Reply Received!*\n\n"
            f"*From:* {company_name}\n"
            f"*Subject:* {subject}\n"
            f"*Classification:* {classification.upper()}\n\n"
            f"_Check your inbox for details._"
        )
        logger.info(f"Telegram: notifying reply from {company_name}")
        return self._send(text)

    def notify_interest(self, company_name: str, score: float, reasoning: str) -> bool:
        """Alert: a company has scored high relevance."""
        text = (
            f"🔥 *High-Interest Company Found!*\n\n"
            f"*Company:* {company_name}\n"
            f"*Relevance Score:* {score:.1f}/10\n\n"
            f"*Why:* {reasoning[:300]}"
        )
        logger.info(f"Telegram: notifying high-interest company {company_name}")
        return self._send(text)

    def notify_send_failure(self, company_name: str, email_address: str, error: str) -> bool:
        """Alert: an email failed to send."""
        text = (
            f"⚠️ *Email Send Failure*\n\n"
            f"*Company:* {company_name}\n"
            f"*Address:* `{email_address}`\n"
            f"*Error:* {error[:200]}"
        )
        logger.warning(f"Telegram: notifying send failure for {company_name}")
        return self._send(text)

    def notify_pipeline_complete(self, stats: dict) -> bool:
        """Alert: the daily pipeline has finished."""
        text = (
            f"✅ *Daily Pipeline Complete*\n\n"
            f"• Discovered: {stats.get('discovered', 'N/A')} companies\n"
            f"• Ranked: {stats.get('ranked', 'N/A')}\n"
            f"• Qualified: {stats.get('qualified', 'N/A')}\n"
            f"• Emails sent: {stats.get('sent', 'N/A')}\n"
            f"• Emails failed: {stats.get('failed', 'N/A')}"
        )
        return self._send(text)
