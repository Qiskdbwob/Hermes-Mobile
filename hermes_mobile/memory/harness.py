"""Memory Harness v1 — candidate extraction, memory policy, and snapshots.

Implements the v1 slice of Memory Harness v2 (docs/memory-harness-v2-gap.md):

- Level-1 extraction: explicit markers ("remember", "i prefer", "ingat",
  "saya lebih suka", ...) in English and Indonesian.
- Simple 3-dimension policy: AUTO_SAVE / ASK / IGNORE. No scoring formula
  beyond confidence + sensitivity + explicitness.
- ASK is bounded: an optional callback with a timeout; channels without a
  callback (gateway/remote) default to IGNORE so the pipeline never hangs.
- Frozen snapshot builder: ranks active memories and renders a stable,
  token-budgeted snapshot for the system prompt.

The harness is event-driven: it runs once per user turn from the agent loop and
from the existing cleanup cron — it never spawns a background process.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from hermes_mobile.memory.provider import MEMORY_TTL_DAYS

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────
# Markers (English + Indonesian). Confidence reflects how directly the
# statement expresses a durable preference.
# ────────────────────────────────────────────────────────────────────────

DIRECT_MARKERS: Dict[str, float] = {
    "remember": 0.95,
    "don't forget": 0.95,
    "do not forget": 0.95,
    "ingat": 0.95,
    "jangan lupa": 0.95,
    "i prefer": 0.95,
    "saya lebih suka": 0.95,
    "saya prefer": 0.9,
    "my project uses": 0.9,
    "proyek saya menggunakan": 0.9,
    "i use": 0.85,
    "saya menggunakan": 0.85,
}

# Habit/behavioral markers: high chance of implying automation or a durable
# behavior change, so they go through ASK instead of auto-saving.
HABIT_MARKERS: Dict[str, float] = {
    "from now on": 0.7,
    "dari sekarang": 0.7,
    "always": 0.65,
    "never": 0.65,
    "selalu": 0.65,
    "tidak pernah": 0.65,
}

SECRET_PATTERNS = (
    "api key",
    "apikey",
    "api_key",
    "password",
    "passwd",
    "secret",
    "bearer ",
    "sk-",
    "senha",
    "token",
)

PERMISSION_PATTERNS = ("grant", "allow access", "give permission", "beri izin", "izinkan")

_PROFILE_HINTS = (
    "prefer",
    "lebih suka",
    "language",
    "bahasa",
    "style",
    "gaya",
    "concise",
    "ringkas",
    "detail",
    "jawaban",
    "answers",
)
_PROJECT_HINTS = (
    "project",
    "proyek",
    "build",
    "environment",
    "lingkungan",
    "device",
    "perangkat",
    "repo",
    "kode",
)
_PATTERN_HINTS = ("setiap", "every", "selalu", "always", "whenever", "rutin", "rutin")


@dataclass
class MemoryCandidate:
    content: str
    session_id: str
    memory_type: str = "stable_fact"
    scope_type: str = "global"
    scope_id: Optional[str] = None
    confidence: float = 0.8
    importance: float = 0.6
    sensitivity: float = 0.0
    source_type: str = "user_explicit"
    evidence_type: str = "user_explicit"
    evidence_text: str = ""
    explicit: bool = True


def _classify(content: str) -> str:
    low = content.lower()
    if any(h in low for h in _PATTERN_HINTS):
        return "learned_pattern"
    if any(h in low for h in _PROFILE_HINTS):
        return "user_profile"
    if any(h in low for h in _PROJECT_HINTS):
        return "stable_fact"
    return "stable_fact"


def _sensitivity(content: str) -> float:
    low = content.lower()
    if any(p in low for p in SECRET_PATTERNS):
        return 1.0
    if any(p in low for p in PERMISSION_PATTERNS):
        return 0.8
    return 0.0


def _importance(memory_type: str) -> float:
    return {"user_profile": 0.7, "stable_fact": 0.7, "learned_pattern": 0.6, "episodic": 0.5}.get(
        memory_type, 0.6
    )


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", str(text or ""))
    return [p.strip() for p in parts if p and len(p.strip()) > 4]


def extract_candidates(text: str, session_id: str) -> List[MemoryCandidate]:
    """Extract explicit memory candidates from a user statement (Level 1).

    Only the user's own words are scanned — assistant echo ("I will remember
    that") would otherwise self-confirm noise into long-term memory.
    """
    candidates: List[MemoryCandidate] = []
    for sentence in _split_sentences(text):
        low = sentence.lower()
        marker = None
        for phrase, confidence in DIRECT_MARKERS.items():
            if phrase in low:
                marker = ("direct", phrase, confidence)
                break
        if marker is None:
            for phrase, confidence in HABIT_MARKERS.items():
                if phrase in low:
                    marker = ("habit", phrase, confidence)
                    break
        if marker is None:
            continue
        if len(sentence) > 300:
            continue  # a marker inside a huge paragraph is probably noise

        kind, _, confidence = marker
        memory_type = _classify(sentence)
        candidates.append(
            MemoryCandidate(
                content=sentence[:240],
                session_id=session_id,
                memory_type=memory_type,
                scope_type="user" if memory_type == "user_profile" else "global",
                confidence=confidence,
                importance=_importance(memory_type),
                sensitivity=_sensitivity(sentence),
                source_type="user_explicit",
                evidence_type="user_repeated" if kind == "habit" else "user_explicit",
                evidence_text=sentence[:300],
                explicit=True,
            )
        )
    return candidates


class MemoryPolicy:
    """Deterministic AUTO_SAVE / ASK / IGNORE decision (3 dimensions)."""

    def evaluate(self, candidate: MemoryCandidate, duplicate: Optional[Any]) -> str:
        if candidate.sensitivity >= 0.7:
            return "IGNORE"
        if duplicate is not None:
            return "IGNORE"
        if candidate.explicit and candidate.confidence >= 0.85 and candidate.sensitivity < 0.4:
            return "AUTO_SAVE"
        if candidate.confidence >= 0.5 and candidate.sensitivity < 0.5:
            return "ASK"
        return "IGNORE"


class MemoryHarness:
    """Runs extraction + policy + persistence once per user turn."""

    def __init__(
        self,
        provider: Optional[Any] = None,
        ask_callback: Optional[Callable[[MemoryCandidate], Awaitable[bool]]] = None,
        ask_timeout: float = 45.0,
    ):
        self.provider = provider
        self.ask_callback = ask_callback
        self.ask_timeout = ask_timeout
        self.policy = MemoryPolicy()

    async def process_turn(self, session_id: str, user_text: str) -> Dict[str, int]:
        """Extract candidates from a user turn and apply the memory policy.

        Returns counts: auto_saved / asked / approved / ignored / duplicates.
        Never raises: memory extraction must not break the conversation turn.
        """
        result = {"auto_saved": 0, "asked": 0, "approved": 0, "ignored": 0, "duplicates": 0}
        if self.provider is None:
            return result
        candidates = extract_candidates(user_text, session_id)
        for candidate in candidates:
            try:
                duplicate = await self.provider.find_duplicate_memory(
                    candidate.content, candidate.scope_type, candidate.scope_id
                )
                if duplicate is not None:
                    result["duplicates"] += 1
                    continue
                decision = self.policy.evaluate(candidate, None)
                if decision == "AUTO_SAVE":
                    await self._persist(candidate, source_type=candidate.source_type)
                    result["auto_saved"] += 1
                elif decision == "ASK":
                    result["asked"] += 1
                    if await self._ask(candidate):
                        await self._persist(candidate, source_type="user_confirmation")
                        result["approved"] += 1
                else:
                    result["ignored"] += 1
            except Exception as exc:
                logger.warning("Memory harness failed for candidate: %s", exc)
        return result

    async def _ask(self, candidate: MemoryCandidate) -> bool:
        """Bounded confirmation: no callback or timeout -> deny (IGNORE)."""
        if self.ask_callback is None:
            return False
        try:
            return bool(
                await asyncio.wait_for(self.ask_callback(candidate), timeout=self.ask_timeout)
            )
        except (asyncio.TimeoutError, asyncio.CancelledError):
            logger.info("Memory confirmation timed out; ignoring candidate")
            return False
        except Exception as exc:
            logger.warning("Memory confirmation failed: %s", exc)
            return False

    async def _persist(self, candidate: MemoryCandidate, source_type: str) -> str:
        ttl = MEMORY_TTL_DAYS.get(candidate.memory_type)
        memory_id = await self.provider.insert_memory_item(
            content=candidate.content,
            memory_type=candidate.memory_type,
            scope_type=candidate.scope_type,
            scope_id=candidate.scope_id,
            confidence=candidate.confidence,
            importance=candidate.importance,
            sensitivity=candidate.sensitivity,
            source_type=source_type,
            source_session_id=candidate.session_id,
            ttl_days=ttl,
        )
        # When the user explicitly confirmed the candidate, record that
        # confirmation as the provenance; otherwise keep the original origin.
        evidence_type = (
            "user_confirmation" if source_type == "user_confirmation" else candidate.evidence_type
        )
        await self.provider.add_memory_evidence(
            memory_id,
            evidence_type,
            session_id=candidate.session_id,
            evidence_text=candidate.evidence_text,
            confidence=candidate.confidence,
            verified=1 if source_type == "user_confirmation" else 0,
        )
        return memory_id

    async def build_snapshot(self, token_budget: int = 800) -> str:
        """Render the frozen memory snapshot (stable within a session).

        Active memory_items are ranked by importance/confidence/recency and fit
        into the token budget. Legacy memory_entries are appended as plain
        stored notes so existing data stays visible to the model.
        """
        if self.provider is None:
            return ""
        items = await self.provider.list_memory_items(statuses=("active",), limit=300)
        items.sort(
            key=lambda m: (
                float(m.get("importance", 0) or 0),
                float(m.get("confidence", 0) or 0),
                str(m.get("updated_at", "") or ""),
            ),
            reverse=True,
        )

        budget_chars = max(200, int(token_budget) * 4)
        sections: Dict[str, List[str]] = {
            "user_profile": [],
            "stable_fact": [],
            "learned_pattern": [],
            "episodic": [],
        }
        used = 0
        for item in items:
            line = f"- {str(item.get('content') or '')[:220]}"
            if used + len(line) > budget_chars:
                break
            sections.setdefault(str(item.get("memory_type") or "stable_fact"), []).append(line)
            used += len(line)

        labels = {
            "user_profile": "User",
            "stable_fact": "Stable facts",
            "learned_pattern": "Patterns",
            "episodic": "Events",
        }
        lines = ["# MEMORY SNAPSHOT"]
        for kind in ("user_profile", "stable_fact", "learned_pattern", "episodic"):
            if sections.get(kind):
                lines.append(f"## {labels[kind]}")
                lines.extend(sections[kind])

        try:
            legacy = await self.provider.list_memory_entries(limit=50)
        except Exception:
            legacy = []
        if legacy:
            lines.append("## Stored notes")
            for entry in legacy:
                lines.append(f"- {str(entry.get('content') or '')[:160]}")

        return "\n".join(lines)
