"""Tests for extractive session summarization (memory/summarizer.py) and the
summary surface of session search (search_sessions / session_search_tool).

Regression for: session_search returned only the first raw message as
title/preview, so "what did we discuss earlier?" was unanswerable.
"""

from types import SimpleNamespace

import pytest

from hermes_mobile.core.agent import Message, ToolCall
from hermes_mobile.memory.summarizer import build_session_summary


class TestBuildSessionSummary:
    def test_empty_messages(self):
        assert build_session_summary([]) == ""

    def test_no_user_messages(self):
        messages = [Message.assistant("hello"), Message.assistant("world")]
        assert build_session_summary(messages) == ""

    def test_single_exchange(self):
        messages = [
            Message.user("Please remember my project uses Gradle Kotlin DSL"),
            Message.assistant("Remembered!"),
        ]
        summary = build_session_summary(messages)
        assert "Gradle" in summary
        assert "Topic:" in summary
        assert "Exchanges: 1" in summary
        assert "Kotlin" in summary  # keyword extracted from user message

    def test_multiple_exchanges_include_latest(self):
        messages = [
            Message.user("What is the weather in Jakarta today"),
            Message.assistant("Sunny and hot"),
            Message.user("Please remember I prefer Indonesian answers"),
            Message.assistant("Noted!"),
        ]
        summary = build_session_summary(messages)
        assert "Exchanges: 2" in summary
        assert "Latest:" in summary
        assert "Indonesian" in summary

    def test_tools_listed(self):
        tc = ToolCall(name="web_search", arguments={"query": "test"})
        messages = [
            Message.user("Search for Hermes Mobile"),
            Message.assistant("Searching...", tool_calls=[tc]),
            Message.tool(content='{"results": []}', tool_call_id=tc.call_id, name="web_search"),
            Message.assistant("Here are the results."),
        ]
        summary = build_session_summary(messages)
        assert "web_search" in summary
        assert "Tools:" in summary

    def test_accepts_dict_messages(self):
        messages = [
            {"role": "user", "content": "Remember my favorite color is blue"},
            {"role": "assistant", "content": "OK"},
        ]
        summary = build_session_summary(messages)
        assert "blue" in summary

    def test_accepts_simplenamespace(self):
        messages = [
            SimpleNamespace(role="user", content="What time is it", tool_calls=[]),
            SimpleNamespace(role="assistant", content="Now", tool_calls=[]),
        ]
        summary = build_session_summary(messages)
        assert "Exchanges: 1" in summary

    def test_indonesian_stopwords_filtered(self):
        summary = build_session_summary(
            [
                Message.user("Tolong ingat bahwa proyek saya menggunakan Postgres"),
                Message.assistant("Oke"),
            ]
        )
        # Stopwords (tolong/saya) must not dominate the keyword list.
        assert "Postgres" in summary


@pytest.mark.asyncio
class TestSearchSessionsWithSummary:
    async def test_plaintext_results_include_summary(self, memory_provider):
        await memory_provider.save_conversation(
            "s1",
            [Message.user("Please remember that my project uses Gradle Kotlin DSL")],
        )
        summary = build_session_summary(
            [Message.user("Please remember that my project uses Gradle Kotlin DSL")]
        )
        await memory_provider.upsert_session_summary("s1", summary)

        result = await memory_provider.search_sessions("Gradle", limit=5)
        assert result
        assert result[0]["id"] == "s1"
        assert "Gradle" in result[0]["summary"]

    async def test_encrypted_results_include_summary(self, temp_dir):
        from hermes_mobile.memory.provider import MobileMemoryProvider

        mp = MobileMemoryProvider(db_path=temp_dir / "enc.db", encrypt=True)
        try:
            await mp.save_conversation(
                "s1", [Message.user("Remember that my password manager is Bitwarden")]
            )
            await mp.upsert_session_summary(
                "s1", "Topic: Remember that my password manager is Bitwarden"
            )
            result = await mp.search_sessions("Bitwarden", limit=5)
            assert result
            assert result[0]["summary"] == "Topic: Remember that my password manager is Bitwarden"
            assert "Bitwarden" in result[0]["preview"]
        finally:
            mp.close()

    async def test_preview_is_best_matching_message(self, memory_provider):
        await memory_provider.save_conversation(
            "s1",
            [
                Message.user("How do I bake bread"),
                Message.assistant("Here is a bread recipe."),
                Message.user("Also, my cat is named Needle"),
                Message.assistant("Nice name!"),
            ],
        )
        result = await memory_provider.search_sessions("Needle", limit=5)
        assert result
        assert "Needle" in result[0]["preview"]

    async def test_session_search_tool_includes_summary(self, memory_provider):
        from hermes_mobile.tools.agent_tools import session_search_tool

        await memory_provider.save_conversation(
            "s1", [Message.user("Please remember that my project uses Gradle Kotlin DSL")]
        )
        await memory_provider.upsert_session_summary(
            "s1", "Topic: Remember my project · Exchanges: 0 · Keywords: gradle, kotlin"
        )
        result = await session_search_tool("Gradle", memory_provider=memory_provider)
        assert result["sessions"]
        assert result["sessions"][0]["summary"] == (
            "Topic: Remember my project · Exchanges: 0 · Keywords: gradle, kotlin"
        )
        assert "summary" in result["sessions"][0]
