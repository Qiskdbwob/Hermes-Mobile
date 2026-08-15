"""Tests for Memory Harness v1 (memory/harness.py + memory_items/evidence/summaries)."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from hermes_mobile.memory.harness import (
    MemoryCandidate,
    MemoryHarness,
    MemoryPolicy,
    extract_candidates,
)
from hermes_mobile.memory.provider import MEMORY_TTL_DAYS, MobileMemoryProvider

# ── Extraction ──────────────────────────────────────────────────────────


class TestExtractCandidates:
    def test_english_direct_marker(self):
        cands = extract_candidates("Please remember that my project uses Gradle Kotlin DSL.", "s1")
        assert len(cands) == 1
        c = cands[0]
        assert c.memory_type == "stable_fact"
        assert c.scope_type == "global"
        assert c.explicit is True
        assert c.confidence >= 0.85

    def test_english_profile_marker(self):
        cands = extract_candidates("I prefer answers in Indonesian.", "s1")
        assert cands
        assert cands[0].memory_type == "user_profile"
        assert cands[0].scope_type == "user"

    def test_indonesian_markers(self):
        cands = extract_candidates("Saya lebih suka jawaban dalam Bahasa Indonesia.", "s1")
        assert cands and cands[0].memory_type == "user_profile"
        cands = extract_candidates("Ingat bahwa proyek saya menggunakan Gradle Kotlin DSL.", "s1")
        assert cands and cands[0].memory_type == "stable_fact"

    def test_habit_marker_medium_confidence(self):
        cands = extract_candidates("Please always give me concise answers.", "s1")
        assert cands
        assert 0.5 <= cands[0].confidence < 0.85

    def test_no_markers_returns_empty(self):
        assert extract_candidates("Hari ini saya sedang mengerjakan README.", "s1") == []

    def test_huge_sentence_skipped(self):
        long_text = "Please remember that " + "x" * 400
        assert extract_candidates(long_text, "s1") == []

    def test_sensitivity_flags_secrets_and_permissions(self):
        cands = extract_candidates("Remember my api key is sk-abc123", "s1")
        assert cands and cands[0].sensitivity >= 0.7
        cands = extract_candidates("Ingat beri izin akses ke folder ini", "s1")
        assert cands and cands[0].sensitivity >= 0.5


# ── Policy ──────────────────────────────────────────────────────────────


class TestMemoryPolicy:
    def test_auto_save_high_confidence_explicit(self):
        c = MemoryCandidate(content="I prefer Indonesian.", session_id="s", confidence=0.95)
        assert MemoryPolicy().evaluate(c, None) == "AUTO_SAVE"

    def test_ask_medium_confidence(self):
        c = MemoryCandidate(
            content="Please always keep answers short.", session_id="s", confidence=0.65
        )
        assert MemoryPolicy().evaluate(c, None) == "ASK"

    def test_ignore_low_confidence(self):
        c = MemoryCandidate(content="maybe I sometimes like tea", session_id="s", confidence=0.4)
        assert MemoryPolicy().evaluate(c, None) == "IGNORE"

    def test_ignore_duplicate(self):
        c = MemoryCandidate(content="I prefer Indonesian.", session_id="s", confidence=0.95)
        assert MemoryPolicy().evaluate(c, {"id": "x"}) == "IGNORE"

    def test_ignore_secret(self):
        c = MemoryCandidate(
            content="My password is hunter2", session_id="s", confidence=0.95, sensitivity=1.0
        )
        assert MemoryPolicy().evaluate(c, None) == "IGNORE"


# ── Harness end-to-end ──────────────────────────────────────────────────


class TestMemoryHarness:
    @pytest.mark.asyncio
    async def test_auto_save_persists_with_evidence(self, memory_provider):
        h = MemoryHarness(provider=memory_provider)
        res = await h.process_turn("s1", "Please remember that my project uses Gradle Kotlin DSL.")
        assert res["auto_saved"] == 1
        items = await memory_provider.list_memory_items(statuses=("active",))
        assert len(items) == 1
        assert items[0]["content"] == "Please remember that my project uses Gradle Kotlin DSL."
        ev = await memory_provider.get_memory_evidence(items[0]["id"])
        assert len(ev) == 1
        assert ev[0]["evidence_type"] == "user_explicit"
        assert ev[0]["session_id"] == "s1"

    @pytest.mark.asyncio
    async def test_duplicate_turn_is_ignored(self, memory_provider):
        h = MemoryHarness(provider=memory_provider)
        await h.process_turn("s1", "Please remember that my project uses Gradle Kotlin DSL.")
        res = await h.process_turn("s2", "Please remember that my project uses Gradle Kotlin DSL.")
        assert res["duplicates"] == 1
        assert res["auto_saved"] == 0
        assert len(await memory_provider.list_memory_items(statuses=("active",))) == 1

    @pytest.mark.asyncio
    async def test_ask_approved_saves_as_confirmed(self, memory_provider):
        asked = []

        async def approve(candidate):
            asked.append(candidate.content)
            return True

        h = MemoryHarness(provider=memory_provider, ask_callback=approve)
        res = await h.process_turn("s1", "Please always give me concise answers.")
        assert res["asked"] == 1 and res["approved"] == 1
        assert asked
        items = await memory_provider.list_memory_items(statuses=("active",))
        assert len(items) == 1
        ev = await memory_provider.get_memory_evidence(items[0]["id"])
        assert ev[0]["verified"] == 1
        assert ev[0]["evidence_type"] == "user_confirmation"
        # the memory item itself records the confirmed source
        assert items[0]["source_type"] == "user_confirmation"

    @pytest.mark.asyncio
    async def test_ask_denied_persists_nothing(self, memory_provider):
        async def deny(candidate):
            return False

        h = MemoryHarness(provider=memory_provider, ask_callback=deny)
        res = await h.process_turn("s1", "Please always give me concise answers.")
        assert res["asked"] == 1 and res["approved"] == 0
        assert await memory_provider.list_memory_items(statuses=("active",)) == []

    @pytest.mark.asyncio
    async def test_ask_without_callback_queues_pending(self, memory_provider):
        h = MemoryHarness(provider=memory_provider)
        res = await h.process_turn("s1", "Please always give me concise answers.")
        assert res["asked"] == 1 and res["approved"] == 0 and res["pending"] == 1
        assert await memory_provider.list_memory_items(statuses=("active",)) == []
        pending = await memory_provider.list_pending_memories()
        assert len(pending) == 1
        assert pending[0]["status"] == "pending_confirmation"
        assert pending[0]["content"] == "Please always give me concise answers."

    @pytest.mark.asyncio
    async def test_ask_timeout_degrades_to_ignore(self, memory_provider):
        async def slow(candidate):
            await asyncio.sleep(5)
            return True

        h = MemoryHarness(provider=memory_provider, ask_callback=slow, ask_timeout=0.01)
        res = await h.process_turn("s1", "Please always give me concise answers.")
        assert res["approved"] == 0
        assert await memory_provider.list_memory_items(statuses=("active",)) == []

    @pytest.mark.asyncio
    async def test_provider_failure_never_raises(self, memory_provider):
        memory_provider.insert_memory_item = AsyncMock(side_effect=RuntimeError("db boom"))
        h = MemoryHarness(provider=memory_provider)
        res = await h.process_turn("s1", "Please remember that my project uses Gradle Kotlin DSL.")
        assert res["auto_saved"] == 0  # failure swallowed, no exception propagated

    @pytest.mark.asyncio
    async def test_no_provider_returns_empty(self):
        h = MemoryHarness(provider=None)
        res = await h.process_turn("s1", "Please remember something important.")
        assert res["auto_saved"] == 0

    @pytest.mark.asyncio
    async def test_build_snapshot_ranks_and_renders(self, memory_provider):
        h = MemoryHarness(provider=memory_provider)
        await h.process_turn("s1", "Please remember that my project uses Gradle Kotlin DSL.")
        snap = await h.build_snapshot(token_budget=400)
        assert "# MEMORY SNAPSHOT" in snap
        assert "Gradle" in snap
        # legacy stored notes appended when present
        await memory_provider.add_memory_entry("note", "a legacy note")
        snap2 = await h.build_snapshot(token_budget=400)
        assert "Stored notes" in snap2

    @pytest.mark.asyncio
    async def test_build_snapshot_respects_budget(self, memory_provider):
        h = MemoryHarness(provider=memory_provider)
        for i in range(20):
            await h.process_turn(
                f"s{i}", f"Please remember that project {i} uses Gradle Kotlin DSL."
            )
        small = await h.build_snapshot(token_budget=50)
        large = await h.build_snapshot(token_budget=2000)
        assert len(small) < len(large)


# ── Provider repository (memory_items / evidence / summaries) ──────────


class TestMemoryItemsRepository:
    @pytest.mark.asyncio
    async def test_insert_and_list_memory_item(self, memory_provider):
        mid = await memory_provider.insert_memory_item(
            content="I prefer Indonesian.",
            memory_type="user_profile",
            scope_type="user",
            confidence=0.9,
            importance=0.7,
            source_type="user_explicit",
            source_session_id="s1",
        )
        items = await memory_provider.list_memory_items(statuses=("active",))
        assert len(items) == 1
        assert items[0]["id"] == mid
        assert items[0]["memory_type"] == "user_profile"
        assert items[0]["content"] == "I prefer Indonesian."

    @pytest.mark.asyncio
    async def test_find_duplicate_exact_normalized(self, memory_provider):
        await memory_provider.insert_memory_item(
            content="I prefer Indonesian!", memory_type="user_profile", scope_type="user"
        )
        dup = await memory_provider.find_duplicate_memory("i prefer indonesian.", "user", None)
        assert dup is not None
        assert "Indonesian" in dup["content"]

    @pytest.mark.asyncio
    async def test_update_status_and_list_pending(self, memory_provider):
        mid = await memory_provider.insert_memory_item(
            content="maybe", status="candidate", confidence=0.5
        )
        pending = await memory_provider.list_pending_memories()
        assert [m["id"] for m in pending] == [mid]
        assert await memory_provider.update_memory_status(mid, "active") is True
        assert await memory_provider.list_pending_memories() == []

    @pytest.mark.asyncio
    async def test_supersede_marks_old(self, memory_provider):
        old = await memory_provider.insert_memory_item(content="old fact", confidence=0.9)
        new = await memory_provider.insert_memory_item(content="new fact", confidence=0.9)
        assert await memory_provider.supersede_memory(old, new) is True
        items = await memory_provider.list_memory_items(statuses=("superseded",))
        assert [m["id"] for m in items] == [old]
        assert items[0]["supersedes_id"] == new

    @pytest.mark.asyncio
    async def test_encrypted_memory_item_roundtrip(self, temp_dir):
        mp = MobileMemoryProvider(db_path=temp_dir / "enc.db", encrypt=True)
        try:
            await mp.insert_memory_item(
                content="I prefer Indonesian.", memory_type="user_profile", scope_type="user"
            )
            items = await mp.list_memory_items()
            assert items[0]["content"] == "I prefer Indonesian."
            assert await mp.find_duplicate_memory("I prefer Indonesian.", "user") is not None
        finally:
            mp.close()

    @pytest.mark.asyncio
    async def test_session_summary_upsert_increments_version(self, memory_provider):
        await memory_provider.upsert_session_summary("s1", "first", token_estimate=10)
        await memory_provider.upsert_session_summary("s1", "second", token_estimate=20)
        assert await memory_provider.get_session_summary("s1") == "second"
        conn = memory_provider._get_conn()
        row = conn.execute(
            "SELECT summary_version FROM session_summaries WHERE session_id = 's1'"
        ).fetchone()
        assert row["summary_version"] == 2

    @pytest.mark.asyncio
    async def test_ttl_cleanup_expires_memory_items(self, memory_provider):
        from datetime import datetime, timedelta

        mid = await memory_provider.insert_memory_item(
            content="ephemeral", memory_type="episodic", ttl_days=1
        )
        # Backdate expiry so the item is already stale.
        conn = memory_provider._get_conn()
        past = (datetime.now() - timedelta(days=2)).isoformat()
        conn.execute("UPDATE memory_items SET expires_at = ? WHERE id = ?", (past, mid))
        conn.commit()
        # Expired items are excluded from active listing and removed by cleanup.
        assert await memory_provider.list_memory_items(statuses=("active",)) == []
        assert await memory_provider.cleanup_expired() is None  # legacy signature: no return
        conn = memory_provider._get_conn()
        row = conn.execute("SELECT COUNT(*) AS c FROM memory_items").fetchone()
        assert row["c"] == 0

    @pytest.mark.asyncio
    async def test_consolidate_memories_counts(self, memory_provider):
        from datetime import datetime, timedelta

        mid = await memory_provider.insert_memory_item(
            content="stale candidate", status="candidate", confidence=0.5
        )
        conn = memory_provider._get_conn()
        past = (datetime.now() - timedelta(days=2)).isoformat()
        conn.execute("UPDATE memory_items SET expires_at = ? WHERE id = ?", (past, mid))
        conn.commit()
        counts = await memory_provider.consolidate_memories()
        assert counts["expired"] == 1

    @pytest.mark.asyncio
    async def test_consolidate_expired_not_rebumped_and_pruned_after_grace(self, memory_provider):
        """Expired rows must not have updated_at bumped every run (which would
        make the 90-day audit-grace prune never match them), and must be aged
        from expires_at once past the grace."""
        from datetime import datetime, timedelta

        mid = await memory_provider.insert_memory_item(
            content="audit row", memory_type="episodic", ttl_days=-30
        )
        first = await memory_provider.consolidate_memories()
        assert first["expired"] == 1 and first["pruned"] == 0

        # Second pass must not re-expire the same row (bug: updated_at was
        # bumped to now every run, so pruning by updated_at never matched).
        second = await memory_provider.consolidate_memories()
        assert second["expired"] == 0

        # Once past the 90-day grace (aged from expires_at), it prunes.
        conn = memory_provider._get_conn()
        past = (datetime.now() - timedelta(days=120)).isoformat()
        conn.execute("UPDATE memory_items SET expires_at = ? WHERE id = ?", (past, mid))
        conn.commit()
        third = await memory_provider.consolidate_memories()
        assert third["pruned"] == 1

    @pytest.mark.asyncio
    async def test_legacy_kv_api_still_works(self, memory_provider):
        # Old tools contract must keep working untouched.
        await memory_provider.store_memory("lang", "id")
        assert await memory_provider.get_memory("lang") == "id"
        entries = await memory_provider.list_memory()
        assert any(e["key"] == "lang" for e in entries)
        await memory_provider.add_memory_entry("note", "hello")
        ctx = await memory_provider.get_relevant_context("hello", limit=5)
        assert "hello" in ctx

    @pytest.mark.asyncio
    async def test_legacy_skill_memory_api_still_works(self, memory_provider):
        await memory_provider.set_skill_memory("my_skill", "count", 3)
        assert await memory_provider.get_skill_memory("my_skill", "count") == 3

    def test_ttl_defaults_exist(self):
        # Stable profile/facts never expire; patterns and episodes do.
        assert MEMORY_TTL_DAYS.get("user_profile") is None
        assert MEMORY_TTL_DAYS.get("stable_fact") is None
        assert MEMORY_TTL_DAYS.get("learned_pattern") == 90
        assert MEMORY_TTL_DAYS.get("episodic") == 30
        assert MEMORY_TTL_DAYS.get("candidate") == 7
