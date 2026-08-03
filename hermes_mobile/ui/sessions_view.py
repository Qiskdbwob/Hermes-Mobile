"""Desktop-parity session browser for Hermes Mobile.

The Desktop keeps sessions in a structured sidebar rather than a modal picker.
On a phone the equivalent is a full-height destination: persistent search,
source-aware sections, durable local pins and a large row target for resuming.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import flet as ft

from hermes_mobile.locales import t
from hermes_mobile.ui.common import MONO_FONT, empty_state, section_label, snack
from hermes_mobile.ui.theme import mode_colors

logger = logging.getLogger(__name__)

_SOURCE_LABELS = {
    "api_server": "API",
    "bluebubbles": "iMessage",
    "cli": "CLI",
    "codex": "Codex",
    "desktop": "Desktop",
    "discord": "Discord",
    "email": "Email",
    "gateway": "Gateway",
    "local": "Local",
    "matrix": "Matrix",
    "mattermost": "Mattermost",
    "mobile": "Mobile",
    "qqbot": "QQ",
    "signal": "Signal",
    "slack": "Slack",
    "sms": "SMS",
    "telegram": "Telegram",
    "tui": "TUI",
    "webhook": "Webhook",
    "weixin": "WeChat",
    "whatsapp": "WhatsApp",
    "yuanbao": "Yuanbao",
}

_SOURCE_ICONS = {
    "cli": ft.Icons.TERMINAL,
    "desktop": ft.Icons.DESKTOP_WINDOWS_OUTLINED,
    "discord": ft.Icons.FORUM_OUTLINED,
    "email": ft.Icons.MAIL_OUTLINE,
    "mobile": ft.Icons.PHONE_ANDROID,
    "telegram": ft.Icons.SEND_ROUNDED,
    "tui": ft.Icons.TERMINAL,
    "webhook": ft.Icons.WEBHOOK,
    "whatsapp": ft.Icons.CHAT_OUTLINED,
}


class SessionPinStore:
    """Small per-remote pin store matching Desktop's device-local pin semantics."""

    def __init__(self, path: Path, scope: str):
        self.path = Path(path)
        self.scope = scope or "default"

    def load(self) -> list[str]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            scopes = payload.get("scopes") if isinstance(payload, dict) else None
            values = scopes.get(self.scope, []) if isinstance(scopes, dict) else []
            if not isinstance(values, list):
                return []
            return list(dict.fromkeys(str(value) for value in values if value))[:200]
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
            return []

    def save(self, session_ids: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                payload = {}
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
            payload = {}
        scopes = payload.get("scopes")
        if not isinstance(scopes, dict):
            scopes = {}
        scopes[self.scope] = list(dict.fromkeys(session_ids))[:200]
        payload = {"version": 1, "scopes": scopes}

        fd, raw_temp = tempfile.mkstemp(prefix="session-pins-", dir=self.path.parent)
        temp_path = Path(raw_temp)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, self.path)
        finally:
            if temp_path.exists():
                temp_path.unlink()


