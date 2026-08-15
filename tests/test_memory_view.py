"""Regression tests for the Memory view and its data tabs.

Covers:
- ``MobileMemoryProvider.list_conversations`` / ``list_memory_entries`` /
  ``list_skill_memory`` (needed by the view and by sync_conversations.py,
  which previously referenced a method that did not exist).
- The view no longer chains rebuilds (build -> refresh -> build -> ...) and
  tab switches update content in place.
"""

from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pytest

from hermes_mobile.core.agent import Message, ToolCall
from hermes_mobile.memory.provider import MobileMemoryProvider
from hermes_mobile.ui.memory_view import MemoryView


class FakePage:
    width = 430
    height = 844

    def __init__(self):
        self.overlay = []
        self.dialogs = []

    def update(self):
        pass

    def show_dialog(self, dialog):
        dialog.open = True
        self.dialogs.append(dialog)


class FakeMemoryProvider:
    """Async in-memory provider with the methods the view calls."""

    def __init__(
        self,
        conversations=None,
        entries=None,
        skill=None,
        stats=None,
        memory_items=None,
        evidence=None,
    ):
        self._conversations = conversations or []
        self._entries = entries or []
        self._skill = skill or []
        self._memory_items = memory_items or []
        self._evidence = evidence or {}
        self.deleted = []
        self._stats = stats or {
            "conversations": 0,
            "sessions": 0,
            "memory_entries": 0,
            "skill_memory_entries": 0,
            "memory_items": 0,
            "pending_memories": 0,
            "db_size_bytes": 0,
        }

    async def get_stats(self):
        return dict(self._stats)

    async def list_conversations(self, limit=50):
        return list(self._conversations)

    async def list_memory_entries(self, limit=100):
        return list(self._entries)

    async def list_skill_memory(self, limit=100):
        return list(self._skill)

    async def list_memory_items(
        self, *, statuses=("active",), memory_types=None, limit=200, include_expired=False
    ):
        return [m for m in self._memory_items if m["status"] in statuses]

    async def update_memory_status(self, memory_id, status):
        for item in self._memory_items:
            if item["id"] == memory_id:
                item["status"] = status
                return True
        return False

    async def delete_memory_item(self, memory_id):
        self._memory_items[:] = [m for m in self._memory_items if m["id"] != memory_id]
        self.deleted.append(memory_id)
        return True

    async def get_memory_evidence(self, memory_id, limit=50):
        return list(self._evidence.get(memory_id, []))


def make_app(provider):
    return SimpleNamespace(
        page=FakePage(),
        memory_provider=provider,
        dark_mode=True,
        current_view="memory",
    )


def walk_controls(control: ft.Control):
    seen = set()
    stack = [control]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        fields = set(getattr(type(current), "__dataclass_fields__", {}))
        fields.update({"controls", "content", "leading", "trailing", "title", "subtitle"})
        for name in fields:
            try:
                value = getattr(current, name)
            except Exception:
                continue
            if isinstance(value, ft.Control):
                stack.append(value)
            elif isinstance(value, (list, tuple)):
                stack.extend(item for item in value if isinstance(item, ft.Control))


def texts(root):
    return [
        str(control.value)
        for control in walk_controls(root)
        if isinstance(control, ft.Text) and control.value
    ]


@pytest.mark.asyncio
async def test_memory_view_builds_without_rebuilding_itself(tmp_path):
    """build() must not spawn a chain of refreshes that rebuild the view."""
    provider = FakeMemoryProvider(
        conversations=[
            {"id": "s1", "message_count": 3, "timestamp": "2026-08-11T10:00:00", "preview": "hello"}
        ],
    )
    app = make_app(provider)
    view = MemoryView(app)
    root = view.build()
    builds = []
    original_build = view.build

    def tracked_build():
        builds.append(1)
        return original_build()

    view.build = tracked_build
    # Give the one-shot load a chance to run (it updates content in place).
    await asyncio_sleep_zero()
    await asyncio_sleep_zero()

    assert isinstance(root, ft.Column)
    # The async load must never re-enter build() — that was the old
    # build -> refresh -> build -> ... infinite loop.
    assert builds == []
    assert "s1" in " ".join(texts(view._content.content))


