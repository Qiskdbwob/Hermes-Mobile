"""Hermes Mobile - Main Flet Application"""

import asyncio
import logging

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


logger = logging.getLogger(__name__)


class HermesMobileApp:
    """Main Hermes Mobile Application"""

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

        self._setup_page()
        try:
            self.settings = get_settings()
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
        self.page.theme_mode = ft.ThemeMode.SYSTEM
        self.page.padding = 0
        self.page.spacing = 0
        platform_str = str(getattr(self.page, "platform", ""))
        self.is_mobile = platform_str.lower() in ("android", "ios")

        if not self.is_mobile:
            self.page.window_width = 480
            self.page.window_height = 860

        # Set up theme
        self.page.theme = ft.Theme(
            color_scheme_seed=ft.Colors.BLUE,
            use_material3=True,
        )

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
        nav_destinations = [
            ft.NavigationBarDestination(
                icon=ft.Icons.CHAT_OUTLINED, selected_icon=ft.Icons.CHAT, label=t("nav.chat")
            ),
            ft.NavigationBarDestination(
                icon=ft.Icons.BUILD_OUTLINED, selected_icon=ft.Icons.BUILD, label=t("nav.tools")
            ),
            ft.NavigationBarDestination(
                icon=ft.Icons.PSYCHOLOGY_OUTLINED,
                selected_icon=ft.Icons.PSYCHOLOGY,
                label=t("nav.memory"),
            ),
            ft.NavigationBarDestination(
                icon=ft.Icons.EXTENSION_OUTLINED,
                selected_icon=ft.Icons.EXTENSION,
                label=t("nav.skills"),
            ),
            ft.NavigationBarDestination(
                icon=ft.Icons.SCHEDULE_OUTLINED,
                selected_icon=ft.Icons.SCHEDULE,
                label=t("nav.cron"),
            ),
            ft.NavigationBarDestination(
                icon=ft.Icons.HUB_OUTLINED, selected_icon=ft.Icons.HUB, label=t("nav.gateway")
            ),
            ft.NavigationBarDestination(
                icon=ft.Icons.EXTENSION_OUTLINED,
                selected_icon=ft.Icons.EXTENSION,
                label=t("nav.plugins"),
            ),
            ft.NavigationBarDestination(
                icon=ft.Icons.SETTINGS_OUTLINED,
                selected_icon=ft.Icons.SETTINGS,
                label=t("nav.settings"),
            ),
        ]

        # Content area
        self.content_area = ft.Container(
            content=self.chat_view.build(),
            expand=True,
            padding=0,
        )

        if self.is_mobile:
            self.nav = ft.NavigationBar(
                selected_index=0,
                destinations=nav_destinations[:5],
                on_change=self._on_navigation_change,
            )
            self.page.add(
                ft.Column(
                    [self.content_area, self.nav],
                    expand=True,
                    spacing=0,
                )
            )
        else:
            self.nav = ft.NavigationRail(
                selected_index=0,
                label_type=ft.NavigationRailLabelType.ALL,
                min_width=100,
                min_extended_width=200,
                leading=ft.Icon(ft.Icons.AUTO_AWESOME, size=32, color=ft.Colors.PRIMARY),
                group_alignment=-0.9,
                destinations=nav_destinations,
                on_change=self._on_navigation_change,
            )
            self.page.add(
                ft.Row(
                    [self.nav, ft.VerticalDivider(width=1), self.content_area],
                    expand=True,
                )
            )

    def _show_error_screen(self):
        """Show error screen if initialization fails"""
        self.page.clean()
        self.page.add(
            ft.Column(
                [
                    ft.Container(height=40),
                    ft.Icon(ft.Icons.ERROR_OUTLINE, size=64, color=ft.Colors.RED_400),
                    ft.Container(height=20),
                    ft.Text("Hermes Mobile - Error", size=24, weight=ft.FontWeight.BOLD),
                    ft.Container(height=10),
                    ft.Text(
                        self.error_message or "Unknown error during initialization",
                        size=14,
                        color=ft.Colors.GREY_600,
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

    def _on_navigation_change(self, e):
        """Handle navigation change"""
        index = e.control.selected_index
        if self.is_mobile:
            views = ["chat", "tools", "memory", "skills", "settings"]
        else:
            views = ["chat", "tools", "memory", "skills", "cron", "gateway", "plugins", "settings"]
        self.current_view = views[index]

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

        self.content_area.content = view_map.get(self.current_view, self.chat_view.build())
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
