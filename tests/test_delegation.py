"""Tests for the delegation module (unit tests, no external API calls)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hermes_mobile.core.delegation import (
    MAX_CONCURRENT_SUBAGENTS,
    SUBAGENT_TIMEOUT,
    delegate_task,
    delegate_parallel_tasks,
    _quick_tool_call,
)


class TestConstants:
    def test_constants_are_reasonable(self):
        assert MAX_CONCURRENT_SUBAGENTS >= 1
        assert MAX_CONCURRENT_SUBAGENTS <= 10
        assert SUBAGENT_TIMEOUT > 0


def _make_mock_response(status_code=200, content="Test response", tool_calls=None):
    """Helper to create a proper httpx mock response."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": content,
                    "tool_calls": tool_calls or [],
                }
            }
        ]
    }
    return mock_response


class TestQuickToolCall:
    async def test_successful_call(self):
        with patch("hermes_mobile.core.delegation.httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=_make_mock_response())

            result = await _quick_tool_call(
                provider_url="https://api.openai.com/v1",
                api_key="sk-test",
                model="gpt-4o",
                system_prompt="You are helpful.",
                user_prompt="Say hello",
            )
            assert result == "Test response"

    async def test_openrouter_headers(self):
        with patch("hermes_mobile.core.delegation.httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=_make_mock_response())

            await _quick_tool_call(
                provider_url="https://openrouter.ai/api/v1",
                api_key="sk-test",
                model="gpt-4o",
                system_prompt="You are helpful.",
                user_prompt="Say hello",
            )
            _, kwargs = mock_client.post.call_args
            headers = kwargs["headers"]
            assert "HTTP-Referer" in headers
            assert "X-Title" in headers

    async def test_http_error(self):
        with patch("hermes_mobile.core.delegation.httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=_make_mock_response(status_code=401))

            result = await _quick_tool_call(
                provider_url="https://api.openai.com/v1",
                api_key="bad-key",
                model="gpt-4o",
                system_prompt="You are helpful.",
                user_prompt="Say hello",
            )
            assert "HTTP 401" in result

    async def test_timeout(self):
        with patch("hermes_mobile.core.delegation.httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            from httpx import TimeoutException

            mock_client.post = AsyncMock(side_effect=TimeoutException("Timed out"))

            result = await _quick_tool_call(
                provider_url="https://api.openai.com/v1",
                api_key="sk-test",
                model="gpt-4o",
                system_prompt="You are helpful.",
                user_prompt="Say hello",
            )
            assert "timed out" in result.lower()

    async def test_tool_call_handling(self):
        with patch("hermes_mobile.core.delegation.httpx.AsyncClient") as mock_client_cls:
            with patch(
                "hermes_mobile.core.delegation.web_search_tool", new_callable=AsyncMock
            ) as mock_search:
                mock_search.return_value = {"results": [{"title": "Result 1"}], "query": "test"}

                mock_client = MagicMock()
                mock_client_cls.return_value.__aenter__.return_value = mock_client
                mock_client.post = AsyncMock(
                    return_value=_make_mock_response(
                        content="Let me search",
                        tool_calls=[
                            {
                                "function": {
                                    "name": "web_search",
                                    "arguments": '{"query": "test query"}',
                                }
                            }
                        ],
                    )
                )

                result = await _quick_tool_call(
                    provider_url="https://api.openai.com/v1",
                    api_key="sk-test",
                    model="gpt-4o",
                    system_prompt="You are helpful.",
                    user_prompt="Search for something",
                    available_tools=[{"type": "function", "function": {"name": "web_search"}}],
                )
                assert "Tool results" in result
                assert "1 results" in result
                mock_search.assert_called_once()


class TestDelegateTask:
    @patch("hermes_mobile.core.delegation.get_settings")
    async def test_no_api_key_returns_error(self, mock_get_settings):
        from hermes_mobile.config.settings import HermesMobileSettings

        settings = HermesMobileSettings()
        settings.default_provider = "openai"
        settings.openai_api_key = None
        settings.default_model = "gpt-4o"
        mock_get_settings.return_value = settings

        result = await delegate_task("test task")
        assert result["task"] == "test task"
        assert result["result"] == "No API key configured for subagent"


class TestDelegateParallelTasks:
    async def test_empty_tasks(self):
        result = await delegate_parallel_tasks([])
        assert result == {"results": [], "summary": "No tasks provided"}

    @patch("hermes_mobile.core.delegation.delegate_task")
    async def test_parallel_execution(self, mock_delegate):
        mock_delegate.return_value = {"task": "test", "result": "done"}

        result = await delegate_parallel_tasks(["task1", "task2", "task3"])
        assert len(result["results"]) == 3
        assert mock_delegate.call_count == 3

    @patch("hermes_mobile.core.delegation.delegate_task")
    async def test_task_descriptions_in_results(self, mock_delegate):
        mock_delegate.return_value = {"task": "test", "result": "done"}

        result = await delegate_parallel_tasks(["Task A", "Task B"])
        assert len(result["results"]) == 2
