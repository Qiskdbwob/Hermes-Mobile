"""Tests for agent intelligence tools."""

from unittest.mock import AsyncMock, MagicMock

from hermes_mobile.tools.agent_tools import (
    AGENT_TOOLS,
    clarify_tool,
    memory_tool,
    register,
    session_search_tool,
)


class TestAgentToolRegistry:
    def test_register_decorator(self):
        @register("test_tool")
        async def my_tool():
            return "result"

        assert "test_tool" in AGENT_TOOLS
        assert AGENT_TOOLS["test_tool"] is my_tool


class TestClarifyTool:
    async def test_basic_clarification(self):
        result = await clarify_tool(topic="coding help")
        assert result["topic"] == "coding help"
        assert len(result["suggestions"]) == 3
        assert all(isinstance(s, str) for s in result["suggestions"])

    async def test_with_context(self):
        result = await clarify_tool(topic="database design", context="building a mobile app")
        assert len(result["suggestions"]) == 4  # context-based + 3 defaults
        assert "mobile app" in result["suggestions"][0]

    async def test_return_format(self):
        result = await clarify_tool(topic="test")
        assert "topic" in result
        assert "suggestions" in result
        assert "context" in result


class TestSessionSearchTool:
    async def test_no_memory_provider(self):
        result = await session_search_tool(query="test query")
        assert result["sessions"] == []
        assert result["query"] == "test query"
        assert "error" in result
        assert "not available" in result["error"]

    async def test_search_with_memory_provider(self, memory_provider):
        # Save some conversation first
        from hermes_mobile.core.agent import Message

        await memory_provider.save_conversation("session-1", [Message.user("Hello world")])
        result = await session_search_tool(
            query="Hello",
            memory_provider=memory_provider,
        )
        assert "sessions" in result
        assert len(result["sessions"]) >= 1
        assert result["sessions"][0]["id"] == "session-1"


class TestMemoryTool:
    async def test_no_memory_provider(self):
        result = await memory_tool(action="search", query="test")
        assert "error" in result
        assert "not available" in result["error"]

    async def test_unknown_action(self, memory_provider):
        result = await memory_tool(action="nonexistent", memory_provider=memory_provider)
        assert "error" in result
        assert "unknown action" in result["error"].lower()

    async def test_search_action(self, memory_provider):
        await memory_provider.add_memory_entry(session_id="mem-test", content="User likes Python")
        result = await memory_tool(action="search", query="Python", memory_provider=memory_provider)
        assert "results" in result
        assert len(result["results"]) >= 1

    async def test_store_action_without_key(self, memory_provider):
        result = await memory_tool(action="store", value="val", memory_provider=memory_provider)
        assert "error" in result

    async def test_store_action_without_value(self, memory_provider):
        result = await memory_tool(action="store", key="k", memory_provider=memory_provider)
        assert "error" in result

    async def test_retrieve_without_key(self, memory_provider):
        result = await memory_tool(action="retrieve", memory_provider=memory_provider)
        assert "error" in result

    async def test_search_without_query(self, memory_provider):
        result = await memory_tool(action="search", memory_provider=memory_provider)
        assert "error" in result

    async def test_store_success(self):
        mock_provider = MagicMock()
        mock_provider.store_memory = AsyncMock()
        result = await memory_tool(
            action="store", key="user_name", value="Alice", memory_provider=mock_provider
        )
        assert result["status"] == "stored"
        assert result["key"] == "user_name"
        mock_provider.store_memory.assert_awaited_once_with("user_name", "Alice")

    async def test_retrieve_success(self):
        mock_provider = MagicMock()
        mock_provider.get_memory = AsyncMock(return_value="Python")
        result = await memory_tool(action="retrieve", key="lang", memory_provider=mock_provider)
        assert result["key"] == "lang"
        assert result["value"] == "Python"

    async def test_retrieve_not_found(self):
        mock_provider = MagicMock()
        mock_provider.get_memory = AsyncMock(return_value=None)
        result = await memory_tool(
            action="retrieve", key="nonexistent", memory_provider=mock_provider
        )
        assert result["key"] == "nonexistent"
        assert result["value"] is None

    async def test_list_action(self):
        mock_provider = MagicMock()
        mock_provider.list_memory = AsyncMock(return_value=[{"key": "a"}, {"key": "b"}])
        result = await memory_tool(action="list", memory_provider=mock_provider)
        assert "entries" in result
        assert len(result["entries"]) == 2

    async def test_delete_success(self):
        mock_provider = MagicMock()
        mock_provider.delete_memory = AsyncMock()
        result = await memory_tool(action="delete", key="temp", memory_provider=mock_provider)
        assert result["status"] == "deleted"
        assert result["key"] == "temp"
        mock_provider.delete_memory.assert_awaited_once_with("temp")

    async def test_delete_without_key(self, memory_provider):
        result = await memory_tool(action="delete", memory_provider=memory_provider)
        assert "error" in result
        assert "Key required" in result["error"]


class TestSessionSearchToolEdgeCases:
    async def test_search_exception(self, memory_provider):
        # Make search_sessions raise an exception
        async def failing_search(*args, **kwargs):
            raise RuntimeError("DB connection lost")

        memory_provider.search_sessions = failing_search
        result = await session_search_tool(query="test", memory_provider=memory_provider)
        assert result["sessions"] == []
        assert "error" in result


class TestMemoryToolEdgeCases:
    async def test_store_exception(self, memory_provider):
        async def failing_store(*args, **kwargs):
            raise RuntimeError("Write failed")

        memory_provider.store_memory = failing_store
        result = await memory_tool(
            action="store", key="k", value="v", memory_provider=memory_provider
        )
        assert "error" in result
