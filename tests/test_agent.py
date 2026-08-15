"""Tests for the agent core (Message, ToolCall, MobileAgent construction)."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hermes_mobile.core.agent import Message, MobileAgent, ToolCall, create_mobile_agent
from hermes_mobile.core.context_compressor import compress_messages, needs_compression
from hermes_mobile.core.prompt_caching import apply_cache_control, supports_caching


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
        """get_tool_schemas returns all built-in tool schemas."""
        agent = MobileAgent()
        schemas = agent.get_tool_schemas()
        assert len(schemas) >= 13  # All built-in tool schemas
        assert schemas[0]["function"]["name"] == "web_search"

    def test_get_tool_schemas_with_skills(self):
        """get_tool_schemas includes skill schemas when skill_manager is set."""
        agent = MobileAgent()
        mock_skill = MagicMock()
        mock_skill.get_schema.return_value = {
            "type": "function",
            "function": {"name": "my_skill", "description": "Custom skill"},
        }
        mock_mgr = MagicMock()
        mock_mgr.get_active_skills.return_value = [mock_skill]
        agent.skill_manager = mock_mgr
        schemas = agent.get_tool_schemas()
        skill_schemas = [s for s in schemas if s.get("function", {}).get("name") == "my_skill"]
        assert len(skill_schemas) == 1
        mock_mgr.get_active_skills.assert_called_once()

    def test_on_message_callback(self):
        received = []

        def callback(msg):
            received.append(msg)

        agent = MobileAgent(on_message=callback)
        agent.add_user_message("Test")
        assert len(received) == 1
        assert received[0].content == "Test"

    @pytest.mark.asyncio
    async def test_streaming_reassembles_and_executes_fragmented_tool_calls(self):
        def chunk(content=None, tool_calls=None):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content=content, tool_calls=tool_calls or [])
                    )
                ]
            )

        def tool_delta(index, *, call_id=None, name=None, arguments=None):
            return SimpleNamespace(
                index=index,
                id=call_id,
                function=SimpleNamespace(name=name, arguments=arguments),
            )

        async def first_response():
            yield chunk(
                tool_calls=[
                    tool_delta(
                        0,
                        call_id="call_stream",
                        name="web_",
                        arguments='{"query":"py',
                    )
                ]
            )
            yield chunk(tool_calls=[tool_delta(0, name="search", arguments='thon"}')])

        async def second_response():
            yield chunk(content="Done")

        agent = MobileAgent()
        agent.max_iterations = 2
        agent._call_model = AsyncMock(  # type: ignore[method-assign]
            side_effect=[first_response(), second_response()]
        )
        agent._execute_tool_calls = AsyncMock()  # type: ignore[method-assign]

        output = [part async for part in agent.run_conversation("Find Python", stream=True)]

        assert output == ["Done"]
        streamed_message = agent.messages[1]
        assert streamed_message.role == "assistant"
        assert streamed_message.content == ""
        assert len(streamed_message.tool_calls) == 1
        call = streamed_message.tool_calls[0]
        assert call.call_id == "call_stream"
        assert call.name == "web_search"
        assert call.arguments == {"query": "python"}
        agent._execute_tool_calls.assert_awaited_once_with([call])
        assert agent.messages[-1].content == "Done"

    @pytest.mark.asyncio
    async def test_non_streaming_response_is_persisted_in_agent_history(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Hello", tool_calls=[]))]
        )
        agent = MobileAgent()
        agent._call_model = AsyncMock(return_value=response)  # type: ignore[method-assign]

        output = [part async for part in agent.run_conversation("Hi", stream=False)]

        assert output == ["Hello"]
        assert [(message.role, message.content) for message in agent.messages] == [
            ("user", "Hi"),
            ("assistant", "Hello"),
        ]

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

    def test_get_api_key_openrouter(self):
        agent = MobileAgent()
        agent.settings.openrouter_api_key = "sk-or-v1-xxx"
        assert agent._get_api_key() == "sk-or-v1-xxx"

    def test_get_api_key_openai(self):
        agent = MobileAgent(provider="openai")
        agent.settings.openai_api_key = "sk-openai-xxx"
        assert agent._get_api_key() == "sk-openai-xxx"

    def test_get_api_key_anthropic(self):
        agent = MobileAgent(provider="anthropic")
        agent.settings.anthropic_api_key = "sk-ant-xxx"
        assert agent._get_api_key() == "sk-ant-xxx"

    def test_get_api_key_gemini(self):
        agent = MobileAgent(provider="gemini")
        agent.settings.gemini_api_key = "AIza-xxx"
        assert agent._get_api_key() == "AIza-xxx"
        profile = agent._get_provider_profile()
        assert profile is not None
        assert profile.name == "google"

    @patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-deepseek"}, clear=False)
    def test_provider_registry_resolves_environment_key_and_endpoint(self):
        agent = MobileAgent(provider="deepseek")

        assert agent._get_api_key() == "sk-deepseek"
        assert agent._get_base_url() == "https://api.deepseek.com/v1"
        assert agent._client is not None

    def test_ollama_builds_client_without_api_key(self, monkeypatch):
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        agent = MobileAgent(provider="ollama")

        assert agent._get_api_key() == ""
        assert agent._client is not None
        assert agent._client_error is None
        assert agent._get_base_url() == "http://localhost:11434/v1"

    def test_ollama_host_env_drives_endpoint(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_HOST", "http://192.168.1.50:11434")
        agent = MobileAgent(provider="ollama")

        assert agent._get_base_url() == "http://192.168.1.50:11434/v1"
        assert agent._client is not None

    def test_ollama_uses_optional_key_from_secret_store(self, tmp_path):
        """A token typed in Settings for a keyless provider is actually used."""
        agent = MobileAgent(provider="ollama")
        agent.settings.data_dir = str(tmp_path)

        from hermes_mobile.remote.secrets import ProviderSecretStore

        ProviderSecretStore(tmp_path).save_key("ollama", "sk-local-gateway")

        assert agent._get_api_key() == "sk-local-gateway"
        agent._init_client()
        assert agent._client is not None
        assert agent._client_error is None

    def test_non_openai_compatible_provider_fails_explicitly(self):
        agent = MobileAgent(provider="anthropic")

        assert agent._client is None
        assert agent._client_error is not None
        assert "requires the 'messages' API" in agent._client_error
        assert "OpenRouter" in agent._client_error

    def test_reconfigure_preserves_messages_and_rebuilds_route(self):
        agent = MobileAgent()
        agent.add_user_message("Keep this context")
        previous_session = agent.session_id

        agent.reconfigure(provider="openai", model="gpt-4o-mini")

        assert agent.provider == "openai"
        assert agent.model == "gpt-4o-mini"
        assert agent.session_id == previous_session
        assert agent.messages[0].content == "Keep this context"

    def test_get_api_key_unknown(self):
        agent = MobileAgent()
        agent.provider = "unknown"
        assert agent._get_api_key() == ""

    def test_get_base_url_unknown_fallback(self):
        agent = MobileAgent(provider="openai")
        agent.settings.openai_api_key = "sk-dummy"
        agent._init_client()
        agent.provider = "unknown"
        assert "openrouter.ai" in agent._get_base_url()

    def test_get_base_url_openai(self):
        agent = MobileAgent(provider="openai")
        assert "api.openai.com" in agent._get_base_url()

    def test_get_base_url_anthropic(self):
        agent = MobileAgent(provider="anthropic")
        assert "api.anthropic.com" in agent._get_base_url()

    def test_get_base_url_gemini(self):
        agent = MobileAgent(provider="gemini")
        assert "generativelanguage.googleapis.com" in agent._get_base_url()

    def test_clear_conversation(self):
        agent = MobileAgent()
        agent.add_user_message("Hello")
        agent.add_assistant_message("Hi")
        old_id = agent.session_id
        agent.clear_conversation()
        assert agent.messages == []
        assert agent.session_id != old_id
        assert agent.iteration == 0

    def test_set_tools(self):
        agent = MobileAgent()
        agent.set_tools([{"name": "my_tool"}])
        assert agent.tools == [{"name": "my_tool"}]

    @patch("hermes_mobile.core.agent.web_search_tool")
    async def test_tool_web_search(self, mock_search):
        mock_search.return_value = {"results": ["item1"]}
        agent = MobileAgent()
        result = await agent._tool_web_search("test query")
        assert result == {"results": ["item1"]}
        mock_search.assert_called_once_with("test query", max_results=5)

    async def test_tool_get_time(self):
        agent = MobileAgent()
        result = await agent._tool_get_time()
        assert "T" in result  # ISO format has T separator

    @patch("hermes_mobile.core.agent.safe_calculate")
    async def test_tool_calculate(self, mock_calc):
        mock_calc.return_value = 42
        agent = MobileAgent()
        result = await agent._tool_calculate("6 * 7")
        assert result == 42
        mock_calc.assert_called_once_with("6 * 7")

    @patch("hermes_mobile.core.agent.validate_and_resolve_path")
    async def test_tool_read_file_success(self, mock_validate):
        mock_path = MagicMock()
        mock_path.read_text.return_value = "file content"
        mock_validate.return_value = (mock_path, None)
        agent = MobileAgent()
        result = await agent._tool_read_file("/tmp/test.txt")
        assert result == "file content"

    @patch("hermes_mobile.core.agent.validate_and_resolve_path")
    async def test_tool_read_file_error(self, mock_validate):
        mock_validate.return_value = (None, "Path traversal detected")
        agent = MobileAgent()
        result = await agent._tool_read_file("../../etc/passwd")
        assert "Error" in result
        assert "Path traversal" in result

    @patch("hermes_mobile.core.agent.validate_and_resolve_path")
    async def test_tool_write_file_success(self, mock_validate):
        mock_path = MagicMock(spec=Path)
        mock_validate.return_value = (mock_path, None)
        agent = MobileAgent()
        result = await agent._tool_write_file("/tmp/test.txt", "content")
        assert "File written to" in result
        mock_path.parent.mkdir.assert_called_once()
        mock_path.write_text.assert_called_once_with("content")

    @patch("hermes_mobile.core.agent.validate_and_resolve_path")
    async def test_tool_list_files_success(self, mock_validate):
        mock_path = MagicMock()
        mock_path.iterdir.return_value = [Path("/tmp/a.txt"), Path("/tmp/b.txt")]
        mock_validate.return_value = (mock_path, None)
        agent = MobileAgent()
        result = await agent._tool_list_files("/tmp")
        assert len(result) == 2

    @patch("hermes_mobile.core.agent.validate_and_resolve_path")
    async def test_tool_list_files_with_current_dir(self, mock_validate):
        agent = MobileAgent()
        result = await agent._tool_list_files(".")
        assert isinstance(result, list)

    @patch("hermes_mobile.core.agent.MobileProcessRegistry.terminal")
    async def test_tool_run_command(self, mock_terminal):
        mock_terminal.return_value = {"output": "stdout here", "exit_code": 0}
        agent = MobileAgent()
        result = await agent._tool_run_command("echo hello")
        assert result["stdout"] == "stdout here"
        assert result["returncode"] == 0

    async def test_tool_delegate_tasks(self):
        agent = MobileAgent()
        agent._tool_delegate_task = AsyncMock(  # type: ignore[method-assign]
            return_value={"status": "completed", "content": "task done"}
        )
        result = await agent._tool_delegate_tasks(["task1"], context="ctx")
        assert result == {
            "status": "completed",
            "mode": "parallel",
            "results": [{"status": "completed", "content": "task done"}],
        }
        agent._tool_delegate_task.assert_awaited_once_with("task1", context="ctx")

    @patch("hermes_mobile.core.agent.clarify_tool")
    async def test_tool_clarify(self, mock_clarify):
        mock_clarify.return_value = {"suggestions": ["Did you mean X?"]}
        agent = MobileAgent()
        result = await agent._tool_clarify("test topic", context="ctx")
        assert result == {"suggestions": ["Did you mean X?"]}

    @patch("hermes_mobile.core.agent.validate_and_resolve_path")
    async def test_tool_read_file_exception(self, mock_validate):
        mock_path = MagicMock()
        mock_path.read_text.side_effect = PermissionError("Permission denied")
        mock_validate.return_value = (mock_path, None)
        agent = MobileAgent()
        result = await agent._tool_read_file("/tmp/restricted.txt")
        assert "Error reading file" in result
        assert "Permission denied" in result

    @patch("hermes_mobile.core.agent.validate_and_resolve_path")
    async def test_tool_write_file_error(self, mock_validate):
        mock_validate.return_value = (None, "Invalid path")
        agent = MobileAgent()
        result = await agent._tool_write_file("/bad/path", "content")
        assert "Error" in result

    @patch("hermes_mobile.core.agent.validate_and_resolve_path")
    async def test_tool_write_file_exception(self, mock_validate):
        mock_path = MagicMock(spec=Path)
        mock_path.parent.mkdir.side_effect = OSError("Filesystem full")
        mock_validate.return_value = (mock_path, None)
        agent = MobileAgent()
        result = await agent._tool_write_file("/tmp/test.txt", "content")
        assert "Error writing file" in result

    @patch("hermes_mobile.core.agent.validate_and_resolve_path")
    async def test_tool_list_files_error(self, mock_validate):
        mock_validate.return_value = (None, "Traversal blocked")
        agent = MobileAgent()
        result = await agent._tool_list_files("/etc")
        assert "Error" in result[0]

    @patch("hermes_mobile.core.agent.validate_and_resolve_path")
    async def test_tool_list_files_exception(self, mock_validate):
        mock_path = MagicMock()
        mock_path.iterdir.side_effect = PermissionError("No access")
        mock_validate.return_value = (mock_path, None)
        agent = MobileAgent()
        result = await agent._tool_list_files("/protected")
        assert "Error" in result[0]

    async def test_tool_run_command_exception(self):
        agent = MobileAgent()
        result = await agent._tool_run_command(None)  # type: ignore[arg-type]
        assert "error" in result

    @patch("hermes_mobile.core.agent.web_extract_tool")
    async def test_tool_web_extract(self, mock_extract):
        mock_extract.return_value = {"content": "page text"}
        agent = MobileAgent()
        result = await agent._tool_web_extract(["https://example.com"])
        assert result == {"content": "page text"}
        mock_extract.assert_called_once_with(["https://example.com"], format="text")

    @patch("hermes_mobile.core.agent.session_search_tool")
    async def test_tool_session_search(self, mock_search):
        mock_search.return_value = {"sessions": [{"id": "1"}]}
        agent = MobileAgent()
        agent.memory_provider = MagicMock()
        result = await agent._tool_session_search("past question")
        assert result == {"sessions": [{"id": "1"}]}
        mock_search.assert_called_once_with(
            "past question", limit=5, memory_provider=agent.memory_provider
        )

    @patch("hermes_mobile.core.agent.memory_tool")
    async def test_tool_memory(self, mock_memory):
        mock_memory.return_value = {"stored": True}
        agent = MobileAgent()
        agent.memory_provider = MagicMock()
        result = await agent._tool_memory("store", key="k", value="v")
        assert result == {"stored": True}
        mock_memory.assert_called_once_with(
            action="store",
            key="k",
            value="v",
            query=None,
            limit=5,
            memory_provider=agent.memory_provider,
        )

    @patch("hermes_mobile.core.agent.browser_navigate_tool")
    async def test_tool_browser_navigate(self, mock_nav):
        mock_nav.return_value = {"url": "https://example.com", "content": "page"}
        agent = MobileAgent()
        result = await agent._tool_browser_navigate("https://example.com")
        assert result == {"url": "https://example.com", "content": "page"}
        mock_nav.assert_called_once_with("https://example.com")

    @patch("hermes_mobile.core.agent.browser_snapshot_tool")
    async def test_tool_browser_snapshot(self, mock_snap):
        mock_snap.return_value = {"snapshot": "textual content"}
        agent = MobileAgent()
        result = await agent._tool_browser_snapshot("https://example.com")
        assert result == {"snapshot": "textual content"}
        mock_snap.assert_called_once_with("https://example.com")

    @patch("hermes_mobile.core.agent.browser_click_selector_tool")
    async def test_tool_browser_click_selector(self, mock_click):
        mock_click.return_value = {"ok": True}
        agent = MobileAgent()
        result = await agent._tool_browser_click(selector="button#go")
        assert result == {"ok": True}
        mock_click.assert_called_once_with("button#go")

    @patch("hermes_mobile.core.agent.browser_click_tool")
    async def test_tool_browser_click_href(self, mock_click):
        mock_click.return_value = {"ok": True}
        agent = MobileAgent()
        result = await agent._tool_browser_click(href="/b")
        assert result == {"ok": True}
        mock_click.assert_called_once_with("/b")

    @patch("hermes_mobile.core.agent.browser_scroll_tool")
    async def test_tool_browser_scroll(self, mock_scroll):
        mock_scroll.return_value = {"ok": True}
        agent = MobileAgent()
        result = await agent._tool_browser_scroll("down", 300)
        assert result == {"ok": True}
        mock_scroll.assert_called_once_with("down", 300)

    @patch("hermes_mobile.core.agent.browser_type_tool")
    async def test_tool_browser_type(self, mock_type):
        mock_type.return_value = {"ok": True}
        agent = MobileAgent()
        result = await agent._tool_browser_type("input[name=q]", "hello")
        assert result == {"ok": True}
        mock_type.assert_called_once_with("input[name=q]", "hello")

    async def test_tool_browser_scroll_without_webview_errors_gracefully(self):
        from hermes_mobile.tools.browser_session import _session

        _session.webview = None
        try:
            agent = MobileAgent()
            result = await agent._tool_browser_scroll("down", 300)
            assert "WebView browser is not active" in result.get("error", "")
        finally:
            _session.webview = None

    def test_extract_tool_calls_empty(self):
        response = MagicMock()
        response.choices[0].message.tool_calls = None
        agent = MobileAgent()
        result = agent._extract_tool_calls(response)
        assert result == []

    def test_extract_tool_calls_with_tools(self):
        response = MagicMock()
        mock_tc = MagicMock()
        mock_tc.id = "call_abc"
        mock_tc.function.name = "web_search"
        mock_tc.function.arguments = '{"query": "test"}'
        response.choices[0].message.tool_calls = [mock_tc]
        agent = MobileAgent()
        result = agent._extract_tool_calls(response)
        assert len(result) == 1
        assert result[0].name == "web_search"
        assert result[0].call_id == "call_abc"
        assert result[0].arguments == {"query": "test"}

    def test_extract_tool_calls_bad_json(self):
        response = MagicMock()
        mock_tc = MagicMock()
        mock_tc.id = "call_bad"
        mock_tc.function.name = "bad_tool"
        mock_tc.function.arguments = "not valid json{{{"
        response.choices[0].message.tool_calls = [mock_tc]
        agent = MobileAgent()
        result = agent._extract_tool_calls(response)
        assert len(result) == 1
        assert result[0].arguments == {}
        # The parse failure is surfaced back to the model instead of being
        # silently swallowed (which executed the tool with garbage args).
        assert result[0].error is not None
        assert "Invalid JSON" in result[0].error

    async def test_execute_tool_calls_success(self):
        agent = MobileAgent()
        tc = ToolCall(name="get_time", arguments={})
        await agent._execute_tool_calls([tc])
        assert tc.result is not None
        assert tc.completed_at is not None
        assert len(agent.messages) == 1
        assert agent.messages[0].role == "tool"

    async def test_execute_tool_calls_error(self):
        agent = MobileAgent()
        tc = ToolCall(name="nonexistent_tool", arguments={})
        await agent._execute_tool_calls([tc])
        assert tc.error is not None
        assert "Unknown tool" in tc.error

    async def test_execute_tool_calls_callback(self):
        calls = []

        def on_tool_call(tc):
            calls.append(("call", tc.name))

        def on_tool_result(tc):
            calls.append(("result", tc.name))

        agent = MobileAgent(on_tool_call=on_tool_call, on_tool_result=on_tool_result)
        tc = ToolCall(name="get_time", arguments={})
        await agent._execute_tool_calls([tc])
        assert len(calls) == 2
        assert calls[0] == ("call", "get_time")
        assert calls[1] == ("result", "get_time")

    async def test_execute_tool_denied_by_approval(self):
        async def deny(name, arguments):
            return False

        agent = MobileAgent(approval_callback=deny)
        tc = ToolCall(name="terminal", arguments={"command": "rm -rf /"})
        await agent._execute_tool_calls([tc])
        assert tc.error is not None
        assert "not approved" in tc.error

    async def test_execute_tool_approved_by_approval(self):
        async def approve(name, arguments):
            return True

        agent = MobileAgent(approval_callback=approve)
        agent.process_registry.terminal = AsyncMock(  # type: ignore[method-assign]
            return_value={"exit_code": 0, "output": "ok"}
        )
        tc = ToolCall(name="terminal", arguments={"command": "echo hi"})
        await agent._execute_tool_calls([tc])
        assert tc.error is None
        assert tc.result is not None
        agent.process_registry.terminal.assert_awaited_once()

    async def test_execute_tool_without_approval_callback_runs(self):
        """Contexts without a callback (gateway/remote) keep the legacy behavior."""
        agent = MobileAgent()
        agent.process_registry.terminal = AsyncMock(  # type: ignore[method-assign]
            return_value={"exit_code": 0, "output": "ok"}
        )
        tc = ToolCall(name="terminal", arguments={"command": "echo hi"})
        await agent._execute_tool_calls([tc])
        assert tc.error is None
        agent.process_registry.terminal.assert_awaited_once()

    async def test_execute_tool_non_sensitive_ignores_approval(self):
        async def deny(name, arguments):
            return False

        agent = MobileAgent(approval_callback=deny)
        result = await agent._execute_tool("get_time", {})
        assert result is not None

    async def test_execute_tool_builtin(self):
        agent = MobileAgent()
        result = await agent._execute_tool("get_time", {})
        assert result is not None

    async def test_execute_tool_skill(self):
        mock_skill = AsyncMock()
        mock_skill.execute.return_value = "skill result"
        agent = MobileAgent()
        agent.skill_manager = MagicMock()
        agent.skill_manager.get_skill.return_value = mock_skill
        result = await agent._execute_tool("my_skill", {"query": "test"})
        assert result == "skill result"
        mock_skill.execute.assert_called_once_with(query="test")

    async def test_execute_tool_unknown(self):
        agent = MobileAgent()
        with pytest.raises(ValueError, match="Unknown tool"):
            await agent._execute_tool("no_such_tool", {})

    @patch("hermes_mobile.core.agent.compress_messages")
    def test_apply_compression_system_user(self, mock_compress):
        mock_compress.return_value = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Hello"},
        ]
        agent = MobileAgent()
        agent.add_user_message("Hello")
        result = agent._apply_compression()
        assert len(result) == 2
        assert result[0].role == "system"
        assert result[1].role == "user"

    @patch("hermes_mobile.core.agent.compress_messages")
    def test_apply_compression_all_roles(self, mock_compress):
        mock_compress.return_value = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {
                "role": "tool",
                "content": '{"result": "ok"}',
                "tool_call_id": "call_1",
                "name": "web_search",
            },
        ]
        agent = MobileAgent()
        agent.add_user_message("Hello")
        result = agent._apply_compression()
        assert len(result) == 4
        assert result[0].role == "system"
        assert result[1].role == "user"
        assert result[2].role == "assistant"
        assert result[3].role == "tool"
        assert result[3].tool_call_id == "call_1"
        assert result[3].name == "web_search"

    @patch("hermes_mobile.memory.provider.MobileMemoryProvider")
    @patch("hermes_mobile.skills.manager.MobileSkillManager")
    @patch("hermes_mobile.core.agent.get_settings")
    def test_create_mobile_agent(self, mock_settings, mock_skill_mgr, mock_mem_provider, tmp_path):
        mock_settings.return_value.default_model = "gpt-4o"
        mock_settings.return_value.default_provider = "openai"
        mock_settings.return_value.get_memory_db_path.return_value = ":memory:"
        mock_settings.return_value.get_data_dir.return_value = str(tmp_path)
        mock_settings.return_value.encrypt_memory = False
        mock_settings.return_value.get_skills_dir.return_value = "/tmp/skills"
        agent = create_mobile_agent()
        assert isinstance(agent, MobileAgent)
        assert agent.model == "gpt-4o"
        assert agent.provider == "openai"
        assert len(agent.tools) > 0

    @patch("hermes_mobile.memory.provider.MobileMemoryProvider")
    @patch("hermes_mobile.skills.manager.MobileSkillManager")
    @patch("hermes_mobile.core.agent.get_settings")
    def test_create_mobile_agent_custom(
        self, mock_settings, mock_skill_mgr, mock_mem_provider, tmp_path
    ):
        mock_settings.return_value.default_model = "gpt-4o"
        mock_settings.return_value.default_provider = "openai"
        mock_settings.return_value.get_memory_db_path.return_value = ":memory:"
        mock_settings.return_value.get_data_dir.return_value = str(tmp_path)
        mock_settings.return_value.encrypt_memory = False
        mock_settings.return_value.get_skills_dir.return_value = "/tmp/skills"
        agent = create_mobile_agent(model="claude-3", provider="anthropic")
        assert agent.model == "claude-3"
        assert agent.provider == "anthropic"


class TestAgentRunConversation:
    @pytest.fixture
    def agent(self):
        return MobileAgent()

    @pytest.fixture
    def mock_response(self):
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message = MagicMock()
        resp.choices[0].message.content = "Hello back!"
        resp.choices[0].message.tool_calls = None
        return resp

    @pytest.fixture
    def mock_stream_chunk(self):
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta = MagicMock()
        chunk.choices[0].delta.content = "Hello "
        chunk.choices[0].delta.tool_calls = None
        return chunk

    @patch("hermes_mobile.core.agent.needs_compression")
    async def test_run_conversation_simple(self, mock_needs_compression, agent, mock_response):
        mock_needs_compression.return_value = False
        agent._client = MagicMock()
        agent._client.chat.completions.create = AsyncMock(return_value=mock_response)

        results = []
        async for chunk in agent.run_conversation("Hello", stream=False):
            results.append(chunk)

        assert "".join(results) == "Hello back!"
        assert len(agent.messages) >= 1  # user message added

    @patch("hermes_mobile.core.agent.needs_compression")
    async def test_run_conversation_streaming(
        self, mock_needs_compression, agent, mock_stream_chunk
    ):
        mock_needs_compression.return_value = False
        mock_async_gen = MagicMock()
        mock_async_gen.__aiter__.return_value = [mock_stream_chunk]
        agent._client = MagicMock()
        agent._client.chat.completions.create = AsyncMock(return_value=mock_async_gen)

        results = []
        async for chunk in agent.run_conversation("Hello", stream=True):
            results.append(chunk)

        assert "".join(results) == "Hello "
        assert len(agent.messages) >= 1

    @patch("hermes_mobile.core.agent.needs_compression")
    async def test_run_conversation_tool_call_flow(self, mock_needs_compression, agent):
        mock_needs_compression.return_value = False
        agent._client = MagicMock()

        # First API call returns a tool call
        tool_response = MagicMock()
        tool_response.choices = [MagicMock()]
        tool_response.choices[0].message.content = "Let me search"
        mock_tc = MagicMock()
        mock_tc.id = "call_1"
        mock_tc.function.name = "get_time"
        mock_tc.function.arguments = "{}"
        tool_response.choices[0].message.tool_calls = [mock_tc]

        # Second API call returns final response (no tool calls)
        final_response = MagicMock()
        final_response.choices = [MagicMock()]
        final_response.choices[0].message.content = "Done!"
        final_response.choices[0].message.tool_calls = None

        agent._client.chat.completions.create = AsyncMock(
            side_effect=[tool_response, final_response]
        )

        results = []
        async for chunk in agent.run_conversation("What time is it?", stream=False):
            results.append(chunk)

        combined = "".join(results)
        assert "Let me search" in combined
        assert "Done!" in combined

    @patch("hermes_mobile.core.agent.needs_compression")
    async def test_run_conversation_compression_triggered(
        self, mock_needs_compression, agent, mock_response
    ):
        mock_needs_compression.side_effect = [True, False]
        agent._apply_compression = MagicMock(return_value=[])
        agent._client = MagicMock()
        agent._client.chat.completions.create = AsyncMock(return_value=mock_response)

        results = []
        async for chunk in agent.run_conversation("Long message", stream=False):
            results.append(chunk)

        assert "".join(results) == "Hello back!"
        agent._apply_compression.assert_called_once()

    @patch("hermes_mobile.core.agent.needs_compression")
    async def test_run_conversation_api_error(self, mock_needs_compression, agent):
        mock_needs_compression.return_value = False
        agent._client = MagicMock()
        agent._client.chat.completions.create = AsyncMock(side_effect=RuntimeError("API failure"))

        results = []
        async for chunk in agent.run_conversation("Hello", stream=False):
            results.append(chunk)

        assert "Error" in "".join(results)

    @patch("hermes_mobile.core.agent.needs_compression")
    async def test_run_conversation_memory_save(self, mock_needs_compression, agent, mock_response):
        mock_needs_compression.return_value = False
        agent._client = MagicMock()
        agent._client.chat.completions.create = AsyncMock(return_value=mock_response)
        agent.memory_provider = AsyncMock()

        async for _ in agent.run_conversation("Remember this", stream=False):
            pass

        agent.memory_provider.save_conversation.assert_awaited_once()


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


class TestAgentSecurityHardening:
    def test_get_messages_for_api_cache_uses_active_provider(self):
        # Regression: caching was keyed to settings.default_provider instead of
        # the agent's active provider, so switching providers at runtime applied
        # (or skipped) cache breakpoints for the wrong provider.
        agent = MobileAgent()
        agent.add_user_message("Hi")
        api = agent.get_messages_for_api()
        assert any("cache_control" in m for m in api)  # openrouter supports caching

        agent.reconfigure(provider="openai", model="gpt-4o-mini")
        api = agent.get_messages_for_api()
        assert not any("cache_control" in m for m in api)  # openai does not

    def test_apply_compression_preserves_assistant_tool_calls(self):
        # Regression: rebuilding compressed messages with Message.assistant(content)
        # dropped tool_calls, orphaning the tool result messages that follow and
        # making the API reject the conversation.
        agent = MobileAgent()
        agent.settings.max_context_tokens = 1  # force compression to trigger
        tc = ToolCall(name="web_search", arguments={"query": "x"}, call_id="c1")
        for i in range(8):
            agent.add_user_message(f"u{i}")
            agent.add_assistant_message(f"a{i}")
        agent.add_user_message("final")
        agent.add_assistant_message("", tool_calls=[tc])
        agent.add_tool_result('{"ok": true}', "c1", "web_search")

        agent._apply_compression()

        assert len(agent.messages) < 20  # actually compressed
        for i, msg in enumerate(agent.messages):
            if msg.role == "tool":
                prev = agent.messages[i - 1]
                assert prev.role == "assistant"
                assert any(c.call_id == msg.tool_call_id for c in prev.tool_calls)

    @pytest.mark.asyncio
    async def test_execute_tool_calls_skips_tool_with_parse_error(self):
        # A tool whose JSON arguments failed to parse must not execute with
        # garbage; the parse error is returned to the model instead.
        agent = MobileAgent()
        agent._execute_tool = AsyncMock(side_effect=AssertionError("must not run"))
        tc = ToolCall(name="web_search", arguments={})
        tc.error = "Invalid JSON tool arguments: {"

        await agent._execute_tool_calls([tc])

        assert len(agent.messages) == 1
        assert agent.messages[0].role == "tool"
        assert "Invalid JSON" in agent.messages[0].content
        agent._execute_tool.assert_not_called()
