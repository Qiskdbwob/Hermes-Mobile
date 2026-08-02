"""Hermes Mobile - Main Flet Application"""

import asyncio
import logging
import os

import flet as ft

from hermes_mobile.locales import t
from hermes_mobile.config.settings import get_settings, reload_settings
from hermes_mobile.core.agent import Message, MobileAgent, ToolCall, create_mobile_agent
from hermes_mobile.cron.scheduler import (
    ensure_default_jobs,
)
from hermes_mobile.gateway.mobile_gateway import (
    GatewayConfig,
    GatewayManager,
)
from hermes_mobile.memory.provider import MobileMemoryProvider
from hermes_mobile.plugins import get_plugin_registry
from hermes_mobile.skills.manager import MobileSkillManager
from hermes_mobile.ui.chat_view import ChatView
from hermes_mobile.ui.cron_view import CronView
from hermes_mobile.ui.gateway_view import GatewayView
from hermes_mobile.ui.memory_view import MemoryView
from hermes_mobile.ui.plugins_view import PluginsView
from hermes_mobile.ui.settings_view import SettingsView
from hermes_mobile.ui.skills_view import SkillsView
from hermes_mobile.ui.tools_view import ToolsView
from hermes_mobile.ui.theme import build_theme, mode_colors

logger = logging.getLogger(__name__)


