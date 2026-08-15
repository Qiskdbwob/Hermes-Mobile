"""Tests for the gateway/pairing system."""

import asyncio
import os
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hermes_mobile.gateway.mobile_gateway import (
    ALPHABET,
    CODE_LENGTH,
    MAX_FAILED_ATTEMPTS,
    MAX_PENDING_PER_PLATFORM,
    BasePlatformAdapter,
    GatewayConfig,
    GatewayManager,
    GatewayStreamConsumer,
    PairingCode,
    PairingManager,
    StreamConsumerConfig,
    _allowlist_env_for_platform,
    _split_allowlist,
    _sync_allowlist_add,
    _sync_allowlist_remove,
    cli_approve,
    cli_list_pending,
    cli_pairing_status,
    cli_revoke,
    get_pairing_manager,
)


class TestPairingCode:
    def test_create_code(self):
        code = PairingCode(
            code="ABC123",
            platform="telegram",
            user_id="user_1",
            user_name="Test User",
            created_at=1000.0,
            expires_at=2000.0,
        )
        assert code.code == "ABC123"
        assert code.platform == "telegram"
        assert code.approved is False
        assert code.revoked is False


class TestPairingManager:
    @pytest.fixture
    def manager(self, temp_dir) -> PairingManager:
        import hermes_mobile.gateway.mobile_gateway as gw

        pairing_dir = temp_dir / "pairing"
        original_fn = gw._get_pairing_dir
        gw._get_pairing_dir = lambda: pairing_dir
        m = PairingManager()
        yield m
        gw._get_pairing_dir = original_fn

    def test_init_creates_dir(self, temp_dir):
        import hermes_mobile.gateway.mobile_gateway as gw

        pairing_dir = temp_dir / "pairing_test"
        original_fn = gw._get_pairing_dir
        gw._get_pairing_dir = lambda: pairing_dir
        PairingManager()
        assert pairing_dir.exists()
        gw._get_pairing_dir = original_fn

    def test_request_pairing(self, manager):
        code = manager.request_pairing("telegram", "user_1", "Test User")
        assert code is not None
        assert len(code.code) == CODE_LENGTH
        assert all(c in ALPHABET for c in code.code)
        assert code.platform == "telegram"
        assert code.user_id == "user_1"

    def test_request_pairing_rate_limit(self, manager):
        code = manager.request_pairing("telegram", "user_2", "Test User")
        assert code is not None
        with pytest.raises(ValueError, match="Rate limited"):
            manager.request_pairing("telegram", "user_2", "Test User")

    def test_approve_code(self, manager):
        code = manager.request_pairing("telegram", "user_3", "Test User")
        assert code.approved is False
        result = manager.approve_code(code.code)
        assert result is True
        assert code.approved is True
        assert code.approved_at is not None

    def test_approve_invalid_code(self, manager):
        assert manager.approve_code("NONEXIST") is False

    def test_approve_expired_code(self, manager):
        code = manager.request_pairing("telegram", "user_expired", "Test")
        code.expires_at = time.time() - 1
        manager._save()
        assert manager.approve_code(code.code) is False

    def test_approve_already_approved(self, manager):
        code = manager.request_pairing("telegram", "user_double", "Test")
        manager.approve_code(code.code)
        assert manager.approve_code(code.code) is True

    def test_revoke_code(self, manager):
        code = manager.request_pairing("telegram", "user_revoke", "Test")
        assert manager.revoke_code(code.code) is True
        assert code.revoked is True

    def test_revoke_code_not_found(self, manager):
        assert manager.revoke_code("NONEXIST") is False

    def test_pending_limit(self, manager):
        for i in range(MAX_PENDING_PER_PLATFORM):
            manager.request_pairing("telegram", f"bulk_user_{i}", f"User {i}")
        with pytest.raises(ValueError, match="Too many pending"):
            manager.request_pairing("telegram", "extra_user", "Extra")

    def test_lockout_after_failures(self, manager):
        for _ in range(MAX_FAILED_ATTEMPTS):
            c = manager.request_pairing("telegram", "lockout_user", "Test")
            c.created_at = time.time() - 10
            c.revoked = True
            manager._record_failed_attempt("telegram", "lockout_user")
            # Reset rate limit so next request_pairing call goes through
            manager._rate_limits.pop("telegram:lockout_user", None)
        manager._save()
        with pytest.raises(ValueError, match="Too many failed"):
            manager.request_pairing("telegram", "lockout_user", "Test")

    def test_is_user_authorized_without_allowlist(self, manager):
        assert manager.is_user_authorized("telegram", "some_user") is False

    def test_is_user_authorized_with_approved_code(self, manager):
        code = manager.request_pairing("telegram", "auth_user", "Auth User")
        manager.approve_code(code.code)
        assert manager.is_user_authorized("telegram", "auth_user") is True

    @patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "user_allow"})
    def test_is_user_authorized_with_allowlist(self, manager):

        assert manager.is_user_authorized("telegram", "user_allow") is True

    def test_get_pending_codes(self, manager):
        manager.request_pairing("telegram", "pending_user_1", "User 1")
        manager.request_pairing("signal", "pending_user_2", "User 2")
        pending = manager.get_pending_codes()
        assert len(pending) >= 2

    def test_get_pending_codes_filtered(self, manager):
        manager.request_pairing("telegram", "filter_user", "User")
        manager.request_pairing("signal", "filter_user_2", "User 2")
        pending = manager.get_pending_codes(platform="telegram")
        assert all(c.platform == "telegram" for c in pending)

    def test_persistence_across_instances(self, temp_dir):
        import hermes_mobile.gateway.mobile_gateway as gw

        pairing_dir = temp_dir / "pairing_persist"
        original_fn = gw._get_pairing_dir
        gw._get_pairing_dir = lambda: pairing_dir

        m1 = PairingManager()
        code = m1.request_pairing("telegram", "persist_user", "Test")
        code_id = code.code
        m1._codes = {}

        m2 = PairingManager()
        assert code_id in m2._codes
        loaded = m2._codes[code_id]
        assert loaded.platform == "telegram"
        assert loaded.user_id == "persist_user"

        gw._get_pairing_dir = original_fn

    def test_cleanup_expired(self, manager):
        code = manager.request_pairing("telegram", "cleanup_user", "Test")
        code.expires_at = time.time() - 1
        manager._save()
        manager.cleanup_expired()
        assert code.code not in manager._codes

    def test_cleanup_expired_no_expired(self, manager):
        manager.request_pairing("telegram", "fresh_user", "Test")
        before = dict(manager._codes)
        manager.cleanup_expired()
        assert manager._codes == before

    def test_load_with_corrupt_files(self, temp_dir):
        import hermes_mobile.gateway.mobile_gateway as gw

        pairing_dir = temp_dir / "pairing_corrupt"
        pairing_dir.mkdir(parents=True, exist_ok=True)
        (pairing_dir / "codes.json").write_text("not valid json")
        (pairing_dir / "rate_limits.json").write_text("not valid json")
        (pairing_dir / "lockouts.json").write_text("not valid json")
        original_fn = gw._get_pairing_dir
        gw._get_pairing_dir = lambda: pairing_dir
        m = PairingManager()
        assert m._codes == {}
        assert m._rate_limits == {}
        assert m._lockouts == {}
        gw._get_pairing_dir = original_fn


