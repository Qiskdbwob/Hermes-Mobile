"""Chat View - Main conversation interface.

Follows the desktop "nous" chat contract: the transcript is flat — assistant
messages render directly on the surface with real markdown, user messages sit
in a subtle tinted bubble with a hairline border, and tool calls are inline
status rows instead of boxed cards.
"""

import asyncio
import logging
from typing import Dict, List, Optional

import flet as ft

from hermes_mobile.core.agent import Message, ToolCall
from hermes_mobile.locales import t
from hermes_mobile.ui.theme import mode_colors

logger = logging.getLogger(__name__)


class ChatView:
    """Main chat interface"""

    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.agent = app.agent

        # Message storage
        self.messages: List[Message] = []
        self.current_assistant_text = ""
        self.current_tool_calls: List[ToolCall] = []

        # Track tool call rows by call_id for in-place updates
        self._tool_call_rows: Dict[str, ft.Row] = {}
        # Track the currently streaming assistant control
        self._streaming_control: Optional[ft.Text] = None
        self._streaming_container: Optional[ft.Container] = None

        # UI Components
        self.chat_list = ft.ListView(
            expand=True,
            spacing=4,
            padding=ft.Padding.only(left=16, right=16, top=12, bottom=12),
            auto_scroll=True,
        )

        self.input_field = ft.TextField(
            hint_text=t("chat.input_placeholder"),
            multiline=True,
            min_lines=1,
            max_lines=5,
            expand=True,
            on_submit=self._on_send,
            border_radius=ft.BorderRadius.all(22),
            filled=True,
            text_size=15,
            content_padding=ft.Padding.only(left=16, right=16, top=12, bottom=12),
        )

        self.send_button = ft.IconButton(
            icon=ft.Icons.ARROW_UPWARD,
            on_click=self._on_send,
            icon_color=ft.Colors.ON_PRIMARY,
            bgcolor=ft.Colors.PRIMARY,
            tooltip=t("chat.send"),
            icon_size=20,
        )

        self.status_text = ft.Text(
            "",
            size=12,
            color=ft.Colors.OUTLINE,
            visible=False,
        )

    def build(self) -> ft.Control:
        """Build the chat view"""
        if not self.messages and not self.chat_list.controls:
            self._show_welcome()

        c = mode_colors(self.app.dark_mode)

        # Conversation header: brand + live provider/model status (desktop parity)
        provider = getattr(self.app.settings, "default_provider", "openrouter")
        model = getattr(self.app.settings, "default_model", "")
        short_model = model.split("/")[-1] if "/" in model else model
        status = f"{provider} · {short_model}"

        header = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.AUTO_AWESOME, size=18, color=ft.Colors.PRIMARY),
                    ft.Container(width=8),
                    ft.Column(
                        [
                            ft.Text(
                                "Hermes Mobile",
                                size=15,
                                weight=ft.FontWeight.W_700,
                                color=c["foreground"],
                            ),
                            ft.Text(
                                status,
                                size=11,
                                color=c["muted_foreground"],
                            ),
                        ],
                        spacing=0,
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=16, vertical=10),
            border=ft.Border.only(bottom=ft.BorderSide(1, c["border"])),
        )

        return ft.Column(
            [
                header,
                # Status bar
                ft.Container(
                    content=self.status_text,
                    padding=ft.Padding.symmetric(horizontal=16, vertical=6),
                    visible=False,
                ),
                # Chat messages
                ft.Container(
                    content=self.chat_list,
                    expand=True,
                ),
                # Input area
                ft.Container(
                    content=ft.Row(
                        [
                            self.input_field,
                            ft.Container(width=4),
                            self.send_button,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    padding=ft.Padding.only(left=12, right=12, top=10, bottom=10),
                    border=ft.Border.only(top=ft.BorderSide(1, c["border"])),
                ),
            ],
            expand=True,
            spacing=0,
        )

    # ------------------------------------------------------------------
    # Welcome / empty states
    # ------------------------------------------------------------------

    def _show_welcome(self):
        """Show the welcome state in the chat list."""
        c = mode_colors(self.app.dark_mode)
        has_api_key = bool(
            self.app.settings
            and (
                self.app.settings.openrouter_api_key
                or self.app.settings.openai_api_key
                or self.app.settings.anthropic_api_key
                or self.app.settings.gemini_api_key
            )
        )

        if has_api_key:
            subtitle = t("chat.ready_help")
        else:
            subtitle = t("chat.no_api_key_hint")

        welcome = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Icon(
                            ft.Icons.AUTO_AWESOME,
                            size=56,
                            color=ft.Colors.PRIMARY,
                        ),
                        padding=ft.Padding.all(20),
                        border_radius=ft.BorderRadius.all(28),
                        bgcolor=c["muted"],
                    ),
                    ft.Container(height=20),
                    ft.Text(
                        "Hermes Mobile",
                        size=26,
                        weight=ft.FontWeight.W_700,
                        color=c["foreground"],
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Container(height=6),
                    ft.Text(
                        subtitle,
                        size=14,
                        color=c["muted_foreground"],
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=0,
            ),
            alignment=ft.Alignment.CENTER,
            expand=True,
        )

        self.chat_list.controls.append(welcome)

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def _on_send(self, e):
        """Handle send button click"""
        text = self.input_field.value
        if text and text.strip():
            self.input_field.value = ""
            self.page.update()
            asyncio.create_task(self.app.send_message(text.strip()))

    # ------------------------------------------------------------------
    # Message lifecycle
    # ------------------------------------------------------------------

    def add_user_message(self, text: str):
        """Add a user message to the chat"""
        message = Message.user(text)
        self.messages.append(message)
        self._add_message_bubble(message)
        self._scroll_to_bottom()

    def append_assistant_message(self, chunk: str):
        """Append a chunk to the current assistant message (streaming)"""
        if self._streaming_control is None:
            self._start_streaming()
        stream = self._streaming_control
        if stream is None:
            return
        self.current_assistant_text += chunk
        stream.value = self.current_assistant_text
        self.page.update()

    def finalize_assistant_message(self):
        """Finalize the current assistant message — swap plain text for markdown"""
        if self._streaming_container is None:
            return
        text = self.current_assistant_text.strip()
        if text:
            message = Message.assistant(text, list(self.current_tool_calls))
            self.messages.append(message)
            self._streaming_container.content = self._build_markdown(text)
        else:
            # Empty response (e.g. no API key): drop the container
            if self._streaming_container in self.chat_list.controls:
                self.chat_list.controls.remove(self._streaming_container)
        self._streaming_container = None
        self._streaming_control = None
        self.current_assistant_text = ""
        self.current_tool_calls = []
        self._scroll_to_bottom()
        self.page.update()

    def _start_streaming(self):
        """Insert the streaming assistant container (plain text while streaming)."""
        c = mode_colors(self.app.dark_mode)
        self._streaming_control = ft.Text(
            "",
            selectable=True,
            size=15,
            color=c["foreground"],
        )
        self._streaming_container = ft.Container(
            content=self._streaming_control,
            padding=ft.Padding.only(left=2, right=2, top=6, bottom=6),
        )
        self.chat_list.controls.append(self._streaming_container)
        self._scroll_to_bottom()

    def _build_markdown(self, text: str) -> ft.Control:
        """Render an assistant message as markdown."""
        c = mode_colors(self.app.dark_mode)
        code_theme = (
            ft.MarkdownCodeTheme.ATELIER_CAVE_DARK
            if self.app.dark_mode
            else ft.MarkdownCodeTheme.ATELIER_CAVE_LIGHT
        )
        fg = ft.TextStyle(size=15, color=c["foreground"])
        return ft.Markdown(
            value=text,
            selectable=True,
            extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
            code_theme=code_theme,
            soft_line_break=True,
            md_style_sheet=ft.MarkdownStyleSheet(
                p_text_style=fg,
                strong_text_style=ft.TextStyle(
                    size=15, weight=ft.FontWeight.W_700, color=c["foreground"]
                ),
                em_text_style=ft.TextStyle(size=15, italic=True, color=c["foreground"]),
                h1_text_style=ft.TextStyle(
                    size=22, weight=ft.FontWeight.W_700, color=c["foreground"]
                ),
                h2_text_style=ft.TextStyle(
                    size=19, weight=ft.FontWeight.W_700, color=c["foreground"]
                ),
                h3_text_style=ft.TextStyle(
                    size=17, weight=ft.FontWeight.W_700, color=c["foreground"]
                ),
                code_text_style=ft.TextStyle(
                    size=13, font_family="monospace", color=ft.Colors.PRIMARY
                ),
                codeblock_padding=ft.Padding.all(10),
                blockquote_text_style=ft.TextStyle(
                    size=15, color=c["muted_foreground"], italic=True
                ),
                list_bullet_text_style=ft.TextStyle(size=15, color=c["foreground"]),
                a_text_style=ft.TextStyle(size=15, color=ft.Colors.PRIMARY),
            ),
        )

    # ------------------------------------------------------------------
    # Tool calls
    # ------------------------------------------------------------------

    def on_tool_call(self, tool_call: ToolCall):
        """Handle tool call from agent"""
        self.current_tool_calls.append(tool_call)
        self._show_tool_call(tool_call)

    def on_tool_result(self, tool_call: ToolCall):
        """Handle tool result from agent"""
        self._update_tool_call(tool_call)

    def on_message(self, message: Message):
        """Handle new message from agent"""
        pass

    def _show_tool_call(self, tool_call: ToolCall):
        """Show a tool call as a flat inline status row."""
        c = mode_colors(self.app.dark_mode)
        status_text = ft.Text(
            tool_call.name,
            size=13,
            weight=ft.FontWeight.W_500,
            color=c["muted_foreground"],
        )
        spinner = ft.ProgressRing(width=14, height=14, stroke_width=2)

        row = ft.Row(
            [
                ft.Icon(ft.Icons.AUTO_AWESOME, size=15, color=ft.Colors.PRIMARY),
                ft.Container(width=6),
                status_text,
                ft.Container(expand=True),
                spinner,
            ],
            spacing=0,
        )
        self._tool_call_rows[tool_call.call_id] = row

        container = ft.Container(
            content=row,
            padding=ft.Padding.only(left=2, right=2, top=4, bottom=4),
        )
        self.chat_list.controls.append(container)
        self.page.update()

    def _update_tool_call(self, tool_call: ToolCall):
        """Update a tool call row with its result."""
        row = self._tool_call_rows.get(tool_call.call_id)
        if row is None:
            return

        c = mode_colors(self.app.dark_mode)
        status_text = row.controls[2]
        if isinstance(status_text, ft.Text):
            if tool_call.error:
                status_text.value = f"{tool_call.name} — failed"
                status_text.color = ft.Colors.ERROR
            else:
                status_text.value = f"{tool_call.name} ✓"
                status_text.color = c["muted_foreground"]

        # Replace the spinner with a status icon
        row.controls[-1] = ft.Icon(
            ft.Icons.CHECK_CIRCLE_OUTLINE
            if not tool_call.error
            else ft.Icons.ERROR_OUTLINE,
            size=15,
            color=ft.Colors.PRIMARY if not tool_call.error else ft.Colors.ERROR,
        )

        # Append a compact result preview below the row
        if tool_call.result is not None and not tool_call.error:
            preview = str(tool_call.result)
            if len(preview) > 120:
                preview = preview[:120] + "…"
            parent = row.parent
            if parent is not None:
                preview_text = ft.Text(
                    preview,
                    size=11,
                    font_family="monospace",
                    color=c["muted_foreground"],
                    selectable=True,
                )
                # Keep it inside the same container: wrap row + preview
                if isinstance(parent, ft.Container):
                    parent.content = ft.Column(
                        [row, preview_text],
                        spacing=2,
                        horizontal_alignment=ft.CrossAxisAlignment.START,
                    )
        self.page.update()

    def _add_message_bubble(self, message: Message):
        """Add a message bubble to the chat list."""
        c = mode_colors(self.app.dark_mode)
        is_user = message.role == "user"

        if is_user:
            bubble = ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            message.content,
                            selectable=True,
                            size=15,
                            color=c["foreground"],
                        ),
                        ft.Row(
                            [
                                ft.Text(
                                    message.timestamp.strftime("%H:%M"),
                                    size=10,
                                    color=c["muted_foreground"],
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.END,
                        ),
                    ],
                    spacing=3,
                ),
                padding=ft.Padding.symmetric(horizontal=14, vertical=10),
                border_radius=ft.BorderRadius.all(14),
                bgcolor=c["user_bubble"],
                border=ft.Border.all(1, c["user_bubble_border"]),
                margin=ft.Margin.only(left=48, right=0),
            )
            self.chat_list.controls.append(bubble)
        else:
            container = ft.Container(
                content=self._build_markdown(message.content),
                padding=ft.Padding.only(left=2, right=2, top=6, bottom=6),
            )
            self.chat_list.controls.append(container)

        self.page.update()

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _scroll_to_bottom(self):
        """Scroll chat to bottom"""
        try:
            self.chat_list.scroll_to(offset=-1, duration=120)
        except Exception:
            pass

    def clear_chat(self):
        """Clear the chat"""
        self.chat_list.controls.clear()
        self.messages.clear()
        self.current_assistant_text = ""
        self.current_tool_calls = []
        self._tool_call_rows.clear()
        self._streaming_container = None
        self._streaming_control = None
        if self.agent:
            try:
                asyncio.create_task(self.agent.clear_conversation())
            except Exception:
                pass
        self.page.update()
