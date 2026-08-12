"""Terminal View - run shell commands and watch output.

Desktop parity for the terminal pane: a compact command line that starts a
background process through the agent's process registry, streams stdout and
stderr as it arrives, and lets the user cancel a running command (the stop
button kills the process tree). Works on Android for commands the bundled
shell permits.
"""

from __future__ import annotations

import asyncio
import logging

import flet as ft

from hermes_mobile.locales import t
from hermes_mobile.ui.theme import mode_colors

logger = logging.getLogger(__name__)

MAX_LINES = 500
POLL_INTERVAL = 0.15


class TerminalView:
    """Terminal interface"""

    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.agent = app.agent

        self._running = False
        self._cancelled = False
        self._session_id = None
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
            hint_text=t("terminal.enter_command"),
            expand=True,
            on_submit=self._on_run,
            text_size=14,
            border_radius=ft.BorderRadius.all(22),
            filled=True,
            content_padding=ft.Padding.only(left=16, right=16, top=10, bottom=10),
        )

        self.run_button = ft.IconButton(
            icon=ft.Icons.PLAY_ARROW,
            on_click=self._on_toggle,
            icon_color=ft.Colors.ON_PRIMARY,
            bgcolor=ft.Colors.PRIMARY,
            tooltip=t("terminal.run"),
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
                        t("nav.terminal"),
                        size=16,
                        weight=ft.FontWeight.W_700,
                        color=c["foreground"],
                    ),
                    ft.Container(expand=True),
                    ft.IconButton(
                        icon=ft.Icons.CLEAR_ALL,
                        tooltip=t("terminal.clear"),
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
        """Start the command in the input field (Enter key)."""
        if self._running:
            return
        cmd = self.command_field.value
        if cmd and cmd.strip():
            self.command_field.value = ""
            self._append(f"$ {cmd.strip()}")
            asyncio.create_task(self._execute(cmd.strip()))

    def _on_toggle(self, e):
        """Start a command, or cancel the running one (stop button)."""
        if self._running:
            asyncio.create_task(self._cancel())
        else:
            self._on_run(e)

    async def _execute(self, command: str):
        """Run *command* as a background process and stream its output."""
        registry = getattr(self.agent, "process_registry", None)
        if registry is None:
            self._append("Error: agent not available")
            return
        self._running = True
        self._cancelled = False
        self.run_button.icon = ft.Icons.STOP
        self.run_button.tooltip = t("terminal.cancel")
        self.page.update()
        try:
            started = await registry.terminal(command, background=True)
            if "error" in started:
                self._append(f"Error: {started['error']}")
                return
            self._session_id = started["session_id"]
            rc = None
            while True:
                state = await registry.process("poll", session_id=self._session_id)
                self._append_output(state.get("output", ""))
                self._append_output(state.get("stderr", ""))
                if state.get("status") == "exited":
                    rc = state.get("exit_code")
                    break
                await asyncio.sleep(POLL_INTERVAL)
            # One final poll lets the reader tasks flush trailing bytes.
            await asyncio.sleep(POLL_INTERVAL)
            final = await registry.process("poll", session_id=self._session_id)
            self._append_output(final.get("output", ""))
            self._append_output(final.get("stderr", ""))
            if self._cancelled:
                self._append("[cancelled]")
            elif rc is not None:
                self._append(f"[exit {rc}]")
        except Exception as ex:
            self._append(f"Error: {ex}")
        finally:
            self._session_id = None
            self._running = False
            self._cancelled = False
            self.run_button.icon = ft.Icons.PLAY_ARROW
            self.run_button.tooltip = t("terminal.run")
            self.page.update()

    async def _cancel(self):
        """Kill the running command's process tree."""
        if self._session_id is None:
            return
        self._cancelled = True
        self._append("[stopping…]")
        registry = getattr(self.agent, "process_registry", None)
        if registry is not None:
            try:
                await registry.process("kill", session_id=self._session_id)
            except Exception as ex:
                logger.warning("cancel failed: %s", ex)

    def _append_output(self, text: str):
        """Append a raw chunk, batching its lines into one frame push.

        Polling used to append one line at a time and push a page.update() per
        line, which flooded the Flutter client on high-output commands. Lines
        are now buffered per poll, and the frame is skipped entirely while the
        terminal view is not the active surface — the process registry keeps
        the session output capped, so nothing is lost on return.
        """
        if not text:
            return
        for line in text.splitlines():
            if line:
                self._lines.append(line)
        if len(self._lines) > MAX_LINES:
            self._lines = self._lines[-MAX_LINES:]
        self.output_field.value = "\n".join(self._lines)
        self._push_output()

    def _push_output(self):
        """Push the transcript to the client only while the view is active."""
        if getattr(self.app, "current_view", None) != "terminal":
            return
        try:
            self.page.update()
        except Exception:
            logger.debug("Terminal output update failed", exc_info=True)

    def _append(self, text: str):
        """Append text to the terminal output."""
        self._lines.append(text)
        if len(self._lines) > MAX_LINES:
            self._lines = self._lines[-MAX_LINES:]
        self.output_field.value = "\n".join(self._lines)
        self._push_output()

    def _clear(self):
        """Clear the terminal output."""
        self._lines = []
        self.output_field.value = ""
        self._push_output()
        self.page.update()