class TestAllowlistHelpers:
    def test_allowlist_env_for_platform(self):
        assert _allowlist_env_for_platform("telegram") == "TELEGRAM_ALLOWED_USERS"
        assert _allowlist_env_for_platform("Telegram") == "TELEGRAM_ALLOWED_USERS"
        assert _allowlist_env_for_platform("discord") == "DISCORD_ALLOWED_USERS"
        assert _allowlist_env_for_platform("unknown") is None

    def test_split_allowlist(self):
        assert _split_allowlist("user1, user2, user3") == ["user1", "user2", "user3"]
        assert _split_allowlist("") == []
        assert _split_allowlist("single") == ["single"]

    def test_sync_allowlist_add_no_env_var(self):
        _sync_allowlist_add("unknown_platform", "user_1")

    def test_sync_allowlist_add_empty_allowlist(self):
        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": ""}):
            _sync_allowlist_add("telegram", "user_1")

    def test_sync_allowlist_add_wildcard(self):
        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "*"}):
            _sync_allowlist_add("telegram", "user_1")

    def test_sync_allowlist_add_already_present(self):
        with (
            patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "user_1"}),
            patch("hermes_mobile.gateway.mobile_gateway.Path") as mock_path,
        ):
            mock_instance = MagicMock()
            mock_path.return_value = mock_instance
            mock_instance.exists.return_value = False
            _sync_allowlist_add("telegram", "user_1")

    def test_sync_allowlist_add_new_user(self, temp_dir):
        env_path = temp_dir / ".env"
        env_path.write_text("TELEGRAM_ALLOWED_USERS=existing_user")
        with (
            patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "existing_user"}),
            patch("hermes_mobile.gateway.mobile_gateway.Path") as mock_path,
        ):
            mock_instance = MagicMock()
            mock_instance.exists.return_value = True
            mock_instance.read_text.return_value = env_path.read_text()
            mock_path.return_value = mock_instance
            _sync_allowlist_add("telegram", "new_user")
            written = mock_instance.write_text.call_args[0][0]
            assert "new_user" in written

    def test_sync_allowlist_add_new_env_var(self, temp_dir):
        env_path = temp_dir / ".env"
        env_path.write_text("OTHER_VAR=value")
        with (
            patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "existing_user"}),
            patch("hermes_mobile.gateway.mobile_gateway.Path") as mock_path,
        ):
            mock_instance = MagicMock()
            mock_instance.exists.return_value = True
            mock_instance.read_text.return_value = env_path.read_text()
            mock_path.return_value = mock_instance
            _sync_allowlist_add("telegram", "new_user")
            written = mock_instance.write_text.call_args[0][0]
            assert "TELEGRAM_ALLOWED_USERS" in written

    def test_sync_allowlist_remove_no_env_var(self):
        _sync_allowlist_remove("unknown", "user_1")

    def test_sync_allowlist_remove_empty(self):
        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": ""}):
            _sync_allowlist_remove("telegram", "user_1")

    def test_sync_allowlist_remove_user_not_found(self):
        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "user_a,user_b"}):
            _sync_allowlist_remove("telegram", "user_c")

    def test_sync_allowlist_remove_user(self):
        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "user_a,user_b"}):
            _sync_allowlist_remove("telegram", "user_a")

    def test_get_pairing_dir(self, temp_dir):
        import hermes_mobile.gateway.mobile_gateway as gw

        original_fn = gw._get_pairing_dir
        gw._get_pairing_dir = lambda: temp_dir / "pairing_test"
        try:
            result = gw._get_pairing_dir()
            assert str(result).endswith("pairing_test")
        finally:
            gw._get_pairing_dir = original_fn


