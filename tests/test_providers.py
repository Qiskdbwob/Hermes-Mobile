"""Tests for provider profiles."""

from unittest.mock import patch

import httpx
import pytest

from hermes_mobile.providers import (
    _DISCOVERED,
    AnthropicProfile,
    DeepSeekProfile,
    GoogleProfile,
    GroqProfile,
    OllamaProfile,
    OpenAIProfile,
    OpenRouterProfile,
    ProviderProfile,
    TogetherProfile,
    XAIProfile,
    _profile_user_agent,
    fetch_provider_models,
    get_provider_profile,
    list_local_providers,
    list_providers,
    register_provider,
)


class TestProviderProfile:
    def test_base_profile_defaults(self):
        p = ProviderProfile(name="test", base_url="https://test.api.com/v1")
        assert p.name == "test"
        assert p.api_mode == "chat_completions"
        assert p.auth_type == "api_key"
        assert p.supports_vision is False
        assert p.fallback_models == ()

    def test_get_hostname_from_base_url(self):
        p = ProviderProfile(name="test", base_url="https://api.example.com/v1")
        assert p.get_hostname() == "api.example.com"

    def test_get_hostname_from_hostname_field(self):
        p = ProviderProfile(name="test", hostname="custom.example.com")
        assert p.get_hostname() == "custom.example.com"

    def test_get_hostname_fallback(self):
        p = ProviderProfile(name="test")
        assert p.get_hostname() == ""

    def test_prepare_messages_default(self):
        p = ProviderProfile(name="test")
        msgs = [{"role": "user", "content": "hello"}]
        assert p.prepare_messages(msgs) is msgs

    def test_build_extra_body_default(self):
        p = ProviderProfile(name="test")
        assert p.build_extra_body() == {}

    def test_build_api_kwargs_default(self):
        p = ProviderProfile(name="test")
        assert p.build_api_kwargs_extras() == {}


class TestBuiltinProfiles:
    def test_openrouter_profile(self):
        p = OpenRouterProfile()
        assert p.name == "openrouter"
        assert p.base_url == "https://openrouter.ai/api/v1"
        assert "OPENROUTER_API_KEY" in p.env_vars
        assert p.supports_vision is True
        assert len(p.fallback_models) >= 3
        assert "HTTP-Referer" in p.default_headers

    def test_openai_profile(self):
        p = OpenAIProfile()
        assert p.name == "openai"
        assert "OPENAI_API_KEY" in p.env_vars
        assert p.base_url == "https://api.openai.com/v1"
        assert p.supports_vision is True

    def test_anthropic_profile(self):
        p = AnthropicProfile()
        assert p.name == "anthropic"
        assert "ANTHROPIC_API_KEY" in p.env_vars
        assert p.supports_vision is True

    def test_google_profile(self):
        p = GoogleProfile()
        assert p.name == "google"
        assert "GEMINI_API_KEY" in p.env_vars
        assert p.supports_vision is True

    def test_groq_profile(self):
        p = GroqProfile()
        assert p.name == "groq"
        assert "GROQ_API_KEY" in p.env_vars
        assert p.base_url == "https://api.groq.com/openai/v1"

    def test_together_profile(self):
        p = TogetherProfile()
        assert p.name == "together"
        assert "TOGETHER_API_KEY" in p.env_vars

    def test_deepseek_profile(self):
        p = DeepSeekProfile()
        assert p.name == "deepseek"
        assert "DEEPSEEK_API_KEY" in p.env_vars

    def test_ollama_profile(self):
        p = OllamaProfile()
        assert p.name == "ollama"
        assert p.base_url == "http://localhost:11434/v1"
        assert "OLLAMA_HOST" in p.env_vars

    def test_xai_profile(self):
        p = XAIProfile()
        assert p.name == "xai"
        assert "XAI_API_KEY" in p.env_vars

    def test_all_profiles_listed(self):
        profiles = list_providers()
        names = [p.name for p in profiles]
        assert "openrouter" in names
        assert "openai" in names
        assert "anthropic" in names
        assert "google" in names
        assert "groq" in names
        assert "together" in names
        assert "deepseek" in names
        assert "xai" in names
        assert "ollama" in names

    def test_local_provider_catalog_includes_ollama(self):
        names = [profile.name for profile in list_local_providers()]
        assert names == [
            "openrouter",
            "openai",
            "google",
            "groq",
            "together",
            "deepseek",
            "xai",
            "ollama",
        ]


