"""Gateway View - Gateway and pairing management interface"""

import time

import flet as ft

from hermes_mobile.gateway.mobile_gateway import (
    cli_approve,
    cli_revoke,
    get_pairing_manager,
)
from hermes_mobile.locales import t
from hermes_mobile.ui.common import empty_state, flat_list_row, snack
from hermes_mobile.ui.theme import mode_colors


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
                    padding=ft.Padding.symmetric(horizontal=20, vertical=16),
                ),
                ft.Divider(height=1),
                # Gateway status
                ft.Container(
                    content=self._build_gateway_status(),
                    padding=ft.Padding.symmetric(horizontal=20, vertical=16),
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
                    padding=ft.Padding.symmetric(horizontal=20, vertical=16),
                    expand=True,
                ),
            ],
            expand=True,
        )

    def _build_gateway_status(self) -> ft.Control:
        """Build gateway status card"""
        enabled = self.gateway_manager.config.enabled if self.gateway_manager else False
        running = self.gateway_manager._running if self.gateway_manager else False
        c = mode_colors(self.app.dark_mode)

        return ft.Container(
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
                                    color=c["muted_foreground"],
                                ),
                                ft.Text(
                                    f"Platforms: {len(self.gateway_manager.config.platforms) if self.gateway_manager else 0}",
                                    size=12,
                                    color=c["muted_foreground"],
                                ),
                                ft.Text(
                                    f"Pairing: {'Enabled' if self.gateway_manager.config.pairing_enabled else 'Disabled'}",
                                    size=12,
                                    color=c["muted_foreground"],
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                    ],
                    spacing=12,
                ),
            padding=ft.Padding.symmetric(horizontal=0, vertical=12),
            border=ft.Border.only(bottom=ft.BorderSide(1, c["border"])),
        )

    def _build_pairing_list(self) -> ft.Control:
        """Build the pairing codes list"""
        pending_codes = self.pairing_manager.get_pending_codes()

        if not pending_codes:
            return empty_state(
                self.app.dark_mode,
                t("gateway.no_pending_codes"),
                t("gateway.no_pending_codes_hint"),
                ft.Icons.VERIFIED_USER_OUTLINED,
            )

        return ft.ListView(
            controls=[self._build_pairing_card(code) for code in pending_codes],
            spacing=12,
            expand=True,
        )

    def _build_pairing_card(self, code) -> ft.Control:
        """Build a dense pending-pairing row."""
        c = mode_colors(self.app.dark_mode)
        time_left = int(code.expires_at - time.time())
        minutes = time_left // 60
        seconds = time_left % 60
        countdown_color = ft.Colors.ORANGE if time_left < 300 else c["success"]
        actions = ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT,
            tooltip="Pairing actions",
            items=[
                ft.PopupMenuItem(
                    content=ft.Text("Approve"),
                    on_click=lambda e, item=code: self._approve_code(item),
                ),
                ft.PopupMenuItem(
                    content=ft.Text("Revoke"),
                    on_click=lambda e, item=code: self._revoke_code(item),
                ),
            ],
        )
        trailing = ft.Row(
            [
                ft.Text(
                    f"{minutes:02d}:{seconds:02d}",
                    size=12,
                    color=countdown_color,
                    font_family="monospace",
                ),
                actions,
            ],
            spacing=0,
            tight=True,
        )
        return flat_list_row(
            self.app.dark_mode,
            f"{code.platform} · {code.user_name}",
            f"{code.user_id}\nCode {code.code}",
            ft.Icon(ft.Icons.VERIFIED_USER, size=18, color=ft.Colors.PRIMARY),
            trailing,
        )

    def _approve_code(self, code):
        """Approve a pairing code"""
        if cli_approve(code.code):
            snack(self.page, f"Approved code for {code.user_name} on {code.platform}")
            self._refresh()
        else:
            snack(self.page, "Failed to approve code", error=True)

    def _revoke_code(self, code):
        """Revoke a pairing code"""
        if cli_revoke(code.code):
            snack(self.page, f"Revoked code for {code.user_name} on {code.platform}")
            self._refresh()
        else:
            snack(self.page, "Failed to revoke code", error=True)

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
