"""Gateway View - Gateway and pairing management interface"""

import flet as ft

from hermes_mobile.gateway.mobile_gateway import (
    cli_approve,
    cli_revoke,
    get_pairing_manager,
)


class GatewayView:
    """Gateway management interface"""

    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.pairing_manager = get_pairing_manager()
        self.gateway_manager = app.gateway_manager

    def build(self) -> ft.Control:
        """Build the gateway view"""
        return ft.Column(
            [
                # Header
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Text("Gateway", size=24, weight=ft.FontWeight.BOLD),
                            ft.Row(
                                [
                                    ft.IconButton(
                                        icon=ft.Icons.REFRESH,
                                        tooltip="Refresh",
                                        on_click=lambda e: self._refresh(),
                                    ),
                                ],
                                spacing=8,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    padding=ft.padding.symmetric(horizontal=20, vertical=16),
                ),
                ft.Divider(height=1),
                # Gateway status
                ft.Container(
                    content=self._build_gateway_status(),
                    padding=ft.padding.symmetric(horizontal=20, vertical=16),
                ),
                ft.Divider(height=1),
                # Pairing codes
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text("Pending Pairing Codes", size=18, weight=ft.FontWeight.BOLD),
                            ft.Divider(height=1),
                            self._build_pairing_list(),
                        ],
                        spacing=12,
                    ),
                    padding=ft.padding.symmetric(horizontal=20, vertical=16),
                    expand=True,
                ),
            ],
            expand=True,
        )

    def _build_gateway_status(self) -> ft.Control:
        """Build gateway status card"""
        enabled = self.gateway_manager.config.enabled if self.gateway_manager else False
        running = self.gateway_manager._running if self.gateway_manager else False

        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.HUB,
                                    color=ft.Colors.GREEN
                                    if (enabled and running)
                                    else ft.Colors.RED,
                                ),
                                ft.Column(
                                    [
                                        ft.Text(
                                            "Gateway Status", weight=ft.FontWeight.BOLD, size=16
                                        ),
                                        ft.Text(
                                            "Running" if (enabled and running) else "Stopped",
                                            size=14,
                                            color=ft.Colors.GREEN
                                            if (enabled and running)
                                            else ft.Colors.RED,
                                        ),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                ft.Switch(
                                    value=enabled,
                                    on_change=lambda e: self._toggle_gateway(e.control.value),
                                ),
                            ],
                            spacing=12,
                        ),
                        ft.Divider(height=1),
                        ft.Row(
                            [
                                ft.Text(
                                    f"Port: {self.gateway_manager.config.port if self.gateway_manager else 8080}",
                                    size=12,
                                    color=ft.Colors.OUTLINE,
                                ),
                                ft.Text(
                                    f"Platforms: {len(self.gateway_manager.config.platforms) if self.gateway_manager else 0}",
                                    size=12,
                                    color=ft.Colors.OUTLINE,
                                ),
                                ft.Text(
                                    f"Pairing: {'Enabled' if self.gateway_manager.config.pairing_enabled else 'Disabled'}",
                                    size=12,
                                    color=ft.Colors.OUTLINE,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                    ],
                    spacing=12,
                ),
                padding=16,
            ),
        )

    def _build_pairing_list(self) -> ft.Control:
        """Build the pairing codes list"""
        pending_codes = self.pairing_manager.get_pending_codes()

        if not pending_codes:
            return ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.VERIFIED_USER, size=48, color=ft.Colors.OUTLINE),
                        ft.Text("No pending pairing codes", size=16, color=ft.Colors.OUTLINE),
                        ft.Text(
                            "Users will receive codes when they message the bot",
                            color=ft.Colors.OUTLINE,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=12,
                ),
                alignment=ft.alignment.center,
                padding=40,
            )

        return ft.ListView(
            controls=[self._build_pairing_card(code) for code in pending_codes],
            spacing=12,
            expand=True,
        )

    def _build_pairing_card(self, code) -> ft.Control:
        """Build a pairing code card"""
        import time

        time_left = int(code.expires_at - time.time())
        minutes = time_left // 60
        seconds = time_left % 60

        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.VERIFIED_USER, color=ft.Colors.PRIMARY),
                                ft.Column(
                                    [
                                        ft.Text(
                                            f"Platform: {code.platform}",
                                            weight=ft.FontWeight.BOLD,
                                            size=14,
                                        ),
                                        ft.Text(
                                            f"User: {code.user_name} ({code.user_id})",
                                            size=12,
                                            color=ft.Colors.OUTLINE,
                                        ),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                ft.Container(
                                    content=ft.Text(
                                        f"{minutes:02d}:{seconds:02d}",
                                        size=14,
                                        weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.ORANGE
                                        if time_left < 300
                                        else ft.Colors.GREEN,
                                    ),
                                    padding=ft.padding.symmetric(horizontal=12, vertical=6),
                                    bgcolor=ft.Colors.with_opacity(
                                        0.1,
                                        ft.Colors.ORANGE if time_left < 300 else ft.Colors.GREEN,
                                    ),
                                    border_radius=12,
                                ),
                            ],
                            spacing=12,
                        ),
                        ft.Divider(height=1),
                        ft.Row(
                            [
                                ft.Text(
                                    f"Code: {code.code}",
                                    size=14,
                                    font_family="monospace",
                                    weight=ft.FontWeight.BOLD,
                                ),
                                ft.TextButton(
                                    "Approve",
                                    icon=ft.Icons.CHECK_CIRCLE,
                                    style=ft.ButtonStyle(color=ft.Colors.GREEN),
                                    on_click=lambda e, c=code: self._approve_code(c),
                                ),
                                ft.TextButton(
                                    "Revoke",
                                    icon=ft.Icons.CANCEL,
                                    style=ft.ButtonStyle(color=ft.Colors.RED),
                                    on_click=lambda e, c=code: self._revoke_code(c),
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                    ],
                    spacing=8,
                ),
                padding=16,
            ),
        )

    def _approve_code(self, code):
        """Approve a pairing code"""
        if cli_approve(code.code):
            self.page.show_snack_bar(
                ft.SnackBar(
                    content=ft.Text(f"Approved code for {code.user_name} on {code.platform}")
                )
            )
            self._refresh()
        else:
            self.page.show_snack_bar(ft.SnackBar(content=ft.Text("Failed to approve code")))

    def _revoke_code(self, code):
        """Revoke a pairing code"""
        if cli_revoke(code.code):
            self.page.show_snack_bar(
                ft.SnackBar(
                    content=ft.Text(f"Revoked code for {code.user_name} on {code.platform}")
                )
            )
            self._refresh()
        else:
            self.page.show_snack_bar(ft.SnackBar(content=ft.Text("Failed to revoke code")))

    def _toggle_gateway(self, enabled: bool):
        """Toggle gateway enabled state"""
        if self.gateway_manager:
            self.gateway_manager.config.enabled = enabled
            if enabled:
                import asyncio

                asyncio.create_task(self.gateway_manager.start())
            else:
                import asyncio

                asyncio.create_task(self.gateway_manager.stop())
            self._refresh()

    def _refresh(self):
        """Refresh the view"""
        self.app.content_area.content = self.build()
        self.page.update()