@pytest.mark.asyncio
async def test_fetch_provider_models_normalizes_openai_and_google_shapes():
    async def run(profile, payload):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_provider_models(profile, "secret", client=client)

    assert await run(OpenAIProfile(), {"data": [{"id": "gpt-z"}, {"id": "gpt-a"}]}) == [
        "gpt-a",
        "gpt-z",
    ]
    assert await run(GoogleProfile(), {"models": [{"name": "models/gemini-x"}]}) == ["gemini-x"]


class TestGetProviderProfile:
    def test_get_by_name(self):
        p = get_provider_profile("openai")
        assert p is not None
        assert p.name == "openai"

    def test_get_by_uppercase_name_fails(self):
        # Case-sensitive lookup - uppercase won't match
        p = get_provider_profile("OpenAI")
        assert p is None

    def test_get_unknown_provider(self):
        p = get_provider_profile("nonexistent_provider_xyz")
        assert p is None

    def test_all_builtins_resolve_by_lowercase_name(self):
        for name in [
            "openrouter",
            "openai",
            "anthropic",
            "google",
            "groq",
            "together",
            "deepseek",
            "xai",
            "ollama",
        ]:
            p = get_provider_profile(name)
            assert p is not None, f"Failed to resolve provider: {name}"
            assert p.name == name

    def test_provider_env_vars_are_tuples(self):
        for p in list_providers():
            assert isinstance(p.env_vars, tuple), f"{p.name}: env_vars not a tuple"

    def test_all_providers_have_display_name(self):
        for p in list_providers():
            assert p.display_name, f"{p.name}: missing display_name"


class TestProfileUserAgent:
    def test_returns_version_string(self):
        ua = _profile_user_agent()
        assert "hermes-mobile" in ua


class TestAnthropicProfileExtras:
    def test_build_api_kwargs_with_reasoning(self):
        p = AnthropicProfile()
        result = p.build_api_kwargs_extras(
            reasoning_config={"type": "thinking", "budget_tokens": 1000}
        )
        assert "thinking" in result
        assert result["thinking"] == {"type": "thinking", "budget_tokens": 1000}

    def test_build_api_kwargs_without_reasoning(self):
        p = AnthropicProfile()
        result = p.build_api_kwargs_extras()
        assert result == {}


class TestOllamaProfileHostname:
    def test_ollama_hostname(self):
        p = OllamaProfile()
        assert p.get_hostname() == "ollama-local"


