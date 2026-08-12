"""Tests for the in-app Telegram token menu and gateway platform wiring.

Regression coverage for two broken pieces found in the Messaging view:
1. ``GatewayConfig`` was built with ``platforms=[]`` hardcoded, so no
   adapter (Telegram included) ever started.
2. There was no UI to enter the Telegram bot token — the gateway only read
   ``TELEGRAM_BOT_TOKEN`` from the environment, which a phone APK does not
   have. The new ``GatewaySecretStore`` persists the token encrypted in the
   app-private data dir, and ``_start_platform`` falls back to it.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from hermes_mobile.config.settings import HermesMobileSettings, save_settings
from hermes_mobile.gateway.mobile_gateway import GatewayConfig, GatewayManager
from hermes_mobile.remote.secrets import GatewaySecretStore


class TestGatewaySecretStore:
    def test_save_and_get_roundtrip(self, temp_dir):
        store = GatewaySecretStore(temp_dir)
        assert store.get_token() == ""
        store.save_token("123:ABC")
        # A fresh store instance (as on next app start) reads the same token.
        assert GatewaySecretStore(temp_dir).get_token() == "123:ABC"

    def test_save_blank_clears(self, temp_dir):
        store = GatewaySecretStore(temp_dir)
        store.save_token("123:ABC")
        store.save_token("   ")
        assert store.get_token() == ""

    def test_token_is_encrypted_on_disk(self, temp_dir):
        store = GatewaySecretStore(temp_dir)
        store.save_token("123:ABC")
        raw = (temp_dir / "gateway" / "credentials.bin").read_bytes()
        assert b"123:ABC" not in raw


class TestGatewayPlatformWiring:
    def test_settings_default_and_persisted(self, test_settings):
        assert test_settings.gateway_platforms == ["telegram"]
        assert "gateway_platforms" in test_settings.to_dict()
        assert save_settings(test_settings)
        reloaded = HermesMobileSettings(data_dir=test_settings.data_dir).load_persisted()
        assert reloaded.gateway_platforms == ["telegram"]

    async def test_start_platform_uses_stored_token(self, temp_dir, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        manager = GatewayManager(GatewayConfig(enabled=True, platforms=["telegram"]))
        manager.settings = SimpleNamespace(get_data_dir=lambda: str(temp_dir))
        GatewaySecretStore(temp_dir).save_token("stored-token")

        fake = AsyncMock()
        fake.platform_name = "telegram"
        with patch(
            "hermes_mobile.gateway.telegram_adapter.TelegramAdapter",
            return_value=fake,
        ) as adapter_cls:
            await manager._start_platform("telegram")

        adapter_cls.assert_called_once_with(token="stored-token", on_message=manager.handle_message)
        fake.start.assert_awaited()
        assert manager.adapters["telegram"] is fake

    async def test_env_var_wins_over_store(self, temp_dir, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token")
        manager = GatewayManager(GatewayConfig(enabled=True, platforms=["telegram"]))
        manager.settings = SimpleNamespace(get_data_dir=lambda: str(temp_dir))
        GatewaySecretStore(temp_dir).save_token("stored-token")

        fake = AsyncMock()
        with patch(
            "hermes_mobile.gateway.telegram_adapter.TelegramAdapter",
            return_value=fake,
        ) as adapter_cls:
            await manager._start_platform("telegram")

        adapter_cls.assert_called_once_with(token="env-token", on_message=manager.handle_message)

    async def test_missing_token_skips_adapter(self, temp_dir, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        manager = GatewayManager(GatewayConfig(enabled=True, platforms=["telegram"]))
        manager.settings = SimpleNamespace(get_data_dir=lambda: str(temp_dir))

        with patch("hermes_mobile.gateway.telegram_adapter.TelegramAdapter") as adapter_cls:
            await manager._start_platform("telegram")

        adapter_cls.assert_not_called()
        assert "telegram" not in manager.adapters


class _FakePage:
    def __init__(self):
        self.overlay = []
        self.dialogs = []
        self.height = 720
        self.width = 400

    def update(self):
        pass


def _make_gateway_app(temp_dir: str):
    settings = SimpleNamespace(
        runtime_mode="local",
        remote_url="",
        remote_auth_mode="auto",
        remote_username="",
        remote_profile="",
        remote_allow_insecure=False,
        gateway_enabled=False,
        gateway_platforms=["telegram"],
    )
    manager = SimpleNamespace(
        config=SimpleNamespace(
            enabled=False,
            port=8080,
            platforms=["telegram"],
            pairing_enabled=True,
        ),
        _running=False,
    )
    return SimpleNamespace(
        page=_FakePage(),
        settings=settings,
        dark_mode=False,
        remote_mode=False,
        remote_client=None,
        remote_status=None,
        remote_secret_store=None,
        gateway_manager=manager,
        gateway_secret_store=GatewaySecretStore(temp_dir),
        content_area=SimpleNamespace(content=None),
    )


def test_gateway_refresh_preserves_typed_token(temp_dir):
    """_refresh() rebuilds the whole view and used to wipe a token the user
    had pasted but not yet saved (e.g. toggling the gateway switch first)."""
    from hermes_mobile.ui.gateway_view import GatewayView

    app = _make_gateway_app(str(temp_dir))
    view = GatewayView(app)
    view.build()
    assert view._telegram_token_field is not None

    view._telegram_token_field.value = "123:typed"
    view._refresh()

    assert view._telegram_token_field.value == "123:typed"
