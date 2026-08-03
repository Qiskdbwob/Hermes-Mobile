"""Tests for MemoryProvider."""

from hermes_mobile.core.agent import Message, ToolCall
from hermes_mobile.memory.provider import MobileMemoryProvider


class TestMobileMemoryProvider:
    def test_init_creates_db(self, temp_dir):
        db_path = temp_dir / "memory.db"
        mp = MobileMemoryProvider(db_path=db_path, encrypt=False)
        assert db_path.exists()
        mp.close()

    def test_init_with_encryption(self, temp_dir):
        db_path = temp_dir / "encrypted.db"
        mp = MobileMemoryProvider(db_path=db_path, encrypt=True, encryption_key="test-key-123")
        assert db_path.exists()
        mp.close()

    def test_init_with_device_based_encryption(self, temp_dir):
        db_path = temp_dir / "device_encrypted.db"
        mp = MobileMemoryProvider(db_path=db_path, encrypt=True)
        key_path = db_path.with_suffix(".db.key")
        assert db_path.exists()
        assert key_path.exists()
        assert key_path.stat().st_mode & 0o777 == 0o600
        mp.close()

    async def test_device_key_survives_hostname_changes(self, temp_dir, monkeypatch):
        db_path = temp_dir / "stable_device.db"
        monkeypatch.setattr("platform.node", lambda: "android-boot-one")
        first = MobileMemoryProvider(db_path=db_path, encrypt=True)
        await first.add_memory_entry("stable", "Survives reboot")
        first.close()

        monkeypatch.setattr("platform.node", lambda: "android-boot-two")
        second = MobileMemoryProvider(db_path=db_path, encrypt=True)
        results = await second.search_memory("Survives")
        second.close()

        assert results[0]["content"] == "Survives reboot"

    def test_legacy_device_ciphertext_remains_readable(self, temp_dir, monkeypatch):
        from cryptography.fernet import Fernet

        monkeypatch.setattr("platform.node", lambda: "legacy-node")
        monkeypatch.setattr("platform.machine", lambda: "legacy-machine")
        legacy_key = MobileMemoryProvider._derive_fernet_key("legacy-nodelegacy-machine")
        legacy_token = Fernet(legacy_key).encrypt(b"legacy memory").decode()

        provider = MobileMemoryProvider(db_path=temp_dir / "migration.db", encrypt=True)
        try:
            assert provider._decrypt(legacy_token) == "legacy memory"
        finally:
            provider.close()

    async def test_get_stats_empty_db(self, memory_provider):
        stats = await memory_provider.get_stats()
        assert isinstance(stats, dict)
        assert stats["conversations"] == 0
        assert stats["memory_entries"] == 0
        assert stats["skill_memory_entries"] == 0

    async def test_save_and_get_conversations(self, memory_provider):
        messages = [
            Message.user("Hello"),
            Message.assistant("Hi there!"),
            Message.user("How are you?"),
            Message.assistant("I'm doing great!"),
        ]
        session_id = "test-session-1"
        await memory_provider.save_conversation(session_id, messages)

        convos = await memory_provider.get_conversation(session_id)
        assert len(convos) == 4
        assert convos[0]["role"] == "user"
        assert convos[0]["content"] == "Hello"
        assert convos[1]["role"] == "assistant"
        assert convos[1]["content"] == "Hi there!"

    async def test_save_conversation_with_tool_calls(self, memory_provider):
        tc = ToolCall(name="web_search", arguments={"query": "test"})
        messages = [
            Message.user("Search the web"),
            Message.assistant("Searching...", tool_calls=[tc]),
            Message.tool(content='{"results": []}', tool_call_id=tc.call_id, name="web_search"),
        ]
        session_id = "test-session-tools"
        await memory_provider.save_conversation(session_id, messages)

        convos = await memory_provider.get_conversation(session_id)
        assert len(convos) == 3
        assert convos[1]["role"] == "assistant"

    async def test_get_stats_reflects_data(self, memory_provider):
        await memory_provider.add_memory_entry(session_id="stats-test", content="Stat test entry")
        stats = await memory_provider.get_stats()
        assert stats["memory_entries"] >= 1

    async def test_add_and_search_memory_entry(self, memory_provider):
        await memory_provider.add_memory_entry(
            session_id="mem-session-1",
            content="The user likes Python programming",
        )

        results = await memory_provider.search_memory("Python programming")
        assert len(results) >= 1
        assert results[0]["content"] == "The user likes Python programming"

    async def test_search_memory_by_keyword(self, memory_provider):
        await memory_provider.add_memory_entry(
            session_id="mem-session-2",
            content="User works with React and TypeScript",
        )
        await memory_provider.add_memory_entry(
            session_id="mem-session-2",
            content="User enjoys hiking on weekends",
        )

        results = await memory_provider.search_memory("React")
        assert len(results) >= 1
        assert "React" in results[0]["content"]

        results = await memory_provider.search_memory("hiking")
        assert len(results) >= 1
        assert "hiking" in results[0]["content"]

        results = await memory_provider.search_memory("zzz_nonexistent_zzz")
        assert len(results) == 0

    async def test_memory_expiration(self, memory_provider):
        await memory_provider.add_memory_entry(
            session_id="expire-test",
            content="This will expire",
            ttl_days=-1,  # Negative TTL = already expired
        )
        await memory_provider.add_memory_entry(
            session_id="expire-test",
            content="This will stay",
            ttl_days=30,
        )

        await memory_provider.cleanup_expired()

        results = await memory_provider.search_memory("will")
        assert len(results) == 1
        assert results[0]["content"] == "This will stay"

    async def test_skill_memory_operations(self, memory_provider):
        await memory_provider.set_skill_memory(
            skill_name="test_skill",
            key="user_count",
            value=42,
            ttl_days=1,
        )

        value = await memory_provider.get_skill_memory("test_skill", "user_count")
        assert value == 42

        value = await memory_provider.get_skill_memory("test_skill", "nonexistent")
        assert value is None

    async def test_get_relevant_context(self, memory_provider):
        await memory_provider.add_memory_entry(
            session_id="ctx-test", content="User prefers dark mode"
        )
        context = await memory_provider.get_relevant_context("dark mode")
        assert "dark mode" in context.lower()

    def test_multiple_providers_different_dbs(self, temp_dir):
        db1 = temp_dir / "db1.db"
        db2 = temp_dir / "db2.db"
        mp1 = MobileMemoryProvider(db_path=db1, encrypt=False)
        mp2 = MobileMemoryProvider(db_path=db2, encrypt=False)
        assert db1.exists()
        assert db2.exists()
        assert db1 != db2
        mp1.close()
        mp2.close()

    def test_close_twice_no_error(self, memory_provider):
        memory_provider.close()
        memory_provider.close()

    async def test_save_empty_conversation(self, memory_provider):
        session_id = "empty-session"
        await memory_provider.save_conversation(session_id, [])
        convos = await memory_provider.get_conversation(session_id)
        assert len(convos) == 0

    async def test_encryption_roundtrip(self, temp_dir):
        db_path = temp_dir / "enc_roundtrip.db"
        mp = MobileMemoryProvider(db_path=db_path, encrypt=True, encryption_key="test-key")
        await mp.add_memory_entry(session_id="enc-test", content="Secret data")
        results = await mp.search_memory("Secret")
        assert len(results) >= 1
        assert results[0]["content"] == "Secret data"
        mp.close()

    async def test_save_conversation_with_encryption(self, temp_dir):
        db_path = temp_dir / "conv_enc.db"
        mp = MobileMemoryProvider(db_path=db_path, encrypt=True, encryption_key="test-key")
        messages = [Message.user("Hello"), Message.assistant("Hi!")]
        await mp.save_conversation("enc-conv", messages)
        convos = await mp.get_conversation("enc-conv")
        assert len(convos) == 2
        assert convos[0]["content"] == "Hello"
        assert convos[1]["content"] == "Hi!"
        mp.close()

    async def test_save_conversation_dedup(self, memory_provider):
        msg = Message.user("Duplicate")
        session_id = "dedup-session"
        await memory_provider.save_conversation(session_id, [msg])
        await memory_provider.save_conversation(session_id, [msg])
        convos = await memory_provider.get_conversation(session_id)
        assert len(convos) == 1

    async def test_get_relevant_context_no_match(self, memory_provider):
        await memory_provider.add_memory_entry(
            session_id="ctx-test", content="User prefers dark mode"
        )
        context = await memory_provider.get_relevant_context("nonexistent_zzz")
        assert context == ""

    async def test_get_conn_reconnects_after_close(self, memory_provider):
        memory_provider._conn = None
        conn = memory_provider._get_conn()
        assert conn is not None

    async def test_set_skill_memory_with_encryption(self, temp_dir):
        db_path = temp_dir / "skill_enc.db"
        mp = MobileMemoryProvider(db_path=db_path, encrypt=True, encryption_key="test-key")
        await mp.set_skill_memory(skill_name="enc_skill", key="secret", value="hidden")
        result = await mp.get_skill_memory("enc_skill", "secret")
        assert result == "hidden"
        mp.close()

    async def test_skill_memory_non_json_value(self, temp_dir):
        mp = MobileMemoryProvider(db_path=temp_dir / "skill_raw2.db", encrypt=False)
        mp._get_conn().execute(
            "INSERT INTO skill_memory (id, skill_name, key, value, created_at) VALUES (?, ?, ?, ?, ?)",
            ("raw:key", "raw_skill", "key", "not-json-string", "2024-01-01T00:00:00"),
        )
        mp._get_conn().commit()
        result = await mp.get_skill_memory("raw_skill", "key")
        assert result == "not-json-string"

    def test_encrypt_no_fernet_returns_data(self, temp_dir):
        mp = MobileMemoryProvider(db_path=temp_dir / "no_fernet.db", encrypt=False)
        assert mp._encrypt("hello") == "hello"
        assert mp._decrypt("world") == "world"

    def test_decrypt_failure_returns_data(self, temp_dir):
        mp = MobileMemoryProvider(
            db_path=temp_dir / "dec_fail.db", encrypt=True, encryption_key="test"
        )
        result = mp._decrypt("not-encrypted-data")
        assert result == "not-encrypted-data"


