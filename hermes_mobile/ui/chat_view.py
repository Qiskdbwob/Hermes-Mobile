"""Chat View - Main conversation interface"""

import asyncio
import logging
from typing import List

import flet as ft

from hermes_mobile.core.agent import Message, ToolCall

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

        # UI Components
        self.chat_list = ft.ListView(
            expand=True,
            spacing=10,
            padding=20,
            auto_scroll=True,
        )

        self.input_field = ft.TextField(
            hint_text="Message Hermes...",
            multiline=True,
            min_lines=1,
            max_lines=5,
            expand=True,
            on_submit=self._on_send,
            border_radius=24,
            filled=True,
        )

        self.send_button = ft.IconButton(
            icon=ft.Icons.SEND,
            on_click=self._on_send,
            icon_color=ft.Colors.PRIMARY,
        )

        self.status_text = ft.Text(
            "",
            size=12,
            color=ft.Colors.OUTLINE,
            visible=False,
        )

    def build(self) -> ft.Control:
        """Build the chat view"""
        # Show welcome message if no messages yet
        if not self.messages:
            self._show_welcome()

        return ft.Column(
            [
                # Status bar
                ft.Container(
                    content=self.status_text,
                    padding=ft.padding.symmetric(horizontal=16, vertical=8),
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
                            self.send_button,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    padding=16,
                    border=ft.border.only(top=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
                ),
            ],
            expand=True,
        )

    def _show_welcome(self):
        """Show welcome message"""
        has_api_key = bool(
            self.app.settings
            and (
                self.app.settings.openrouter_api_key
                or self.app.settings.openai_api_key
                or self.app.settings.anthropic_api_key
                or self.app.settings.gemini_api_key
            )
        )

        if not has_api_key:
            welcome = ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.AUTO_AWESOME, size=64, color=ft.Colors.PRIMARY),
                        ft.Container(height=16),
                        ft.Text("Welcome to Hermes Mobile!", size=24, weight=ft.FontWeight.BOLD),
                        ft.Container(height=8),
                        ft.Text(
                            "To get started, add an API key in Settings.",
                            size=14,
                            color=ft.Colors.OUTLINE,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Container(height=4),
                        ft.Text(
                            "Go to Settings > API Key to configure.",
                            size=14,
                            color=ft.Colors.OUTLINE,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                alignment=ft.alignment.center,
                padding=40,
            )
            self.chat_list.controls.append(welcome)
        else:
            welcome = ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.AUTO_AWESOME, size=64, color=ft.Colors.PRIMARY),
                        ft.Container(height=16),
                        ft.Text("Hermes Mobile", size=24, weight=ft.FontWeight.BOLD),
                        ft.Container(height=8),
                        ft.Text(
                            "Ready to help. Send a message to start.",
                            size=14,
                            color=ft.Colors.OUTLINE,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                alignment=ft.alignment.center,
                expand=True,
            )
            self.chat_list.controls.append(welcome)

    def _on_send(self, e):
        """Handle send button click"""
        text = self.input_field.value
        if text and text.strip():
            self.input_field.value = ""
            self.page.update()
            asyncio.create_task(self.app.send_message(text.strip()))

    def add_user_message(self, text: str):
        """Add a user message to the chat"""
        message = Message.user(text)
        self.messages.append(message)
        self._add_message_bubble(message)
        self._scroll_to_bottom()

    def append_assistant_message(self, chunk: str):
        """Append a chunk to the current assistant message"""
        self.current_assistant_text += chunk
        self._update_last_assistant_message()

    def finalize_assistant_message(self):
        """Finalize the current assistant message"""
        if self.current_assistant_text:
            message = Message.assistant(self.current_assistant_text, self.current_tool_calls)
            self.messages.append(message)
            self.current_assistant_text = ""
            self.current_tool_calls = []

    def on_tool_call(self, tool_call: ToolCall):
        """Handle tool call from agent"""
        self.current_tool_calls.append(tool_call)
        self._show_tool_call(tool_call)

    def on_tool_result(self, tool_call: ToolCall):
        """Handle tool result from agent"""
        self._update_tool_call(tool_call)

    def on_message(self, message: Message):
        """Handle new message from agent"""
        # This is called for all messages including tool results
        pass

    def _add_message_bubble(self, message: Message):
        """Add a message bubble to the chat list"""
        is_user = message.role == "user"

        bubble = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        message.content,
                        selectable=True,
                        size=16,
                    ),
                    ft.Row(
                        [
                            ft.Text(
                                message.timestamp.strftime("%H:%M"),
                                size=10,
                                color=ft.Colors.OUTLINE,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.END,
                    ),
                ],
                spacing=4,
            ),
            padding=ft.padding.all(16),
            border_radius=ft.border_radius.only(
                top_left=20,
                top_right=20,
                bottom_left=20 if not is_user else 4,
                bottom_right=4 if not is_user else 20,
            ),
            bgcolor=ft.Colors.PRIMARY_CONTAINER if is_user else ft.Colors.SURFACE_CONTAINER_HIGHEST,
            alignment=ft.alignment.center_right if is_user else ft.alignment.center_left,
            margin=ft.margin.only(left=50 if is_user else 0, right=0 if is_user else 50),
        )

        self.chat_list.controls.append(bubble)
        self.page.update()

    def _update_last_assistant_message(self):
        """Update the last assistant message with streaming content"""
        if not self.chat_list.controls:
            return

        last_control = self.chat_list.controls[-1]
        if isinstance(last_control, ft.Container):
            content_col = last_control.content
            if isinstance(content_col, ft.Column) and content_col.controls:
                text_control = content_col.controls[0]
                if isinstance(text_control, ft.Text):
                    text_control.value = self.current_assistant_text
                    self.page.update()

    def _show_tool_call(self, tool_call: ToolCall):
        """Show a tool call in the chat"""
        tool_card = ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.BUILD, size=18, color=ft.Colors.PRIMARY),
                                ft.Text(
                                    f"Calling {tool_call.name}...",
                                    weight=ft.FontWeight.W_500,
                                ),
                                ft.ProgressRing(width=16, height=16, stroke_width=2),
                            ],
                            spacing=8,
                        ),
                        ft.Container(
                            content=ft.Text(
                                str(tool_call.arguments),
                                size=12,
                                font_family="monospace",
                                color=ft.Colors.OUTLINE,
                            ),
                            padding=ft.padding.only(left=26),
                        ),
                    ],
                    spacing=4,
                ),
                padding=16,
            ),
            color=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        )

        self.chat_list.controls.append(tool_card)
        self.page.update()

    def _update_tool_call(self, tool_call: ToolCall):
        """Update a tool call with its result"""
        # Find and update the tool call card
        for i, control in enumerate(self.chat_list.controls):
            if isinstance(control, ft.Card):
                content = control.content
                if isinstance(content, ft.Container):
                    col = content.content
                    if isinstance(col, ft.Column) and col.controls:
                        row = col.controls[0]
                        if isinstance(row, ft.Row) and row.controls:
                            text = row.controls[1]
                            if isinstance(text, ft.Text) and tool_call.name in text.value:
                                # Update with result
                                if tool_call.error:
                                    text.value = f"{tool_call.name} failed: {tool_call.error}"
                                    text.color = ft.Colors.ERROR
                                else:
                                    text.value = f"{tool_call.name} completed"
                                    text.color = ft.Colors.PRIMARY

                                # Remove progress ring
                                if len(row.controls) > 2:
                                    row.controls.pop()

                                # Add result preview
                                result_text = str(tool_call.result)[:200]
                                if len(str(tool_call.result)) > 200:
                                    result_text += "..."

                                col.controls.append(
                                    ft.Container(
                                        content=ft.Text(
                                            result_text,
                                            size=11,
                                            font_family="monospace",
                                            color=ft.Colors.OUTLINE,
                                        ),
                                        padding=ft.padding.only(left=26, top=4),
                                    )
                                )
                                self.page.update()
                                break

    def _scroll_to_bottom(self):
        """Scroll chat to bottom"""
        self.chat_list.scroll_to(offset=-1, duration=100)

    def clear_chat(self):
        """Clear the chat"""
        self.chat_list.controls.clear()
        self.messages.clear()
        self.current_assistant_text = ""
        self.current_tool_calls = []
        self.agent.clear_conversation()
        self.page.update()
