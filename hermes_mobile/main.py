"""Hermes Mobile - Main Flet Application"""

import asyncio
import logging
import os
from typing import Any, Mapping, cast

import flet as ft

from hermes_mobile.config.settings import get_settings, reload_settings
from hermes_mobile.core.agent import Message, MobileAgent, ToolCall, create_mobile_agent
from hermes_mobile.cron.scheduler import (
    ensure_default_jobs,
)
from hermes_mobile.gateway.mobile_gateway import (
    GatewayConfig,
    GatewayManager,
)
from hermes_mobile.locales import set_locale, t
from hermes_mobile.memory.provider import MobileMemoryProvider
from hermes_mobile.plugins import get_plugin_registry
from hermes_mobile.remote import RemoteEvent, RemoteHermesClient, RemoteSecretStore
from hermes_mobile.skills.manager import MobileSkillManager
from hermes_mobile.ui.artifacts_view import ArtifactsView
from hermes_mobile.ui.chat_view import ChatView
from hermes_mobile.ui.common import brand_mark, snack, status_dot
from hermes_mobile.ui.cron_view import CronView
from hermes_mobile.ui.gateway_view import GatewayView
from hermes_mobile.ui.kanban_view import KanbanView
from hermes_mobile.ui.memory_view import MemoryView
from hermes_mobile.ui.pet_view import MobilePet
from hermes_mobile.ui.plugins_view import PluginsView
from hermes_mobile.ui.sessions_view import SessionsView
from hermes_mobile.ui.settings_view import SettingsView
from hermes_mobile.ui.skills_view import SkillsView
from hermes_mobile.ui.terminal_view import TerminalView
from hermes_mobile.ui.theme import build_theme, mode_colors
from hermes_mobile.ui.tools_view import ToolsView

logger = logging.getLogger(__name__)


