"""Telegram platform adapter for Hermes Mobile.

Uses httpx long-polling against the Telegram Bot API.
Runs as a background task in the mobile gateway.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"
POLL_TIMEOUT = 30
RETRY_DELAY = 5
MAX_RETRY_DELAY = 60


class TelegramAdapter:
    """Long-polling Telegram bot adapter."""

    def __init__(
        self,
        token: str,
        on_message: Any = None,
    ):
        self._token = token
        self._base_url = f"{TELEGRAM_API}/bot{token}"
        self._offset: int = 0
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None

        self.on_message = on_message

    async def start(self) -> None:
        self._running = True
        self._client = httpx.AsyncClient(timeout=POLL_TIMEOUT + 10)
        self._task = asyncio.create_task(self._poll_loop())

        me = await self._api("getMe")
        if me.get("ok"):
            username = me["result"].get("username", "unknown")
            logger.info("Telegram bot @%s started", username)
        else:
            logger.error("Telegram bot init failed: %s", me)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()
            self._client = None

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        parse_mode: str = "HTML",
        **kwargs,
    ) -> Optional[int]:
        result = await self._api(
            "sendMessage",
            chat_id=chat_id,
            text=text[:4096],
            parse_mode=parse_mode or "HTML",
            disable_web_page_preview=True,
            **kwargs,
        )
        if result.get("ok"):
            return result["result"]["message_id"]
        logger.error("sendMessage failed: %s", result)
        return None

    async def edit_message(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        parse_mode: str = "HTML",
    ) -> bool:
        result = await self._api(
            "editMessageText",
            chat_id=chat_id,
            message_id=message_id,
            text=text[:4096],
            parse_mode=parse_mode or "HTML",
            disable_web_page_preview=True,
        )
        return result.get("ok", False)

    async def _api(self, method: str, **kwargs) -> Dict[str, Any]:
        retry_delay = RETRY_DELAY
        last_error = None

        for attempt in range(3):
            try:
                if not self._client:
                    self._client = httpx.AsyncClient(timeout=POLL_TIMEOUT + 10)

                response = await self._client.post(
                    f"{self._base_url}/{method}",
                    json={k: v for k, v in kwargs.items() if v is not None},
                )
                return response.json()
            except httpx.TimeoutException as e:
                last_error = e
                logger.warning("Telegram API timeout (attempt %d): %s", attempt + 1, method)
            except Exception as e:
                last_error = e
                logger.warning("Telegram API error: %s", e)

            if attempt < 2:
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)

        return {"ok": False, "error": str(last_error)}

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                updates = await self._api(
                    "getUpdates",
                    offset=self._offset,
                    timeout=POLL_TIMEOUT,
                    allowed_updates=["message", "edited_message"],
                )

                if updates.get("ok"):
                    for update in updates["result"]:
                        self._offset = update["update_id"] + 1
                        await self._process_update(update)
                else:
                    error_code = updates.get("error_code")
                    if error_code == 409:
                        # Another long-poll lease holds this bot token: a second
                        # app instance, a leftover process, or a webhook that was
                        # never deleted. Keep polling after a longer backoff so a
                        # fixed/restarted instance recovers on its own.
                        logger.error(
                            "Telegram 409 Conflict on getUpdates: another instance "
                            "is polling this bot (or a webhook is still set). Stop "
                            "the other instance / call deleteWebhook, then restart "
                            "the gateway."
                        )
                        await asyncio.sleep(MAX_RETRY_DELAY)
                    else:
                        # Rate limited (429), transient API errors: back off and
                        # retry instead of hot-looping.
                        await asyncio.sleep(RETRY_DELAY)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Telegram poll error: %s", e)
                await asyncio.sleep(RETRY_DELAY)

    async def _process_update(self, update: Dict[str, Any]) -> None:
        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        chat = message.get("chat", {})
        from_user = message.get("from", {})
        text = message.get("text") or message.get("caption", "")
        chat_id = chat.get("id")
        user_id = from_user.get("id")

        if not text or not chat_id:
            return

        formatted = {
            "platform": "telegram",
            "chat_id": str(chat_id),
            "user_id": str(user_id) if user_id else "",
            "text": text,
            "message_id": message.get("message_id"),
            "chat_type": chat.get("type", "private"),
            "user_name": (
                from_user.get("first_name", "")
                + (" " + from_user.get("last_name", "") if from_user.get("last_name") else "")
            ).strip()
            or from_user.get("username", "Unknown"),
            "is_edit": "edited_message" in update,
        }

        if self.on_message:
            try:
                await self.on_message(
                    formatted["platform"],
                    formatted["chat_id"],
                    formatted["user_id"],
                    formatted["text"],
                    {
                        "message_id": formatted.get("message_id"),
                        "chat_type": formatted.get("chat_type", "private"),
                        "user_name": formatted.get("user_name", "Unknown"),
                        "is_edit": formatted.get("is_edit", False),
                    },
                )
            except Exception as e:
                logger.error("on_message handler error: %s", e)