def test_get_pairing_manager_singleton():
    pm1 = get_pairing_manager()
    pm2 = get_pairing_manager()
    assert pm1 is pm2


class TestBasePlatformAdapter:
    def test_constructor(self):
        adapter = BasePlatformAdapter({"key": "value"})
        assert adapter.config == {"key": "value"}
        assert adapter.platform_name == "base"

    def test_start_stop(self):
        adapter = BasePlatformAdapter({})
        result_start = asyncio.run(adapter.start())
        assert result_start is None
        result_stop = asyncio.run(adapter.stop())
        assert result_stop is None

    def test_send_message_not_implemented(self):
        adapter = BasePlatformAdapter({})
        with pytest.raises(NotImplementedError):
            asyncio.run(adapter.send_message("chat", "text"))

    def test_edit_message_not_implemented(self):
        adapter = BasePlatformAdapter({})
        with pytest.raises(NotImplementedError):
            asyncio.run(adapter.edit_message("chat", "msg_id", "text"))

    def test_delete_message(self):
        adapter = BasePlatformAdapter({})
        result = asyncio.run(adapter.delete_message("chat", "msg_id"))
        assert result is None

    def test_handle_update(self):
        adapter = BasePlatformAdapter({})
        result = asyncio.run(adapter.handle_update({"key": "value"}))
        assert result is None


class MockAdapter:
    def __init__(self):
        self.sent_messages = []
        self.edited_messages = []

    async def send_message(self, chat_id, text, parse_mode=None, **kwargs):
        self.sent_messages.append((chat_id, text, parse_mode))
        return "msg_1"

    async def edit_message(self, chat_id, message_id, text, parse_mode=None):
        self.edited_messages.append((chat_id, message_id, text, parse_mode))


