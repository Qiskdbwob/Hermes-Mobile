"""Tests for Telegram adapter."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hermes_mobile.gateway.telegram_adapter import (
    MAX_RETRY_DELAY,
    POLL_TIMEOUT,
    RETRY_DELAY,
    TelegramAdapter,
)


@pytest.fixture
def adapter():
    return TelegramAdapter(token="test:token")


class TestInit:
    def test_stores_token(self):
        a = TelegramAdapter(token="abc123")
        assert a._token == "abc123"
        assert "abc123" in a._base_url

    def test_initial_state(self, adapter):
        assert adapter._running is False
        assert adapter._offset == 0
        assert adapter._task is None
        assert adapter._client is None
        assert adapter.on_message is None

    def test_on_message_callback(self):
        cb = MagicMock()
        a = TelegramAdapter(token="x", on_message=cb)
        assert a.on_message is cb


class TestStart:
    @patch.object(TelegramAdapter, "_api")
    async def test_starts_successfully(self, mock_api, adapter):
        mock_api.return_value = {"ok": True, "result": {"username": "TestBot"}}

        await adapter.start()

        assert adapter._running is True
        assert adapter._client is not None
        assert adapter._task is not None
        mock_api.assert_awaited_with("getMe")

    @patch.object(TelegramAdapter, "_api")
    async def test_handles_failed_get_me(self, mock_api, adapter):
        mock_api.return_value = {"ok": False, "error": "unauthorized"}

        await adapter.start()

        assert adapter._running is True
        assert adapter._task is not None

    @patch.object(TelegramAdapter, "_api")
    async def test_creates_client_with_timeout(self, mock_api, adapter):
        with patch("hermes_mobile.gateway.telegram_adapter.httpx.AsyncClient") as mock_cls:
            mock_api.return_value = {"ok": True, "result": {"username": "Bot"}}
            await adapter.start()
            mock_cls.assert_called_once_with(timeout=POLL_TIMEOUT + 10)


class TestStop:
    @patch.object(TelegramAdapter, "_api")
    async def test_stops_cleanly(self, mock_api, adapter):
        mock_api.return_value = {"ok": True, "result": {}}

        await adapter.start()
        assert adapter._running is True

        await adapter.stop()
        assert adapter._running is False
        assert adapter._client is None

    async def test_stop_idempotent(self, adapter):
        await adapter.stop()
        assert adapter._running is False


class TestSendMessage:
    @patch.object(TelegramAdapter, "_api")
    async def test_sends_successfully(self, mock_api, adapter):
        mock_api.return_value = {"ok": True, "result": {"message_id": 42}}

        msg_id = await adapter.send_message(chat_id=123, text="Hello")
        assert msg_id == 42
        mock_api.assert_awaited_with(
            "sendMessage",
            chat_id=123,
            text="Hello",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    @patch.object(TelegramAdapter, "_api")
    async def test_returns_none_on_failure(self, mock_api, adapter):
        mock_api.return_value = {"ok": False}

        msg_id = await adapter.send_message(chat_id=123, text="Hi")
        assert msg_id is None

    @patch.object(TelegramAdapter, "_api")
    async def test_truncates_long_text(self, mock_api, adapter):
        mock_api.return_value = {"ok": True, "result": {"message_id": 1}}

        long_text = "x" * 5000
        await adapter.send_message(chat_id=1, text=long_text)
        called_text = mock_api.call_args[1]["text"]
        assert len(called_text) == 4096


class TestEditMessage:
    @patch.object(TelegramAdapter, "_api")
    async def test_edits_successfully(self, mock_api, adapter):
        mock_api.return_value = {"ok": True}

        result = await adapter.edit_message(chat_id=123, message_id=5, text="Updated")
        assert result is True

    @patch.object(TelegramAdapter, "_api")
    async def test_edit_failure(self, mock_api, adapter):
        mock_api.return_value = {"ok": False}

        result = await adapter.edit_message(chat_id=123, message_id=5, text="Nope")
        assert result is False

    @patch.object(TelegramAdapter, "_api")
    async def test_truncates_long_text(self, mock_api, adapter):
        mock_api.return_value = {"ok": True}

        long_text = "x" * 5000
        await adapter.edit_message(chat_id=1, message_id=1, text=long_text)
        called_text = mock_api.call_args[1]["text"]
        assert len(called_text) == 4096


class TestApi:
    async def test_sends_post_to_correct_url(self, adapter):
        with patch.object(adapter, "_client") as mock_client:
            mock_client.post = AsyncMock()
            mock_client.post.return_value.json = MagicMock(return_value={"ok": True})

            result = await adapter._api("getMe")
            assert result == {"ok": True}
            mock_client.post.assert_called_once_with(
                "https://api.telegram.org/bottest:token/getMe",
                json={},
            )

    async def test_excludes_none_values(self, adapter):
        mock_client = MagicMock()
        mock_client.post = AsyncMock()
        mock_client.post.return_value.json = MagicMock(return_value={"ok": True})
        adapter._client = mock_client

        await adapter._api("sendMessage", chat_id=1, text="hi", extra=None)
        called_json = mock_client.post.call_args[1]["json"]
        assert "chat_id" in called_json
        assert "text" in called_json
        assert "extra" not in called_json

    async def test_retries_on_timeout(self, adapter):
        import httpx

        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        adapter._client = mock_client

        result = await adapter._api("getMe")
        assert result["ok"] is False
        assert mock_client.post.call_count >= 1

    @patch("asyncio.sleep", return_value=None)
    async def test_retries_on_generic_exception(self, mock_sleep, adapter):
        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=ValueError("connection error"))
        adapter._client = mock_client

        result = await adapter._api("getMe")
        assert result["ok"] is False
        assert "connection error" in result.get("error", "").lower()
        assert mock_client.post.call_count == 3

    async def test_creates_client_on_demand(self, adapter):
        with patch("hermes_mobile.gateway.telegram_adapter.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.post = AsyncMock()
            mock_client.post.return_value.json = MagicMock(return_value={"ok": True})
            mock_cls.return_value = mock_client

            assert adapter._client is None
            result = await adapter._api("getMe")
            assert result == {"ok": True}
            assert adapter._client is not None


class TestProcessUpdate:
    @patch.object(TelegramAdapter, "_api")
    async def test_ignores_update_without_message(self, mock_api, adapter):
        cb = AsyncMock()
        adapter.on_message = cb

        await adapter._process_update({"update_id": 1})
        cb.assert_not_called()

    @patch.object(TelegramAdapter, "_api")
    async def test_processes_text_message(self, mock_api, adapter):
        cb = AsyncMock()
        adapter.on_message = cb

        update = {
            "update_id": 1,
            "message": {
                "message_id": 10,
                "text": "hello world",
                "chat": {"id": 123, "type": "private"},
                "from": {
                    "id": 456,
                    "first_name": "John",
                    "last_name": "Doe",
                    "username": "jdoe",
                },
            },
        }

        await adapter._process_update(update)
        cb.assert_awaited_once()
        args = cb.call_args[0][0]
        assert args["platform"] == "telegram"
        assert args["chat_id"] == "123"
        assert args["user_id"] == "456"
        assert args["text"] == "hello world"
        assert args["message_id"] == 10
        assert args["user_name"] == "John Doe"
        assert args["is_edit"] is False

    @patch.object(TelegramAdapter, "_api")
    async def test_processes_edited_message(self, mock_api, adapter):
        cb = AsyncMock()
        adapter.on_message = cb

        update = {
            "update_id": 2,
            "edited_message": {
                "message_id": 11,
                "text": "edited text",
                "chat": {"id": 789, "type": "group"},
                "from": {"id": 111, "first_name": "Alice"},
            },
        }

        await adapter._process_update(update)
        cb.assert_awaited_once()
        args = cb.call_args[0][0]
        assert args["text"] == "edited text"
        assert args["chat_id"] == "789"
        assert args["is_edit"] is True

    @patch.object(TelegramAdapter, "_api")
    async def test_handles_caption_as_text(self, mock_api, adapter):
        cb = AsyncMock()
        adapter.on_message = cb

        update = {
            "update_id": 3,
            "message": {
                "message_id": 12,
                "caption": "photo caption",
                "chat": {"id": 1, "type": "private"},
                "from": {"id": 2, "first_name": "User"},
            },
        }

        await adapter._process_update(update)
        assert cb.call_args[0][0]["text"] == "photo caption"

    @patch.object(TelegramAdapter, "_api")
    async def test_skips_missing_text_and_chat_id(self, mock_api, adapter):
        cb = AsyncMock()
        adapter.on_message = cb

        await adapter._process_update(
            {
                "update_id": 4,
                "message": {"message_id": 13, "chat": {}, "from": {}},
            }
        )
        cb.assert_not_called()

    @patch.object(TelegramAdapter, "_api")
    async def test_handles_on_message_exception(self, mock_api, adapter):
        cb = AsyncMock(side_effect=ValueError("handler error"))
        adapter.on_message = cb

        update = {
            "update_id": 5,
            "message": {
                "message_id": 14,
                "text": "hi",
                "chat": {"id": 1, "type": "private"},
                "from": {"id": 2, "first_name": "U"},
            },
        }

        # Should not raise
        await adapter._process_update(update)
        cb.assert_awaited_once()

    @patch.object(TelegramAdapter, "_api")
    async def test_user_name_fallback(self, mock_api, adapter):
        cb = AsyncMock()
        adapter.on_message = cb

        update = {
            "update_id": 6,
            "message": {
                "message_id": 15,
                "text": "test",
                "chat": {"id": 1, "type": "private"},
                "from": {"id": 2},
            },
        }

        await adapter._process_update(update)
        assert cb.call_args[0][0]["user_name"] == "Unknown"


class TestPollLoop:
    @patch.object(TelegramAdapter, "_api")
    async def test_polls_and_processes_updates(self, mock_api, adapter):
        process_mock = AsyncMock()
        adapter._process_update = process_mock

        calls = 0

        async def api_side_effect(method, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {
                    "ok": True,
                    "result": [
                        {
                            "update_id": 1,
                            "message": {"text": "a", "chat": {"id": 1}, "from": {"id": 1}},
                        },
                        {
                            "update_id": 2,
                            "message": {"text": "b", "chat": {"id": 2}, "from": {"id": 2}},
                        },
                    ],
                }
            adapter._running = False
            return {"ok": True, "result": []}

        mock_api.side_effect = api_side_effect
        adapter._running = True
        await adapter._poll_loop()

        assert process_mock.call_count == 2
        assert adapter._offset == 3

    async def test_stops_when_not_running(self, adapter):
        adapter._running = False
        await adapter._poll_loop()  # Should return immediately
        assert True
