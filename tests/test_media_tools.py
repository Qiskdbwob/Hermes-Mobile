"""Tests for vision_analyze / image_generate tool hardening.

Covers:
- vision_analyze blocks local paths outside the file sandbox (no exfil).
- vision model is chosen per active provider (OpenRouter IDs only for
  OpenRouter), and unsupported providers fail gracefully.
- image_generate uses the active provider's key/base_url/model consistently
  and saves b64 payloads to disk instead of returning truncated data.
"""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from hermes_mobile.providers import GroqProfile, OpenAIProfile, OpenRouterProfile
from hermes_mobile.tools.media_tools import image_generate_tool, vision_analyze_tool


def make_agent(profile, *, client=None, workspace=None, api_key="sk-test", base_url=None):
    agent = SimpleNamespace(
        _client=client,
        _workspace=workspace,
        provider=profile.name,
        model="test-model",
    )
    agent._get_provider_profile = lambda: profile
    agent._get_base_url = lambda: base_url or profile.base_url
    agent._get_api_key = lambda: api_key
    agent._require_client = lambda: client
    return agent


class FakeCompletions:
    def __init__(self):
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="desc"))])


class TestVisionAnalyze:
    async def test_blocks_local_path_outside_sandbox(self, tmp_path):
        profile = OpenAIProfile()
        client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
        agent = make_agent(profile, client=client, workspace=tmp_path)
        outside = tmp_path.parent / "leak.txt"
        outside.write_text("should not be read")

        result = await vision_analyze_tool(str(outside), agent=agent)

        assert "blocked" in result.get("error", "").lower()
        assert "outside" in result.get("error", "").lower()

    async def test_reads_local_path_inside_workspace(self, tmp_path):
        profile = OpenAIProfile()
        completions = FakeCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        agent = make_agent(profile, client=client, workspace=tmp_path)
        img = tmp_path / "photo.png"
        img.write_bytes(b"\x89PNG fake")

        result = await vision_analyze_tool(str(img), agent=agent)

        assert result["analysis"] == "desc"
        call = completions.calls[0]
        assert call["model"] == "gpt-4o-mini"
        part = call["messages"][0]["content"][1]
        assert part["type"] == "image_url"
        assert part["image_url"]["url"].startswith("data:image/png;base64,")

    async def test_uses_openrouter_model_id_for_openrouter(self):
        profile = OpenRouterProfile()
        completions = FakeCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        agent = make_agent(profile, client=client)

        result = await vision_analyze_tool("https://example.com/x.png", agent=agent)

        assert result["analysis"] == "desc"
        assert completions.calls[0]["model"] == "openai/gpt-4o-mini"

    async def test_unsupported_provider_errors(self):
        profile = GroqProfile()  # supports_vision=False
        client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
        agent = make_agent(profile, client=client)

        result = await vision_analyze_tool("https://example.com/x.png", agent=agent)

        assert "does not support vision" in result["error"]

    async def test_missing_client_reports_reason(self):
        agent = make_agent(OpenAIProfile(), client=None)
        agent._client_error = "Provider 'anthropic' requires the 'messages' API"

        result = await vision_analyze_tool("https://example.com/x.png", agent=agent)

        assert "messages" in result["error"]


class TestImageGenerate:
    async def test_uses_active_provider_endpoint_and_model(self):
        profile = OpenAIProfile()
        agent = make_agent(profile, api_key="sk-openai")
        with patch("hermes_mobile.tools.media_tools.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_client
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"data": [{"url": "https://img.example/1.png"}]}
            mock_client.post = AsyncMock(return_value=resp)

            result = await image_generate_tool("a cat", agent=agent)

        assert result["url"] == "https://img.example/1.png"
        called_url = mock_client.post.call_args[0][0]
        assert called_url == "https://api.openai.com/v1/images/generations"
        payload = mock_client.post.call_args.kwargs["json"]
        assert payload["model"] == "gpt-image-1"
        headers = mock_client.post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer sk-openai"

    async def test_unsupported_provider_errors_gracefully(self):
        agent = make_agent(GroqProfile(), api_key="sk-groq")

        result = await image_generate_tool("a cat", agent=agent)

        assert "does not expose an image generation endpoint" in result["error"]

    async def test_missing_key_errors(self):
        agent = make_agent(OpenAIProfile(), api_key="")

        result = await image_generate_tool("a cat", agent=agent)

        assert "No API key configured" in result["error"]

    async def test_b64_saved_to_file(self, test_settings):
        agent = make_agent(OpenAIProfile(), api_key="sk-openai")
        raw = b"\x89PNG generated"
        with patch("hermes_mobile.tools.media_tools.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_client
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"data": [{"b64_json": base64.b64encode(raw).decode()}]}
            mock_client.post = AsyncMock(return_value=resp)

            result = await image_generate_tool("a dog", agent=agent)

        assert "saved_path" in result
        saved = Path(result["saved_path"])
        assert saved.exists()
        assert saved.read_bytes() == raw