class TestGatewayStreamConsumer:
    @staticmethod
    def _make_consumer(adapter=None, chat_id="chat_1", config=None, metadata=None):
        if adapter is None:
            adapter = MockAdapter()
        if config is None:
            config = StreamConsumerConfig(
                edit_interval=0.01,
                buffer_threshold=50,
                cursor="▌",
                fresh_message_after=30.0,
                transport="edit",
            )
        return GatewayStreamConsumer(adapter, chat_id, config, metadata or {"user_name": "Test"})

    @staticmethod
    def _make_fast_config():
        return StreamConsumerConfig(
            edit_interval=0.01,
            buffer_threshold=10,
            cursor="▌",
            fresh_message_after=30.0,
            transport="edit",
        )

    async def test_constructor(self):
        config = self._make_fast_config()
        consumer = self._make_consumer(config=config)
        assert consumer.adapter is not None
        assert consumer.chat_id == "chat_1"
        assert consumer.config is config
        assert consumer.metadata == {"user_name": "Test"}
        assert consumer._buffer == ""
        assert consumer._message_id is None
        assert consumer._finished is False

    async def test_on_delta(self):
        consumer = self._make_consumer()
        consumer.on_delta("Hello")
        assert consumer._queue.qsize() == 1
        item = consumer._queue.get_nowait()
        assert item == "Hello"

    async def test_on_tool_start(self):
        consumer = self._make_consumer()
        consumer.on_tool_start("search", {"q": "test"})
        assert consumer._queue.qsize() == 2
        consumer._queue.get_nowait()
        item = consumer._queue.get_nowait()
        assert "search" in item

    async def test_on_tool_result_with_error(self):
        consumer = self._make_consumer()
        consumer.on_tool_result("search", None, error="Failed")
        assert consumer._queue.qsize() == 1
        item = consumer._queue.get_nowait()
        assert "search failed" in item

    async def test_on_tool_result_success(self):
        consumer = self._make_consumer()
        consumer.on_tool_result("search", "Found 10 results")
        assert consumer._queue.qsize() == 1
        item = consumer._queue.get_nowait()
        assert "search completed" in item

    async def test_on_tool_result_truncated(self):
        consumer = self._make_consumer()
        long_result = "x" * 1000
        consumer.on_tool_result("search", long_result)
        item = consumer._queue.get_nowait()
        assert "..." in item

    async def test_on_commentary(self):
        consumer = self._make_consumer()
        consumer.on_commentary("thinking...")
        assert consumer._queue.qsize() == 2
        consumer._queue.get_nowait()
        item = consumer._queue.get_nowait()
        assert item == "thinking..."

    async def test_flush_pending_sync(self):
        consumer = self._make_consumer()
        event = consumer.flush_pending_sync()
        assert isinstance(event, threading.Event)

    async def test_finish(self):
        consumer = self._make_consumer()
        consumer.finish()
        assert consumer._queue.qsize() == 1
        item = consumer._queue.get_nowait()
        import hermes_mobile.gateway.mobile_gateway as gw

        assert item is gw._DONE

    async def test_run_empty(self):
        consumer = self._make_consumer()
        consumer.finish()
        result = await consumer.run()
        # No delta was sent, so _message_id remained None
        assert result is None

    async def test_run_with_delta(self):
        adapter = MockAdapter()
        consumer = self._make_consumer(adapter=adapter)
        consumer.on_delta("Hello world")
        consumer.finish()
        result = await consumer.run()
        assert result == "msg_1"
        assert len(adapter.sent_messages) == 1
        chat_id, text, parse_mode = adapter.sent_messages[0]
        assert chat_id == "chat_1"
        assert "Hello world" in text
        assert parse_mode == "markdown"

    async def test_run_cursor_removed_on_finish(self):
        adapter = MockAdapter()
        consumer = self._make_consumer(adapter=adapter)
        consumer.on_delta("Final")
        consumer.finish()
        await consumer.run()
        final_text = adapter.edited_messages[-1][2] if adapter.edited_messages else ""
        if not final_text:
            final_text = adapter.sent_messages[0][1] if adapter.sent_messages else ""
        assert "▌" not in final_text

    async def test_run_buffer_threshold_triggers_edit(self):
        adapter = MockAdapter()
        consumer = self._make_consumer(adapter=adapter)
        text = "x" * 60
        consumer.on_delta(text)
        consumer.finish()
        await consumer.run()
        assert len(adapter.sent_messages) >= 1

    async def test_run_new_segment(self):
        adapter = MockAdapter()
        consumer = self._make_consumer(adapter=adapter)
        consumer.on_delta("part one")
        consumer.on_tool_start("tool_name", {"arg": 1})
        consumer.on_delta("part two")
        consumer.finish()
        await consumer.run()
        assert len(adapter.sent_messages) >= 1

    async def test_run_flush(self):
        adapter = MockAdapter()
        consumer = self._make_consumer(adapter=adapter)
        consumer.on_delta("flush test")
        event = consumer.flush_pending_sync()
        consumer.finish()
        await consumer.run()
        assert event.is_set()

    async def test_run_commentary(self):
        adapter = MockAdapter()
        consumer = self._make_consumer(adapter=adapter)
        consumer.on_commentary("I'm thinking")
        consumer.on_delta("result")
        consumer.finish()
        await consumer.run()
        assert len(adapter.sent_messages) >= 1

    async def test_run_edit_failure_disables_progressive(self):
        failing_adapter = MagicMock()
        failing_adapter.send_message = AsyncMock(side_effect=Exception("API error"))
        failing_adapter.edit_message = AsyncMock()
        consumer = self._make_consumer(adapter=failing_adapter, config=self._make_fast_config())
        consumer.on_delta("hello " * 20)
        consumer.finish()
        await consumer.run()


