"""Lightweight context compression for mobile conversations.

When conversation history approaches the model's context limit,
compress older turns into a concise summary while preserving the
system prompt and most recent messages.

Adapted from Hermes Desktop agent/context_compressor.py.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

TOKEN_ESTIMATE_CHARS_PER_TOKEN = 4
COMPRESSION_THRESHOLD_RATIO = 0.75
TAIL_PRESERVE_COUNT = 6
SUMMARY_PLACEHOLDER = "[Previous conversation summarized]"


def estimate_tokens(messages: List[Dict[str, Any]]) -> int:
    """Rough token estimate: characters / 4."""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += len(content)
        tool_calls = msg.get("tool_calls", [])
        if tool_calls:
            total += len(str(tool_calls))
    return max(1, total // TOKEN_ESTIMATE_CHARS_PER_TOKEN)


def needs_compression(
    messages: List[Dict[str, Any]],
    max_tokens: int = 128000,
) -> bool:
    """Check if messages should be compressed."""
    current = estimate_tokens(messages)
    threshold = int(max_tokens * COMPRESSION_THRESHOLD_RATIO)
    return current > threshold


def compress_messages(
    messages: List[Dict[str, Any]],
    max_tokens: int = 128000,
    previous_summary: str | None = None,
) -> List[Dict[str, Any]]:
    """Compress a conversation by summarizing the middle section.

    Strategy:
    - Keep system prompt (index 0)
    - Keep the most recent TAIL_PRESERVE_COUNT messages
    - Summarize everything in between
    - Return compressed message list

    The caller should then call a cheap LLM to generate the actual
    summary text, then insert it as a system message.

    Returns the compressed message list with a placeholder summary.
    """
    if not messages or len(messages) <= TAIL_PRESERVE_COUNT:
        return messages

    system_prompt = messages[0] if messages[0].get("role") == "system" else None
    tail_start = max(1, len(messages) - TAIL_PRESERVE_COUNT)
    middle = messages[1:tail_start] if system_prompt else messages[:tail_start]
    tail = messages[tail_start:]

    summary_text = _build_summary_text(middle)

    if previous_summary:
        summary_text = previous_summary + "\n\n" + summary_text

    compressed = []
    if system_prompt:
        compressed.append(system_prompt)

    compressed.append(
        {
            "role": "system",
            "content": f"Previous conversation summary:\n{summary_text[:4000]}",
        }
    )

    compressed.extend(tail)

    return compressed


def _build_summary_text(messages: List[Dict[str, Any]]) -> str:
    """Build a text summary of middle conversation turns."""
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if role == "user":
            lines.append(f"User: {content[:200]}")
        elif role == "assistant":
            lines.append(f"Assistant: {content[:200]}")
        elif role == "tool":
            name = msg.get("name", "unknown")
            result = content[:100]
            lines.append(f"Tool [{name}]: {result}")

    return "\n".join(lines[-20:])


def get_conversation_stats(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Get conversation statistics for monitoring."""
    estimated_tokens = estimate_tokens(messages)
    return {
        "message_count": len(messages),
        "estimated_tokens": estimated_tokens,
        "needs_compression": needs_compression(messages),
        "roles": {
            role: sum(1 for m in messages if m.get("role") == role)
            for role in ("system", "user", "assistant", "tool")
        },
    }
