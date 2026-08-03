"""Memory View - Memory management interface"""

import asyncio

import flet as ft

from hermes_mobile.ui.theme import mode_colors


class MemoryView:
    """Memory management interface"""

    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.memory_provider = app.memory_provider
        self._cached_stats = None

    def build(self) -> ft.Control:
        """Build the memory view"""
        # Schedule async stats refresh
        asyncio.create_task(self._refresh_stats())

        return ft.Column(
            [
                # Header with stats
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text("Memory", size=24, weight=ft.FontWeight.BOLD),
                                    ft.IconButton(
                                        icon=ft.Icons.REFRESH,
                                        tooltip="Refresh",
                                        on_click=lambda e: self._refresh(),
                                    ),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                            ft.Divider(height=1),
                            self._build_stats_row(),
                        ],
                        spacing=12,
                    ),
                    padding=ft.Padding.symmetric(horizontal=20, vertical=16),
                ),
                # Tabs for different memory types
                ft.Tabs(
                    length=3,
                    selected_index=0,
                    animation_duration=300,
                    content=ft.Column(
                        [
                            ft.TabBar(
                                tabs=[
                                    ft.Tab(label="Conversations", icon=ft.Icons.CHAT),
                                    ft.Tab(label="Long-term", icon=ft.Icons.PSYCHOLOGY),
                                    ft.Tab(label="Skill", icon=ft.Icons.EXTENSION),
                                ],
                            ),
                            ft.TabBarView(
                                expand=True,
                                controls=[
                                    self._build_empty_tab("No conversations yet"),
                                    self._build_empty_tab("No long-term memory yet"),
                                    self._build_empty_tab("No skill memory yet"),
                                ],
                            ),
                        ],
                        expand=True,
                        spacing=0,
                    ),
                    expand=True,
                ),
            ],
            expand=True,
        )

    async def _refresh_stats(self):
        """Fetch stats asynchronously and update UI"""
        try:
            stats = await self.memory_provider.get_stats()
            self._cached_stats = stats
            # Update the stats row if the view is currently displayed
            if self.app.current_view == "memory":
                self.app.content_area.content = self.build()
                self.page.update()
        except Exception:
            self._cached_stats = {
                "conversations": 0,
                "sessions": 0,
                "memory_entries": 0,
                "db_size_bytes": 0,
            }

    def _build_stats_row(self) -> ft.Control:
        """Build memory statistics row"""
        stats = self._cached_stats or {}
        return ft.Row(
            [
                self._build_stat_card("Chats", str(stats.get("conversations", 0)), ft.Icons.CHAT),
                self._build_stat_card("Sessions", str(stats.get("sessions", 0)), ft.Icons.MESSAGE),
                self._build_stat_card(
                    "Entries", str(stats.get("memory_entries", 0)), ft.Icons.MEMORY
                ),
                self._build_stat_card(
                    "Size", self._format_size(stats.get("db_size_bytes", 0)), ft.Icons.STORAGE
                ),
            ],
            spacing=0,
        )

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

    def _build_empty_tab(self, text: str) -> ft.Control:
        """Build an empty state for a memory tab."""
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

    def _on_tab_change(self, e):
        """Handle tab change"""
        self._refresh()

    def _refresh(self):
        """Refresh the view"""
        self.app.content_area.content = self.build()
        self.page.update()
