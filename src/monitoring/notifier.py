from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, telegram_bot_token: str = "", telegram_chat_id: str = "") -> None:
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.enabled = bool(telegram_bot_token and telegram_chat_id)

    async def send(self, message: str) -> None:
        if not self.enabled:
            logger.info("notify(log-only): %s", message)
            return

        url = (
            f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
        )
        payload = {"chat_id": self.telegram_chat_id, "text": message}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
        except Exception as exc:
            logger.warning("telegram notify failed err=%s msg=%s", exc, message)
