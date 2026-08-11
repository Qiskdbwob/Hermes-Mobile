"""Tests for context compression module."""

from hermes_mobile.core.context_compressor import (
    TAIL_PRESERVE_COUNT,
    TOKEN_ESTIMATE_CHARS_PER_TOKEN,
    _build_summary_text,
    compress_messages,
    estimate_tokens,
    get_conversation_stats,
    needs_compression,
)


class TestEstimateTokens:
    def test_empty_list(self):
        assert estimate_tokens([]) == 1

    def test_simple_messages(self):
        messages = [{"role": "user", "content": "Hello"}]
        assert estimate_tokens(messages) == max(1, 5 // TOKEN_ESTIMATE_CHARS_PER_TOKEN)

    def test_multiple_messages(self):
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"},
        ]
        total_chars = len("You are a helpful assistant.") + len("Hello!")
        assert estimate_tokens(messages) == max(1, total_chars // TOKEN_ESTIMATE_CHARS_PER_TOKEN)

    def test_with_tool_calls(self):
        messages = [
            {
                "role": "assistant",
                "content": "Searching...",
                "tool_calls": [{"function": {"name": "search"}}],
            }
        ]
        assert estimate_tokens(messages) >= 1

    def test_non_string_content(self):
        messages = [{"role": "user", "content": ["not", "a", "string"]}]
        assert estimate_tokens(messages) >= 1


class TestNeedsCompression:
    def test_small_messages_no_compression(self):
        messages = [
            {"role": "system", "content": "You are a helper."},
            {"role": "user", "content": "Hi"},
        ]
        assert needs_compression(messages, max_tokens=100000) is False

    def test_large_messages_needs_compression(self):
        huge_content = "A" * 1000000  # 1M chars ~ 250K tokens
        messages = [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": huge_content},
        ]
        assert needs_compression(messages, max_tokens=10000) is True

    def test_threshold_edge(self):
        # Just barely over 75% threshold
        content = "x" * (
            int(10000 * 0.75 * TOKEN_ESTIMATE_CHARS_PER_TOKEN) + TOKEN_ESTIMATE_CHARS_PER_TOKEN
        )
        messages = [{"role": "user", "content": content}]
        assert needs_compression(messages, max_tokens=10000) is True


class TestBuildSummaryText:
    def test_user_assistant_messages(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        summary = _build_summary_text(messages)
        assert "User: Hello" in summary
        assert "Assistant: Hi there" in summary

    def test_tool_messages(self):
        messages = [{"role": "tool", "content": "Result data", "name": "web_search"}]
        summary = _build_summary_text(messages)
        assert "Tool [web_search]" in summary

    def test_empty_list(self):
        assert _build_summary_text([]) == ""

    def test_truncated_content(self):
        long_content = "A" * 500
        messages = [{"role": "user", "content": long_content}]
        summary = _build_summary_text(messages)
        assert len(summary) < len(long_content) + 20

    def test_unknown_role(self):
        messages = [{"role": "unknown_role", "content": "something"}]
        summary = _build_summary_text(messages)
        assert "unknown_role" not in summary


class TestCompressMessages:
    def test_empty_list(self):
        assert compress_messages([]) == []

    def test_small_list_no_compression(self):
        messages = [
            {"role": "system", "content": "You are Hermes."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        result = compress_messages(messages)
        # Less than TAIL_PRESERVE_COUNT (6), so returned as-is
        assert result == messages

    def test_compresses_long_conversation(self):
        messages = [
            {"role": "system", "content": "You are Hermes."},
        ]
        # Add more messages than TAIL_PRESERVE_COUNT
        for i in range(10):
            messages.append({"role": "user", "content": f"Message {i}"})
            messages.append({"role": "assistant", "content": f"Response {i}"})
        # 1 system + 20 exchanges = 21 messages
        result = compress_messages(messages)
        # Should have: system + summary + tail (6)
        assert len(result) < len(messages)
        assert result[0] == messages[0]  # System prompt preserved
        # Check there's a summary message
        assert any("Previous conversation summary" in m.get("content", "") for m in result)

    def test_no_system_message_preserved(self):
        messages = [{"role": "user", "content": "A"}] * 10
        result = compress_messages(messages)
        assert len(result) < len(messages)

    def test_previous_summary_passed(self):
        messages = [{"role": "user", "content": "A"}] * 10
        result = compress_messages(messages, previous_summary="Previous summary here")
        assert any("Previous summary here" in m.get("content", "") for m in result)

    def test_preserves_tail_messages(self):
        messages = [{"role": "system", "content": "System."}]
        for i in range(8):
            messages.append({"role": "user", "content": f"Q{i}"})
            messages.append({"role": "assistant", "content": f"A{i}"})
        # 1 system + 16 messages = 17 total
        result = compress_messages(messages)
        # Last TAIL_PRESERVE_COUNT messages should be preserved verbatim
        tail = result[-TAIL_PRESERVE_COUNT:]
        last_original = messages[-TAIL_PRESERVE_COUNT:]
        assert tail == last_original


class TestCompressionToolCallBoundaries:
    def test_tail_never_starts_with_orphaned_tool_message(self):
        # The naive cut (last TAIL_PRESERVE_COUNT) lands on a "tool" message
        # whose assistant(tool_calls) was summarized away. The compressed
        # history must never start its tail with an orphaned tool result.
        messages = [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "u0"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "web_search", "arguments": "{}"}, "id": "c1"}],
            },
            {"role": "tool", "content": "r1", "tool_call_id": "c1", "name": "web_search"},
            {"role": "tool", "content": "r2", "tool_call_id": "c1", "name": "web_search"},
            {"role": "user", "content": "u1"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "get_time", "arguments": "{}"}, "id": "c2"}],
            },
            {"role": "tool", "content": "t", "tool_call_id": "c2", "name": "get_time"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a2"},
        ]
        # Naive tail_start (10 - 6) lands exactly on an orphaned tool message.
        assert messages[4]["role"] == "tool"

        result = compress_messages(messages)
        rest = result[1:]  # after the system prompt
        assert rest, "compression must keep a tail"
        assert rest[0]["role"] != "tool"
        for i, m in enumerate(rest):
            if m["role"] == "tool":
                assert i > 0 and rest[i - 1]["role"] == "assistant"
                assert rest[i - 1].get("tool_calls"), "tool result needs its assistant call"

    def test_tail_preserves_assistant_tool_calls_and_results(self):
        messages = [{"role": "system", "content": "S"}]
        for i in range(4):
            messages.append({"role": "user", "content": f"u{i}"})
            messages.append({"role": "assistant", "content": f"a{i}"})
        messages.append({"role": "user", "content": "u4"})
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "web_search", "arguments": "{}"}, "id": "c9"}],
            }
        )
        messages.append(
            {"role": "tool", "content": "r", "tool_call_id": "c9", "name": "web_search"}
        )

        result = compress_messages(messages)
        tail = result[1:]
        assert any(m.get("tool_calls") for m in tail)
        assert any(m["role"] == "tool" for m in tail)


class TestGetConversationStats:
    def test_empty_conversation(self):
        stats = get_conversation_stats([])
        assert stats["message_count"] == 0
        assert stats["estimated_tokens"] >= 1
        assert stats["needs_compression"] is False

    def test_role_counts(self):
        messages = [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "U1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "U2"},
        ]
        stats = get_conversation_stats(messages)
        assert stats["message_count"] == 4
        assert stats["roles"]["system"] == 1
        assert stats["roles"]["user"] == 2
        assert stats["roles"]["assistant"] == 1

    def test_estimated_tokens_field(self):
        messages = [{"role": "user", "content": "Hello world"}]
        stats = get_conversation_stats(messages)
        assert isinstance(stats["estimated_tokens"], int)
        assert stats["estimated_tokens"] >= 1
