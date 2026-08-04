"""Provider Profiles System - Declarative provider configuration like Hermes Desktop"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Sentinel for "omit temperature entirely" (some providers manage it server-side)
OMIT_TEMPERATURE = object()


def _profile_user_agent() -> str:
    """Return a hermes-mobile/<version> UA string."""
    try:
        from hermes_mobile import __version__ as _ver

        return f"hermes-mobile/{_ver}"
    except Exception:
        return "hermes-mobile"


@dataclass
class ProviderProfile:
    """Base provider profile — subclass or instantiate with overrides."""

    # ── Identity ─────────────────────────────────────────────
    name: str
    api_mode: str = "chat_completions"
    aliases: Tuple[str, ...] = ()

    # ── Human-readable metadata ───────────────────────────────
    display_name: str = ""
    description: str = ""
    signup_url: str = ""

    # ── Auth & endpoints ─────────────────────────────────────
    env_vars: Tuple[str, ...] = ()
    base_url: str = ""
    models_url: str = ""
    auth_type: str = "api_key"  # api_key|oauth_device_code|oauth_external|copilot|aws_sdk
    supports_health_check: bool = True

    # ── Vision support ────────────────────────────────────────
    supports_vision: bool = False
    supports_vision_tool_messages: bool = True

    # ── Model catalog ─────────────────────────────────────────
    fallback_models: Tuple[str, ...] = ()
    hostname: str = ""

    # ── Client-level quirks (set once at client construction) ─
    default_headers: Dict[str, str] = field(default_factory=dict)

    # ── Request-level quirks ─────────────────────────────────
    fixed_temperature: Any = None
    default_max_tokens: Optional[int] = None
    default_aux_model: str = ""

    # ── Hooks (override in subclass for complex providers) ───

    def get_hostname(self) -> str:
        """Return the provider's base hostname for URL-based detection."""
        if self.hostname:
            return self.hostname
        if self.base_url:
            from urllib.parse import urlparse

            return urlparse(self.base_url).hostname or ""
        return ""

    def prepare_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Provider-specific message preprocessing. Default: pass-through."""
        return messages

    def build_extra_body(
        self, *, session_id: Optional[str] = None, **context: Any
    ) -> Dict[str, Any]:
        """Provider-specific extra_body fields. Default: empty dict."""
        return {}

    def build_api_kwargs_extras(
        self,
        *,
        reasoning_config: Optional[Dict] = None,
        **context: Any,
    ) -> Dict[str, Any]:
        """Provider-specific API kwargs extras. Default: empty dict."""
        return {}


# ═══════════════════════════════════════════════════════════════
# Built-in Provider Profiles
# ═══════════════════════════════════════════════════════════════


class OpenRouterProfile(ProviderProfile):
    def __init__(self):
        super().__init__(
            name="openrouter",
            display_name="OpenRouter",
            description="Access 300+ models via unified API",
            signup_url="https://openrouter.ai/",
            env_vars=("OPENROUTER_API_KEY",),
            base_url="https://openrouter.ai/api/v1",
            models_url="https://openrouter.ai/api/v1/models",
            auth_type="api_key",
            supports_vision=True,
            supports_vision_tool_messages=True,
            fallback_models=(
                "anthropic/claude-3.5-sonnet",
                "openai/gpt-4o",
                "google/gemini-1.5-pro",
                "meta-llama/llama-3.1-405b-instruct",
                "mistralai/mistral-large",
            ),
            hostname="openrouter.ai",
            default_headers={
                "HTTP-Referer": "https://github.com/hermes-mobile",
                "X-Title": "Hermes Mobile",
            },
        )


class OpenAIProfile(ProviderProfile):
    def __init__(self):
        super().__init__(
            name="openai",
            display_name="OpenAI",
            description="Official OpenAI API",
            signup_url="https://platform.openai.com/",
            env_vars=("OPENAI_API_KEY",),
            base_url="https://api.openai.com/v1",
            models_url="https://api.openai.com/v1/models",
            auth_type="api_key",
            supports_vision=True,
            supports_vision_tool_messages=True,
            fallback_models=(
                "gpt-4o",
                "gpt-4o-mini",
                "gpt-4-turbo",
                "gpt-3.5-turbo",
            ),
            hostname="api.openai.com",
        )


class AnthropicProfile(ProviderProfile):
    def __init__(self):
        super().__init__(
            name="anthropic",
            display_name="Anthropic",
            description="Claude models via Anthropic API",
            signup_url="https://console.anthropic.com/",
            env_vars=("ANTHROPIC_API_KEY",),
            base_url="https://api.anthropic.com/v1",
            models_url="https://api.anthropic.com/v1/models",
            auth_type="api_key",
            api_mode="messages",
            supports_vision=True,
            supports_vision_tool_messages=True,
            fallback_models=(
                "claude-3-5-sonnet-20241022",
                "claude-3-5-haiku-20241022",
                "claude-3-opus-20240229",
            ),
            hostname="api.anthropic.com",
            default_headers={
                "anthropic-version": "2023-06-01",
            },
        )

    def build_api_kwargs_extras(
        self, *, reasoning_config: Optional[Dict] = None, **context: Any
    ) -> Dict[str, Any]:
        extras = {}
        if reasoning_config:
            extras["thinking"] = reasoning_config
        return extras


class GoogleProfile(ProviderProfile):
    def __init__(self):
        super().__init__(
            name="google",
            aliases=("gemini",),
            display_name="Google AI",
            description="Gemini models via Google AI Studio",
            signup_url="https://aistudio.google.com/",
            env_vars=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            models_url="https://generativelanguage.googleapis.com/v1beta/models",
            auth_type="api_key",
            supports_vision=True,
            supports_vision_tool_messages=True,
            fallback_models=(
                "gemini-1.5-pro",
                "gemini-1.5-flash",
                "gemini-1.0-pro",
            ),
            hostname="generativelanguage.googleapis.com",
        )


class GroqProfile(ProviderProfile):
    def __init__(self):
        super().__init__(
            name="groq",
            display_name="Groq",
            description="Fast inference for open models",
            signup_url="https://console.groq.com/",
            env_vars=("GROQ_API_KEY",),
            base_url="https://api.groq.com/openai/v1",
            models_url="https://api.groq.com/openai/v1/models",
            auth_type="api_key",
            supports_vision=False,
            fallback_models=(
                "llama-3.1-70b-versatile",
                "llama-3.1-8b-instant",
                "mixtral-8x7b-32768",
                "gemma2-9b-it",
            ),
            hostname="api.groq.com",
        )


class TogetherProfile(ProviderProfile):
    def __init__(self):
        super().__init__(
            name="together",
            display_name="Together AI",
            description="Open models with fast inference",
            signup_url="https://api.together.xyz/",
            env_vars=("TOGETHER_API_KEY",),
            base_url="https://api.together.xyz/v1",
            models_url="https://api.together.xyz/v1/models",
            auth_type="api_key",
            supports_vision=True,
            fallback_models=(
                "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo",
                "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
                "mistralai/Mixtral-8x7B-Instruct-v0.1",
            ),
            hostname="api.together.xyz",
        )


class DeepSeekProfile(ProviderProfile):
    def __init__(self):
        super().__init__(
            name="deepseek",
            display_name="DeepSeek",
            description="DeepSeek models",
            signup_url="https://platform.deepseek.com/",
            env_vars=("DEEPSEEK_API_KEY",),
            base_url="https://api.deepseek.com/v1",
            models_url="https://api.deepseek.com/v1/models",
            auth_type="api_key",
            fallback_models=(
                "deepseek-chat",
                "deepseek-coder",
            ),
            hostname="api.deepseek.com",
        )


class XAIProfile(ProviderProfile):
    def __init__(self):
        super().__init__(
            name="xai",
            display_name="xAI",
            description="Grok models via xAI",
            signup_url="https://console.x.ai/",
            env_vars=("XAI_API_KEY",),
            base_url="https://api.x.ai/v1",
            models_url="https://api.x.ai/v1/models",
            auth_type="api_key",
            fallback_models=("grok-beta",),
            hostname="api.x.ai",
        )


class OllamaProfile(ProviderProfile):
    def __init__(self):
        super().__init__(
            name="ollama",
            display_name="Ollama (Local)",
            description="Local models via Ollama",
            signup_url="https://ollama.com/",
            env_vars=("OLLAMA_HOST",),
            base_url="http://localhost:11434/v1",
            models_url="http://localhost:11434/api/tags",
            auth_type="api_key",
            supports_vision=True,
            fallback_models=(
                "llama3.1:70b",
                "llama3.1:8b",
                "mistral:7b",
                "codellama:7b",
            ),
            hostname="localhost",
        )

    def get_hostname(self) -> str:
        return "ollama-local"


# ═══════════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════════

_REGISTRY: Dict[str, ProviderProfile] = {}
_ALIASES: Dict[str, str] = {}
_DISCOVERED = False


def register_provider(profile: ProviderProfile) -> None:
    """Register a provider profile by name and aliases."""
    _REGISTRY[profile.name] = profile
    for alias in profile.aliases:
        _ALIASES[alias] = profile.name


def get_provider_profile(name: str) -> Optional[ProviderProfile]:
    """Look up a provider profile by name or alias."""
    global _DISCOVERED
    if not _DISCOVERED:
        _discover_providers()
    canonical = _ALIASES.get(name, name)
    return _REGISTRY.get(canonical)


def list_providers() -> List[ProviderProfile]:
    """Return all registered provider profiles."""
    global _DISCOVERED
    if not _DISCOVERED:
        _discover_providers()
    seen: set[int] = set()
    result: List[ProviderProfile] = []
    for profile in _REGISTRY.values():
        pid = id(profile)
        if pid not in seen:
            seen.add(pid)
            result.append(profile)
    return result


def list_local_providers() -> List[ProviderProfile]:
    """Return only providers this Android runtime can call honestly."""
    return [
        profile
        for profile in list_providers()
        if profile.api_mode == "chat_completions" and profile.name != "ollama"
    ]


async def fetch_provider_models(
    profile: ProviderProfile,
    api_key: str = "",
    *,
    client: Any = None,
) -> List[str]:
    """Fetch and normalize the provider's current model catalog."""
    import httpx

    if not profile.models_url:
        return list(profile.fallback_models)
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=20.0)
    headers: Dict[str, str] = {}
    params: Dict[str, str] = {}
    if profile.name == "google":
        if api_key:
            params["key"] = api_key
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        response = await http.get(profile.models_url, headers=headers, params=params)
        response.raise_for_status()
        payload = response.json()
    finally:
        if owns_client:
            await http.aclose()
    raw = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(raw, list) and isinstance(payload, dict):
        raw = payload.get("models")
    models: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str):
            model = item
        elif isinstance(item, dict):
            model = str(item.get("id") or item.get("name") or item.get("model") or "")
        else:
            continue
        model = model.removeprefix("models/").strip()
        if model:
            models.append(model)
    return sorted(set(models), key=str.lower) or list(profile.fallback_models)


def _discover_providers() -> None:
    """Populate the registry with built-in providers."""
    global _DISCOVERED
    _DISCOVERED = True

    # Register built-in profiles
    for profile_class in [
        OpenRouterProfile,
        OpenAIProfile,
        AnthropicProfile,
        GoogleProfile,
        GroqProfile,
        TogetherProfile,
        DeepSeekProfile,
        XAIProfile,
        OllamaProfile,
    ]:
        try:
            register_provider(profile_class())
        except Exception as exc:
            logger.warning("Failed to register provider %s: %s", profile_class.__name__, exc)


# Initialize on import
_discover_providers()
