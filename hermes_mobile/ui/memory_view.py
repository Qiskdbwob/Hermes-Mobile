"""Memory View - Memory management interface"""

import flet as ft


class MemoryView:
    """Memory management interface"""

    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.memory_provider = app.memory_provider

    def build(self) -> ft.Control:
        """Build the memory view"""
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
                    padding=ft.padding.symmetric(horizontal=20, vertical=16),
                ),
                # Tabs for different memory types
                ft.Tabs(
                    selected_index=0,
                    animation_duration=300,
                    tabs=[
                        ft.Tab(text="Conversations", icon=ft.Icons.CHAT),
                        ft.Tab(text="Long-term Memory", icon=ft.Icons.PSYCHOLOGY),
                        ft.Tab(text="Skill Memory", icon=ft.Icons.EXTENSION),
                    ],
                    on_change=self._on_tab_change,
                    expand=True,
                ),
            ],
            expand=True,
        )

    def _build_stats_row(self) -> ft.Control:
        """Build memory statistics row"""
        stats = self.memory_provider.get_stats()

        return ft.Row(
            [
                self._build_stat_card("Conversations", str(stats["conversations"]), ft.Icons.CHAT),
                self._build_stat_card("Messages", str(stats["messages"]), ft.Icons.MESSAGE),
                self._build_stat_card(
                    "Memory Entries", str(stats["memory_entries"]), ft.Icons.MEMORY
                ),
                self._build_stat_card(
                    "Size", self._format_size(stats["db_size_bytes"]), ft.Icons.STORAGE
                ),
            ],
            spacing=12,
        )

    def _build_stat_card(self, label: str, value: str, icon) -> ft.Control:
        """Build a stat card"""
        return ft.Container(
            content=ft.Column(
                [
                    ft.Icon(icon, size=24, color=ft.Colors.PRIMARY),
                    ft.Text(value, size=20, weight=ft.FontWeight.BOLD),
                    ft.Text(label, size=12, color=ft.Colors.OUTLINE),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
            ),
            padding=16,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border_radius=12,
            expand=True,
        )

    def _format_size(self, bytes_: int) -> str:
        """Format bytes to human readable"""
        for unit in ["B", "KB", "MB", "GB"]:
            if bytes_ < 1024:
                return f"{bytes_:.1f} {unit}"
            bytes_ /= 1024
        return f"{bytes_:.1f} TB"

    def _on_tab_change(self, e):
        """Handle tab change"""
        self._refresh()

    def _refresh(self):
        """Refresh the view"""
        self.app.content_area.content = self.build()
        self.page.update()
