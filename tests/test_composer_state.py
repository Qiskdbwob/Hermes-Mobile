"""Tests for durable composer draft/queue state."""

from pathlib import Path

from hermes_mobile.ui.composer_state import ComposerStateStore


def test_composer_state_store_persists_draft_and_queue(tmp_path: Path):
    store = ComposerStateStore(tmp_path)
    key = ComposerStateStore.key("remote", "https://example.test", "default", "abc")

    store.save_draft(key, "unfinished prompt")
    store.enqueue(key, "first")
    store.enqueue(key, "second")

    reopened = ComposerStateStore(tmp_path)
    assert reopened.load_draft(key) == "unfinished prompt"
    assert reopened.load_queue(key) == ["first", "second"]

    assert reopened.pop_next(key) == "first"
    assert reopened.load_queue(key) == ["second"]

    reopened.save_draft(key, "")
    reopened.save_queue(key, [])
    assert reopened.load_draft(key) == ""
    assert reopened.load_queue(key) == []


def test_composer_state_key_has_no_empty_segments():
    assert ComposerStateStore.key("remote", "", None, "session") == "remote|_|_|session"