@pytest.mark.asyncio
async def test_memory_view_tab_switch_loads_longterm_in_place():
    provider = FakeMemoryProvider(
        entries=[
            {
                "id": "m1",
                "session_id": "s1",
                "content": "user likes python",
                "created_at": "2026-08-11T09:00:00",
                "expires_at": None,
            }
        ],
    )
    app = make_app(provider)
    view = MemoryView(app)
    view.build()
    await asyncio_sleep_zero()
    await asyncio_sleep_zero()

    assert view.active_tab == "conversations"
    view._on_tab_change("longterm")
    assert view.active_tab == "longterm"
    await asyncio_sleep_zero()
    await asyncio_sleep_zero()

    rendered = " ".join(texts(view._content.content))
    assert "user likes python" in rendered


@pytest.mark.asyncio
async def test_memory_view_skill_tab_lists_entries():
    provider = FakeMemoryProvider(
        skill=[
            {
                "skill_name": "my_skill",
                "key": "count",
                "value": 42,
                "created_at": "2026-08-11T08:00:00",
            }
        ],
    )
    app = make_app(provider)
    view = MemoryView(app)
    view.build()
    view._on_tab_change("skill")
    await asyncio_sleep_zero()
    await asyncio_sleep_zero()

    rendered = " ".join(texts(view._content.content))
    assert "my_skill" in rendered
    assert "42" in rendered


@pytest.mark.asyncio
async def test_memory_view_empty_tabs_show_hint_not_crash():
    app = make_app(FakeMemoryProvider())
    view = MemoryView(app)
    view.build()
    view._on_tab_change("longterm")
    await asyncio_sleep_zero()
    await asyncio_sleep_zero()
    assert "No long-term memory yet" in " ".join(texts(view._content.content))


async def asyncio_sleep_zero():
    import asyncio

    await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Provider listing methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_list_conversations_summarizes_sessions(temp_dir):
    mp = MobileMemoryProvider(db_path=temp_dir / "list.db", encrypt=False)
    try:
        await mp.save_conversation(
            "session-a",
            [Message.user("first"), Message.assistant("reply")],
        )
        await mp.save_conversation(
            "session-b",
            [Message.user("older session message")],
        )
        conversations = await mp.list_conversations(limit=10)
        assert len(conversations) == 2
        by_id = {item["id"]: item for item in conversations}
        assert by_id["session-a"]["message_count"] == 2
        assert by_id["session-b"]["message_count"] == 1
        # Most recently saved first.
        assert conversations[0]["id"] == "session-b"
    finally:
        mp.close()


@pytest.mark.asyncio
async def test_provider_list_memory_entries_excludes_expired(temp_dir):
    mp = MobileMemoryProvider(db_path=temp_dir / "list_mem.db", encrypt=False)
    try:
        await mp.add_memory_entry("s1", "stays")
        await mp.add_memory_entry("s1", "expires soon", ttl_days=-1)
        entries = await mp.list_memory_entries(limit=10)
        contents = [entry["content"] for entry in entries]
        assert "stays" in contents
        assert "expires soon" not in contents
    finally:
        mp.close()


@pytest.mark.asyncio
async def test_provider_list_skill_memory_roundtrip_encrypted(temp_dir):
    mp = MobileMemoryProvider(
        db_path=temp_dir / "list_skill.db", encrypt=True, encryption_key="test-key"
    )
    try:
        await mp.set_skill_memory("calc", "last_result", 42)
        entries = await mp.list_skill_memory(limit=10)
        assert len(entries) == 1
        assert entries[0]["skill_name"] == "calc"
        assert entries[0]["key"] == "last_result"
        assert entries[0]["value"] == 42
    finally:
        mp.close()


