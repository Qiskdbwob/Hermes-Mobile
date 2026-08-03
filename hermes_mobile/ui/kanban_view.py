"""Kanban View - visual kanban board.

Desktop parity for multi-agent coordination: renders the JSON-backed board as
three columns (backlog / in_progress / done) with cards that can be moved,
completed, blocked and commented. On narrow screens the columns stack
vertically for comfortable scrolling.
"""

from __future__ import annotations

import asyncio
import logging

import flet as ft

from hermes_mobile.tools.kanban_tools import (
    COLUMNS,
    kanban_block_tool,
    kanban_comment_tool,
    kanban_complete_tool,
    kanban_create_tool,
    kanban_list_sync,
    kanban_move_tool,
    kanban_unblock_tool,
)
from hermes_mobile.ui.common import close_dialog, open_dialog, snack
from hermes_mobile.ui.theme import mode_colors

logger = logging.getLogger(__name__)

COLUMN_META = {
    "backlog": ("Backlog", ft.Icons.INBOX_OUTLINED),
    "in_progress": ("In Progress", ft.Icons.PENDING_ACTIONS),
    "done": ("Done", ft.Icons.CHECK_CIRCLE_OUTLINE),
}


class KanbanView:
    """Kanban board interface"""

    def __init__(self, app):
        self.app = app
        self.page = app.page

    def build(self) -> ft.Control:
        """Build the kanban board view"""
        dark = self.app.dark_mode
        c = mode_colors(dark)

        header = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.VIEW_KANBAN, size=18, color=ft.Colors.PRIMARY),
                    ft.Container(width=6),
                    ft.Text(
                        "Kanban",
                        size=16,
                        weight=ft.FontWeight.W_700,
                        color=c["foreground"],
                    ),
                    ft.Container(expand=True),
                    ft.IconButton(
                        icon=ft.Icons.ADD,
                        tooltip="New task",
                        on_click=lambda e: self._open_create_dialog(),
                    ),
                    ft.IconButton(
                        icon=ft.Icons.REFRESH,
                        tooltip="Refresh",
                        on_click=lambda e: self._refresh(),
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=16, vertical=10),
        )

        try:
            board = kanban_list_sync()
        except Exception as e:
            logger.warning("Kanban load failed: %s", e)
            board = {"tasks": [], "columns": COLUMNS}

        tasks = board.get("tasks", [])
        body = ft.ListView(
            controls=[
                ft.Container(
                    content=ft.Column(
                        [
                            self._build_column_header(name, tasks),
                            *[self._build_card(t) for t in tasks if t.get("column") == name],
                        ],
                        spacing=8,
                    ),
                    padding=ft.Padding.only(bottom=18),
                )
                for name in board.get("columns", COLUMNS)
            ],
            padding=ft.Padding.all(12),
            spacing=0,
            expand=True,
        )

        return ft.Column(
            [header, ft.Container(height=1, bgcolor=c["border"]), body],
            expand=True,
            spacing=0,
        )

    def _build_column_header(self, column: str, tasks) -> ft.Control:
        dark = self.app.dark_mode
        c = mode_colors(dark)
        label, icon = COLUMN_META.get(column, (column.title(), ft.Icons.LABEL_OUTLINE))
        count = len([t for t in tasks if t.get("column") == column])
        return ft.Row(
            [
                ft.Icon(icon, size=16, color=ft.Colors.PRIMARY),
                ft.Container(width=6),
                ft.Text(label, size=14, weight=ft.FontWeight.W_700, color=c["foreground"]),
                ft.Container(
                    content=ft.Text(str(count), size=11, color=c["muted_foreground"]),
                    padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                    bgcolor=c["muted"],
                    border_radius=ft.BorderRadius.all(10),
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _build_card(self, task) -> ft.Control:
        dark = self.app.dark_mode
        c = mode_colors(dark)
        title = ft.Text(
            task.get("title", "Untitled"),
            size=14,
            weight=ft.FontWeight.W_600,
            color=c["foreground"],
            max_lines=2,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        desc = ""
        if task.get("description"):
            desc = task["description"]
            if len(desc) > 80:
                desc = desc[:80] + "…"
        body = ft.Column(
            [
                title,
                ft.Text(desc, size=12, color=c["muted_foreground"], max_lines=2)
                if desc
                else ft.Container(),
            ],
            spacing=2,
        )
        if task.get("blocked"):
            body.controls.append(
                ft.Text(
                    "⛔ " + (task.get("block_reason") or "blocked"),
                    size=11,
                    color=ft.Colors.ERROR,
                )
            )

        actions = ft.Row(
            [
                ft.IconButton(
                    icon=ft.Icons.CHECK_CIRCLE_OUTLINE,
                    tooltip="Complete",
                    icon_size=18,
                    on_click=lambda e, t=task: self._complete(t),
                ),
                ft.IconButton(
                    icon=ft.Icons.LOCK_OPEN if task.get("blocked") else ft.Icons.LOCK_OUTLINE,
                    tooltip="Unblock" if task.get("blocked") else "Block",
                    icon_size=18,
                    on_click=lambda e, t=task: self._toggle_block(t),
                ),
                ft.IconButton(
                    icon=ft.Icons.COMMENT_OUTLINED,
                    tooltip="Comment",
                    icon_size=18,
                    on_click=lambda e, t=task: self._open_comment_dialog(t),
                ),
                ft.Container(expand=True),
                ft.IconButton(
                    icon=ft.Icons.ARROW_FORWARD,
                    tooltip="Move next",
                    icon_size=18,
                    on_click=lambda e, t=task: self._move_next(t),
                ),
            ],
            spacing=0,
        )

        return ft.Container(
            content=ft.Column([body, actions], spacing=4),
            padding=ft.Padding.all(12),
            border_radius=ft.BorderRadius.all(10),
            bgcolor=c["card"],
            border=ft.Border.all(
                1, c["user_bubble_border"] if task.get("blocked") else c["border"]
            ),
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _complete(self, task):
        asyncio.create_task(self._run(kanban_complete_tool(task["id"]), "Completed"))

    def _move_next(self, task):
        idx = COLUMNS.index(task["column"]) if task["column"] in COLUMNS else 0
        if idx < len(COLUMNS) - 1:
            nxt = COLUMNS[idx + 1]
            asyncio.create_task(self._run(kanban_move_tool(task["id"], nxt), f"Moved to {nxt}"))
        else:
            snack(self.page, "Already in the last column")

    def _toggle_block(self, task):
        if task.get("blocked"):
            asyncio.create_task(self._run(kanban_unblock_tool(task["id"]), "Unblocked"))
        else:
            self._open_block_dialog(task)

    async def _run(self, coro, ok_msg: str):
        try:
            result = await coro
            if "error" in result:
                snack(self.page, result["error"], error=True)
            else:
                snack(self.page, ok_msg)
        except Exception as e:
            snack(self.page, str(e), error=True)
        self._refresh()

    def _refresh(self):
        if self.app.content_area is not None:
            self.app.content_area.content = self.build()
            self.page.update()

    # ------------------------------------------------------------------
    # Dialogs
    # ------------------------------------------------------------------

    def _open_create_dialog(self):
        title_field = ft.TextField(label="Title", autofocus=True)
        desc_field = ft.TextField(label="Description", multiline=True, min_lines=2, max_lines=4)
        column_dropdown = ft.Dropdown(
            label="Column",
            value="backlog",
            options=[
                ft.dropdown.Option(key=col, text=COLUMN_META.get(col, (col, None))[0])
                for col in COLUMNS
            ],
        )
        dialog = ft.AlertDialog(
            title=ft.Text("New task"),
            content=ft.Column(
                [title_field, desc_field, column_dropdown],
                spacing=10,
                tight=True,
                width=360,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: close_dialog(self.page, dialog)),
                ft.TextButton(
                    "Create",
                    on_click=lambda e: self._create_task(
                        title_field.value, desc_field.value, column_dropdown.value, dialog
                    ),
                ),
            ],
        )
        open_dialog(self.page, dialog)

    def _create_task(self, title, desc, column, dialog):
        if not title or not title.strip():
            snack(self.page, "Title is required", error=True)
            return
        close_dialog(self.page, dialog)
        asyncio.create_task(
            self._run(
                kanban_create_tool(title.strip(), desc or "", column or "backlog"),
                "Task created",
            )
        )

    def _open_comment_dialog(self, task):
        field = ft.TextField(label="Comment", autofocus=True)
        dialog = ft.AlertDialog(
            title=ft.Text(f"Comment on: {task['title'][:40]}"),
            content=ft.Container(content=field, width=360),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: close_dialog(self.page, dialog)),
                ft.TextButton(
                    "Add",
                    on_click=lambda e: self._add_comment(task, field.value, dialog),
                ),
            ],
        )
        open_dialog(self.page, dialog)

    def _add_comment(self, task, text, dialog):
        if not text or not text.strip():
            snack(self.page, "Comment is required", error=True)
            return
        close_dialog(self.page, dialog)
        asyncio.create_task(self._run(kanban_comment_tool(task["id"], text.strip()), "Commented"))

    def _open_block_dialog(self, task):
        field = ft.TextField(label="Reason (optional)", autofocus=True)
        dialog = ft.AlertDialog(
            title=ft.Text(f"Block: {task['title'][:40]}"),
            content=ft.Container(content=field, width=360),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: close_dialog(self.page, dialog)),
                ft.TextButton(
                    "Block",
                    on_click=lambda e: self._block_task(task, field.value, dialog),
                ),
            ],
        )
        open_dialog(self.page, dialog)

    def _block_task(self, task, reason, dialog):
        close_dialog(self.page, dialog)
        asyncio.create_task(self._run(kanban_block_tool(task["id"], reason or ""), "Blocked"))