class TestGatewayManager:
    @pytest.fixture(autouse=True)
    def _isolate_pairing_dir(self, temp_dir):
        """Isolate pairing manager to a temp directory."""
        import hermes_mobile.gateway.mobile_gateway as gw

        original_fn = gw._get_pairing_dir
        gw._get_pairing_dir = lambda: temp_dir / "pairing"
        gw._pairing_manager = None
        yield
        gw._get_pairing_dir = original_fn

    @pytest.fixture
    def config(self) -> GatewayConfig:
        return GatewayConfig(enabled=False)

    def test_constructor(self, config):
        manager = GatewayManager(config)
        assert manager.config is config
        assert manager._running is False
        assert manager.adapters == {}

    @patch("hermes_mobile.gateway.mobile_gateway.create_mobile_agent")
    @patch("hermes_mobile.gateway.mobile_gateway.MobileMemoryProvider")
    def test_initialize(self, mock_memory, mock_agent, config):
        mock_memory_instance = MagicMock()
        mock_memory.return_value = mock_memory_instance
        mock_settings = MagicMock()
        mock_settings.get_memory_db_path.return_value = ":memory:"
        mock_settings.encrypt_memory = False
        config.settings = mock_settings

        manager = GatewayManager(config)
        manager.settings = mock_settings
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(manager.initialize())
        finally:
            loop.close()

    async def test_start_disabled(self, config):
        manager = GatewayManager(config)
        await manager.start()
        assert manager._running is False

    @patch("hermes_mobile.gateway.mobile_gateway.create_mobile_agent")
    @patch("hermes_mobile.gateway.mobile_gateway.MobileMemoryProvider")
    async def test_stop(self, mock_memory, mock_agent):
        cfg = GatewayConfig(enabled=False)
        manager = GatewayManager(cfg)
        mock_adapter = AsyncMock()
        mock_adapter.stop = AsyncMock()
        manager.adapters = {"telegram": mock_adapter}
        mock_mem = MagicMock()
        manager.memory_provider = mock_mem
        await manager.stop()
        assert manager._running is False
        mock_adapter.stop.assert_awaited_once()
        mock_mem.close.assert_called_once()

    @patch("hermes_mobile.gateway.mobile_gateway.create_mobile_agent")
    @patch("hermes_mobile.gateway.mobile_gateway.MobileMemoryProvider")
    async def test_handle_message_unauthorized_starts_pairing(self, mock_memory, mock_agent):
        import hermes_mobile.gateway.mobile_gateway as gw

        gw._pairing_manager = None
        cfg = GatewayConfig(enabled=False)
        manager = GatewayManager(cfg)
        manager.pairing_manager = get_pairing_manager()
        mock_adapter = AsyncMock()
        mock_adapter.send_message = AsyncMock(return_value="msg_1")
        manager.adapters = {"telegram": mock_adapter}

        await manager.handle_message(
            "telegram", "chat_1", "unknown_user", "hello", {"user_name": "New User"}
        )
        # Should have tried to send pairing message
        assert mock_adapter.send_message.called

    @patch("hermes_mobile.gateway.mobile_gateway.create_mobile_agent")
    @patch("hermes_mobile.gateway.mobile_gateway.MobileMemoryProvider")
    async def test_handle_message_no_adapter(self, mock_memory, mock_agent):
        import hermes_mobile.gateway.mobile_gateway as gw

        gw._pairing_manager = None
        cfg = GatewayConfig(enabled=False)
        manager = GatewayManager(cfg)
        manager.pairing_manager = get_pairing_manager()
        # Mark user as authorized
        code = manager.pairing_manager.request_pairing("telegram", "auth_usr", "Test")
        manager.pairing_manager.approve_code(code.code)

        await manager.handle_message("telegram", "chat_1", "auth_usr", "hello", {})
        # No adapter registered, should log error but not crash

    @patch("hermes_mobile.gateway.mobile_gateway.create_mobile_agent")
    @patch("hermes_mobile.gateway.mobile_gateway.MobileMemoryProvider")
    async def test_telegram_adapter_wires_into_handle_message(self, mock_memory, mock_agent):
        """Regression: the adapter must unpack update fields into the manager's
        positional signature. Previously it passed a single dict, so every
        Telegram message died with TypeError."""
        import hermes_mobile.gateway.mobile_gateway as gw

        gw._pairing_manager = None
        manager = GatewayManager(GatewayConfig(enabled=False))
        manager.pairing_manager = get_pairing_manager()
        mock_adapter = AsyncMock()
        mock_adapter.send_message = AsyncMock(return_value="msg_1")
        manager.adapters = {"telegram": mock_adapter}

        from hermes_mobile.gateway.telegram_adapter import TelegramAdapter

        tg = TelegramAdapter(token="test:token", on_message=manager.handle_message)
        update = {
            "update_id": 1,
            "message": {
                "message_id": 10,
                "text": "hello",
                "chat": {"id": 123, "type": "private"},
                "from": {"id": 456, "first_name": "John"},
            },
        }

        await tg._process_update(update)

        # Unauthorized user -> pairing code message sent through the adapter.
        assert mock_adapter.send_message.called

    @patch("hermes_mobile.gateway.mobile_gateway.create_mobile_agent")
    @patch("hermes_mobile.gateway.mobile_gateway.MobileMemoryProvider")
    def test_send_pairing_message_no_adapter(self, mock_memory, mock_agent):
        cfg = GatewayConfig(enabled=False)
        manager = GatewayManager(cfg)
        code = PairingCode(
            code="TESTCODE",
            platform="telegram",
            user_id="user",
            user_name="Test",
            created_at=time.time(),
            expires_at=time.time() + 3600,
        )
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                manager._send_pairing_message("telegram", "chat_1", code)
            )
            assert result is None
        finally:
            loop.close()