class SessionsView:
    """Full-height mobile translation of the Desktop session sidebar."""

    def __init__(self, app):
        self.app = app
        self.page = app.page
        settings = app.settings
        remote_url = str(getattr(settings, "remote_url", "") or "").rstrip("/")
        profile = str(getattr(settings, "remote_profile", "") or "default")
        scope = f"{remote_url}|{profile}"
        self.pin_store = SessionPinStore(
            settings.get_data_dir() / "ui" / "session-pins.json",
            scope,
        )
        self.pinned_ids = self.pin_store.load()
        self.sessions: list[Mapping[str, Any]] = []
        self.query = ""
        self.loading = False
        self.error = ""

        c = mode_colors(self.app.dark_mode)
        self.search_field = ft.TextField(
            hint_text=t("sessions.search"),
            prefix_icon=ft.Icons.SEARCH,
            on_change=self._on_search,
            text_size=13,
            dense=True,
            border=ft.InputBorder.OUTLINE,
            border_width=1,
            border_color=c["border"],
            focused_border_color=c["ring"],
            bgcolor=c["input"],
            border_radius=8,
            content_padding=ft.Padding.symmetric(horizontal=12, vertical=10),
        )
        self.session_list = ft.ListView(
            expand=True,
            spacing=0,
            padding=ft.Padding.only(left=12, right=12, bottom=12),
        )
        self.pet_layer = ft.Container(visible=False)
        self.pet_footer = ft.Container(visible=False)
        self.pet_name_text = ft.Text(
            t("sessions.pet_title"),
            size=11,
            weight=ft.FontWeight.W_600,
            color=c["foreground"],
        )
        self.count_text = ft.Text("", size=11, color=c["muted_foreground"])

    def build(self) -> ft.Control:
        c = mode_colors(self.app.dark_mode)
        self.pet_footer = ft.Container(
            content=ft.Row(
                [
                    self.pet_layer,
                    ft.Column(
                        [
                            self.pet_name_text,
                            ft.Text(
                                t("sessions.pet_help"),
                                size=9,
                                color=c["muted_foreground"],
                            ),
                        ],
                        spacing=1,
                        expand=True,
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            height=78,
            padding=ft.Padding.only(left=14, right=14, top=2, bottom=2),
            bgcolor=c["sidebar"],
            border=ft.Border.only(top=ft.BorderSide(1, c["border"])),
            visible=self.pet_layer.visible,
        )
        self._render()
        return ft.Column(
            [
                ft.Container(
                    content=self.search_field,
                    padding=ft.Padding.only(left=12, right=12, top=12, bottom=6),
                ),
                ft.Container(
                    content=ft.Row(
                        [
                            self.count_text,
                            ft.Container(expand=True),
                            ft.IconButton(
                                icon=ft.Icons.REFRESH,
                                icon_size=17,
                                icon_color=c["muted_foreground"],
                                tooltip=t("sessions.refresh"),
                                on_click=lambda e: asyncio.create_task(self.refresh()),
                                visual_density=ft.VisualDensity.COMPACT,
                            ),
                        ],
                        spacing=4,
                    ),
                    padding=ft.Padding.only(left=16, right=8, bottom=2),
                ),
                self.session_list,
                self.pet_footer,
            ],
            expand=True,
            spacing=0,
        )

    async def refresh(self) -> None:
        client = getattr(self.app, "remote_client", None)
        if client is None or client.state != "open":
            self.error = t("sessions.remote_offline")
            self.loading = False
            self._render(update=True)
            return

        self.loading = True
        self.error = ""
        self._render(update=True)
        session_result, pet_result = await asyncio.gather(
            client.list_sessions(limit=100),
            client.get_pet_info(),
            return_exceptions=True,
        )
        if isinstance(session_result, Exception):
            self.sessions = []
            self.error = str(session_result)
        else:
            self.sessions = sorted(
                session_result,
                key=lambda item: float(item.get("started_at") or 0),
                reverse=True,
            )
        if isinstance(pet_result, Mapping) and pet_result.get("enabled"):
            self._set_pet(pet_result)
        else:
            self.pet_layer.visible = False
            self.pet_footer.visible = False
        self.loading = False
        self._render(update=True)

    def _on_search(self, event) -> None:
        self.query = str(getattr(event.control, "value", "") or "").strip().lower()
        self._render(update=True)

    def _filtered(self) -> list[Mapping[str, Any]]:
        if not self.query:
            return list(self.sessions)
        result = []
        for item in self.sessions:
            source = self._source(item)
            terms = " ".join(
                [
                    str(item.get("title") or ""),
                    str(item.get("preview") or ""),
                    source,
                    self._source_label(source),
                ]
            ).lower()
            if self.query in terms:
                result.append(item)
        return result

    def _render(self, *, update: bool = False) -> None:
        if self.loading:
            self.count_text.value = t("common.loading")
            self.session_list.controls = [
                ft.Container(
                    content=ft.ProgressRing(width=22, height=22, stroke_width=2),
                    padding=ft.Padding.only(top=36),
                    alignment=ft.Alignment.TOP_CENTER,
                )
            ]
        elif self.error:
            self.count_text.value = ""
            self.session_list.controls = [
                empty_state(
                    self.app.dark_mode,
                    t("sessions.could_not_load"),
                    self.error,
                    icon=ft.Icons.CLOUD_OFF_OUTLINED,
                    action=ft.Button(
                        content=t("sessions.retry"),
                        icon=ft.Icons.REFRESH,
                        on_click=lambda e: asyncio.create_task(self.refresh()),
                    ),
                )
            ]
        else:
            filtered = self._filtered()
            count_key = "sessions.count_one" if len(filtered) == 1 else "sessions.count"
            self.count_text.value = t(count_key).format(count=len(filtered))
            if not filtered:
                self.session_list.controls = [
                    empty_state(
                        self.app.dark_mode,
                        t("sessions.empty"),
                        t("sessions.empty_help"),
                        icon=ft.Icons.FORUM_OUTLINED,
                    )
                ]
            else:
                pinned = [item for item in filtered if self._id(item) in self.pinned_ids]
                telegram = [
                    item
                    for item in filtered
                    if self._id(item) not in self.pinned_ids and self._source(item) == "telegram"
                ]
                recent = [
                    item
                    for item in filtered
                    if self._id(item) not in self.pinned_ids and self._source(item) != "telegram"
                ]
                controls: list[ft.Control] = []
                for title, items in (
                    (t("sessions.pinned"), pinned),
                    ("Telegram", telegram),
                    (t("sessions.recent"), recent),
                ):
                    if not items:
                        continue
                    controls.append(
                        ft.Container(
                            content=section_label(self.app.dark_mode, title, str(len(items))),
                            padding=ft.Padding.only(left=4, right=4, top=14, bottom=6),
                        )
                    )
                    controls.extend(self._session_row(item) for item in items)
                self.session_list.controls = controls
        if update:
            try:
                self.page.update()
            except Exception:
                logger.debug("Could not update sessions view", exc_info=True)

    def _session_row(self, item: Mapping[str, Any]) -> ft.Control:
        c = mode_colors(self.app.dark_mode)
        session_id = self._id(item)
        source = self._source(item)
        pinned = session_id in self.pinned_ids
        title = str(item.get("title") or "").strip()
        preview = " ".join(str(item.get("preview") or "").split())
        if not title:
            title = preview[:72] or t("sessions.untitled")
        message_count = int(item.get("message_count") or 0)
        when = self._format_when(item.get("started_at"))
        badge = self._source_badge(source)

        return ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=ft.Icon(
                            _SOURCE_ICONS.get(source, ft.Icons.CHAT_BUBBLE_OUTLINE),
                            size=17,
                            color=c["primary"] if source == "telegram" else c["muted_foreground"],
                        ),
                        width=32,
                        height=32,
                        alignment=ft.Alignment.CENTER,
                        bgcolor=c["accent"] if source == "telegram" else c["muted"],
                        border_radius=8,
                    ),
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text(
                                        title,
                                        size=13,
                                        weight=ft.FontWeight.W_500,
                                        color=c["foreground"],
                                        max_lines=1,
                                        overflow=ft.TextOverflow.ELLIPSIS,
                                        expand=True,
                                    ),
                                    ft.Text(
                                        when,
                                        size=9,
                                        color=c["muted_foreground"],
                                        font_family=MONO_FONT,
                                    ),
                                ],
                                spacing=8,
                            ),
                            ft.Row(
                                [
                                    badge,
                                    ft.Text(
                                        preview or t("sessions.no_preview"),
                                        size=11,
                                        color=c["muted_foreground"],
                                        max_lines=1,
                                        overflow=ft.TextOverflow.ELLIPSIS,
                                        expand=True,
                                    ),
                                    ft.Text(
                                        str(message_count),
                                        size=9,
                                        color=c["muted_foreground"],
                                        font_family=MONO_FONT,
                                        tooltip=t("sessions.messages"),
                                    ),
                                ],
                                spacing=6,
                            ),
                        ],
                        spacing=3,
                        expand=True,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.PUSH_PIN if pinned else ft.Icons.PUSH_PIN_OUTLINED,
                        icon_size=16,
                        icon_color=c["primary"] if pinned else c["muted_foreground"],
                        tooltip=t("sessions.unpin") if pinned else t("sessions.pin"),
                        on_click=lambda e, sid=session_id: self._toggle_pin(sid),
                        padding=6,
                        visual_density=ft.VisualDensity.COMPACT,
                    ),
                ],
                spacing=9,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.only(left=6, right=2, top=9, bottom=9),
            border=ft.Border.only(bottom=ft.BorderSide(1, c["border"])),
            border_radius=6,
            ink=True,
            on_click=lambda e, sid=session_id, name=title: asyncio.create_task(
                self.app.resume_remote_session(sid, name)
            ),
        )

    def _source_badge(self, source: str) -> ft.Control:
        c = mode_colors(self.app.dark_mode)
        return ft.Container(
            content=ft.Text(
                self._source_label(source).upper(),
                size=8,
                color=c["primary"] if source == "telegram" else c["muted_foreground"],
                font_family=MONO_FONT,
                weight=ft.FontWeight.W_600,
            ),
            padding=ft.Padding.symmetric(horizontal=5, vertical=2),
            bgcolor=c["accent"] if source == "telegram" else c["muted"],
            border=ft.Border.all(1, c["border"]),
            border_radius=4,
        )

    def _toggle_pin(self, session_id: str) -> None:
        if session_id in self.pinned_ids:
            self.pinned_ids = [value for value in self.pinned_ids if value != session_id]
        else:
            self.pinned_ids = [session_id, *self.pinned_ids]
        try:
            self.pin_store.save(self.pinned_ids)
        except OSError as exc:
            logger.warning("Could not persist session pin: %s", exc)
            snack(self.page, t("sessions.pin_error"), error=True)
        self._render(update=True)

    def _set_pet(self, info: Mapping[str, Any]) -> None:
        try:
            raw = base64.b64decode(str(info.get("spritesheetBase64") or ""), validate=True)
            frame_w = max(1, int(info.get("frameW") or 192))
            frame_h = max(1, int(info.get("frameH") or 208))
            frames = max(1, int(info.get("framesByState", {}).get("idle") or 1))
            rows = max(1, len(info.get("stateRows") or ["idle"]))
        except (ValueError, TypeError, binascii.Error):
            self.pet_layer.visible = False
            return
        scale = min(68 / frame_w, 74 / frame_h)
        draw_w = frame_w * scale
        draw_h = frame_h * scale
        image = ft.Image(
            src=raw,
            width=frame_w * max(1, int(info.get("framesPerState") or frames)) * scale,
            height=frame_h * rows * scale,
            fit=ft.BoxFit.FILL,
            filter_quality=ft.FilterQuality.NONE,
            gapless_playback=True,
            left=0,
            top=0,
            semantics_label=str(info.get("displayName") or "Hermes pet"),
        )
        sprite = ft.Stack(
            [image],
            width=draw_w,
            height=draw_h,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
        self.pet_layer.content = sprite
        self.pet_layer.visible = True
        display_name = str(info.get("displayName") or t("sessions.pet_title"))
        self.pet_layer.tooltip = display_name
        self.pet_name_text.value = display_name
        self.pet_footer.visible = True

    @staticmethod
    def _id(item: Mapping[str, Any]) -> str:
        return str(item.get("id") or "")

    @staticmethod
    def _source(item: Mapping[str, Any]) -> str:
        return str(item.get("source") or "local").strip().lower() or "local"

    @staticmethod
    def _source_label(source: str) -> str:
        return _SOURCE_LABELS.get(source, source.replace("_", " ").replace("-", " ").title())

    @staticmethod
    def _format_when(value: Any) -> str:
        try:
            stamp = datetime.fromtimestamp(float(value))
        except (TypeError, ValueError, OSError):
            return ""
        now = datetime.now()
        if stamp.date() == now.date():
            return stamp.strftime("%H:%M")
        if stamp.year == now.year:
            return stamp.strftime("%b %d")
        return stamp.strftime("%Y-%m-%d")
