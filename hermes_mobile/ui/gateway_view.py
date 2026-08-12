"""Remote Hermes connection and local messaging gateway management."""

import asyncio
import logging
import time

import flet as ft

from hermes_mobile.config.settings import save_settings
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

logger = logging.getLogger(__name__)


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
        self._connect_button = None
        self._telegram_token_field = None
        # Draft of the Telegram token while the user is typing it. _refresh()
        # rebuilds the whole view (fields are recreated), so the typed value is
        # carried across rebuilds until the user saves or leaves.
        self._telegram_token_draft = None
        self._connect_progress = None
        self._feedback_text = None
        self._feedback_row = None
        self._feedback_container = None
        self._saving = False
        self._connection_feedback = ""
        self._connection_feedback_error = False

    def build(self) -> ft.Control:
        c = mode_colors(self.app.dark_mode)
        return ft.Column(
            [
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(
                                        t("gateway.connections_title"),
                                        size=24,
                                        weight=ft.FontWeight.BOLD,
                                    ),
                                    ft.Text(
                                        t("gateway.connections_subtitle"),
                                        size=12,
                                        color=c["muted_foreground"],
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.REFRESH,
                                tooltip=t("gateway.refresh_tooltip"),
                                on_click=lambda e: self._refresh(),
                            ),
                        ]
                    ),
                    padding=ft.Padding.symmetric(horizontal=20, vertical=16),
                ),
                hairline(self.app.dark_mode),
                self._build_body_list(),
            ],
            expand=True,
            spacing=0,
        )

    def _build_body_list(self) -> ft.ListView:
        return ft.ListView(
            controls=[
                ft.Container(
                    content=ft.Column(
                        [
                            section_label(
                                self.app.dark_mode,
                                t("gateway.remote_section"),
                                t("gateway.remote_section_sub"),
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
                                t("gateway.gateway_section"),
                                t("gateway.gateway_section_sub"),
                            ),
                            self._build_gateway_status(),
                            self._build_gateway_token_form(),
                            ft.Text(
                                t("gateway.pending_codes"),
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
        )

    def _build_remote_status(self) -> ft.Control:
        c = mode_colors(self.app.dark_mode)
        client = self.app.remote_client
        state = client.state if client is not None else "local"
        remote_selected = self.app.remote_mode
        if remote_selected:
            label = {
                "open": t("gateway.status_connected"),
                "connecting": t("gateway.status_connecting"),
                "error": t("gateway.status_failed"),
                "closed": t("gateway.status_disconnected"),
            }.get(state, t("gateway.status_disconnected"))
            color = {
                "open": c["success"],
                "connecting": ft.Colors.ORANGE,
                "error": ft.Colors.ERROR,
            }.get(state, c["muted_foreground"])
            version = getattr(self.app.remote_status, "version", "")
            detail = (
                f"Hermes {version}"
                if version
                else (self.app.settings.remote_url or t("gateway.no_url"))
            )
        else:
            label = t("gateway.local_agent")
            color = c["success"]
            detail = t("gateway.local_agent_detail")

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
                        t("gateway.remote_badge") if remote_selected else t("gateway.local_badge"),
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
            label=t("gateway.runtime"),
            value=getattr(settings, "runtime_mode", "local"),
            options=[
                ft.DropdownOption(key="local", text=t("gateway.runtime_local")),
                ft.DropdownOption(key="remote", text=t("gateway.runtime_remote")),
            ],
            on_select=lambda e: self._toggle_remote_fields(),
            text_size=14,
            **field_style,
        )
        self._url_field = field(
            t("gateway.remote_url"),
            getattr(settings, "remote_url", ""),
            hint_text=t("gateway.remote_url_hint"),
            keyboard_type=ft.KeyboardType.URL,
        )
        self._auth_field = ft.Dropdown(
            label=t("gateway.auth"),
            value=getattr(settings, "remote_auth_mode", "auto"),
            options=[
                ft.DropdownOption(key="auto", text=t("gateway.auth_auto")),
                ft.DropdownOption(key="basic", text=t("gateway.auth_basic")),
                ft.DropdownOption(key="token", text=t("gateway.auth_token")),
            ],
            on_select=lambda e: self._toggle_remote_fields(),
            text_size=14,
            **field_style,
        )
        self._username_field = field(
            t("gateway.username"), getattr(settings, "remote_username", ""), autocorrect=False
        )
        self._password_field = field(
            t("gateway.password"),
            secrets.get("password", ""),
            password=True,
            can_reveal_password=True,
        )
        self._token_field = field(
            t("gateway.session_token"),
            secrets.get("token", ""),
            password=True,
            can_reveal_password=True,
        )
        self._profile_field = field(t("gateway.profile"), getattr(settings, "remote_profile", ""))
        self._allow_insecure_field = ft.Switch(
            label=t("gateway.allow_insecure"),
            value=bool(getattr(settings, "remote_allow_insecure", False)),
        )

        connected = self.app.remote_client is not None and self.app.remote_client.state == "open"
        self._connect_button = flat_button(
            t("gateway.save_connect"),
            ft.Icons.LINK,
            lambda e: asyncio.create_task(self._save_remote(connect=True)),
            self.app.dark_mode,
            primary=True,
        )
        self._connect_button.disabled = self._saving
        action_controls = [
            self._connect_button,
        ]
        if connected:
            disconnect_button = flat_button(
                t("gateway.disconnect"),
                ft.Icons.LINK_OFF,
                lambda e: asyncio.create_task(self._disconnect()),
                self.app.dark_mode,
            )
            disconnect_button.disabled = self._saving
            action_controls.append(disconnect_button)

        feedback_color = (
            ft.Colors.ERROR
            if self._connection_feedback_error
            else (c["primary"] if self._saving else c["success"])
        )
        self._connect_progress = ft.ProgressRing(
            width=16,
            height=16,
            stroke_width=2,
            color=c["primary"],
            visible=self._saving,
        )
        self._feedback_text = ft.Text(
            self._connection_feedback,
            size=12,
            color=feedback_color,
            selectable=True,
            expand=True,
        )
        self._feedback_row = ft.Row(
            [self._connect_progress, self._feedback_text],
            spacing=8,
            visible=bool(self._connection_feedback),
        )
        self._feedback_container = ft.Container(
            content=self._feedback_row,
            height=24,
            alignment=ft.Alignment.CENTER_LEFT,
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
                    t("gateway.remote_note"),
                    size=11,
                    color=c["muted_foreground"],
                ),
                self._feedback_container,
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

    def _set_connection_feedback(
        self, message: str, *, error: bool, busy: bool, kind: str = "save"
    ):
        """Keep connection progress visible and prevent duplicate submissions."""
        self._connection_feedback = message
        self._connection_feedback_error = error
        self._saving = busy
        c = mode_colors(self.app.dark_mode)
        if self._connect_button is not None:
            self._connect_button.disabled = busy
            if busy:
                busy_label = t("gateway.connecting") if kind == "connect" else t("gateway.saving")
            else:
                busy_label = t("gateway.save_connect")
            self._connect_button.content = busy_label
            self._connect_button.icon = ft.Icons.SYNC if busy else ft.Icons.LINK
        if self._connect_progress is not None:
            self._connect_progress.visible = busy
        if self._feedback_text is not None:
            self._feedback_text.value = message
            self._feedback_text.color = (
                ft.Colors.ERROR if error else (c["primary"] if busy else c["success"])
            )
        if self._feedback_row is not None:
            self._feedback_row.visible = bool(message)
        self.page.update()

    async def _save_remote(self, connect: bool):
        if self._saving:
            return
        self._set_connection_feedback(t("gateway.saving_settings"), error=False, busy=True)
        settings = self.app.settings
        setting_names = (
            "runtime_mode",
            "remote_url",
            "remote_auth_mode",
            "remote_username",
            "remote_profile",
            "remote_allow_insecure",
        )
        previous_settings = {name: getattr(settings, name) for name in setting_names}
        previous_secrets = (
            self.app.remote_secret_store.load() if self.app.remote_secret_store else {}
        )
        previous_connected = bool(
            self.app.remote_client is not None and self.app.remote_client.state == "open"
        )
        try:
            mode = str(self._runtime_field.value or "local")
            url = str(self._url_field.value or "").strip()
            if mode == "remote":
                normalized = normalize_remote_base_url(url)
                if (
                    not insecure_transport_is_private(normalized)
                    and normalized.startswith("http://")
                    and not self._allow_insecure_field.value
                ):
                    raise ValueError(t("gateway.public_http_blocked"))
                url = normalized

            settings.runtime_mode = mode
            settings.remote_url = url
            settings.remote_auth_mode = str(self._auth_field.value or "auto")
            settings.remote_username = str(self._username_field.value or "").strip()
            settings.remote_profile = str(self._profile_field.value or "").strip()
            settings.remote_allow_insecure = bool(self._allow_insecure_field.value)
            if self.app.remote_secret_store:
                self.app.remote_secret_store.save(
                    password=str(self._password_field.value or ""),
                    token=str(self._token_field.value or ""),
                )

            if mode == "remote" and connect:
                self._set_connection_feedback(
                    t("gateway.connecting_remote"),
                    error=False,
                    busy=True,
                    kind="connect",
                )
                await self.app.disconnect_remote()
                connected = await self.app.connect_remote(announce=False)
                if not connected:
                    raise RuntimeError(
                        getattr(self.app, "remote_error", "") or t("gateway.remote_connect_failed")
                    )
                version = getattr(self.app.remote_status, "version", "")
                message = t(
                    "gateway.connected_version",
                    version=version or t("gateway.unknown_version"),
                )
            else:
                await self.app.disconnect_remote()
                message = t("gateway.local_selected")
            if not save_settings(settings):
                raise RuntimeError(t("gateway.settings_save_failed"))
            self.app.chat_view.clear_chat(show_welcome=True)
            self._set_connection_feedback(message, error=False, busy=False)
            snack(self.page, message)
        except Exception as exc:
            logger.exception("Could not save and apply the Remote connection")
            message = str(exc).strip() or t("gateway.remote_connect_failed")
            try:
                await self.app.disconnect_remote()
                for name, value in previous_settings.items():
                    setattr(settings, name, value)
                if self.app.remote_secret_store:
                    self.app.remote_secret_store.save(
                        password=str(previous_secrets.get("password") or ""),
                        token=str(previous_secrets.get("token") or ""),
                    )
                if not save_settings(settings):
                    logger.error("Could not persist the previous Remote configuration")
                if previous_connected and previous_settings["runtime_mode"] == "remote":
                    await self.app.connect_remote(announce=False)
            except Exception:
                logger.exception("Could not restore the previous Remote connection")
            self._set_connection_feedback(
                t("gateway.connection_failed", message=message),
                error=True,
                busy=False,
            )
            snack(self.page, message, error=True)
        finally:
            self._saving = False
            self._refresh()

    async def _disconnect(self):
        await self.app.disconnect_remote()
        snack(self.page, t("gateway.remote_disconnected"))
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
                                        t("gateway.service_title"),
                                        weight=ft.FontWeight.W_600,
                                        size=15,
                                    ),
                                    ft.Text(
                                        (
                                            t("gateway.running")
                                            if enabled and running
                                            else t("gateway.stopped")
                                        ),
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
                        t(
                            "gateway.status_line",
                            port=port,
                            platforms=platforms,
                            status=(
                                t("gateway.enabled_text")
                                if pairing_enabled
                                else t("gateway.disabled_text")
                            ),
                        ),
                        size=11,
                        color=c["muted_foreground"],
                    ),
                ],
                spacing=8,
            ),
            padding=ft.Padding.symmetric(vertical=6),
        )

    def _build_gateway_token_form(self) -> ft.Control:
        """In-app menu to set the Telegram bot token (stored encrypted)."""
        c = mode_colors(self.app.dark_mode)
        store = getattr(self.app, "gateway_secret_store", None)
        configured = bool(store and store.get_token())
        field_style = {
            "border": ft.InputBorder.OUTLINE,
            "border_color": c["border"],
            "border_radius": 8,
        }
        self._telegram_token_field = ft.TextField(
            label=t("gateway.telegram_token"),
            password=True,
            can_reveal_password=True,
            value=self._telegram_token_draft or "",
            hint_text=t("gateway.telegram_token_hint"),
            text_size=14,
            content_padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            **field_style,
        )
        save_button = flat_button(
            t("gateway.save_token"),
            ft.Icons.SAVE,
            lambda e: asyncio.create_task(self._save_telegram_token()),
            self.app.dark_mode,
            primary=True,
        )
        status_color = c["success"] if configured else ft.Colors.ORANGE
        status_text = t("gateway.token_configured") if configured else t("gateway.token_missing")
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(t("gateway.telegram_title"), size=15, weight=ft.FontWeight.W_600),
                    self._telegram_token_field,
                    ft.Row([save_button], spacing=8, wrap=True),
                    ft.Text(status_text, size=11, color=status_color),
                ],
                spacing=10,
            ),
            padding=ft.Padding.only(top=8),
        )

    async def _save_telegram_token(self):
        """Persist the token and restart the gateway to pick it up."""
        store = getattr(self.app, "gateway_secret_store", None)
        if store is None:
            snack(self.page, "Gateway secret store is unavailable", error=True)
            return
        token = str(self._telegram_token_field.value or "").strip()
        try:
            store.save_token(token)
            # Make sure the Telegram platform is in the active config and stays
            # enabled on future launches (the old build hardcoded platforms=[]).
            self.app.settings.gateway_platforms = ["telegram"]
            self.app.gateway_manager.config.platforms = ["telegram"]
            save_settings(self.app.settings)
        except Exception as exc:
            logger.exception("Could not save Telegram token")
            snack(self.page, t("gateway.token_save_failed", error=str(exc)), error=True)
            return

        if self.app.gateway_manager._running:
            try:
                await self.app.gateway_manager.stop()
                await self.app.gateway_manager.start()
            except Exception as exc:
                logger.exception("Could not restart gateway with new token")
                snack(
                    self.page,
                    t("gateway.token_restart_failed", error=str(exc)),
                    error=True,
                )
                self._refresh()
                return
        # Never echo the secret back: clear the draft so the rebuilt field is
        # empty (the status line below still confirms the token is configured).
        self._telegram_token_draft = ""
        message = t("gateway.token_saved") if token else t("gateway.token_cleared")
        snack(self.page, message)
        self._refresh()

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
            tooltip=t("gateway.pairing_actions"),
            items=[
                ft.PopupMenuItem(
                    content=ft.Text(t("gateway.approve")),
                    on_click=lambda e, item=code: self._approve_code(item),
                ),
                ft.PopupMenuItem(
                    content=ft.Text(t("gateway.revoke")),
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
            f"{code.user_id}\n" + t("gateway.code_label", code=code.code),
            ft.Icon(ft.Icons.VERIFIED_USER, size=18, color=ft.Colors.PRIMARY),
            trailing,
        )

    def _approve_code(self, code):
        if cli_approve(code.code):
            snack(
                self.page,
                t("gateway.approve_success", user=code.user_name, platform=code.platform),
            )
            self._refresh()
        else:
            snack(self.page, t("gateway.approve_failed"), error=True)

    def _revoke_code(self, code):
        if cli_revoke(code.code):
            snack(
                self.page,
                t("gateway.revoke_success", user=code.user_name, platform=code.platform),
            )
            self._refresh()
        else:
            snack(self.page, t("gateway.revoke_failed"), error=True)

    def _toggle_gateway(self, enabled: bool):
        if not self.gateway_manager:
            return
        self.gateway_manager.config.enabled = enabled
        # Persist the toggle — previously it only lived in the in-memory
        # config and reverted on the next app start.
        try:
            self.app.settings.gateway_enabled = enabled
            save_settings(self.app.settings)
        except Exception:
            logger.exception("Could not persist gateway toggle")
        if enabled:
            asyncio.create_task(self.gateway_manager.start())
        else:
            asyncio.create_task(self.gateway_manager.stop())
        self._refresh()

    def _refresh(self):
        # Preserve the in-progress token entry across the rebuild (fields are
        # recreated by build()). Saved tokens are cleared in the save handler.
        if self._telegram_token_field is not None:
            self._telegram_token_draft = self._telegram_token_field.value
        self.app.content_area.content = self.build()
        self.page.update()
