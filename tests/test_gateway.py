"""Tests for the gateway/pairing system."""

import json
import time
from pathlib import Path

import pytest

from hermes_mobile.gateway.mobile_gateway import (
    CODE_LENGTH,
    CODE_TTL_SECONDS,
    MAX_FAILED_ATTEMPTS,
    MAX_PENDING_PER_PLATFORM,
    RATE_LIMIT_SECONDS,
    ALPHABET,
    PairingCode,
    PairingManager,
    _allowlist_env_for_platform,
    _split_allowlist,
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

    def test_revoke_code(self, manager):
        code = manager.request_pairing("telegram", "user_revoke", "Test")
        assert manager.revoke_code(code.code) is True
        assert code.revoked is True

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
            manager._rate_limits.pop(f"telegram:lockout_user", None)
        manager._save()
        with pytest.raises(ValueError, match="Too many failed"):
            manager.request_pairing("telegram", "lockout_user", "Test")

    def test_is_user_authorized_without_allowlist(self, manager):
        assert manager.is_user_authorized("telegram", "some_user") is False

    def test_is_user_authorized_with_approved_code(self, manager):
        code = manager.request_pairing("telegram", "auth_user", "Auth User")
        manager.approve_code(code.code)
        assert manager.is_user_authorized("telegram", "auth_user") is True

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