@pytest.mark.asyncio
async def test_provider_list_conversations_encrypted_preview_decrypted(temp_dir):
    mp = MobileMemoryProvider(
        db_path=temp_dir / "list_enc.db", encrypt=True, encryption_key="test-key"
    )
    try:
        tc = ToolCall(name="web_search", arguments={"query": "x"}, call_id="c1")
        await mp.save_conversation(
            "enc-session",
            [
                Message.user("plain hello"),
                Message.assistant("secret reply", tool_calls=[tc]),
                Message.tool(content="secret tool output", tool_call_id="c1", name="web_search"),
            ],
        )
        conversations = await mp.list_conversations(limit=10)
        assert conversations[0]["message_count"] == 3
        assert "secret" in conversations[0]["preview"]
    finally:
        mp.close()


# ---------------------------------------------------------------------------
# Memory Harness tab (memory_items)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_tab_defaults_to_active_filter():
    provider = FakeMemoryProvider(
        memory_items=[
            {
                "id": "m1",
                "memory_type": "stable_fact",
                "status": "active",
                "confidence": 0.9,
                "content": "project uses Gradle Kotlin DSL",
                "created_at": "2026-08-11T08:00:00",
            },
            {
                "id": "m2",
                "memory_type": "user_profile",
                "status": "candidate",
                "confidence": 0.65,
                "content": "user prefers concise answers",
                "created_at": "2026-08-11T08:00:00",
            },
        ],
    )
    app = make_app(provider)
    view = MemoryView(app)
    view.build()
    view._on_tab_change("memory")
    await asyncio_sleep_zero()
    await asyncio_sleep_zero()

    rendered = " ".join(texts(view._content.content))
    assert "Gradle Kotlin DSL" in rendered
    assert "concise answers" not in rendered  # candidate hidden by default filter


@pytest.mark.asyncio
async def test_memory_tab_pending_filter_and_approve():
    provider = FakeMemoryProvider(
        memory_items=[
            {
                "id": "m2",
                "memory_type": "user_profile",
                "status": "candidate",
                "confidence": 0.65,
                "content": "user prefers concise answers",
                "created_at": "2026-08-11T08:00:00",
            }
        ],
    )
    app = make_app(provider)
    view = MemoryView(app)
    view.build()
    view._on_tab_change("memory")
    await asyncio_sleep_zero()
    await asyncio_sleep_zero()
    assert "concise answers" not in " ".join(texts(view._content.content))

    view._on_memory_filter_change("pending")
    await asyncio_sleep_zero()
    await asyncio_sleep_zero()
    rendered = " ".join(texts(view._content.content))
    assert "concise answers" in rendered
    assert "pending" in rendered.lower()

    view._approve_memory("m2")
    await asyncio_sleep_zero()
    await asyncio_sleep_zero()
    assert provider._memory_items[0]["status"] == "active"


@pytest.mark.asyncio
async def test_memory_tab_delete_confirms_then_removes():
    provider = FakeMemoryProvider(
        memory_items=[
            {
                "id": "m1",
                "memory_type": "stable_fact",
                "status": "active",
                "confidence": 0.9,
                "content": "project uses Gradle Kotlin DSL",
                "created_at": "2026-08-11T08:00:00",
            }
        ],
    )
    app = make_app(provider)
    view = MemoryView(app)
    view.build()
    view._on_tab_change("memory")
    await asyncio_sleep_zero()
    await asyncio_sleep_zero()

    dialog = view._delete_memory(provider._memory_items[0])
    assert dialog.open is True
    # Simulate tapping the destructive action.
    dialog.actions[1].on_click(None)
    await asyncio_sleep_zero()
    await asyncio_sleep_zero()

    assert provider.deleted == ["m1"]
    rendered = " ".join(texts(view._content.content))
    assert "Gradle Kotlin DSL" not in rendered


