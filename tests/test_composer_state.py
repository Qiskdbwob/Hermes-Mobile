"""Tests for durable composer draft/queue state."""

from pathlib import Path
from types import SimpleNamespace

from hermes_mobile.main import HermesMobileApp
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


class FakePage:
    platform = "android"
    width = 430
    theme_mode = None

    def __init__(self):
        self.overlay = []

    def update(self):
        pass


def test_failed_queued_message_is_requeued_at_front(tmp_path: Path):
    app = HermesMobileApp.__new__(HermesMobileApp)
    app.page = FakePage()
    app.composer_state_store = ComposerStateStore(tmp_path)
    app.settings = SimpleNamespace(runtime_mode="local")
    app.current_session_title = "test-session"
    app._message_queue = ["second"]

    app._requeue_front_message("first")

    assert app._message_queue == ["first", "second"]
    assert app.composer_state_store.load_queue(app._composer_key()) == ["first", "second"]
