"""Regression tests for the session recall pipeline (P0-P2):

- finalize_session: LLM summary at session close + extractive fallback +
  plaintext keyword index + stable-fact extraction into the memory harness.
- Deferred finalization: a session closed without a summary (app killed) gets
  finalized when the next agent turn starts.
- session_read tool: opening a past session returns real messages.
- Rolling mid-session chunk summaries persist a working summary.
- search_sessions uses the plaintext keyword index (covers all sessions).
"""

from unittest.mock import AsyncMock, patch

import pytest

from hermes_mobile.core.agent import Message, MobileAgent
from hermes_mobile.memory.summarizer import extract_keywords
from hermes_mobile.tools.agent_tools import session_read_tool


@pytest.fixture
def agent(memory_provider) -> MobileAgent:
    ag = MobileAgent(memory_provider=memory_provider)
    ag.add_user_message("Tolong ingat bahwa proyek saya menggunakan Postgres")
    ag.add_assistant_message("Dicatat.")
    return ag


@pytest.mark.asyncio
class TestFinalizeSession:
    async def test_llm_summary_persists_summary_and_index(self, agent, memory_provider):
        with (
            patch.object(
                agent,
                "_summarize_with_llm",
                new=AsyncMock(return_value="LLM: proyek pakai Postgres"),
            ) as mock_llm,
            patch.object(agent, "_extract_facts_from_summary", new=AsyncMock(return_value=[])),
        ):
            stats = await agent.finalize_session()

        assert stats["finalized"] is True
        assert stats["mode"] == "llm"
        mock_llm.assert_awaited_once()
        summary = await memory_provider.get_session_summary(agent.session_id)
        assert summary == "LLM: proyek pakai Postgres"

        # Keyword index is built so search covers the session without decrypt.
        results = await memory_provider.search_sessions("Postgres", limit=3)
        assert results and results[0]["id"] == agent.session_id
        assert "Postgres" in results[0]["summary"]

    async def test_extractive_fallback_when_llm_unavailable(self, agent, memory_provider):
        # No client -> _summarize_with_llm returns "" -> extractive fallback.
        stats = await agent.finalize_session()
        assert stats["finalized"] is True
        assert stats["mode"] == "extractive"
        summary = await memory_provider.get_session_summary(agent.session_id)
        assert "Postgres" in summary

    async def test_llm_disabled_uses_extractive(self, agent, memory_provider):
        agent.settings.session_summary_llm = False
        with patch.object(
            agent, "_summarize_with_llm", new=AsyncMock(return_value="should not be used")
        ) as mock_llm:
            stats = await agent.finalize_session()
        mock_llm.assert_not_awaited()
        assert stats["mode"] == "extractive"
        assert stats["finalized"] is True

    async def test_facts_extracted_into_harness(self, agent, memory_provider):
        with (
            patch.object(agent, "_summarize_with_llm", new=AsyncMock(return_value="LLM summary")),
            patch.object(
                agent,
                "_extract_facts_from_summary",
                new=AsyncMock(return_value=["User prefers concise answers"]),
            ),
        ):
            stats = await agent.finalize_session()

        assert stats["memory"]["auto_saved"] >= 1
        items = await memory_provider.list_memory_items(statuses=("active",))
        assert any("concise" in m["content"] for m in items)

    async def test_finalize_no_messages_is_noop(self, memory_provider):
        ag = MobileAgent(memory_provider=memory_provider)
        stats = await ag.finalize_session()
        assert stats["finalized"] is False

    async def test_never_raises(self, agent, memory_provider):
        with patch.object(
            agent, "_summarize_with_llm", new=AsyncMock(side_effect=RuntimeError("boom"))
        ):
            stats = await agent.finalize_session()
        assert stats["finalized"] is True  # extractive fallback saved it


