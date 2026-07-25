"""Tests for the agent core (Message, ToolCall, MobileAgent construction)."""

import json

import pytest

from hermes_mobile.core.agent import Message, MobileAgent, ToolCall, create_mobile_agent
from hermes_mobile.core.context_compressor import compress_messages, needs_compression
from hermes_mobile.core.prompt_caching import supports_caching, apply_cache_control


class TestMessage:
    def test_user_message(self):
        msg = Message.user("Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.id is not None

    def test_assistant_message(self):
        msg = Message.assistant("Hi")
        assert msg.role == "assistant"
        assert msg.content == "Hi"

    def test_system_message(self):
        msg = Message.system("You are a helpful assistant.")
        assert msg.role == "system"
        assert msg.content == "You are a helpful assistant."

    def test_tool_message(self):
        msg = Message.tool(content='{"result": "ok"}', tool_call_id="call_123", name="web_search")
        assert msg.role == "tool"
        assert msg.content == '{"result": "ok"}'
        assert msg.tool_call_id == "call_123"
        assert msg.name == "web_search"

    def test_message_with_tool_calls(self):
        tc = ToolCall(name="web_search", arguments={"query": "test"})
        msg = Message.assistant("Searching...", tool_calls=[tc])
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].name == "web_search"

    def test_to_dict(self):
        msg = Message.user("Hello")
        d = msg.to_dict()
        assert d["role"] == "user"
        assert d["content"] == "Hello"
        assert "timestamp" in d
        assert "id" in d

    def test_default_timestamp(self):
        msg = Message.user("test")
        assert msg.timestamp is not None


class TestToolCall:
    def test_default_call_id(self):
        tc = ToolCall(name="test", arguments={})
        assert tc.call_id is not None
        assert len(tc.call_id) > 0

    def test_custom_call_id(self):
        tc = ToolCall(name="test", arguments={}, call_id="custom_id")
        assert tc.call_id == "custom_id"

    def test_to_dict(self):
        tc = ToolCall(name="web_search", arguments={"query": "python"})
        d = tc.to_dict()
        assert d["name"] == "web_search"
        assert d["arguments"] == {"query": "python"}
        assert d["result"] is None
        assert d["error"] is None

    def test_to_dict_with_result(self):
        tc = ToolCall(name="calculate", arguments={"expr": "2+2"})
        tc.result = "4"
        d = tc.to_dict()
        assert d["result"] == "4"


class TestMobileAgent:
    def test_create_agent_defaults(self):
        agent = MobileAgent()
        assert agent.model == "anthropic/claude-3.5-sonnet"
        assert agent.provider == "openrouter"
        assert agent.system_prompt is not None
        assert agent.session_id is not None
        assert agent.messages == []

    def test_create_agent_custom_values(self):
        agent = MobileAgent(
            model="gpt-4o",
            provider="openai",
            system_prompt="Custom prompt",
            tools=[{"type": "function", "function": {"name": "test_tool"}}],
        )
        assert agent.model == "gpt-4o"
        assert agent.provider == "openai"
        assert agent.system_prompt == "Custom prompt"
        assert len(agent.tools) == 1

    def test_add_message(self):
        agent = MobileAgent()
        msg = Message.user("Hello")
        agent.add_message(msg)
        assert len(agent.messages) == 1
        assert agent.messages[0].content == "Hello"

    def test_add_user_message(self):
        agent = MobileAgent()
        agent.add_user_message("Test input")
        assert len(agent.messages) == 1
        assert agent.messages[0].role == "user"
        assert agent.messages[0].content == "Test input"

    def test_add_assistant_message(self):
        agent = MobileAgent()
        agent.add_assistant_message("Response")
        assert len(agent.messages) == 1
        assert agent.messages[0].role == "assistant"

    def test_add_tool_result(self):
        agent = MobileAgent()
        agent.add_tool_result("result content", "call_1", "web_search")
        assert len(agent.messages) == 1
        assert agent.messages[0].role == "tool"
        assert agent.messages[0].tool_call_id == "call_1"
        assert agent.messages[0].name == "web_search"

    def test_get_messages_for_api_format(self):
        agent = MobileAgent()
        agent.add_user_message("Hello")
        agent.add_assistant_message("Hi!")
        api_messages = agent.get_messages_for_api()
        assert len(api_messages) == 3  # system + user + assistant
        assert api_messages[0]["role"] == "system"
        assert api_messages[1]["role"] == "user"
        assert api_messages[1]["content"] == "Hello"
        assert api_messages[2]["role"] == "assistant"

    def test_get_messages_for_api_with_tool_calls(self):
        agent = MobileAgent()
        tc = ToolCall(name="web_search", arguments={"query": "python"}, call_id="call_xyz")
        agent.add_assistant_message("Searching...", tool_calls=[tc])
        agent.add_tool_result('{"result": "ok"}', "call_xyz", "web_search")
        api_messages = agent.get_messages_for_api()
        assert len(api_messages) == 3  # system + assistant + tool
        assistant_msg = api_messages[1]
        assert assistant_msg["role"] == "assistant"
        assert "tool_calls" in assistant_msg
        assert assistant_msg["tool_calls"][0]["id"] == "call_xyz"
        assert assistant_msg["tool_calls"][0]["function"]["name"] == "web_search"

        tool_msg = api_messages[2]
        assert tool_msg["role"] == "tool"
        assert tool_msg["tool_call_id"] == "call_xyz"

    def test_get_tool_schemas(self):
        """get_tool_schemas returns all 14 built-in tool schemas."""
        agent = MobileAgent()
        schemas = agent.get_tool_schemas()
        assert len(schemas) >= 13  # All built-in tool schemas
        assert schemas[0]["function"]["name"] == "web_search"

    def test_on_message_callback(self):
        received = []

        def callback(msg):
            received.append(msg)

        agent = MobileAgent(on_message=callback)
        agent.add_user_message("Test")
        assert len(received) == 1
        assert received[0].content == "Test"

    def test_create_mobile_agent_function(self):
        agent = create_mobile_agent()
        assert isinstance(agent, MobileAgent)
        assert len(agent.tools) > 0  # Should have default tools

    def test_builtin_tools_property(self):
        agent = MobileAgent()
        tools = agent._builtin_tools
        assert "web_search" in tools
        assert "read_file" in tools
        assert "calculate" in tools
        assert "get_time" in tools


class TestContextCompressor:
    def test_needs_compression_small(self):
        messages = [
            {"role": "system", "content": "You are a helper."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        assert needs_compression(messages, 100000) is False

    def test_compress_messages_empty(self):
        result = compress_messages([])
        assert isinstance(result, list)

    def test_compress_messages_preserves_system(self):
        messages = [
            {"role": "system", "content": "You are Hermes."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        result = compress_messages(messages)
        assert any(m.get("role") == "system" for m in result)


class TestPromptCaching:
    def test_supports_caching_anthropic(self):
        assert supports_caching("anthropic") is True

    def test_supports_caching_openrouter(self):
        assert supports_caching("openrouter") is True

    def test_supports_caching_unknown_provider(self):
        assert supports_caching("openai") is False
        assert supports_caching("nonexistent") is False

    def test_apply_cache_control(self):
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
        ]
        result = apply_cache_control(messages, "openrouter")
        assert len(result) == 2
