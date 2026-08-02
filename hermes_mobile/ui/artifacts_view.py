"""Artifacts View - files produced by the agent.

Mirrors the desktop "Artifacts" destination: a durable page listing the files
the agent has read/written in the app workspace, with text previews. Keeps the
mobile agent honest about what it has touched on device.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import flet as ft

from hermes_mobile.config.settings import get_settings
from hermes_mobile.ui.common import close_dialog, open_dialog, section_header, snack
from hermes_mobile.ui.theme import mode_colors

logger = logging.getLogger(__name__)

# Skip heavy/binary-ish extensions in the artifact list
_SKIP_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mp3", ".db", ".pyc"}
_MAX_PREVIEW = 4000


class ArtifactsView:
    """Artifacts (workspace files) interface"""

    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.settings = get_settings()

    @property
    def workspace(self) -> Path:
        """The directory the agent works in (its data dir)."""
        return self.settings.get_data_dir()

    def build(self) -> ft.Control:
        """Build the artifacts view"""
        dark = self.app.dark_mode
        c = mode_colors(dark)
        files = self._list_files()

        header = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.FOLDER_OPEN, size=20, color=ft.Colors.PRIMARY),
                    ft.Container(width=6),
                    ft.Text(
                        "Workspace",
                        size=16,
                        weight=ft.FontWeight.W_700,
                        color=c["foreground"],
                    ),
                    ft.Container(expand=True),
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

        if not files:
            body = ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.FOLDER_OPEN, size=44, color=c["muted_foreground"]),
                        ft.Container(height=10),
                        ft.Text(
                            "No artifacts yet",
                            size=15,
                            weight=ft.FontWeight.W_600,
                            color=c["foreground"],
                        ),
                        ft.Text(
                            "Files the agent creates or edits will appear here.",
                            size=13,
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
            return ft.Column(
                [header, ft.Container(height=1, bgcolor=c["border"]), body],
                expand=True,
                spacing=0,
            )

        items = [self._build_file_row(f) for f in files]
        list_view = ft.ListView(controls=items, padding=ft.Padding.all(12), spacing=8, expand=True)

        return ft.Column(
            [header, ft.Container(height=1, bgcolor=c["border"]), list_view],
            expand=True,
            spacing=0,
        )

    def _list_files(self) -> List[Path]:
        """List workspace files recursively, newest first."""
        ws = self.workspace
        try:
            files = [
                p
                for p in ws.rglob("*")
                if p.is_file()
                and p.suffix.lower() not in _SKIP_EXTENSIONS
                and "__pycache__" not in p.parts
                and ".git" not in p.parts
            ]
        except Exception as e:
            logger.warning("Artifacts listing failed: %s", e)
            return []
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return files[:100]

    def _build_file_row(self, path: Path) -> ft.Control:
        """Build a flat file row with meta + preview action."""
        dark = self.app.dark_mode
        c = mode_colors(dark)
        rel = path.relative_to(self.workspace)
        try:
            size = path.stat().st_size
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            size = 0
            mtime = datetime.now()

        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(self._icon_for(path), size=18, color=ft.Colors.PRIMARY),
                    ft.Container(width=8),
                    ft.Column(
                        [
                            ft.Text(
                                str(rel),
                                size=14,
                                weight=ft.FontWeight.W_500,
                                color=c["foreground"],
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ft.Text(
                                f"{self._fmt_size(size)} · {mtime.strftime('%b %d %H:%M')}",
                                size=11,
                                color=c["muted_foreground"],
                            ),
                        ],
                        spacing=1,
                        expand=True,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.VISIBILITY_OUTLINED,
                        tooltip="Preview",
                        icon_size=18,
                        on_click=lambda e, p=path: self._preview(p),
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            border_radius=ft.BorderRadius.all(10),
            bgcolor=c["card"],
            border=ft.Border.all(1, c["border"]),
        )

    def _preview(self, path: Path):
        """Show a text preview of a file in a dialog."""
        dark = self.app.dark_mode
        c = mode_colors(dark)
        try:
            text = path.read_text(errors="replace")[:_MAX_PREVIEW]
            if len(text) >= _MAX_PREVIEW:
                text += "\n… (truncated)"
        except Exception as e:
            text = f"Could not read file: {e}"

        dialog = ft.AlertDialog(
            title=ft.Text(str(path.relative_to(self.workspace))),
            content=ft.Container(
                content=ft.Text(
                    text,
                    size=12,
                    font_family="monospace",
                    color=c["foreground"],
                    selectable=True,
                ),
                width=420,
                height=420,
            ),
            actions=[
                ft.TextButton("Close", on_click=lambda e: close_dialog(self.page, dialog))
            ],
        )
        open_dialog(self.page, dialog)

    def _refresh(self):
        """Rebuild the view."""
        if self.app.content_area is not None:
            self.app.content_area.content = self.build()
            self.page.update()

    @staticmethod
    def _icon_for(path: Path):
        if path.suffix.lower() in (".md", ".txt", ".rst"):
            return ft.Icons.DESCRIPTION_OUTLINED
        if path.suffix.lower() in (".py", ".js", ".ts", ".sh", ".json", ".yaml", ".yml", ".toml"):
            return ft.Icons.CODE
        if path.suffix.lower() in (".csv", ".xlsx", ".jsonl"):
            return ft.Icons.TABLE_CHART
        return ft.Icons.INSERT_DRIVE_FILE_OUTLINED

    @staticmethod
    def _fmt_size(size: float) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