class HermesMobileApp:
    """Main Hermes Mobile Application"""

    # Mobile bottom navigation: the five primary destinations. The remaining
    # views (cron, gateway, plugins) live behind the overflow menu.
    MOBILE_VIEWS = ["chat", "tools", "memory", "skills", "settings"]
    DESKTOP_VIEWS = [
        "chat",
        "tools",
        "memory",
        "skills",
        "cron",
        "gateway",
        "plugins",
        "settings",
    ]
    OVERFLOW_VIEWS = ["cron", "gateway", "plugins"]

    def __init__(self, page: ft.Page):
        self.page = page
        self.error_message = None
        self.settings = None
        self.agent: MobileAgent = None
        self.memory_provider: MobileMemoryProvider = None
        self.skill_manager: MobileSkillManager = None
        self.gateway_manager: GatewayManager = None
        self.plugin_registry = None

        # UI Components
        self.chat_view: ChatView = None
        self.settings_view: SettingsView = None
        self.skills_view: SkillsView = None
        self.memory_view: MemoryView = None
        self.cron_view: CronView = None
        self.gateway_view: GatewayView = None
        self.plugins_view: PluginsView = None
        self.tools_view: ToolsView = None

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

    def _setup_page(self):
        """Configure the Flet page"""
        self.page.title = "Hermes Mobile"
        self.page.padding = 0
        self.page.spacing = 0
        platform_str = str(getattr(self.page, "platform", ""))
        self.is_mobile = platform_str.lower() in ("android", "ios")
        # Allow forcing the mobile layout for desktop testing
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
        if theme_setting == "dark":
            self.page.theme_mode = ft.ThemeMode.DARK
        elif theme_setting == "light":
            self.page.theme_mode = ft.ThemeMode.LIGHT
        else:
            self.page.theme_mode = ft.ThemeMode.SYSTEM

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
        self.chat_view = ChatView(self)
        self.settings_view = SettingsView(self)
        self.skills_view = SkillsView(self)
        self.memory_view = MemoryView(self)
        self.cron_view = CronView(self)
        self.gateway_view = GatewayView(self)
        self.plugins_view = PluginsView(self)
        self.tools_view = ToolsView(self)

        # Ensure default cron jobs exist
        ensure_default_jobs()

    def _build_ui(self):
        """Build the main UI"""
        self._views = list(self.MOBILE_VIEWS if self.is_mobile else self.DESKTOP_VIEWS)

        def nav_dest(cls, view: str):
            specs = {
                "chat": (ft.Icons.CHAT_OUTLINED, ft.Icons.CHAT, t("nav.chat")),
                "tools": (ft.Icons.BUILD_OUTLINED, ft.Icons.BUILD, t("nav.tools")),
                "memory": (
                    ft.Icons.PSYCHOLOGY_OUTLINED,
                    ft.Icons.PSYCHOLOGY,
                    t("nav.memory"),
                ),
                "skills": (
                    ft.Icons.EXTENSION_OUTLINED,
                    ft.Icons.EXTENSION,
                    t("nav.skills"),
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
        )

        # Brand header (mobile)
        self.app_bar = self._build_app_bar()

        if self.is_mobile:
            self.nav = ft.NavigationBar(
                selected_index=0,
                destinations=bar_destinations,
                on_change=self._on_navigation_change,
                height=64,
            )
            self.page.add(
                ft.Column(
                    [
                        self.app_bar,
                        ft.Container(self.content_area, expand=True),
                        self.nav,
                    ],
                    expand=True,
                    spacing=0,
                )
            )
        else:
            self.nav = ft.NavigationRail(
                selected_index=0,
                label_type=ft.NavigationRailLabelType.ALL,
                min_width=110,
                min_extended_width=190,
                leading=ft.Container(
                    content=ft.Icon(ft.Icons.AUTO_AWESOME, size=28, color=ft.Colors.PRIMARY),
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
        """Build the brand header shown on mobile."""
        c = mode_colors(self.dark_mode)

        self._gateway_indicator = ft.Container(
            width=8,
            height=8,
            border_radius=4,
            bgcolor=c["muted_foreground"],
            tooltip=t("gateway.offline") if hasattr(t, "gateway") else "Gateway",
        )

        overflow_menu = ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT,
            tooltip=t("nav.more"),
            items=[
                ft.PopupMenuItem(
                    icon=ft.Icons.SCHEDULE,
                    content=t("nav.cron"),
                    on_click=lambda e: self._navigate_to("cron"),
                ),
                ft.PopupMenuItem(
                    icon=ft.Icons.HUB,
                    content=t("nav.gateway"),
                    on_click=lambda e: self._navigate_to("gateway"),
                ),
                ft.PopupMenuItem(
                    icon=ft.Icons.EXTENSION,
                    content=t("nav.plugins"),
                    on_click=lambda e: self._navigate_to("plugins"),
                ),
                ft.PopupMenuItem(
                    icon=ft.Icons.SETTINGS,
                    content=t("nav.settings"),
                    on_click=lambda e: self._navigate_to("settings"),
                ),
            ],
        )

        self._app_bar_title = ft.Text(
            "Hermes Mobile",
            size=17,
            weight=ft.FontWeight.W_700,
            color=c["foreground"],
        )
        self._app_bar_subtitle = ft.Text(
            "",
            size=11,
            color=c["muted_foreground"],
            visible=False,
        )

        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.AUTO_AWESOME, size=22, color=ft.Colors.PRIMARY),
                    ft.Column(
                        [self._app_bar_title, self._app_bar_subtitle],
                        spacing=0,
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                    ft.Container(expand=True),
                    self._gateway_indicator,
                    ft.Container(width=4),
                    overflow_menu,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.only(left=16, right=8, top=10, bottom=10),
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
                    ft.ElevatedButton(
                        "Retry",
                        icon=ft.Icons.REFRESH,
                        on_click=lambda e: self.page.window.close(),
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                expand=True,
            )
        )
        self.page.update()

    def _navigate_to(self, view: str):
        """Navigate to a view by name (used by overflow menu)."""
        if view not in self._views:
            return
        index = self._views.index(view)
        self._switch_view(view)
        if self.nav is not None:
            try:
                self.nav.selected_index = index
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
        """Switch the content area to the given view (preserves state)."""
        self.current_view = view

        view_map = {
            "chat": self.chat_view.build(),
            "tools": self.tools_view.build(),
            "memory": self.memory_view.build(),
            "skills": self.skills_view.build(),
            "cron": self.cron_view.build(),
            "gateway": self.gateway_view.build(),
            "plugins": self.plugins_view.build(),
            "settings": self.settings_view.build(),
        }

        new_content = view_map.get(view)
        if new_content is not None and self.content_area is not None:
            self.content_area.content = new_content
            self._update_app_bar_title(view)
            self.page.update()

    def _update_app_bar_title(self, view: str):
        """Update the mobile header title for the active view."""
        if self.is_mobile and hasattr(self, "_app_bar_title"):
            titles = {
                "chat": "Hermes Mobile",
                "tools": t("nav.tools"),
                "memory": t("nav.memory"),
                "skills": t("nav.skills"),
                "cron": t("nav.cron"),
                "gateway": t("nav.gateway"),
                "plugins": t("nav.plugins"),
                "settings": t("nav.settings"),
            }
            self._app_bar_title.value = titles.get(view, "Hermes Mobile")
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

    async def send_message(self, text: str):
        """Send a message to the agent"""
        if not text.strip():
            return

        # Add user message to chat view
        self.chat_view.add_user_message(text)

        # Run agent conversation
        async for chunk in self.agent.run_conversation(text, stream=True):
            self.chat_view.append_assistant_message(chunk)

        self.chat_view.finalize_assistant_message()

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
        if app.memory_provider:
            app.memory_provider.close()
        if app.agent and app.agent.memory_provider:
            await app.agent.memory_provider.cleanup_expired()
        if app.gateway_manager:
            await app.gateway_manager.stop()

    page.on_close = on_close

    # Keep the app running
    await asyncio.Event().wait()


if __name__ == "__main__":
    ft.app(target=main, assets_dir="assets")
