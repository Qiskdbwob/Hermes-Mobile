"""Lightweight extractive session summarization.

Builds a deterministic plaintext summary from conversation messages without any
LLM call: title (first user message), exchange count, key topics (stopword-
filtered word frequency across user messages), tools used, and the last user
question. Cheap, offline, and safe for encrypted storage — the summary is
persisted encrypted like every other value in ``session_summaries``.

The summary gives ``session_search`` real signal: before this module existed,
session search only had the raw first message of a session as "preview", which
made questions like "apa yang saya bahas tadi?" unanswerable.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable, List

_STOPWORDS = {
    # English
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "of",
    "to",
    "in",
    "on",
    "for",
    "with",
    "at",
    "by",
    "from",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "it",
    "this",
    "that",
    "these",
    "those",
    "i",
    "you",
    "he",
    "she",
    "we",
    "they",
    "my",
    "your",
    "our",
    "their",
    "me",
    "us",
    "him",
    "her",
    "them",
    "do",
    "does",
    "did",
    "can",
    "could",
    "will",
    "would",
    "should",
    "shall",
    "may",
    "might",
    "must",
    "what",
    "which",
    "who",
    "whom",
    "when",
    "where",
    "why",
    "how",
    "not",
    "no",
    "yes",
    "please",
    "just",
    "about",
    "into",
    "over",
    "after",
    "before",
    "more",
    "most",
    "some",
    "any",
    "all",
    "each",
    "every",
    "both",
    "few",
    "also",
    "too",
    "very",
    "really",
    "ok",
    "okay",
    "thanks",
    "thank",
    "sure",
    # Indonesian
    "saya",
    "aku",
    "kamu",
    "anda",
    "engkau",
    "dia",
    "ia",
    "kami",
    "kita",
    "mereka",
    "yang",
    "dan",
    "atau",
    "di",
    "ke",
    "dari",
    "untuk",
    "dengan",
    "pada",
    "adalah",
    "ini",
    "itu",
    "apakah",
    "tolong",
    "bisa",
    "dapat",
    "akan",
    "tidak",
    "jangan",
    "bukan",
    "kalau",
    "jika",
    "karena",
    "sebab",
    "tapi",
    "tetapi",
    "juga",
    "sudah",
    "belum",
    "masih",
    "lagi",
    "saat",
    "ketika",
    "seperti",
    "tentang",
    "oleh",
    "sampai",
    "setelah",
    "sebelum",
    "ada",
    "saja",
    "ya",
    "oke",
    "terima",
    "kasih",
    "mau",
    "ingin",
    "harus",
    "boleh",
}

_WORD_RE = re.compile(r"[a-zA-Z0-9_]{3,}")

_MAX_TITLE = 60
_MAX_TOPICS = 6
_MAX_SUMMARY = 600
_MAX_TOOLS = 8


def _text_of(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("content") or "")
    return str(getattr(msg, "content", None) or "")


def _role_of(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("role") or "")
    return str(getattr(msg, "role", "") or "")


def _tool_names(msg: Any) -> List[str]:
    """Collect tool names from an assistant message (dict or Message object)."""
    if isinstance(msg, dict):
        calls = msg.get("tool_calls") or []
    else:
        calls = getattr(msg, "tool_calls", None) or []
    names: List[str] = []
    for tc in calls:
        if isinstance(tc, dict):
            fn = tc.get("function") or {}
            if isinstance(fn, dict):
                name = fn.get("name")
            else:
                name = getattr(fn, "name", None)
        else:
            # Project ToolCall exposes .name directly (no .function wrapper).
            name = getattr(tc, "name", None) or getattr(getattr(tc, "function", None), "name", None)
        if name:
            names.append(str(name))
    return names


def _squash(text: str, limit: int) -> str:
    return re.sub(r"\s+", " ", text).strip()[:limit]


def extract_keywords(text: str, limit: int = 40) -> List[str]:
    """Extract the most frequent non-stopword tokens from *text*.

    Used to build the plaintext ``session_keywords`` search index: tokens are
    non-sensitive (stopword-filtered), mirroring the existing
    ``normalized_hash`` plaintext-for-dedup pattern. Returns lowercase tokens,
    most frequent first.
    """
    words: Counter[str] = Counter()
    for word in _WORD_RE.findall(str(text or "").lower()):
        if word not in _STOPWORDS and len(word) >= 3:
            words[word] += 1
    return [word for word, _ in words.most_common(limit)]


def build_session_summary(messages: Iterable[Any]) -> str:
    """Build an extractive summary of a conversation (no LLM call).

    Accepts a list of dicts (``{"role": ..., "content": ..., "tool_calls": ...}``)
    or objects with the same attributes (``Message`` from ``core.agent``).
    Returns "" for empty/conversations with no user messages.
    """
    messages = list(messages)
    user_texts = []
    for m in messages:
        if _role_of(m) != "user":
            continue
        text = _text_of(m).strip()
        if text:
            user_texts.append(text)
    if not user_texts:
        return ""

    title = _squash(user_texts[0], _MAX_TITLE)
    exchange_count = sum(1 for m in messages if _role_of(m) == "assistant")

    words: Counter[str] = Counter()
    for text in user_texts:
        for word in _WORD_RE.findall(text.lower()):
            if word not in _STOPWORDS:
                words[word] += 1
    topics = ", ".join(word for word, _ in words.most_common(_MAX_TOPICS))

    tools: List[str] = []
    seen: set = set()
    for m in messages:
        for name in _tool_names(m):
            if name and name not in seen:
                seen.add(name)
                tools.append(name)

    parts = [f"Topic: {title}", f"Exchanges: {exchange_count}"]
    if topics:
        parts.append(f"Keywords: {topics}")
    if tools:
        parts.append(f"Tools: {', '.join(tools[:_MAX_TOOLS])}")
    if len(user_texts) > 1:
        parts.append(f"Latest: {_squash(user_texts[-1], _MAX_TITLE)}")

    summary = " · ".join(parts)
    return summary[:_MAX_SUMMARY]
