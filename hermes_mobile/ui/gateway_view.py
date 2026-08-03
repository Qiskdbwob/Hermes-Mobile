"""Remote Hermes connection and local messaging gateway management."""

import asyncio
import time

import flet as ft

from hermes_mobile.gateway.mobile_gateway import (
    cli_approve,
    cli_revoke,
    get_pairing_manager,
)
from hermes_mobile.locales import t
from hermes_mobile.remote import insecure_transport_is_private, normalize_remote_base_url
from hermes_mobile.ui.common import (
    empty_state,
    flat_button,
    flat_list_row,
    hairline,
    section_label,
    snack,
    status_dot,
)
from hermes_mobile.ui.theme import mode_colors


class GatewayView:
    """Manage the Desktop-compatible remote runtime and messaging gateway."""

    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.pairing_manager = get_pairing_manager()
        self.gateway_manager = app.gateway_manager
        self._runtime_field = None
        self._url_field = None
        self._auth_field = None
        self._username_field = None
        self._password_field = None
        self._token_field = None
        self._profile_field = None
        self._allow_insecure_field = None

    def build(self) -> ft.Control:
        c = mode_colors(self.app.dark_mode)
        return ft.Column(
            [
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text("Connections", size=24, weight=ft.FontWeight.BOLD),
                                    ft.Text(
                                        "Run on this phone or connect to a full Hermes backend.",
                                        size=12,
                                        color=c["muted_foreground"],
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.REFRESH,
                                tooltip="Refresh status",
                                on_click=lambda e: self._refresh(),
                            ),
                        ]
                    ),
                    padding=ft.Padding.symmetric(horizontal=20, vertical=16),
                ),
                hairline(self.app.dark_mode),
                ft.ListView(
                    controls=[
                        ft.Container(
                            content=ft.Column(
                                [
                                    section_label(
                                        self.app.dark_mode,
                                        "HERMES REMOTE",
                                        "Desktop protocol",
                                    ),
                                    self._build_remote_status(),
                                    self._build_remote_form(),
                                ],
                                spacing=14,
                            ),
                            padding=ft.Padding.symmetric(horizontal=20, vertical=18),
                        ),
                        hairline(self.app.dark_mode),
                        ft.Container(
                            content=ft.Column(
                                [
                                    section_label(
                                        self.app.dark_mode,
                                        "MESSAGING GATEWAY",
                                        "Telegram · Discord · Pairing",
                                    ),
                                    self._build_gateway_status(),
                                    ft.Text(
                                        "Pending pairing codes",
                                        size=15,
                                        weight=ft.FontWeight.W_600,
                                    ),
                                    self._build_pairing_list(),
                                ],
                                spacing=12,
                            ),
                            padding=ft.Padding.symmetric(horizontal=20, vertical=18),
                        ),
                    ],
                    expand=True,
                    spacing=0,
                ),
            ],
            expand=True,
            spacing=0,
        )

    def _build_remote_status(self) -> ft.Control:
        c = mode_colors(self.app.dark_mode)
        client = self.app.remote_client
        state = client.state if client is not None else "local"
        remote_selected = self.app.remote_mode
        if remote_selected:
            label = {
                "open": "Connected",
                "connecting": "Connecting",
                "error": "Connection failed",
                "closed": "Disconnected",
            }.get(state, "Disconnected")
            color = {
                "open": c["success"],
                "connecting": ft.Colors.ORANGE,
                "error": ft.Colors.ERROR,
            }.get(state, c["muted_foreground"])
            version = getattr(self.app.remote_status, "version", "")
            detail = f"Hermes {version}" if version else (self.app.settings.remote_url or "No URL")
        else:
            label = "Local agent"
            color = c["success"]
            detail = "Runs the embedded mobile runtime on this device"

        return ft.Container(
            content=ft.Row(
                [
                    status_dot(color, 9, label),
                    ft.Column(
                        [
                            ft.Text(label, size=15, weight=ft.FontWeight.W_600),
                            ft.Text(detail, size=12, color=c["muted_foreground"]),
                        ],
                        spacing=1,
                        expand=True,
                    ),
                    ft.Text(
                        "REMOTE" if remote_selected else "LOCAL",
                        size=11,
                        weight=ft.FontWeight.W_600,
                        color=color,
                    ),
                ],
                spacing=12,
            ),
            padding=ft.Padding.symmetric(vertical=6),
        )

    def _build_remote_form(self) -> ft.Control:
        c = mode_colors(self.app.dark_mode)
        settings = self.app.settings
        secrets = self.app.remote_secret_store.load() if self.app.remote_secret_store else {}
        field_style = {
            "border": ft.InputBorder.OUTLINE,
            "border_color": c["border"],
            "border_radius": 8,
        }

        def field(label, value="", **kwargs):
            return ft.TextField(
                label=label,
                value=value,
                text_size=14,
                content_padding=ft.Padding.symmetric(horizontal=12, vertical=10),
                **field_style,
                **kwargs,
            )

        self._runtime_field = ft.Dropdown(
            label="Agent runtime",
            value=getattr(settings, "runtime_mode", "local"),
            options=[
                ft.DropdownOption(key="local", text="Local — runs on this phone"),
                ft.DropdownOption(key="remote", text="Remote — full Hermes backend"),
            ],
            on_select=lambda e: self._toggle_remote_fields(),
            text_size=14,
            **field_style,
        )
        self._url_field = field(
            "Remote URL",
            getattr(settings, "remote_url", ""),
            hint_text="https://hermes.example.com or http://100.x.x.x:9119",
            keyboard_type=ft.KeyboardType.URL,
        )
        self._auth_field = ft.Dropdown(
            label="Authentication",
            value=getattr(settings, "remote_auth_mode", "auto"),
            options=[
                ft.DropdownOption(key="auto", text="Auto detect"),
                ft.DropdownOption(key="basic", text="Username + password"),
                ft.DropdownOption(key="token", text="Session token"),
            ],
            on_select=lambda e: self._toggle_remote_fields(),
            text_size=14,
            **field_style,
        )
        self._username_field = field(
            "Username", getattr(settings, "remote_username", ""), autocorrect=False
        )
        self._password_field = field(
            "Password",
            secrets.get("password", ""),
            password=True,
            can_reveal_password=True,
        )
        self._token_field = field(
            "Session / bearer token",
            secrets.get("token", ""),
            password=True,
            can_reveal_password=True,
        )
        self._profile_field = field("Profile (optional)", getattr(settings, "remote_profile", ""))
        self._allow_insecure_field = ft.Switch(
            label="Allow public plain HTTP (not recommended)",
            value=bool(getattr(settings, "remote_allow_insecure", False)),
        )

        connected = self.app.remote_client is not None and self.app.remote_client.state == "open"
        action_controls = [
            flat_button(
                "Save & connect",
                ft.Icons.LINK,
                lambda e: asyncio.create_task(self._save_remote(connect=True)),
                self.app.dark_mode,
                primary=True,
            )
        ]
        if connected:
            action_controls.append(
                flat_button(
                    "Disconnect",
                    ft.Icons.LINK_OFF,
                    lambda e: asyncio.create_task(self._disconnect()),
                    self.app.dark_mode,
                )
            )

        remote_controls = ft.Column(
            [
                self._url_field,
                self._auth_field,
                self._username_field,
                self._password_field,
                self._token_field,
                self._profile_field,
                self._allow_insecure_field,
                ft.Text(
                    "Basic login uses the backend's HttpOnly session cookie and a one-time "
                    "WebSocket ticket. Credentials are encrypted in the app-private "
                    "data directory.",
                    size=11,
                    color=c["muted_foreground"],
                ),
                ft.Row(action_controls, spacing=8, wrap=True),
            ],
            spacing=10,
        )
        self._remote_fields = remote_controls
        root = ft.Column([self._runtime_field, remote_controls], spacing=10)
        self._toggle_remote_fields(update=False)
        return root

    def _toggle_remote_fields(self, update: bool = True):
        remote = self._runtime_field is not None and self._runtime_field.value == "remote"
        auth = self._auth_field.value if self._auth_field is not None else "auto"
        if hasattr(self, "_remote_fields"):
            self._remote_fields.visible = remote
        if self._username_field is not None:
            self._username_field.visible = auth in {"auto", "basic"}
        if self._password_field is not None:
            self._password_field.visible = auth in {"auto", "basic"}
        if self._token_field is not None:
            self._token_field.visible = auth in {"auto", "token"}
        if update:
            self.page.update()

    async def _save_remote(self, connect: bool):
        settings = self.app.settings
        mode = str(self._runtime_field.value or "local")
        url = str(self._url_field.value or "").strip()
        if mode == "remote":
            try:
                normalized = normalize_remote_base_url(url)
            except ValueError as exc:
                snack(self.page, str(exc), error=True)
                return
            if not insecure_transport_is_private(normalized) and normalized.startswith("http://"):
                if not self._allow_insecure_field.value:
                    snack(
                        self.page,
                        "Public HTTP is blocked. Use HTTPS or explicitly allow insecure transport.",
                        error=True,
                    )
                    return
            url = normalized

        settings.runtime_mode = mode
        settings.remote_url = url
        settings.remote_auth_mode = str(self._auth_field.value or "auto")
        settings.remote_username = str(self._username_field.value or "").strip()
        settings.remote_profile = str(self._profile_field.value or "").strip()
        settings.remote_allow_insecure = bool(self._allow_insecure_field.value)
        settings.save()
        if self.app.remote_secret_store:
            self.app.remote_secret_store.save(
                password=str(self._password_field.value or ""),
                token=str(self._token_field.value or ""),
            )

        self.app.chat_view.clear_chat(show_welcome=True)
        if mode == "remote" and connect:
            await self.app.connect_remote(announce=True)
        else:
            await self.app.disconnect_remote()
            snack(self.page, "Local agent selected")
        self._refresh()

    async def _disconnect(self):
        await self.app.disconnect_remote()
        snack(self.page, "Hermes Remote disconnected")
        self._refresh()

    def _build_gateway_status(self) -> ft.Control:
        enabled = self.gateway_manager.config.enabled if self.gateway_manager else False
        running = self.gateway_manager._running if self.gateway_manager else False
        c = mode_colors(self.app.dark_mode)
        state_color = c["success"] if enabled and running else c["muted_foreground"]
        port = self.gateway_manager.config.port if self.gateway_manager else 8080
        platforms = len(self.gateway_manager.config.platforms) if self.gateway_manager else 0
        pairing_enabled = bool(self.gateway_manager and self.gateway_manager.config.pairing_enabled)
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            status_dot(state_color, 9),
                            ft.Column(
                                [
                                    ft.Text(
                                        "Local messaging service",
                                        weight=ft.FontWeight.W_600,
                                        size=15,
                                    ),
                                    ft.Text(
                                        "Running" if enabled and running else "Stopped",
                                        size=12,
                                        color=state_color,
                                    ),
                                ],
                                spacing=1,
                                expand=True,
                            ),
                            ft.Switch(
                                value=enabled,
                                on_change=lambda e: self._toggle_gateway(e.control.value),
                            ),
                        ],
                        spacing=12,
                    ),
                    ft.Text(
                        f"Port {port}  ·  {platforms} platforms  ·  "
                        f"Pairing {'enabled' if pairing_enabled else 'disabled'}",
                        size=11,
                        color=c["muted_foreground"],
                    ),
                ],
                spacing=8,
            ),
            padding=ft.Padding.symmetric(vertical=6),
        )

    def _build_pairing_list(self) -> ft.Control:
        pending_codes = self.pairing_manager.get_pending_codes()
        if not pending_codes:
            return empty_state(
                self.app.dark_mode,
                t("gateway.no_pending_codes"),
                t("gateway.no_pending_codes_hint"),
                ft.Icons.VERIFIED_USER_OUTLINED,
            )
        return ft.Column(
            controls=[self._build_pairing_card(code) for code in pending_codes],
            spacing=8,
        )

    def _build_pairing_card(self, code) -> ft.Control:
        c = mode_colors(self.app.dark_mode)
        time_left = max(0, int(code.expires_at - time.time()))
        minutes, seconds = divmod(time_left, 60)
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
        if cli_approve(code.code):
            snack(self.page, f"Approved code for {code.user_name} on {code.platform}")
            self._refresh()
        else:
            snack(self.page, "Failed to approve code", error=True)

    def _revoke_code(self, code):
        if cli_revoke(code.code):
            snack(self.page, f"Revoked code for {code.user_name} on {code.platform}")
            self._refresh()
        else:
            snack(self.page, "Failed to revoke code", error=True)

    def _toggle_gateway(self, enabled: bool):
        if self.gateway_manager:
            self.gateway_manager.config.enabled = enabled
            if enabled:
                asyncio.create_task(self.gateway_manager.start())
            else:
                asyncio.create_task(self.gateway_manager.stop())
            self._refresh()

    def _refresh(self):
        self.app.content_area.content = self.build()
        self.page.update()
