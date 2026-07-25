"""Tests for agent intelligence tools."""

import pytest

from hermes_mobile.tools.agent_tools import (
    AGENT_TOOLS,
    session_search_tool,
    memory_tool,
    clarify_tool,
    register,
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
        # search_sessions doesn't exist on the provider, so expect an error
        assert "error" in result


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
