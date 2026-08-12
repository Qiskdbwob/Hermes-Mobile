"""Tests for the key/value memory store backing the agent's memory tool.

Regression coverage for the fix: memory_tool actions store/retrieve/list/
delete used provider methods that did not exist, so every action except
search failed with an AttributeError surfaced as an error string.
"""

from hermes_mobile.memory.provider import MobileMemoryProvider


class TestKvMemory:
    async def test_store_and_get(self, memory_provider):
        await memory_provider.store_memory("color", "blue")
        assert await memory_provider.get_memory("color") == "blue"

    async def test_store_upserts_same_key(self, memory_provider):
        await memory_provider.store_memory("k", "v1")
        await memory_provider.store_memory("k", "v2")
        assert await memory_provider.get_memory("k") == "v2"

    async def test_get_missing_returns_none(self, memory_provider):
        assert await memory_provider.get_memory("missing") is None

    async def test_list_returns_newest_first(self, memory_provider):
        await memory_provider.store_memory("a", "1")
        await memory_provider.store_memory("b", "2")
        entries = await memory_provider.list_memory()
        keys = [e["key"] for e in entries]
        assert set(keys) == {"a", "b"}
        assert keys[0] == "b"  # newest first

    async def test_delete(self, memory_provider):
        await memory_provider.store_memory("tmp", "x")
        assert await memory_provider.delete_memory("tmp") is True
        assert await memory_provider.get_memory("tmp") is None
        assert await memory_provider.delete_memory("tmp") is False

    async def test_expired_entry_is_invisible(self, memory_provider):
        await memory_provider.store_memory("stale", "old", ttl_days=1)
        conn = memory_provider._get_conn()
        conn.execute("UPDATE kv_memory SET expires_at = '2000-01-01T00:00:00' WHERE key = 'stale'")
        conn.commit()

        assert await memory_provider.get_memory("stale") is None
        keys = [e["key"] for e in await memory_provider.list_memory()]
        assert "stale" not in keys

    async def test_encrypted_roundtrip(self, temp_dir):
        provider = MobileMemoryProvider(
            db_path=temp_dir / "enc_kv.db",
            encrypt=True,
            encryption_key="kv-test-key",
        )
        try:
            await provider.store_memory("secret", "value-42")
            assert await provider.get_memory("secret") == "value-42"
        finally:
            provider.close()


class TestMemoryToolEndToEnd:
    """memory_tool against the real provider (not mocks)."""

    async def test_all_actions_work_with_real_provider(self, memory_provider):
        from hermes_mobile.tools.agent_tools import memory_tool

        stored = await memory_tool(
            action="store", key="city", value="Jakarta", memory_provider=memory_provider
        )
        assert stored["status"] == "stored"

        retrieved = await memory_tool(
            action="retrieve", key="city", memory_provider=memory_provider
        )
        assert retrieved["value"] == "Jakarta"

        listed = await memory_tool(action="list", memory_provider=memory_provider)
        assert any(e["key"] == "city" for e in listed["entries"])

        deleted = await memory_tool(action="delete", key="city", memory_provider=memory_provider)
        assert deleted["status"] == "deleted"
        assert await memory_provider.get_memory("city") is None