class HermesMobileApp:
    """Main Hermes Mobile Application"""

    # Desktop information architecture on a phone: only durable destinations
    # live in the bottom bar. Operational surfaces stay in the More menu.
    MOBILE_VIEWS = ["chat", "skills", "messaging", "artifacts"]
    DESKTOP_VIEWS = [
        "chat",
        "sessions",
        "skills",
        "messaging",
        "artifacts",
        "tools",
        "memory",
        "cron",
        "gateway",
        "plugins",
        "terminal",
        "kanban",
        "settings",
    ]
    OVERFLOW_VIEWS = ["tools", "memory", "cron", "plugins", "terminal", "kanban", "settings"]

    def __init__(self, page: ft.Page):
        self.page = page
        self.error_message = None
        self.settings = None
        self.agent: MobileAgent = None
        self.memory_provider: MobileMemoryProvider = None
        self.skill_manager: MobileSkillManager = None
        self.gateway_manager: GatewayManager = None
        self.plugin_registry = None
        self.remote_client: RemoteHermesClient | None = None
        self.remote_status = None
        self.remote_model = ""
        self.remote_error = ""
        self.current_session_title = t("chat.new_session")
        self.remote_secret_store: RemoteSecretStore | None = None
        self._remote_connect_lock = asyncio.Lock()
        self._remote_tool_calls: dict[str, ToolCall] = {}
        self._active_local_turn: asyncio.Task | None = None

        # UI Components
        self.chat_view: ChatView = None
        self.settings_view: SettingsView = None
        self.skills_view: SkillsView = None
        self.memory_view: MemoryView = None
        self.cron_view: CronView = None
        self.gateway_view: GatewayView = None
        self.plugins_view: PluginsView = None
        self.tools_view: ToolsView = None
        self.artifacts_view: ArtifactsView = None
        self.terminal_view: TerminalView = None
        self.kanban_view: KanbanView = None
        self.sessions_view: SessionsView = cast(SessionsView, None)
        self.pet_view: MobilePet = cast(MobilePet, None)

        # Navigation
        self.current_view = "chat"
        self.nav = None
        self.content_area = None
        self.app_bar = None
        self._nav_destinations = []
        self._views = list(self.MOBILE_VIEWS)

        # Settings must load before _setup_page so the theme applies
        try:
            self.settings = get_settings()
            set_locale(str(getattr(self.settings, "language", "en") or "en"))
        except Exception as e:
            logger.error("Failed to load settings: %s", e, exc_info=True)
            self.settings = None

        self._setup_page()
        try:
            self._initialize_components()
        except Exception as e:
            logger.error("Failed to initialize components: %s", e, exc_info=True)
            self.error_message = f"Initialization error: {e}"
            self._show_error_screen()
            return
        try:
            self._build_ui()
        except Exception as e:
            logger.error("Failed to build UI: %s", e, exc_info=True)
            self.error_message = f"UI build error: {e}"
            self._show_error_screen()

        if self.remote_mode:
            try:
                asyncio.get_running_loop().create_task(self.connect_remote())
            except RuntimeError:
                logger.warning("Remote auto-connect deferred: no running event loop")

    def _setup_page(self):
        """Configure the Flet page"""
        self.page.title = "Hermes Mobile"
        self.page.padding = 0
        self.page.spacing = 0
        raw_platform = getattr(self.page, "platform", "")
        platform_str = str(getattr(raw_platform, "value", raw_platform)).lower()
        page_width = float(getattr(self.page, "width", 0) or 0)
        self.is_mobile = platform_str in ("android", "ios") or (0 < page_width < 768)
        self.page.on_resize = self._on_page_resize
        # Allow forcing the mobile layout for desktop/web visual testing
        if os.environ.get("HERMES_MOBILE_LAYOUT", "").lower() == "mobile":
            self.is_mobile = True

        if platform_str.lower() not in ("android", "ios"):
            # Desktop window: phone-sized so the mobile layout is testable
            self.page.window = ft.Window(
                width=480,
                height=900,
                resizable=False,
            )

        # Apply the "nous" identity (matches Hermes Desktop)
        theme_setting = str(getattr(self.settings, "theme", "system") or "system").lower()
        self.page.theme = build_theme(dark=False)
        self.page.dark_theme = build_theme(dark=True)
        self._set_theme_mode(theme_setting)

    def _set_theme_mode(self, theme_setting: str) -> None:
        """Set the requested effective Flet theme without rebuilding controls."""
        if theme_setting == "dark":
            self.page.theme_mode = ft.ThemeMode.DARK
        elif theme_setting == "light":
            self.page.theme_mode = ft.ThemeMode.LIGHT
        else:
            self.page.theme_mode = ft.ThemeMode.SYSTEM

    def apply_theme(self, theme_setting: str) -> None:
        """Apply a theme and rebuild every token-bound shell surface in place."""
        self.page.theme = build_theme(dark=False)
        self.page.dark_theme = build_theme(dark=True)
        self._set_theme_mode(str(theme_setting or "system").lower())
        if self.chat_view is None:
            self.page.update()
            return

        active_view = self.current_view
        self.page.clean()
        self._build_ui()
        if active_view != "chat":
            self._switch_view(active_view)
        self._refresh_connection_chrome()
        self.page.update()

    def _on_page_resize(self, event: Any):
        """Swap the shell when a web/desktop viewport crosses the phone breakpoint."""
        raw_platform = getattr(self.page, "platform", "")
        platform_name = str(getattr(raw_platform, "value", raw_platform)).lower()
        width = float(getattr(event, "width", 0) or getattr(self.page, "width", 0) or 0)
        force_mobile = os.environ.get("HERMES_MOBILE_LAYOUT", "").lower() == "mobile"
        should_be_mobile = force_mobile or platform_name in ("android", "ios") or (0 < width < 768)
        if should_be_mobile == self.is_mobile or self.chat_view is None:
            return

        active_view = self.current_view
        self.is_mobile = should_be_mobile
        self.page.clean()
        self._build_ui()
        if active_view != "chat":
            self._switch_view(active_view)
        self._refresh_connection_chrome()
        self.page.update()

    @property
    def remote_mode(self) -> bool:
        """Whether chat should execute on the configured remote Hermes backend."""
        return bool(self.settings and getattr(self.settings, "runtime_mode", "local") == "remote")

    @property
    def dark_mode(self) -> bool:
        """Whether the effective color mode is dark."""
        mode = getattr(self.page, "theme_mode", ft.ThemeMode.SYSTEM)
        if mode == ft.ThemeMode.DARK:
            return True
        if mode == ft.ThemeMode.LIGHT:
            return False
        # SYSTEM: trust the platform-reported brightness
        pb = getattr(self.page, "platform_brightness", None)
        return pb == ft.Brightness.DARK

    def _initialize_components(self):
        """Initialize core components"""
        # Initialize memory provider
        self.memory_provider = MobileMemoryProvider(
            db_path=self.settings.get_memory_db_path(),
            encrypt=self.settings.encrypt_memory,
        )
        self.remote_secret_store = RemoteSecretStore(self.settings.get_data_dir())

        # Initialize skill manager
        self.skill_manager = MobileSkillManager(
            skills_dir=self.settings.get_skills_dir(),
        )

        # Initialize agent
        self.agent = create_mobile_agent(
            on_tool_call=self._on_tool_call,
            on_tool_result=self._on_tool_result,
            on_message=self._on_message,
        )

        # Initialize plugin registry
        self.plugin_registry = get_plugin_registry()

        # Initialize gateway manager
        gateway_config = GatewayConfig(
            enabled=self.settings.gateway_enabled,
            port=self.settings.gateway_port,
            platforms=[],
        )
        self.gateway_manager = GatewayManager(gateway_config)

        # Initialize views
        self.pet_view = MobilePet(self)
        self.chat_view = ChatView(self)
        self.settings_view = SettingsView(self)
        self.skills_view = SkillsView(self)
        self.memory_view = MemoryView(self)
        self.cron_view = CronView(self)
        self.gateway_view = GatewayView(self)
        self.plugins_view = PluginsView(self)
        self.tools_view = ToolsView(self)
        self.artifacts_view = ArtifactsView(self)
        self.terminal_view = TerminalView(self)
        self.kanban_view = KanbanView(self)
        self.sessions_view = SessionsView(self)

        # Ensure default cron jobs exist
        ensure_default_jobs()

    def _build_ui(self):
        """Build the main UI"""
        self._views = list(self.MOBILE_VIEWS if self.is_mobile else self.DESKTOP_VIEWS)
        c = mode_colors(self.dark_mode)

        def nav_dest(cls, view: str):
            specs = {
                "chat": (ft.Icons.CHAT_OUTLINED, ft.Icons.CHAT, t("nav.chat")),
                "skills": (
                    ft.Icons.EXTENSION_OUTLINED,
                    ft.Icons.EXTENSION,
                    t("nav.skills"),
                ),
                "messaging": (
                    ft.Icons.HUB_OUTLINED,
                    ft.Icons.HUB,
                    t("nav.messaging"),
                ),
                "artifacts": (
                    ft.Icons.FOLDER_OUTLINED,
                    ft.Icons.FOLDER,
                    t("nav.artifacts"),
                ),
                "tools": (ft.Icons.BUILD_OUTLINED, ft.Icons.BUILD, t("nav.tools")),
                "memory": (
                    ft.Icons.PSYCHOLOGY_OUTLINED,
                    ft.Icons.PSYCHOLOGY,
                    t("nav.memory"),
                ),
                "cron": (
                    ft.Icons.SCHEDULE_OUTLINED,
                    ft.Icons.SCHEDULE,
                    t("nav.cron"),
                ),
                "gateway": (ft.Icons.HUB_OUTLINED, ft.Icons.HUB, t("nav.gateway")),
                "plugins": (
                    ft.Icons.EXTENSION_OUTLINED,
                    ft.Icons.EXTENSION,
                    t("nav.plugins"),
                ),
                "terminal": (
                    ft.Icons.TERMINAL_OUTLINED,
                    ft.Icons.TERMINAL,
                    t("nav.terminal"),
                ),
                "kanban": (
                    ft.Icons.VIEW_KANBAN_OUTLINED,
                    ft.Icons.VIEW_KANBAN,
                    t("nav.kanban"),
                ),
                "settings": (
                    ft.Icons.SETTINGS_OUTLINED,
                    ft.Icons.SETTINGS,
                    t("nav.settings"),
                ),
            }
            icon, sel_icon, label = specs[view]
            return cls(icon=icon, selected_icon=sel_icon, label=label)

        bar_destinations = [nav_dest(ft.NavigationBarDestination, v) for v in self._views]
        rail_destinations = [nav_dest(ft.NavigationRailDestination, v) for v in self._views]
        self._nav_destinations = bar_destinations

        # Content area
        self.content_area = ft.Container(
            content=self.chat_view.build(),
            expand=True,
            padding=0,
            bgcolor=c["background"],
        )

        # Brand header (mobile)
        self.app_bar = self._build_app_bar()

        if self.is_mobile:
            self.nav = ft.NavigationBar(
                selected_index=0,
                destinations=bar_destinations,
                on_change=self._on_navigation_change,
                height=58,
            )
            mobile_shell = ft.Column(
                [
                    self.app_bar,
                    ft.Container(self.content_area, expand=True),
                    self.nav,
                ],
                expand=True,
                spacing=0,
            )
            self.page.add(
                ft.SafeArea(
                    content=ft.Stack([mobile_shell, self.pet_view.build()], expand=True),
                    avoid_intrusions_top=True,
                    avoid_intrusions_bottom=True,
                    maintain_bottom_view_padding=True,
                    expand=True,
                )
            )
        else:
            self.nav = ft.NavigationRail(
                selected_index=0,
                label_type=ft.NavigationRailLabelType.ALL,
                min_width=110,
                min_extended_width=190,
                leading=ft.Container(
                    content=brand_mark(34),
                    padding=ft.Padding.only(left=12, top=8, bottom=16),
                ),
                group_alignment=-0.9,
                destinations=rail_destinations,
                on_change=self._on_navigation_change,
            )
            self.page.add(
                ft.Row(
                    [self.nav, ft.VerticalDivider(width=1), self.content_area],
                    expand=True,
                    spacing=0,
                )
            )

    def _build_app_bar(self) -> ft.Control:
        """Build one compact mobile shell header — no duplicate chat header."""
        c = mode_colors(self.dark_mode)
        if self.remote_mode:
            provider = "Remote"
            short_model = "connecting"
        else:
            provider = getattr(self.settings, "default_provider", "openrouter")
            model = getattr(self.settings, "default_model", "")
            short_model = model.split("/")[-1] if model else t("chat.model_not_configured")

        self._gateway_indicator = status_dot(
            c["muted_foreground"],
            size=7,
            tooltip=t("gateway.offline"),
        )
        self._new_session_button = ft.IconButton(
            icon=ft.Icons.ADD,
            icon_size=19,
            icon_color=c["muted_foreground"],
            tooltip=t("chat.new_session"),
            on_click=self._start_new_session,
        )
        self._sessions_button = ft.IconButton(
            icon=ft.Icons.FORUM_OUTLINED,
            icon_size=18,
            icon_color=c["muted_foreground"],
            tooltip=t("sessions.title"),
            on_click=lambda e: asyncio.create_task(self.show_remote_sessions()),
        )

        overflow_menu = ft.PopupMenuButton(
            icon=ft.Icons.MORE_HORIZ,
            icon_color=c["muted_foreground"],
            tooltip=t("nav.more"),
            items=[
                ft.PopupMenuItem(
                    icon=ft.Icons.BUILD_OUTLINED,
                    content=t("nav.tools"),
                    on_click=lambda e: self._navigate_to("tools"),
                ),
                ft.PopupMenuItem(
                    icon=ft.Icons.PSYCHOLOGY_OUTLINED,
                    content=t("nav.memory"),
                    on_click=lambda e: self._navigate_to("memory"),
                ),
                ft.PopupMenuItem(
                    icon=ft.Icons.SCHEDULE_OUTLINED,
                    content=t("nav.cron"),
                    on_click=lambda e: self._navigate_to("cron"),
                ),
                ft.PopupMenuItem(
                    icon=ft.Icons.EXTENSION_OUTLINED,
                    content=t("nav.plugins"),
                    on_click=lambda e: self._navigate_to("plugins"),
                ),
                ft.PopupMenuItem(
                    icon=ft.Icons.TERMINAL_OUTLINED,
                    content=t("nav.terminal"),
                    on_click=lambda e: self._navigate_to("terminal"),
                ),
                ft.PopupMenuItem(
                    icon=ft.Icons.VIEW_KANBAN_OUTLINED,
                    content=t("nav.kanban"),
                    on_click=lambda e: self._navigate_to("kanban"),
                ),
                ft.PopupMenuItem(
                    icon=ft.Icons.SETTINGS_OUTLINED,
                    content=t("nav.settings"),
                    on_click=lambda e: self._navigate_to("settings"),
                ),
            ],
        )

        self._app_bar_title = ft.Text(
            t("chat.new_session"),
            size=14,
            weight=ft.FontWeight.W_600,
            color=c["foreground"],
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self._app_bar_subtitle = ft.Text(
            f"{provider} · {short_model}",
            size=10,
            color=c["muted_foreground"],
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )

        self._app_bar_leading = ft.Container(
            content=brand_mark(30),
            width=42,
            alignment=ft.Alignment.CENTER_LEFT,
        )
        return ft.Container(
            content=ft.Row(
                [
                    self._app_bar_leading,
                    ft.Container(width=2),
                    ft.Column(
                        [self._app_bar_title, self._app_bar_subtitle],
                        spacing=0,
                        alignment=ft.MainAxisAlignment.CENTER,
                        expand=True,
                    ),
                    self._gateway_indicator,
                    self._sessions_button,
                    self._new_session_button,
                    overflow_menu,
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.only(left=12, right=4, top=8, bottom=8),
            bgcolor=c["sidebar"],
            border=ft.Border.only(bottom=ft.BorderSide(1, c["sidebar_border"])),
        )

    def _show_error_screen(self):
        """Show error screen if initialization fails"""
        self.page.clean()
        self.page.add(
            ft.Column(
                [
                    ft.Container(height=40),
                    ft.Icon(ft.Icons.ERROR_OUTLINE, size=64, color=ft.Colors.ERROR),
                    ft.Container(height=20),
                    ft.Text("Hermes Mobile - Error", size=24, weight=ft.FontWeight.BOLD),
                    ft.Container(height=10),
                    ft.Text(
                        self.error_message or "Unknown error during initialization",
                        size=14,
                        color=ft.Colors.OUTLINE,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Container(height=20),
                    ft.Button(
                        "Retry",
                        icon=ft.Icons.REFRESH,
                        on_click=self._retry_initialization,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                expand=True,
            )
        )
        self.page.update()

    def _retry_initialization(self, e=None):
        """Retry startup in place instead of closing the application."""
        self.page.clean()
        self.error_message = None
        try:
            self._setup_page()
            self._initialize_components()
            self._build_ui()
        except Exception as exc:
            logger.exception("Retry initialization failed")
            self.error_message = str(exc)
            self._show_error_screen()

    def _navigate_to(self, view: str):
        """Navigate from the primary bar or the operational More menu."""
        if view not in self.DESKTOP_VIEWS:
            return
        self._switch_view(view)
        if self.nav is not None and view in self._views:
            try:
                self.nav.selected_index = self._views.index(view)
            except Exception:
                pass
        self.page.update()

    def _on_navigation_change(self, e):
        """Handle navigation change"""
        try:
            index = None
            if hasattr(e, "control") and e.control is not None:
                index = getattr(e.control, "selected_index", None)
            if index is None and hasattr(e, "data") and e.data not in (None, ""):
                index = int(e.data)
            if index is None:
                return

            if index < 0 or index >= len(self._views):
                return

            self._switch_view(self._views[index])
        except Exception as ex:
            print(f"Navigation error: {ex}")

    def _switch_view(self, view: str):
        """Build only the requested surface and preserve every other view's state."""
        builders = {
            "chat": self.chat_view.build,
            "sessions": self.sessions_view.build,
            "tools": self.tools_view.build,
            "memory": self.memory_view.build,
            "skills": self.skills_view.build,
            "messaging": self.gateway_view.build,
            "artifacts": self.artifacts_view.build,
            "cron": self.cron_view.build,
            "gateway": self.gateway_view.build,
            "plugins": self.plugins_view.build,
            "terminal": self.terminal_view.build,
            "kanban": self.kanban_view.build,
            "settings": self.settings_view.build,
        }
        builder = builders.get(view)
        if builder is None or self.content_area is None:
            return

        try:
            new_content = builder()
        except Exception as exc:
            logger.exception("Failed to build view %s", view)
            snack(self.page, f"Could not open {view}: {exc}", error=True)
            return

        self.current_view = view
        self.content_area.content = new_content
        self._update_app_bar_title(view)
        self.page.update()
        if view == "artifacts" and self.remote_mode:
            asyncio.create_task(self.artifacts_view.refresh_remote())
        elif view == "skills" and self.remote_mode:
            asyncio.create_task(self.skills_view.refresh_remote())
        elif view == "settings":
            if self.remote_mode:
                asyncio.create_task(self.settings_view.refresh_remote_models())
                asyncio.create_task(self.settings_view.refresh_pet_gallery())
            else:
                asyncio.create_task(self.settings_view.refresh_local_models())

    def _update_app_bar_title(self, view: str):
        """Keep title, context and chat-only actions synchronized."""
        if not self.is_mobile or not hasattr(self, "_app_bar_title"):
            return
        if view == "chat":
            self._app_bar_title.visible = True
            self._app_bar_subtitle.visible = True
            self._app_bar_title.value = self.current_session_title
            if self.remote_mode:
                state = self.remote_client.state if self.remote_client else "offline"
                version = getattr(self.remote_status, "version", "")
                model = str(self.remote_model or "")
                detail = model.split("/")[-1] if model else (version or state)
                self._app_bar_subtitle.value = f"Remote · {detail}"
            else:
                provider = getattr(self.settings, "default_provider", "openrouter")
                model = getattr(self.settings, "default_model", "")
                short_model = model.split("/")[-1] if model else t("chat.model_not_configured")
                self._app_bar_subtitle.value = f"{provider} · {short_model}"
        elif view == "sessions":
            self._app_bar_title.visible = True
            self._app_bar_subtitle.visible = True
            self._app_bar_title.value = t("sessions.title")
            self._app_bar_subtitle.value = t("sessions.subtitle")
        else:
            # Operational pages own their visible heading and actions. Keeping a
            # second title in the shell wastes scarce phone height and reads as
            # an accidental duplicate.
            self._app_bar_title.visible = False
            self._app_bar_subtitle.visible = False
        if view == "sessions":
            self._app_bar_leading.content = ft.IconButton(
                icon=ft.Icons.ARROW_BACK,
                icon_size=19,
                icon_color=mode_colors(self.dark_mode)["foreground"],
                tooltip=t("common.back"),
                on_click=lambda e: self._navigate_to("chat"),
                padding=0,
            )
        else:
            self._app_bar_leading.content = brand_mark(30)
        self._new_session_button.visible = view in {"chat", "sessions"}
        self._sessions_button.visible = view != "sessions"

    async def show_remote_sessions(self):
        """Open the full-height, source-aware Remote session browser."""
        if not self.remote_mode:
            snack(self.page, "Select Remote runtime in Connections first", error=True)
            self._navigate_to("gateway")
            return
        if self.remote_client is None or self.remote_client.state != "open":
            if not await self.connect_remote(announce=True):
                return
        client = self.remote_client
        if client is None:
            return
        self._navigate_to("sessions")
        await self.sessions_view.refresh()

    async def resume_remote_session(self, session_id: str, title: str):
        """Resume a selected stored session and return to the transcript."""
        client = self.remote_client
        if client is None:
            return
        try:
            result = await client.resume_session(session_id)
        except Exception as exc:
            snack(self.page, str(exc), error=True)
            return
        self.activate_remote_session_result(result, title)

    def activate_remote_session_result(self, result: Mapping[str, Any], title: str) -> None:
        """Render a session result that is already active in the remote runtime."""
        self.chat_view.load_remote_history(result.get("messages") or [])
        self.current_session_title = title
        self._navigate_to("chat")
        self._app_bar_title.value = title
        self.page.update()

    async def connect_remote(self, announce: bool = False):
        """Serialize Remote connection attempts across startup and lifecycle hooks."""
        async with self._remote_connect_lock:
            return await self._connect_remote_locked(announce)

    async def _connect_remote_locked(self, announce: bool = False):
        """Connect chat to the configured Hermes remote backend."""
        if not self.settings or not self.remote_secret_store:
            return False
        if self.remote_client is not None and self.remote_client.state == "open":
            self.remote_error = ""
            if announce:
                version = getattr(self.remote_status, "version", "") or "unknown version"
                snack(self.page, f"Connected to Hermes {version}")
            return True
        remote_url = str(getattr(self.settings, "remote_url", "") or "").strip()
        if not remote_url:
            if announce:
                snack(self.page, "Set a Remote URL first", error=True)
            return False

        if self.remote_client is not None:
            await self.remote_client.close()
        secrets = self.remote_secret_store.load()
        client = RemoteHermesClient(
            remote_url,
            auth_mode=getattr(self.settings, "remote_auth_mode", "auto"),
            token=secrets.get("token", ""),
            username=getattr(self.settings, "remote_username", ""),
            password=secrets.get("password", ""),
            profile=getattr(self.settings, "remote_profile", ""),
            timeout=getattr(self.settings, "request_timeout", 120),
            allow_insecure=getattr(self.settings, "remote_allow_insecure", False),
            on_event=self._on_remote_event,
            on_state=self._on_remote_state,
        )
        self.remote_client = client
        self.remote_error = ""
        try:
            self.remote_status = await client.connect()
        except Exception as exc:
            self.remote_error = str(exc)
            logger.exception("Remote backend connection failed")
            self._refresh_connection_chrome()
            if announce:
                snack(self.page, str(exc), error=True)
            return False
        self.remote_error = ""
        self._refresh_connection_chrome()
        await self.refresh_pet()
        if announce:
            version = self.remote_status.version or "unknown version"
            snack(self.page, f"Connected to Hermes {version}")
        return True

    async def disconnect_remote(self):
        """Close the active remote socket without touching the local agent."""
        if self.remote_client is not None:
            await self.remote_client.close()
        self.remote_client = None
        self.remote_status = None
        self.remote_model = ""
        self.remote_error = ""
        self._remote_tool_calls.clear()
        if self.pet_view is not None:
            self.pet_view.hide()
        self._refresh_connection_chrome()

    async def refresh_pet(self) -> None:
        """Load the active profile pet without coupling it to Sessions."""
        client = self.remote_client
        if client is None or client.state != "open" or self.pet_view is None:
            if self.pet_view is not None:
                self.pet_view.hide()
            return
        try:
            self.pet_view.set_info(await client.get_pet_info())
            self.page.update()
        except Exception as exc:
            logger.info("Remote pet unavailable: %s", exc)
            self.pet_view.hide()

    async def _on_remote_state(self, state: str):
        logger.info("Remote Hermes state: %s", state)
        self._refresh_connection_chrome()
        if self.chat_view is not None:
            self.chat_view.refresh_welcome()

    def _refresh_connection_chrome(self):
        """Reflect actual runtime connectivity in the mobile shell."""
        if not hasattr(self, "_gateway_indicator"):
            return
        c = mode_colors(self.dark_mode)
        state = self.remote_client.state if self.remote_client else "local"
        colors = {
            "open": c["success"],
            "connecting": ft.Colors.ORANGE,
            "error": ft.Colors.ERROR,
            "closed": c["muted_foreground"],
            "local": c["success"],
        }
        self._gateway_indicator.bgcolor = colors.get(state, c["muted_foreground"])
        self._gateway_indicator.tooltip = (
            f"Hermes Remote: {state}" if self.remote_mode else "Local agent ready"
        )
        if self.current_view == "chat":
            self._update_app_bar_title("chat")
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_remote_event(self, event: RemoteEvent):
        """Project canonical Desktop gateway events onto the mobile transcript."""
        client = self.remote_client
        if event.session_id and client and client.session_id:
            if event.session_id != client.session_id:
                return
        payload = event.payload
        if event.type == "message.delta":
            text = str(payload.get("text") or "")
            if text:
                self.chat_view.append_assistant_message(text)
        elif event.type == "message.interim":
            text = str(payload.get("text") or "")
            if text:
                self.chat_view.append_assistant_message(text)
                self.chat_view.finalize_assistant_message()
        elif event.type == "message.complete":
            if not self.chat_view.current_assistant_text:
                text = str(payload.get("text") or "")
                if text:
                    self.chat_view.append_assistant_message(text)
            self.chat_view.finalize_assistant_message()
            self.chat_view.set_busy(False)
            if self.pet_view is not None:
                self.pet_view.flash_activity("wave")
            self.chat_view.set_status("")
        elif event.type == "tool.start":
            tool_id = str(payload.get("tool_id") or payload.get("id") or "remote-tool")
            arguments = payload.get("args") if isinstance(payload.get("args"), dict) else {}
            tool_call = ToolCall(
                name=str(payload.get("name") or "tool"),
                arguments=arguments,
                call_id=tool_id,
            )
            self._remote_tool_calls[tool_id] = tool_call
            self.chat_view.on_tool_call(tool_call)
        elif event.type == "tool.complete":
            tool_id = str(payload.get("tool_id") or payload.get("id") or "remote-tool")
            tool_call = self._remote_tool_calls.get(tool_id)
            if tool_call is None:
                tool_call = ToolCall(
                    name=str(payload.get("name") or "tool"),
                    arguments=payload.get("args") if isinstance(payload.get("args"), dict) else {},
                    call_id=tool_id,
                )
                self.chat_view.on_tool_call(tool_call)
            tool_call.result = payload.get("result") or payload.get("preview") or "Completed"
            if payload.get("error"):
                tool_call.error = str(payload["error"])
            self.chat_view.on_tool_result(tool_call)
        elif event.type == "status.update":
            self.chat_view.set_status(str(payload.get("text") or payload.get("kind") or ""))
        elif event.type in {
            "clarify.request",
            "approval.request",
            "secret.request",
            "sudo.request",
        }:
            self.chat_view.show_remote_request(event)
        elif event.type == "session.info":
            model = str(payload.get("model") or "")
            self.remote_model = model
            title = str(payload.get("title") or "")
            if title and hasattr(self, "_app_bar_title"):
                self.current_session_title = title
                self._app_bar_title.value = title
            if model and hasattr(self, "_app_bar_subtitle"):
                self._app_bar_subtitle.value = f"Remote · {model.split('/')[-1]}"
            self._refresh_connection_chrome()
        elif event.type == "pet.changed":
            await self.refresh_pet()
        elif event.type == "error":
            message = str(payload.get("message") or "Remote Hermes error")
            self.chat_view.append_assistant_message(f"**Error:** {message}")
            self.chat_view.finalize_assistant_message()
            self.chat_view.set_busy(False)
            if self.pet_view is not None:
                self.pet_view.flash_activity("failed")
            self.chat_view.set_status("")
        elif event.type == "background.complete":
            self.chat_view.set_status(str(payload.get("text") or "Background task complete"))

    def _start_new_session(self, e=None):
        """Create a genuinely clean local or remote agent session."""
        if self.chat_view is not None:
            self.chat_view.clear_chat(show_welcome=True)
        if self.remote_client is not None:
            self.remote_client.session_id = None
            self.remote_client.stored_session_id = None
        self._remote_tool_calls.clear()
        self.current_session_title = t("chat.new_session")
        self._navigate_to("chat")
        self._app_bar_title.value = t("chat.new_session")
        self.page.update()

    def _on_tool_call(self, tool_call: ToolCall):
        """Handle tool call from agent"""
        if self.chat_view:
            self.chat_view.on_tool_call(tool_call)

    def _on_tool_result(self, tool_call: ToolCall):
        """Handle tool result from agent"""
        if self.chat_view:
            self.chat_view.on_tool_result(tool_call)

    def _on_message(self, message: Message):
        """Handle new message from agent"""
        if self.chat_view:
            self.chat_view.on_message(message)

    async def _handle_slash_command(self, text: str):
        """Process local slash commands before they reach the agent loop."""
        cmd = text.strip().lower()
        parts = cmd.split(None, 1)
        command = parts[0].lstrip("/")
        arg = parts[1] if len(parts) > 1 else ""

        if command in ("new", "reset"):
            self._start_new_session()
        elif command in ("stop", "interrupt", "cancel"):
            await self.interrupt_turn()
        elif command == "model" and arg:
            self.settings.default_model = arg
            if self.remote_client:
                self.remote_client.model = arg
            elif self.agent:
                self.agent.model = arg
                self.agent._init_client()
            snack(self.page, f"Model changed to {arg}")
            self._app_bar_subtitle.value = arg.split("/")[-1] if "/" in arg else arg
            self.page.update()
        elif command == "provider" and arg:
            self.settings.default_provider = arg
            snack(self.page, f"Provider changed to {arg}")
            self.page.update()
        elif command == "undo":
            if self.chat_view and self.chat_view.messages:
                self.chat_view.messages.pop()
                if self.chat_view.messages:
                    self.chat_view.messages.pop()
                self.chat_view._render_messages()
                self.page.update()
        elif command == "retry":
            if self.chat_view and self.chat_view.messages:
                self.chat_view.messages.pop()
                self.chat_view._render_messages()
                self.page.update()
                last_user = ""
                for msg in reversed(self.chat_view.messages):
                    if msg.get("role") == "user":
                        last_user = msg.get("content", "")
                        break
                if last_user:
                    await self.send_message(last_user)
        else:
            snack(self.page, f"Unknown command: /{command}")

    async def send_message(self, text: str):
        """Send one turn through the selected local or remote runtime."""
        if not text.strip() or self.chat_view is None:
            return

        if text.startswith("/") and not text.startswith("//"):
            await self._handle_slash_command(text)
            return

        self.chat_view.set_busy(True)
        self.chat_view.add_user_message(text)
        if self.remote_mode:
            self.chat_view.set_status("Connecting to Hermes Remote…")
            try:
                if self.remote_client is None or self.remote_client.state != "open":
                    if not await self.connect_remote():
                        raise RuntimeError("Hermes Remote is not connected")
                client = self.remote_client
                if client is None:
                    raise RuntimeError("Hermes Remote connection was lost")
                self.chat_view.set_status("Hermes is working…")
                await client.submit_prompt(text)
                # message.complete owns finalization and unlocks the composer.
                return
            except Exception as exc:
                logger.exception("Remote conversation turn failed")
                self.chat_view.append_assistant_message(f"**Remote error:** {exc}")
                self.chat_view.finalize_assistant_message()
                self.chat_view.set_busy(False)
                if self.pet_view is not None:
                    self.pet_view.flash_activity("failed")
                self.chat_view.set_status("")
                return

        if self.agent is None:
            self.chat_view.set_busy(False)
            return
        self._active_local_turn = asyncio.current_task()
        reaction = ""
        try:
            async for chunk in self.agent.run_conversation(text, stream=True):
                self.chat_view.append_assistant_message(chunk)
            self.chat_view.finalize_assistant_message()
            reaction = "wave"
        except asyncio.CancelledError:
            self.chat_view.finalize_assistant_message()
            self.chat_view.set_status("Stopped")
        except Exception as exc:
            logger.exception("Conversation turn failed")
            self.chat_view.append_assistant_message(f"**Error:** {exc}")
            self.chat_view.finalize_assistant_message()
            reaction = "failed"
        finally:
            self._active_local_turn = None
            self.chat_view.set_busy(False)
            if reaction and self.pet_view is not None:
                self.pet_view.flash_activity(reaction)

    async def interrupt_turn(self):
        """Interrupt the active local task or canonical remote session."""
        if self.remote_mode and self.remote_client is not None:
            try:
                self.chat_view.set_status("Stopping…")
                await self.remote_client.interrupt()
            except Exception as exc:
                snack(self.page, str(exc), error=True)
            return
        task = self._active_local_turn
        if task is not None and not task.done():
            task.cancel()

    def reload_settings(self):
        """Reload settings and reinitialize components"""
        self.settings = reload_settings()
        self._setup_page()
        self._initialize_components()
        self._build_ui()


async def main(page: ft.Page):
    """Main entry point"""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    app = HermesMobileApp(page)

    # Handle window events
    async def on_close(e):
        if app.remote_client:
            await app.remote_client.close()
        if app.memory_provider:
            app.memory_provider.close()
        if app.agent and app.agent.memory_provider:
            await app.agent.memory_provider.cleanup_expired()
        if app.gateway_manager:
            await app.gateway_manager.stop()

    async def on_lifecycle(e):
        state = str(getattr(e, "state", "")).lower()
        if "resume" in state and app.remote_mode:
            if app.remote_client is None or app.remote_client.state != "open":
                await app.connect_remote()

    page.on_close = on_close
    page.on_app_lifecycle_state_change = on_lifecycle

    # Keep the app running
    await asyncio.Event().wait()


if __name__ == "__main__":
    ft.run(main, assets_dir="assets")
