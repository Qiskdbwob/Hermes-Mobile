"""Regression coverage for the Desktop-parity mobile session browser."""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

import flet as ft
import pytest

from hermes_mobile.remote.client import RemoteHermesClient
from hermes_mobile.ui.sessions_view import SessionPinStore, SessionsView


class FakePage:
    theme_mode = ft.ThemeMode.DARK

    def __init__(self):
        self.updates = 0

    def update(self):
        self.updates += 1


def walk_controls(control: ft.Control):
    seen: set[int] = set()
    stack = [control]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        fields = set(getattr(type(current), "__dataclass_fields__", {}))
        fields.update(
            {
                "controls",
                "content",
                "leading",
                "trailing",
                "title",
                "subtitle",
                "label",
                "actions",
            }
        )
        for name in fields:
            try:
                value = getattr(current, name)
            except Exception:
                continue
            if isinstance(value, ft.Control):
                stack.append(value)
            elif isinstance(value, (list, tuple)):
                stack.extend(item for item in value if isinstance(item, ft.Control))


def make_app(tmp_path: Path):
    return SimpleNamespace(
        page=FakePage(),
        settings=SimpleNamespace(
            remote_url="https://hermes.example.test",
            remote_profile="default",
            get_data_dir=lambda: tmp_path,
        ),
        dark_mode=True,
        current_view="sessions",
        _start_new_session=lambda event=None: None,
        resume_remote_session=lambda session_id, title: None,
    )


def text_values(control: ft.Control) -> list[str]:
    return [
        str(item.value)
        for item in walk_controls(control)
        if isinstance(item, ft.Text) and item.value
    ]


def test_session_browser_groups_pinned_telegram_and_recent_without_duplicates(tmp_path):
    view = SessionsView(make_app(tmp_path))
    view.sessions = [
        {
            "id": "pinned-telegram",
            "title": "Pinned bot chat",
            "preview": "From Telegram",
            "source": "telegram",
            "started_at": 100,
            "message_count": 4,
        },
        {
            "id": "telegram-chat",
            "title": "Telegram support",
            "preview": "Gateway conversation",
            "source": "telegram",
            "started_at": 90,
            "message_count": 8,
        },
        {
            "id": "desktop-chat",
            "title": "Desktop work",
            "preview": "Local workspace",
            "source": "desktop",
            "started_at": 80,
            "message_count": 3,
        },
    ]
    view.pinned_ids = ["pinned-telegram"]

    root = view.build()
    texts = text_values(root)

    assert "PINNED" in texts
    assert "TELEGRAM" in texts
    assert "RECENT" in texts
    assert texts.count("Pinned bot chat") == 1
    assert texts.count("Telegram support") == 1
    assert texts.count("Desktop work") == 1
    assert texts.count("TELEGRAM") >= 2  # section + visible source badges
    assert any(
        isinstance(item, ft.IconButton) and item.icon == ft.Icons.PUSH_PIN
        for item in walk_controls(root)
    )


def test_pin_store_is_scoped_deduplicated_and_private(tmp_path):
    path = tmp_path / "ui" / "session-pins.json"
    first = SessionPinStore(path, "server-a|default")
    second = SessionPinStore(path, "server-b|default")

    first.save(["one", "one", "two"])
    second.save(["other"])

    assert first.load() == ["one", "two"]
    assert second.load() == ["other"]
    assert path.stat().st_mode & 0o777 == 0o600


def test_remote_pet_payload_builds_a_clipped_sprite(tmp_path):
    view = SessionsView(make_app(tmp_path))
    tiny_png = base64.b64encode(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAF/gL+Xw0Y5QAAAABJRU5ErkJggg=="
        )
    ).decode("ascii")

    view._set_pet(
        {
            "enabled": True,
            "displayName": "Pool Dog",
            "spritesheetBase64": tiny_png,
            "frameW": 192,
            "frameH": 208,
            "framesPerState": 6,
            "framesByState": {"idle": 1},
            "stateRows": ["idle"],
            "loopMs": 1200,
        }
    )

    assert view.pet_layer.visible is True
    assert view.pet_layer.tooltip == "Pool Dog"
    assert view.pet_name_text.value == "Pool Dog"
    assert isinstance(view.pet_layer.content, ft.Stack)
    assert view.pet_layer.content.clip_behavior == ft.ClipBehavior.HARD_EDGE


def test_single_search_result_uses_singular_count(tmp_path):
    view = SessionsView(make_app(tmp_path))
    view.sessions = [{"id": "one", "title": "Only", "source": "desktop"}]
    view.build()

    assert view.count_text.value == "1 session"


@pytest.mark.asyncio
async def test_remote_client_uses_canonical_pet_info_rpc(monkeypatch):
    client = object.__new__(RemoteHermesClient)
    client.profile = "work"
    calls = []

    async def request(method, params):
        calls.append((method, params))
        return {"enabled": True, "displayName": "Pool Dog"}

    monkeypatch.setattr(client, "request", request)

    result = await client.get_pet_info()

    assert calls == [("pet.info", {"profile": "work"})]
    assert result["displayName"] == "Pool Dog"


@pytest.mark.asyncio
async def test_resume_uses_desktop_rest_transcript_when_live_rpc_is_empty(monkeypatch):
    client = object.__new__(RemoteHermesClient)
    client.profile = ""
    client.session_id = None
    client.stored_session_id = None

    async def request(method, params):
        assert method == "session.resume"
        return {"session_id": "live-1", "session_key": "stored-1", "messages": []}

    async def get_session_messages(session_id):
        assert session_id == "stored-1"
        return [
            {"role": "user", "content": "Question"},
            {"role": "assistant", "content": "Answer"},
        ]

    monkeypatch.setattr(client, "request", request)
    monkeypatch.setattr(client, "get_session_messages", get_session_messages)

    result = await client.resume_session("stored-1")

    assert [item["content"] for item in result["messages"]] == ["Question", "Answer"]
    assert client.session_id == "live-1"
    assert client.stored_session_id == "stored-1"