class TestOllamaOpenAICompat:
    def test_ollama_is_keyless(self):
        p = OllamaProfile()
        assert p.api_mode == "chat_completions"
        assert p.auth_type == "none"
        assert p.requires_api_key is False

    def test_ollama_resolve_urls_default(self, monkeypatch):
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        p = OllamaProfile()
        assert p.resolve_base_url() == "http://localhost:11434/v1"
        assert p.resolve_models_url() == "http://localhost:11434/api/tags"

    def test_ollama_resolve_urls_honors_host_env(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_HOST", "http://192.168.1.50:11434")
        p = OllamaProfile()
        assert p.resolve_base_url() == "http://192.168.1.50:11434/v1"
        assert p.resolve_models_url() == "http://192.168.1.50:11434/api/tags"

    def test_ollama_resolve_urls_honors_setting(self, monkeypatch):
        from hermes_mobile.config.settings import settings as global_settings

        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        monkeypatch.setattr(global_settings, "ollama_host", "http://10.0.0.5:11434")
        p = OllamaProfile()
        assert p.resolve_base_url() == "http://10.0.0.5:11434/v1"
        assert p.resolve_models_url() == "http://10.0.0.5:11434/api/tags"

    def test_ollama_resolve_urls_setting_beats_env(self, monkeypatch):
        from hermes_mobile.config.settings import settings as global_settings

        monkeypatch.setenv("OLLAMA_HOST", "http://env-host:11434")
        monkeypatch.setattr(global_settings, "ollama_host", "http://settings-host:11434")
        p = OllamaProfile()
        assert p.resolve_base_url() == "http://settings-host:11434/v1"
        assert p.resolve_models_url() == "http://settings-host:11434/api/tags"

    def test_ollama_resolve_urls_normalizes_v1_endpoint(self, monkeypatch):
        from hermes_mobile.config.settings import settings as global_settings

        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        monkeypatch.setattr(global_settings, "ollama_host", "http://10.0.0.5:11434/v1")
        p = OllamaProfile()
        # A full /v1 URL typed by the user is normalized, not doubled.
        assert p.resolve_base_url() == "http://10.0.0.5:11434/v1"
        assert p.resolve_models_url() == "http://10.0.0.5:11434/api/tags"

    async def test_fetch_ollama_models_uses_resolved_url(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_HOST", "http://192.168.1.50:11434")
        profile = OllamaProfile()
        captured = {}

        async def handler(request):
            captured["url"] = str(request.url)
            return httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}]})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            models = await fetch_provider_models(profile, "", client=client)

        assert models == ["llama3.1:8b"]
        assert "192.168.1.50" in captured["url"]
        assert "/api/tags" in captured["url"]


class TestRegisterProvider:
    def test_register_with_aliases(self):
        p = ProviderProfile(
            name="test-provider",
            aliases=("tp", "testp"),
            base_url="https://test.api/v1",
        )
        register_provider(p)
        # Should be findable by alias
        tp = get_provider_profile("tp")
        assert tp is not None
        assert tp.name == "test-provider"
        testp = get_provider_profile("testp")
        assert testp is not None


class TestDiscoveryEdgeCases:
    def test_get_provider_triggers_discovery(self):
        # Ensure discovery runs on first get_provider_profile call
        p = get_provider_profile("openai")
        assert p is not None
        assert p.name == "openai"

    def test_list_providers_triggers_discovery(self):
        providers = list_providers()
        assert len(providers) >= 9

    def test_discovery_lazy_get_provider(self):
        saved = _DISCOVERED
        try:
            import hermes_mobile.providers as p

            p._DISCOVERED = False
            p._REGISTRY.clear()
            p._ALIASES.clear()
            result = get_provider_profile("openai")
            assert result is not None
            assert p._DISCOVERED is True
        finally:
            import hermes_mobile.providers as p

            p._DISCOVERED = saved
            p._discover_providers()

    def test_discovery_lazy_list_providers(self):
        saved = _DISCOVERED
        try:
            import hermes_mobile.providers as p

            p._DISCOVERED = False
            p._REGISTRY.clear()
            p._ALIASES.clear()
            result = list_providers()
            assert len(result) >= 9
            assert p._DISCOVERED is True
        finally:
            import hermes_mobile.providers as p

            p._DISCOVERED = saved
            p._discover_providers()

    def test_discover_providers_error_handling(self):
        saved = _DISCOVERED
        try:
            import hermes_mobile.providers as p

            p._DISCOVERED = False
            p._REGISTRY.clear()
            p._ALIASES.clear()

            with patch.object(p.OpenAIProfile, "__init__", side_effect=RuntimeError("Init failed")):
                p._discover_providers()
                result = list_providers()
                assert "openai" not in [r.name for r in result]
        finally:
            import hermes_mobile.providers as p

            p._DISCOVERED = saved
            p._discover_providers()

    def test_user_agent_version_import_failure(self):
        import hermes_mobile

        saved = getattr(hermes_mobile, "__version__", None)
        try:
            del hermes_mobile.__version__
            ua = _profile_user_agent()
            assert ua == "hermes-mobile"
        finally:
            if saved is not None:
                hermes_mobile.__version__ = saved

    def test_user_agent_normal(self):
        with patch("hermes_mobile.__version__", "1.2.3", create=True):
            ua = _profile_user_agent()
            assert ua == "hermes-mobile/1.2.3"