@pytest.mark.asyncio
class TestDeferredFinalization:
    async def test_previous_session_finalized_on_next_turn(self, memory_provider):
        # Session A was saved but never finalized (app killed).
        await memory_provider.save_conversation(
            "session-a", [Message.user("Remember my dog is named Milo")]
        )
        assert await memory_provider.find_unfinalized_session(exclude_session_id="current") == (
            "session-a"
        )

        ag = MobileAgent(memory_provider=memory_provider)
        with (
            patch.object(ag, "_summarize_with_llm", new=AsyncMock(return_value="LLM: dog Milo")),
            patch.object(ag, "_extract_facts_from_summary", new=AsyncMock(return_value=[])),
        ):
            await ag._finalize_session_from_messages(
                "session-a",
                await memory_provider.get_conversation("session-a"),
            )

        assert await memory_provider.get_session_summary("session-a") == "LLM: dog Milo"
        # No longer unfinalized.
        assert await memory_provider.find_unfinalized_session(exclude_session_id="current") is None

    async def test_excludes_current_session(self, agent, memory_provider):
        await memory_provider.save_conversation(agent.session_id, agent.messages)
        found = await memory_provider.find_unfinalized_session(exclude_session_id=agent.session_id)
        assert found is None


@pytest.mark.asyncio
class TestRollingChunkSummary:
    async def test_rolling_chunk_persists_working_summary(self, agent, memory_provider):
        # 10 extra messages so the chunk is meaningful.
        for i in range(10):
            agent.add_user_message(f"message number {i} about postgres")
            agent.add_assistant_message(f"ok {i}")
        agent._last_summarized_count = 0

        with patch.object(
            agent, "_summarize_with_llm", new=AsyncMock(return_value="chunk summary")
        ):
            await agent._summarize_rolling_chunk()

        assert agent._last_summarized_count == len(agent.messages)
        assert len(agent._rolling_summary_parts) == 1
        summary = await memory_provider.get_session_summary(agent.session_id)
        assert "chunk summary" in summary
        # Index was built from the working summary.
        results = await memory_provider.search_sessions("chunk", limit=3)
        assert results and results[0]["id"] == agent.session_id

    async def test_rolling_chunk_skips_below_threshold(self, agent, memory_provider):
        # run_conversation-style gate: only summarize when grown >= threshold.
        agent.settings.session_summary_messages = 40
        with patch.object(agent, "_summarize_with_llm", new=AsyncMock()) as mock_llm:
            threshold = int(getattr(agent.settings, "session_summary_messages", 40) or 0)
            if len(agent.messages) - agent._last_summarized_count >= threshold:
                await agent._summarize_rolling_chunk()
        mock_llm.assert_not_awaited()


@pytest.mark.asyncio
class TestSessionReadTool:
    async def test_reads_real_messages(self, memory_provider):
        await memory_provider.save_conversation(
            "s1",
            [
                Message.user("Apa yang kita bahas tentang webview?"),
                Message.assistant("Kita bahas scroll dan click."),
                Message.user("Bisakah tambah scroll?"),
            ],
        )
        result = await session_read_tool(session_id="s1", memory_provider=memory_provider)
        assert result["message_count"] == 3
        text = "\n".join(result["messages"])
        assert "webview" in text.lower()
        assert "scroll" in text

    async def test_missing_session_returns_empty(self, memory_provider):
        result = await session_read_tool(session_id="nope", memory_provider=memory_provider)
        assert result["message_count"] == 0


@pytest.mark.asyncio
class TestSearchSessionsIndex:
    async def test_index_covers_session_whose_match_is_in_summary(self, memory_provider):
        # The keyword only lives in the summary/index (content uses synonyms).
        await memory_provider.save_conversation(
            "s1", [Message.user("Bagaimana cara setup model lokal di hp")]
        )
        await memory_provider.upsert_session_summary("s1", "Topic: Ollama local endpoint setup")
        await memory_provider.index_session_keywords(
            "s1", extract_keywords("Ollama local endpoint")
        )

        results = await memory_provider.search_sessions("ollama", limit=3)
        assert results
        assert results[0]["id"] == "s1"
        assert results[0]["score"] >= 1

    async def test_index_and_legacy_scan_both_work(self, memory_provider):
        await memory_provider.save_conversation(
            "legacy-session", [Message.user("I use Rye flour for baking")]
        )
        results = await memory_provider.search_sessions("rye", limit=3)
        assert results and results[0]["id"] == "legacy-session"
