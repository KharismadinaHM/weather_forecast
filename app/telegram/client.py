"""Telegram Bot API HTTP client with retry and error handling (PLAN.md Section 16)."""

import asyncio

import httpx

from app.config.settings import Settings, get_settings
from app.logging_config import get_logger

logger = get_logger("telegram_client")


class TelegramClient:
    """Client for sending notifications and alerts to Telegram."""

    TELEGRAM_API_BASE: str = "https://api.telegram.org"

    def __init__(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        cfg = settings or get_settings()
        self.bot_token = bot_token or cfg.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or cfg.TELEGRAM_CHAT_ID
        self._http_client = http_client

    @property
    def is_configured(self) -> bool:
        """Check if bot token and chat ID are configured."""
        return bool(self.bot_token and self.chat_id)

    async def send_message(
        self,
        text: str,
        chat_id: str | None = None,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
    ) -> bool:
        """Send a message to configured or specified Telegram chat ID."""
        target_chat = chat_id or self.chat_id
        if not self.bot_token or not target_chat:
            logger.info(
                "Telegram not configured; message logged locally",
                chat_id=target_chat,
                text_preview=text[:120],
            )
            return False

        url = f"{self.TELEGRAM_API_BASE}/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": target_chat,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }

        # Retry loop with backoff (Section 16)
        backoffs = [1.0, 3.0, 5.0]
        for attempt, delay in enumerate(backoffs, start=1):
            try:
                if self._http_client:
                    resp = await self._http_client.post(url, json=payload, timeout=10.0)
                else:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.post(url, json=payload)

                if resp.status_code == 200:
                    logger.info("Telegram message sent successfully", chat_id=target_chat)
                    return True

                logger.warning(
                    "Telegram API non-200 response",
                    status_code=resp.status_code,
                    body=resp.text[:200],
                    attempt=attempt,
                )
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                logger.warning(
                    "Telegram API request failed, retrying",
                    error=str(exc),
                    attempt=attempt,
                )

            if attempt < len(backoffs):
                await asyncio.sleep(delay)

        logger.error("Failed to send Telegram message after max retries")
        return False
