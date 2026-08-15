"""Memory View - Memory management interface.

Shows memory statistics plus four data tabs (Conversations, Memory,
Long-term, Skill) fed from the memory provider. The Memory tab manages the
Memory Harness v1 ``memory_items`` (filter by status, approve candidates,
view evidence, delete) while Long-term keeps the legacy ``memory_entries``.

Every async load is a one-shot task that updates its own container in place —
nothing here rebuilds the whole view from inside a refresh, which previously
caused an endless rebuild/refresh loop while the view was open.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import flet as ft

from hermes_mobile.ui.common import close_dialog, open_dialog, snack
from hermes_mobile.ui.theme import mode_colors

logger = logging.getLogger(__name__)

_TABS = (
    ("conversations", "Conversations", ft.Icons.CHAT),
    ("memory", "Memory", ft.Icons.FACT_CHECK),
    ("longterm", "Long-term", ft.Icons.PSYCHOLOGY),
    ("skill", "Skill", ft.Icons.EXTENSION),
)
_TAB_KEYS = {key for key, _, _ in _TABS}

# (key, label, statuses, include_expired) — archive rows (superseded/expired/
# rejected) have past expires_at, so they need the expiry filter disabled.
_MEMORY_FILTERS = (
    ("active", "Active", ("active",), False),
    ("pending", "Pending", ("candidate", "pending_confirmation"), False),
    ("archived", "Archived", ("superseded", "expired", "rejected"), True),
)

_TYPE_LABELS = {
    "user_profile": "Profile",
    "stable_fact": "Fact",
    "learned_pattern": "Pattern",
    "episodic": "Event",
}
_TYPE_ICONS = {
    "user_profile": ft.Icons.PERSON_OUTLINE,
    "stable_fact": ft.Icons.FACT_CHECK,
    "learned_pattern": ft.Icons.AUTO_AWESOME,
    "episodic": ft.Icons.EVENT,
}
_STATUS_COLORS = {
    "active": ft.Colors.GREEN,
    "candidate": ft.Colors.AMBER,
    "pending_confirmation": ft.Colors.AMBER,
    "superseded": ft.Colors.OUTLINE,
    "expired": ft.Colors.OUTLINE,
    "rejected": ft.Colors.OUTLINE,
}


class MemoryView:
    """Memory management interface"""

    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.memory_provider = app.memory_provider
        self._cached_stats: Optional[Dict[str, Any]] = None
        self.active_tab = "conversations"
        self._memory_filter = "active"
        self._stats_row: Optional[ft.Row] = None
        self._tab_strip: Optional[ft.Row] = None
        self._content: Optional[ft.Container] = None

    def _schedule(self, coro) -> None:
        """Schedule a one-shot task; tolerate test environments with no loop."""
        try:
            asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            # No running loop (structural tests): close the coroutine so it is
            # not left as an unawaited object.
            coro.close()

    def build(self) -> ft.Control:
        """Build the memory view (stats row + functional tabs)."""
        dark = self.app.dark_mode
        self._stats_row = self._build_stats_row()
        self._content = ft.Container(content=self._loading_state(), expand=True)
        # One-shot loads only: each refreshes its own control in place.
        self._schedule(self._refresh_stats())
        self._schedule(self._load_active_tab())
        return ft.Column(
            [
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text("Memory", size=24, weight=ft.FontWeight.BOLD),
                                    ft.IconButton(
                                        icon=ft.Icons.REFRESH,
                                        tooltip="Refresh",
                                        on_click=lambda e: self.refresh(),
                                    ),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                            ft.Divider(height=1),
                            self._stats_row,
                        ],
                        spacing=12,
                    ),
                    padding=ft.Padding.symmetric(horizontal=20, vertical=16),
                ),
                self._build_tab_strip(),
                ft.Container(height=1, bgcolor=mode_colors(dark)["border"]),
                self._content,
            ],
            expand=True,
            spacing=0,
        )

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def _refresh_stats(self) -> None:
        """Fetch stats once and update only the stats row in place."""
        try:
            stats = await self.memory_provider.get_stats()
            self._cached_stats = stats
        except Exception:
            logger.exception("Memory stats refresh failed")
            self._cached_stats = {
                "conversations": 0,
                "sessions": 0,
                "memory_entries": 0,
                "skill_memory_entries": 0,
                "memory_items": 0,
                "pending_memories": 0,
                "db_size_bytes": 0,
            }
        if self._stats_row is not None:
            self._stats_row.controls = self._build_stat_cards()
            if getattr(self.app, "current_view", "") == "memory":
                try:
                    self.page.update()
                except Exception:
                    logger.debug("Could not update memory stats", exc_info=True)

    def refresh(self) -> None:
        """User-requested refresh: re-run one-shot loads in place."""
        self._schedule(self._refresh_stats())
        self._schedule(self._load_active_tab())

    def _build_stats_row(self) -> ft.Row:
        row = ft.Row(spacing=0)
        self._stats_row = row
        row.controls = self._build_stat_cards()
        return row

    def _build_stat_cards(self) -> List[ft.Control]:
        stats = self._cached_stats or {}
        return [
            self._build_stat_card("Chats", str(stats.get("conversations", 0)), ft.Icons.CHAT),
            self._build_stat_card("Sessions", str(stats.get("sessions", 0)), ft.Icons.MESSAGE),
            self._build_stat_card("Facts", str(stats.get("memory_items", 0)), ft.Icons.FACT_CHECK),
            self._build_stat_card(
                "Pending", str(stats.get("pending_memories", 0)), ft.Icons.PENDING_ACTIONS
            ),
            self._build_stat_card(
                "Size", self._format_size(stats.get("db_size_bytes", 0)), ft.Icons.STORAGE
            ),
        ]

    def _build_stat_card(self, label: str, value: str, icon) -> ft.Control:
        """Build one compact metric cell separated by hairlines."""
        c = mode_colors(self.app.dark_mode)
        return ft.Container(
            content=ft.Column(
                [
                    ft.Icon(icon, size=20, color=ft.Colors.PRIMARY),
                    ft.Text(value, size=18, weight=ft.FontWeight.W_700, color=c["foreground"]),
                    ft.Text(label, size=11, color=c["muted_foreground"]),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=3,
            ),
            padding=ft.Padding.symmetric(horizontal=4, vertical=10),
            border=ft.Border.only(right=ft.BorderSide(1, c["border"])),
            expand=True,
        )

    def _format_size(self, bytes_: int) -> str:
        """Format bytes to human readable"""
        for unit in ["B", "KB", "MB", "GB"]:
            if bytes_ < 1024:
                return f"{bytes_:.1f} {unit}"
            bytes_ /= 1024
        return f"{bytes_:.1f} TB"

    # ------------------------------------------------------------------
    # Tabs
    # ------------------------------------------------------------------

    def _build_tab_strip(self) -> ft.Control:
        colors = mode_colors(self.app.dark_mode)
        pills = []
        for key, label, icon in _TABS:
            active = key == self.active_tab
            pills.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(
                                icon,
                                size=14,
                                color=colors["primary_foreground"]
                                if active
                                else colors["muted_foreground"],
                            ),
                            ft.Text(
                                label,
                                size=11,
                                weight=ft.FontWeight.W_600 if active else ft.FontWeight.W_500,
                                color=colors["primary_foreground"]
                                if active
                                else colors["muted_foreground"],
                            ),
                        ],
                        spacing=5,
                        tight=True,
                    ),
                    padding=ft.Padding.symmetric(horizontal=12, vertical=7),
                    bgcolor=colors["primary"] if active else None,
                    border=ft.Border.all(1, colors["primary"] if active else colors["border"]),
                    border_radius=ft.BorderRadius.all(18),
                    ink=True,
                    on_click=lambda e, value=key: self._on_tab_change(value),
                )
            )
        self._tab_strip = ft.Row(pills, spacing=8, wrap=True)
        return ft.Container(
            content=self._tab_strip,
            padding=ft.Padding.only(left=16, right=16, top=10, bottom=8),
        )

    def _on_tab_change(self, tab: str) -> None:
        """Switch tab and load its data in place (no full view rebuild)."""
        if tab not in _TAB_KEYS or tab == self.active_tab:
            return
        self.active_tab = tab
        if self._tab_strip is not None:
            self._tab_strip.controls = self._build_tab_strip().content.controls
        if self._content is not None:
            self._content.content = self._loading_state()
            self._schedule(self._load_active_tab())
        try:
            self.page.update()
        except Exception:
            logger.debug("Could not update memory tabs", exc_info=True)

    # ------------------------------------------------------------------
    # Tab content
    # ------------------------------------------------------------------

    def _loading_state(self) -> ft.Control:
        c = mode_colors(self.app.dark_mode)
        return ft.Column(
            [
                ft.ProgressRing(width=24, height=24, stroke_width=2),
                ft.Container(height=6),
                ft.Text("Loading…", size=12, color=c["muted_foreground"]),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            expand=True,
        )

    def _empty_state(self, text: str) -> ft.Control:
        c = mode_colors(self.app.dark_mode)
        return ft.Container(
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.INBOX_OUTLINED, size=40, color=c["muted_foreground"]),
                    ft.Container(height=8),
                    ft.Text(
                        text,
                        size=14,
                        color=c["muted_foreground"],
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            alignment=ft.Alignment.CENTER,
            expand=True,
        )

    async def _load_active_tab(self) -> None:
        """One-shot load of the active tab; updates only self._content."""
        try:
            if self.active_tab == "conversations":
                controls = await self._load_conversations()
            elif self.active_tab == "memory":
                controls = await self._load_memory_items()
            elif self.active_tab == "longterm":
                controls = await self._load_longterm()
            else:
                controls = await self._load_skill_memory()
        except Exception:
            logger.exception("Memory tab load failed")
            controls = [self._empty_state("Could not load memory data")]
        if self._content is not None:
            self._content.content = ft.ListView(
                controls=controls,
                padding=ft.Padding.symmetric(horizontal=16, vertical=8),
                spacing=0,
                expand=True,
            )
            if getattr(self.app, "current_view", "") == "memory":
                try:
                    self.page.update()
                except Exception:
                    logger.debug("Could not update memory tab", exc_info=True)

    async def _load_conversations(self) -> List[ft.Control]:
        conversations = await self.memory_provider.list_conversations(limit=50)
        if not conversations:
            return [self._empty_state("No conversations yet")]
        c = mode_colors(self.app.dark_mode)
        controls: List[ft.Control] = []
        for item in conversations:
            when = self._format_when(item.get("timestamp"))
            preview = str(item.get("preview") or "No messages")
            count = int(item.get("message_count") or 0)
            controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.CHAT_BUBBLE_OUTLINE, size=16, color=c["primary"]),
                            ft.Column(
                                [
                                    ft.Row(
                                        [
                                            ft.Text(
                                                str(item.get("id") or "session")[:28],
                                                size=13,
                                                weight=ft.FontWeight.W_600,
                                                color=c["foreground"],
                                                max_lines=1,
                                                overflow=ft.TextOverflow.ELLIPSIS,
                                                expand=True,
                                            ),
                                            ft.Text(
                                                when,
                                                size=10,
                                                color=c["muted_foreground"],
                                                font_family="monospace",
                                            ),
                                        ],
                                        spacing=8,
                                    ),
                                    ft.Text(
                                        preview,
                                        size=11,
                                        color=c["muted_foreground"],
                                        max_lines=1,
                                        overflow=ft.TextOverflow.ELLIPSIS,
                                    ),
                                    ft.Text(
                                        f"{count} message{'s' if count != 1 else ''}",
                                        size=9,
                                        color=c["muted_foreground"],
                                        font_family="monospace",
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                        ],
                        spacing=9,
                    ),
                    padding=ft.Padding.only(left=4, right=4, top=9, bottom=9),
                    border=ft.Border.only(bottom=ft.BorderSide(1, c["border"])),
                )
            )
        return controls

    # ------------------------------------------------------------------
    # Memory Harness tab (memory_items)
    # ------------------------------------------------------------------

    async def _load_memory_items(self) -> List[ft.Control]:
        controls: List[ft.Control] = [self._build_memory_filter_chips()]
        filter_row = next(
            (f for f in _MEMORY_FILTERS if f[0] == self._memory_filter), _MEMORY_FILTERS[0]
        )
        _, _, statuses, include_expired = filter_row
        try:
            items = await self.memory_provider.list_memory_items(
                statuses=statuses, limit=200, include_expired=include_expired
            )
        except Exception:
            logger.exception("Memory items load failed")
            items = []
        if not items:
            controls.append(
                self._empty_state("No memory here yet — ask the agent to remember something")
            )
            return controls
        controls.extend(self._build_memory_item_row(item) for item in items)
        return controls

    def _build_memory_filter_chips(self) -> ft.Control:
        colors = mode_colors(self.app.dark_mode)
        pills = []
        for key, label, _, _ in _MEMORY_FILTERS:
            active = key == self._memory_filter
            pills.append(
                ft.Container(
                    content=ft.Text(
                        label,
                        size=11,
                        weight=ft.FontWeight.W_600 if active else ft.FontWeight.W_500,
                        color=colors["primary_foreground"]
                        if active
                        else colors["muted_foreground"],
                    ),
                    padding=ft.Padding.symmetric(horizontal=12, vertical=6),
                    bgcolor=colors["primary"] if active else None,
                    border=ft.Border.all(1, colors["primary"] if active else colors["border"]),
                    border_radius=ft.BorderRadius.all(18),
                    ink=True,
                    on_click=lambda e, value=key: self._on_memory_filter_change(value),
                )
            )
        return ft.Row(pills, spacing=8)

    def _on_memory_filter_change(self, key: str) -> None:
        """Switch the memory status filter and reload the tab in place."""
        if key == self._memory_filter:
            return
        self._memory_filter = key
        if self._content is not None:
            self._content.content = self._loading_state()
            self._schedule(self._load_active_tab())
        try:
            self.page.update()
        except Exception:
            logger.debug("Could not update memory filter", exc_info=True)

    def _build_memory_item_row(self, item: Dict[str, Any]) -> ft.Control:
        c = mode_colors(self.app.dark_mode)
        status = str(item.get("status") or "active")
        kind = str(item.get("memory_type") or "stable_fact")
        confidence = float(item.get("confidence") or 0)
        when = self._format_when(item.get("created_at"))

        actions: List[ft.Control] = []
        if status in ("candidate", "pending_confirmation"):
            actions.append(
                ft.IconButton(
                    icon=ft.Icons.CHECK,
                    tooltip="Approve",
                    icon_color=ft.Colors.GREEN,
                    on_click=lambda e, mid=str(item.get("id")): self._approve_memory(mid),
                )
            )
        actions.append(
            ft.IconButton(
                icon=ft.Icons.INFO_OUTLINE,
                tooltip="Evidence",
                on_click=lambda e, mid=str(item.get("id")): self._show_evidence(mid),
            )
        )
        actions.append(
            ft.IconButton(
                icon=ft.Icons.DELETE_OUTLINE,
                tooltip="Delete",
                icon_color=c["destructive"],
                on_click=lambda e, item=item: self._delete_memory(item),
            )
        )

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(
                                _TYPE_ICONS.get(kind, ft.Icons.PSYCHOLOGY),
                                size=14,
                                color=c["primary"],
                            ),
                            ft.Text(
                                _TYPE_LABELS.get(kind, kind.replace("_", " ")),
                                size=10,
                                weight=ft.FontWeight.W_600,
                                color=c["muted_foreground"],
                            ),
                            ft.Container(
                                content=ft.Text(
                                    status.replace("_", " "),
                                    size=9,
                                    weight=ft.FontWeight.W_600,
                                    color=_STATUS_COLORS.get(status, ft.Colors.OUTLINE),
                                ),
                                padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                                border=ft.Border.all(
                                    1, _STATUS_COLORS.get(status, ft.Colors.OUTLINE)
                                ),
                                border_radius=ft.BorderRadius.all(9),
                            ),
                            ft.Text(
                                f"{confidence:.0%}",
                                size=10,
                                color=c["muted_foreground"],
                                font_family="monospace",
                            ),
                            ft.Text(
                                when,
                                size=10,
                                color=c["muted_foreground"],
                                font_family="monospace",
                            ),
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                    ft.Text(
                        str(item.get("content") or ""),
                        size=13,
                        color=c["foreground"],
                        selectable=True,
                        max_lines=3,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    ft.Row(actions, spacing=0),
                ],
                spacing=4,
            ),
            padding=ft.Padding.only(left=4, right=4, top=8, bottom=8),
            border=ft.Border.only(bottom=ft.BorderSide(1, c["border"])),
        )

    def _approve_memory(self, memory_id: str) -> None:
        """Approve a candidate/pending memory so it enters the active set."""

        async def run():
            try:
                ok = await self.memory_provider.update_memory_status(memory_id, "active")
                snack(self.page, "Memory approved" if ok else "Memory not found", error=not ok)
            except Exception:
                logger.exception("Could not approve memory")
                snack(self.page, "Could not approve memory", error=True)
            finally:
                self._reload_memory_tab()

        self._schedule(run())

    def _delete_memory(self, item: Dict[str, Any]) -> ft.AlertDialog:
        """Ask for confirmation, then hard-delete the memory item + evidence."""
        memory_id = str(item.get("id") or "")
        content = str(item.get("content") or "")
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()

        def resolve(value: bool):
            close_dialog(self.page, dialog)
            if not future.done():
                future.set_result(value)

        dialog = ft.AlertDialog(
            title=ft.Text("Delete memory?"),
            content=ft.Text(
                content[:200] if content else "Remove this memory permanently?",
                size=13,
                selectable=True,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: resolve(False)),
                ft.Button("Delete", on_click=lambda e: resolve(True)),
            ],
            modal=True,
        )
        open_dialog(self.page, dialog)

        async def run():
            try:
                if not await future:
                    return
                ok = await self.memory_provider.delete_memory_item(memory_id)
                snack(self.page, "Memory deleted" if ok else "Memory not found", error=not ok)
            except Exception:
                logger.exception("Could not delete memory")
                snack(self.page, "Could not delete memory", error=True)
            finally:
                self._reload_memory_tab()

        self._schedule(run())
        return dialog

    def _show_evidence(self, memory_id: str) -> None:
        """Show provenance records for a memory item in a dialog."""

        async def run():
            try:
                records = await self.memory_provider.get_memory_evidence(memory_id, limit=50)
            except Exception:
                logger.exception("Could not load memory evidence")
                records = []
            if not records:
                snack(self.page, "No evidence records for this memory", error=True)
                return
            lines: List[ft.Control] = []
            for record in records:
                when = self._format_when(record.get("created_at"))
                verified = " ✓ verified" if record.get("verified") else ""
                header = f"{str(record.get('evidence_type') or 'unknown')}{verified} · {when}"
                lines.append(
                    ft.Text(
                        header,
                        size=11,
                        weight=ft.FontWeight.W_600,
                        color=ft.Colors.OUTLINE,
                        font_family="monospace",
                    )
                )
                lines.append(
                    ft.Text(
                        str(record.get("evidence_text") or "(no excerpt)")[:300],
                        size=12,
                        selectable=True,
                    )
                )
            dialog = ft.AlertDialog(
                title=ft.Text("Memory evidence"),
                content=ft.Container(
                    content=ft.ListView(controls=lines, spacing=8),
                    width=420,
                    height=340,
                ),
                actions=[
                    ft.TextButton("Close", on_click=lambda e: close_dialog(self.page, dialog))
                ],
                modal=True,
            )
            open_dialog(self.page, dialog)

        self._schedule(run())

    def _reload_memory_tab(self) -> None:
        """Re-run the active tab load after a mutation (approve/delete)."""
        if self.active_tab == "memory":
            self._schedule(self._load_active_tab())

    async def _load_longterm(self) -> List[ft.Control]:
        entries = await self.memory_provider.list_memory_entries(limit=100)
        if not entries:
            return [self._empty_state("No long-term memory yet")]
        c = mode_colors(self.app.dark_mode)
        controls: List[ft.Control] = []
        for item in entries:
            when = self._format_when(item.get("created_at"))
            controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text(
                                        str(item.get("content") or ""),
                                        size=13,
                                        color=c["foreground"],
                                        expand=True,
                                        selectable=True,
                                    ),
                                    ft.Text(
                                        when,
                                        size=10,
                                        color=c["muted_foreground"],
                                        font_family="monospace",
                                    ),
                                ],
                                spacing=8,
                                vertical_alignment=ft.CrossAxisAlignment.START,
                            )
                        ],
                        spacing=2,
                    ),
                    padding=ft.Padding.symmetric(vertical=9),
                    border=ft.Border.only(bottom=ft.BorderSide(1, c["border"])),
                )
            )
        return controls

    async def _load_skill_memory(self) -> List[ft.Control]:
        entries = await self.memory_provider.list_skill_memory(limit=100)
        if not entries:
            return [self._empty_state("No skill memory yet")]
        c = mode_colors(self.app.dark_mode)
        controls: List[ft.Control] = []
        for item in entries:
            when = self._format_when(item.get("created_at"))
            try:
                value = str(item.get("value") or "")
            except Exception:
                value = ""
            controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.EXTENSION_OUTLINED, size=15, color=c["primary"]),
                            ft.Column(
                                [
                                    ft.Text(
                                        f"{item.get('skill_name')} · {item.get('key')}",
                                        size=12,
                                        weight=ft.FontWeight.W_600,
                                        color=c["foreground"],
                                        font_family="monospace",
                                    ),
                                    ft.Text(
                                        value[:200],
                                        size=11,
                                        color=c["muted_foreground"],
                                        max_lines=3,
                                        overflow=ft.TextOverflow.ELLIPSIS,
                                    ),
                                    ft.Text(
                                        when,
                                        size=9,
                                        color=c["muted_foreground"],
                                        font_family="monospace",
                                    ),
                                ],
                                spacing=1,
                                expand=True,
                            ),
                        ],
                        spacing=9,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                    padding=ft.Padding.only(left=4, right=4, top=8, bottom=8),
                    border=ft.Border.only(bottom=ft.BorderSide(1, c["border"])),
                )
            )
        return controls

    @staticmethod
    def _format_when(value: Any) -> str:
        if not value:
            return ""
        try:
            stamp = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            try:
                stamp = datetime.fromtimestamp(float(value))
            except (TypeError, ValueError):
                return ""
        return stamp.strftime("%b %d, %H:%M")
