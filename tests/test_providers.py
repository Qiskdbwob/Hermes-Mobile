"""Tests for provider profiles."""

from hermes_mobile.providers import (
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
    get_provider_profile,
    list_providers,
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
