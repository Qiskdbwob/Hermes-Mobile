"""Terminal View - run shell commands and watch output.

Desktop parity for the terminal pane: a compact command line that executes
through the agent's run_command tool and streams stdout/stderr into a mono
output area. Useful on desktop testing; on Android it still works for
commands the sandbox permits.
"""

from __future__ import annotations

import asyncio
import logging

import flet as ft

from hermes_mobile.ui.theme import mode_colors

logger = logging.getLogger(__name__)

MAX_LINES = 500


class TerminalView:
    """Terminal interface"""

    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.agent = app.agent

        self._running = False
        self._lines: list[str] = []

        self.output_field = ft.TextField(
            value="",
            multiline=True,
            read_only=True,
            expand=True,
            text_style=ft.TextStyle(font_family="monospace", size=12),
            border_radius=ft.BorderRadius.all(10),
            content_padding=ft.Padding.all(12),
        )

        self.command_field = ft.TextField(
            hint_text="Enter a command…",
            expand=True,
            on_submit=self._on_run,
            text_size=14,
            border_radius=ft.BorderRadius.all(22),
            filled=True,
            content_padding=ft.Padding.only(left=16, right=16, top=10, bottom=10),
        )

        self.run_button = ft.IconButton(
            icon=ft.Icons.PLAY_ARROW,
            on_click=self._on_run,
            icon_color=ft.Colors.ON_PRIMARY,
            bgcolor=ft.Colors.PRIMARY,
            tooltip="Run",
        )

    def build(self) -> ft.Control:
        """Build the terminal view"""
        dark = self.app.dark_mode
        c = mode_colors(dark)

        header = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.TERMINAL, size=18, color=ft.Colors.PRIMARY),
                    ft.Container(width=6),
                    ft.Text(
                        "Terminal",
                        size=16,
                        weight=ft.FontWeight.W_700,
                        color=c["foreground"],
                    ),
                    ft.Container(expand=True),
                    ft.IconButton(
                        icon=ft.Icons.CLEAR_ALL,
                        tooltip="Clear",
                        icon_size=18,
                        on_click=lambda e: self._clear(),
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=16, vertical=10),
        )

        return ft.Column(
            [
                header,
                ft.Container(height=1, bgcolor=c["border"]),
                ft.Container(
                    content=self.output_field,
                    expand=True,
                    padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                ),
                ft.Container(
                    content=ft.Row(
                        [
                            self.command_field,
                            ft.Container(width=6),
                            self.run_button,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    padding=ft.Padding.only(left=12, right=12, top=8, bottom=10),
                    border=ft.Border.only(top=ft.BorderSide(1, c["border"])),
                ),
            ],
            expand=True,
            spacing=0,
        )

    def _on_run(self, e):
        """Run the command in the input field."""
        cmd = self.command_field.value
        if cmd and cmd.strip() and not self._running:
            self.command_field.value = ""
            self._append(f"$ {cmd.strip()}")
            asyncio.create_task(self._execute(cmd.strip()))

    async def _execute(self, command: str):
        """Execute a command through the agent and stream output."""
        self._running = True
        self.run_button.icon = ft.Icons.STOP
        self.page.update()
        try:
            if self.agent is None:
                self._append("Error: agent not available")
                return
            result = await self.agent._tool_run_command(command)
            if "error" in result:
                self._append(f"Error: {result['error']}")
            else:
                if result.get("stdout"):
                    self._append(result["stdout"].rstrip())
                if result.get("stderr"):
                    self._append(result["stderr"].rstrip(), error=True)
                rc = result.get("returncode")
                if rc is not None:
                    self._append(f"[exit {rc}]")
        except Exception as ex:
            self._append(f"Error: {ex}", error=True)
        finally:
            self._running = False
            self.run_button.icon = ft.Icons.PLAY_ARROW
            self.page.update()

    def _append(self, text: str, error: bool = False):
        """Append text to the terminal output."""
        self._lines.append(text)
        if len(self._lines) > MAX_LINES:
            self._lines = self._lines[-MAX_LINES:]
        current = self.output_field.value or ""
        current = "\n".join(self._lines)
        self.output_field.value = current
        self.page.update()

    def _clear(self):
        """Clear the terminal output."""
        self._lines = []
        self.output_field.value = ""
        self.page.update()