class TestCLIHelpers:
    @pytest.fixture(autouse=True)
    def _isolate_pairing_dir(self, temp_dir):
        """Isolate pairing manager to a temp directory."""
        import hermes_mobile.gateway.mobile_gateway as gw

        original_fn = gw._get_pairing_dir
        gw._get_pairing_dir = lambda: temp_dir / "pairing"
        gw._pairing_manager = None
        yield
        gw._get_pairing_dir = original_fn

    def _fresh_manager(self):
        import hermes_mobile.gateway.mobile_gateway as gw

        gw._pairing_manager = None
        return get_pairing_manager()

    def test_cli_approve(self):

        pm = self._fresh_manager()
        code = pm.request_pairing("telegram", "cli_user", "Test")
        assert cli_approve(code.code) is True
        assert code.approved is True

    def test_cli_revoke(self):
        pm = self._fresh_manager()
        code = pm.request_pairing("telegram", "cli_revoke_user", "Test")
        assert cli_revoke(code.code) is True
        assert code.revoked is True

    def test_cli_list_pending(self):
        pm = self._fresh_manager()
        pm.request_pairing("telegram", "cli_list_user", "Test")
        pending = cli_list_pending()
        assert any(c.user_id == "cli_list_user" for c in pending)

    def test_cli_list_pending_filtered(self):
        pm = self._fresh_manager()
        pm.request_pairing("signal", "cli_signal_user", "Test")
        pending = cli_list_pending(platform="signal")
        assert all(c.platform == "signal" for c in pending)

    def test_cli_pairing_status(self):
        pm = self._fresh_manager()
        code = pm.request_pairing("telegram", "cli_status_user", "Test")
        assert cli_pairing_status("telegram", "cli_status_user") is False
        pm.approve_code(code.code)
        assert cli_pairing_status("telegram", "cli_status_user") is True


