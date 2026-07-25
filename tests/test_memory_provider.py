"""Tests for MemoryProvider."""

import json
from datetime import datetime, timedelta

import pytest

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
        assert db_path.exists()
        mp.close()

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
