"""Dedicated tests for the prompt caching module."""

from hermes_mobile.core.prompt_caching import (
    CACHEABLE_PROVIDERS,
    _wrap_with_cache,
    apply_cache_control,
    compute_cache_breakpoints,
    estimate_cache_savings,
    hash_content,
    supports_caching,
)


class TestConstants:
    def test_cacheable_providers(self):
        assert "anthropic" in CACHEABLE_PROVIDERS
        assert "openrouter" in CACHEABLE_PROVIDERS


class TestHashContent:
    def test_hash_returns_16_chars(self):
        h = hash_content("system prompt")
        assert len(h) == 16
        assert isinstance(h, str)

    def test_hash_deterministic(self):
        assert hash_content("hello") == hash_content("hello")

    def test_hash_different_for_different_inputs(self):
        assert hash_content("hello") != hash_content("world")

    def test_hash_empty_string(self):
        h = hash_content("")
        assert len(h) == 16


class TestSupportsCaching:
    def test_anthropic(self):
        assert supports_caching("anthropic") is True

    def test_openrouter(self):
        assert supports_caching("openrouter") is True

    def test_openai(self):
        assert supports_caching("openai") is False

    def test_google(self):
        assert supports_caching("google") is False

    def test_case_sensitive(self):
        assert supports_caching("Anthropic") is False

    def test_empty_provider(self):
        assert supports_caching("") is False


class TestComputeCacheBreakpoints:
    def test_returns_none_for_unsupported_provider(self):
        result = compute_cache_breakpoints([{"role": "user", "content": "hi"}], "openai")
        assert result is None

    def test_system_prompt_only(self):
        result = compute_cache_breakpoints(
            [{"role": "system", "content": "You are a bot"}], "anthropic"
        )
        assert result == [0]

    def test_system_and_one_user(self):
        result = compute_cache_breakpoints(
            [
                {"role": "system", "content": "You are a bot"},
                {"role": "user", "content": "Hello"},
            ],
            "anthropic",
        )
        assert result is not None
        # system at 0, total >= 2 so also total - 2 = 0
        # duplicate 0 is fine, both entries mark the same index
        assert 0 in result
        assert len(result) == 2

    def test_system_and_two_messages(self):
        result = compute_cache_breakpoints(
            [
                {"role": "system", "content": "You are a bot"},
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
            ],
            "anthropic",
        )
        # system at 0, total >= 2 so also total - 2 = 1
        # if total >= 3 but not >= 4, uses total - 2
        assert 0 in result
        assert result == [0, 1]

    def test_system_and_four_messages(self):
        result = compute_cache_breakpoints(
            [
                {"role": "system", "content": "You are a bot"},
                {"role": "user", "content": "A"},
                {"role": "assistant", "content": "B"},
                {"role": "user", "content": "C"},
            ],
            "anthropic",
        )
        # system at 0, total >= 4 so total - 3 = 1
        assert result == [0, 1]

    def test_no_system_message(self):
        result = compute_cache_breakpoints(
            [
                {"role": "user", "content": "A"},
                {"role": "assistant", "content": "B"},
            ],
            "anthropic",
        )
        # no system at index 0, total >= 2 so total - 2 = 0
        assert result == [0]

    def test_no_system_with_four_messages(self):
        result = compute_cache_breakpoints(
            [
                {"role": "user", "content": "A"},
                {"role": "assistant", "content": "B"},
                {"role": "user", "content": "C"},
                {"role": "assistant", "content": "D"},
            ],
            "anthropic",
        )
        # no system at index 0, total >= 4 so total - 3 = 1
        assert result == [1]

    def test_single_message(self):
        result = compute_cache_breakpoints([{"role": "user", "content": "hello"}], "anthropic")
        # no system at index 0, total < 2
        assert result == []

    def test_empty_messages(self):
        result = compute_cache_breakpoints([], "anthropic")
        assert result == []


class TestWrapWithCache:
    def test_wraps_string_content(self):
        result = _wrap_with_cache("hello", "anthropic")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["type"] == "text"
        assert result[0]["text"] == "hello"
        assert result[0]["cache_control"] == {"type": "ephemeral"}

    def test_wraps_list_content(self):
        original = [
            {"type": "text", "text": "part1"},
            {"type": "text", "text": "part2"},
        ]
        result = _wrap_with_cache(original, "anthropic")
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0] == {"type": "text", "text": "part1"}
        assert result[1] == {
            "type": "text",
            "text": "part2",
            "cache_control": {"type": "ephemeral"},
        }

    def test_empty_list_content(self):
        result = _wrap_with_cache([], "anthropic")
        assert result == []

    def test_non_string_non_list_content(self):
        result = _wrap_with_cache(42, "anthropic")
        assert result == 42

    def test_preserves_other_keys(self):
        original = [
            {"type": "text", "text": "a", "extra": "value"},
        ]
        result = _wrap_with_cache(original, "anthropic")
        assert result[0]["extra"] == "value"


class TestApplyCacheControl:
    def test_returns_original_for_unsupported_provider(self):
        messages = [{"role": "user", "content": "hi"}]
        result = apply_cache_control(messages, "openai")
        assert result is messages

    def test_anthropic_cache_control(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = apply_cache_control(messages, "anthropic")
        assert len(result) == 3
        # system message should be wrapped
        assert isinstance(result[0]["content"], list)
        assert result[0]["content"][0]["cache_control"]["type"] == "ephemeral"
        # last exchange should be cached too (total >= 2 -> total - 2 = 1)
        assert isinstance(result[1]["content"], list)
        assert result[1]["content"][0]["cache_control"]["type"] == "ephemeral"

    def test_openrouter_cache_control(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = apply_cache_control(messages, "openrouter")
        assert len(result) == 3
        assert result[0].get("cache_control") == {"type": "ephemeral"}
        assert result[1].get("cache_control") == {"type": "ephemeral"}
        # Last message should not have cache_control
        assert "cache_control" not in result[2]

    def test_does_not_mutate_original(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]
        original_content = messages[0]["content"]
        apply_cache_control(messages, "anthropic")
        # Original should be unchanged
        assert messages[0]["content"] == original_content


class TestEstimateCacheSavings:
    def test_unsupported_provider(self):
        result = estimate_cache_savings([{"role": "user", "content": "hi"}], "openai")
        assert result == {"supported": False, "estimated_savings_pct": 0}

    def test_supported_provider_with_system_prompt(self):
        messages = [
            {"role": "system", "content": "x" * 100},
            {"role": "user", "content": "hello"},
        ]
        result = estimate_cache_savings(messages, "anthropic")
        assert result["supported"] is True
        assert result["estimated_savings_pct"] > 0
        assert "cacheable_tokens" in result
        assert "total_tokens" in result

    def test_empty_messages(self):
        result = estimate_cache_savings([], "anthropic")
        assert result["supported"] is True
        assert result["estimated_savings_pct"] == 0

    def test_all_content_cacheable(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ]
        result = estimate_cache_savings(messages, "anthropic")
        # Both messages should be cacheable (system + last exchange)
        assert result["supported"] is True
        assert result["estimated_savings_pct"] > 0

    def test_returns_expected_keys(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]
        result = estimate_cache_savings(messages, "openrouter")
        assert set(result.keys()) == {
            "supported",
            "estimated_savings_pct",
            "cacheable_tokens",
            "total_tokens",
        }