class TestGatewayMisc:
    """Additional gateway tests for uncovered edge cases."""

    @pytest.fixture(autouse=True)
    def _isolate_pairing_dir(self, temp_dir):
        """Isolate pairing manager to a temp directory."""
        import hermes_mobile.gateway.mobile_gateway as gw

        original_fn = gw._get_pairing_dir
        gw._get_pairing_dir = lambda: temp_dir / "pairing_misc"
        gw._pairing_manager = None
        yield
        gw._get_pairing_dir = original_fn

    @patch("hermes_mobile.gateway.mobile_gateway.os.getenv")
    def test_sync_allowlist_add_write_exception(self, mock_getenv):
        """_sync_allowlist_add handles .env write failure gracefully."""
        mock_getenv.side_effect = lambda k, d="": (
            "HERMES_TELEGRAM_ALLOWLIST" if k == "HERMES_TELEGRAM_ALLOWLIST" else d
        )
        # Neither .env exists nor env var is writable — should not crash
        _sync_allowlist_add("telegram", "new_user")
        # line 91-92: exception handler — at minimum does not raise

    @patch("hermes_mobile.gateway.mobile_gateway.os.getenv")
    def test_sync_allowlist_remove_approved_flow(self, mock_getenv):
        """_sync_allowlist_remove called from revoke_code for approved code."""
        from hermes_mobile.gateway.mobile_gateway import _sync_allowlist_remove

        mock_getenv.side_effect = lambda k, d="": (
            "HERMES_TEST_ALLOWLIST" if k == "HERMES_TEST_ALLOWLIST" else d
        )
        # Should not crash when allowlist env is set but no .env file exists
        _sync_allowlist_remove("telegram", "some_user")

    @patch("hermes_mobile.gateway.mobile_gateway.create_mobile_agent")
    @patch("hermes_mobile.gateway.mobile_gateway.MobileMemoryProvider")
    async def test_handle_message_with_agent_error(self, mock_memory, mock_agent):
        """GatewayManager.handle_message handles agent errors gracefully."""
        import hermes_mobile.gateway.mobile_gateway as gw

        gw._pairing_manager = None
        cfg = GatewayConfig(enabled=False)
        manager = GatewayManager(cfg)
        manager.pairing_manager = get_pairing_manager()
        # Authorize user
        code = manager.pairing_manager.request_pairing("telegram", "auth_user", "Test")
        manager.pairing_manager.approve_code(code.code)

        mock_adapter = AsyncMock()
        mock_adapter.send_message = AsyncMock(return_value="msg_1")
        manager.adapters = {"telegram": mock_adapter}

        # Mock agent to raise an error during streaming
        class _RaisingAsyncGen:
            """Async generator that raises on first iteration."""

            def __aiter__(self):
                return self

            async def __anext__(self):
                raise ValueError("API error")

        mock_agent_instance = MagicMock()
        mock_agent_instance.run_conversation = MagicMock(return_value=_RaisingAsyncGen())
        manager.agent = mock_agent_instance

        await manager.handle_message("telegram", "chat_1", "auth_user", "hello", {})
        # Should send error message back
        mock_adapter.send_message.assert_called()
        error_call_args = mock_adapter.send_message.call_args
        assert "Error" in str(error_call_args)

    @patch("hermes_mobile.gateway.mobile_gateway.create_mobile_agent")
    @patch("hermes_mobile.gateway.mobile_gateway.MobileMemoryProvider")
    async def test_stop_with_tasks(self, mock_memory, mock_agent):
        """GatewayManager.stop cancels background tasks."""
        cfg = GatewayConfig(enabled=False)
        manager = GatewayManager(cfg)

        # Add a mock task that will be cancelled
        async def never_ending():
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                raise

        task = asyncio.create_task(never_ending())
        manager._tasks.append(task)
        manager._running = True

        await manager.stop()
        assert manager._running is False
        assert task.cancelled()

    async def test_gateway_consumer_finalize_edit_error(self):
        """GatewayStreamConsumer._finalize handles edit error gracefully."""
        adapter = AsyncMock()
        adapter.send_message = AsyncMock(return_value="msg_1")
        adapter.edit_message = AsyncMock(side_effect=Exception("edit failed"))

        config = StreamConsumerConfig(
            edit_interval=0.01,
            buffer_threshold=50,
            cursor="▌",
            fresh_message_after=30.0,
            transport="edit",
        )
        consumer = GatewayStreamConsumer(adapter, "chat_1", config, {})
        consumer.on_delta("Hello world")
        consumer.finish()
        result = await consumer.run()
        # Should not crash — edit error is caught by except Exception
        assert result is not None
