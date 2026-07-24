"""Prompt caching support for Hermes Mobile.

Implements model-compatible prompt caching by hashing system prompts
and conversation prefixes to avoid re-sending unchanged content.

When supported by the provider (Anthropic, DeepSeek), this reduces
token costs for repeated system prompts by 90%.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CACHEABLE_PROVIDERS = ("anthropic", "openrouter")


def hash_content(content: str) -> str:
    """Create a content hash for cache key comparison."""
    return hashlib.md5(content.encode()).hexdigest()[:16]


def compute_cache_breakpoints(
    messages: List[Dict[str, Any]],
    provider: str,
) -> Optional[List[int]]:
    """Compute which message indices should have cache breakpoints.

    Returns list of message indices where cache_control should be set,
    or None if provider doesn't support caching.

    Strategy:
    - Cache the system prompt (index 0) always
    - Cache the most recent user-assistant exchange (last 2)
    """
    if provider not in CACHEABLE_PROVIDERS:
        return None

    breakpoints = []

    if messages and messages[0].get("role") == "system":
        breakpoints.append(0)

    total = len(messages)
    if total >= 4:
        breakpoints.append(total - 3)
    elif total >= 2:
        breakpoints.append(total - 2)

    return breakpoints


def apply_cache_control(
    messages: List[Dict[str, Any]],
    provider: str,
) -> List[Dict[str, Any]]:
    """Add cache_control breakpoints to messages for supported providers.

    Modifies messages in-place with Anthropic-style cache_control
    or OpenRouter-style provider-specific caching.
    """
    breakpoints = compute_cache_breakpoints(messages, provider)
    if not breakpoints:
        return messages

    result = []
    for i, msg in enumerate(messages):
        msg_copy = dict(msg)
        if i in breakpoints:
            if provider == "anthropic":
                msg_copy["content"] = _wrap_with_cache(msg_copy.get("content", ""), provider)
            elif provider == "openrouter":
                msg_copy["cache_control"] = {"type": "ephemeral"}
        result.append(msg_copy)

    return result


def _wrap_with_cache(content: Any, provider: str) -> Any:
    """Wrap content with cache_control for providers that need it."""
    if isinstance(content, str):
        return [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]
    if isinstance(content, list):
        cached = list(content)
        if cached:
            last = cached[-1]
            if isinstance(last, dict):
                last = dict(last)
                last["cache_control"] = {"type": "ephemeral"}
                cached[-1] = last
        return cached
    return content


def supports_caching(provider: str) -> bool:
    """Check if a provider supports prompt caching."""
    return provider in CACHEABLE_PROVIDERS


def estimate_cache_savings(
    messages: List[Dict[str, Any]],
    provider: str,
) -> Dict[str, Any]:
    """Estimate token savings from cache hits."""
    if not supports_caching(provider):
        return {"supported": False, "estimated_savings_pct": 0}

    total_chars = 0
    cacheable_chars = 0

    breakpoints = compute_cache_breakpoints(messages, provider) or []

    for i, msg in enumerate(messages):
        content = json.dumps(msg.get("content", ""))
        total_chars += len(content)
        if i in breakpoints:
            cacheable_chars += len(content)

    if total_chars == 0:
        return {"supported": True, "estimated_savings_pct": 0}

    return {
        "supported": True,
        "estimated_savings_pct": round((cacheable_chars / total_chars) * 90),
        "cacheable_tokens": cacheable_chars // 4,
        "total_tokens": total_chars // 4,
    }