@pytest.mark.asyncio
async def test_memory_tab_cancel_delete_keeps_item():
    provider = FakeMemoryProvider(
        memory_items=[
            {
                "id": "m1",
                "memory_type": "stable_fact",
                "status": "active",
                "confidence": 0.9,
                "content": "project uses Gradle Kotlin DSL",
                "created_at": "2026-08-11T08:00:00",
            }
        ],
    )
    app = make_app(provider)
    view = MemoryView(app)
    view.build()
    view._on_tab_change("memory")
    await asyncio_sleep_zero()
    await asyncio_sleep_zero()

    dialog = view._delete_memory(provider._memory_items[0])
    dialog.actions[0].on_click(None)
    await asyncio_sleep_zero()
    await asyncio_sleep_zero()

    assert provider.deleted == []
    assert "Gradle Kotlin DSL" in " ".join(texts(view._content.content))


@pytest.mark.asyncio
async def test_memory_tab_evidence_dialog_lists_records():
    provider = FakeMemoryProvider(
        memory_items=[
            {
                "id": "m1",
                "memory_type": "stable_fact",
                "status": "active",
                "confidence": 0.9,
                "content": "project uses Gradle Kotlin DSL",
                "created_at": "2026-08-11T08:00:00",
            }
        ],
        evidence={
            "m1": [
                {
                    "evidence_type": "user_explicit",
                    "evidence_text": "Remember that the project uses Gradle.",
                    "verified": 0,
                    "confidence": 0.9,
                    "created_at": "2026-08-11T08:00:00",
                }
            ]
        },
    )
    app = make_app(provider)
    view = MemoryView(app)
    view.build()
    view._on_tab_change("memory")
    await asyncio_sleep_zero()
    await asyncio_sleep_zero()

    view._show_evidence("m1")
    await asyncio_sleep_zero()
    await asyncio_sleep_zero()

    assert app.page.dialogs
    dialog_texts = " ".join(texts(app.page.dialogs[-1]))
    assert "user_explicit" in dialog_texts
    assert "Remember that the project uses Gradle." in dialog_texts


@pytest.mark.asyncio
async def test_provider_delete_memory_item_removes_evidence(temp_dir):
    mp = MobileMemoryProvider(db_path=temp_dir / "del.db", encrypt=True, encryption_key="k")
    try:
        item_id = await mp.insert_memory_item(content="remember x", memory_type="stable_fact")
        await mp.add_memory_evidence(item_id, "user_explicit", evidence_text="excerpt")
        assert await mp.delete_memory_item(item_id) is True
        assert await mp.list_memory_items(statuses=("active",)) == []
        assert await mp.get_memory_evidence(item_id) == []
        assert await mp.delete_memory_item(item_id) is False
    finally:
        mp.close()


@pytest.mark.asyncio
async def test_provider_list_memory_items_include_expired_flag(temp_dir):
    mp = MobileMemoryProvider(db_path=temp_dir / "exp.db", encrypt=False)
    try:
        await mp.insert_memory_item(content="stale fact", memory_type="stable_fact", ttl_days=-1)
        assert await mp.list_memory_items(statuses=("active",)) == []
        items = await mp.list_memory_items(statuses=("active",), include_expired=True)
        assert len(items) == 1
        assert items[0]["content"] == "stale fact"
    finally:
        mp.close()


@pytest.mark.asyncio
async def test_provider_stats_count_pending_memories(temp_dir):
    mp = MobileMemoryProvider(db_path=temp_dir / "stats.db", encrypt=False)
    try:
        await mp.insert_memory_item(content="active fact", memory_type="stable_fact")
        await mp.insert_memory_item(
            content="pending fact", memory_type="stable_fact", status="candidate"
        )
        stats = await mp.get_stats()
        assert stats["memory_items"] == 2
        assert stats["pending_memories"] == 1
    finally:
        mp.close()