class TestSearchSessions:
    async def test_search_sessions_with_multiple_messages(self, memory_provider):
        """Multiple messages in same session trigger dedup path (line 363)."""
        from hermes_mobile.core.agent import Message

        await memory_provider.save_conversation(
            "session-multi", [Message.user("Hello world"), Message.user("Hello again")]
        )
        result = await memory_provider.search_sessions("Hello", limit=5)
        assert len(result) == 1
        assert result[0]["id"] == "session-multi"

    async def test_search_sessions_with_encryption(self, temp_dir):
        """Encrypted provider reaches decrypt path (line 366)."""
        from hermes_mobile.core.agent import Message

        mp = MobileMemoryProvider(
            db_path=temp_dir / "search_enc.db",
            encrypt=True,
            encryption_key="test-key",
        )
        try:
            await mp.save_conversation("session-enc", [Message.user("Secret data")])
            result = await mp.search_sessions("Secret")
            assert len(result) >= 1
            assert result[0]["id"] == "session-enc"
        finally:
            mp.close()

    async def test_search_sessions_encrypted_hits_limit(self, temp_dir):
        """Encrypted search hits limit and breaks (line 369)."""
        from hermes_mobile.core.agent import Message

        mp = MobileMemoryProvider(
            db_path=temp_dir / "search_enc_limit.db",
            encrypt=True,
            encryption_key="test-key",
        )
        try:
            for i in range(3):
                await mp.save_conversation(
                    f"session-{i}", [Message.user(f"Matching data for session {i}")]
                )
            result = await mp.search_sessions("Matching", limit=2)
            assert len(result) == 2
        finally:
            mp.close()
