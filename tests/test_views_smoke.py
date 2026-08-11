"""Smoke test: every Flet view builds without raising.

This is the integration gate the per-view tests don't cover: each view is
constructed and built with a realistic fake app, exactly the path
``HermesMobileApp._switch_view`` exercises at runtime.
"""

from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pytest

from hermes_mobile.config.settings import HermesMobileSettings
from hermes_mobile.core.agent import Message
from hermes_mobile.memory.provider import MobileMemoryProvider
from hermes_mobile.skills.manager import MobileSkillManager
from hermes_mobile.ui.artifacts_view import ArtifactsView
from hermes_mobile.ui.chat_view import ChatView
from hermes_mobile.ui.cron_view import CronView
from hermes_mobile.ui.gateway_view import GatewayView
from hermes_mobile.ui.kanban_view import KanbanView
from hermes_mobile.ui.memory_view import MemoryView
from hermes_mobile.ui.plugins_view import PluginsView
from hermes_mobile.ui.sessions_view import SessionsView
from hermes_mobile.ui.settings_view import SettingsView
from hermes_mobile.ui.skills_view import SkillsView
from hermes_mobile.ui.terminal_view import TerminalView
from hermes_mobile.ui.tools_view import ToolsView


class FakePage:
    width = 430
    height = 844
    theme_mode = ft.ThemeMode.LIGHT

    def __init__(self):
        self.overlay = []
        self.dialogs = []

    def update(self):
        pass

    def show_dialog(self, dialog):
        self.dialogs.append(dialog)


class FakeAgent:
    def __init__(self):
        self.messages = [Message.user("hi")]
        self.tools = []
        self.model = "openai/gpt-test"
        self._workspace = None

    def clear_conversation(self):
        self.messages = []

    def set_tools(self, tools):
        self.tools = tools


class FakeGatewayManager:
    config = SimpleNamespace(enabled=False, port=8080, platforms=[], pairing_enabled=True)
    _running = False

    async def start(self):
        pass

    async def stop(self):
        pass


@pytest.fixture
def app(tmp_path):
    settings = HermesMobileSettings(data_dir=str(tmp_path))
    settings.runtime_mode = "local"
    page = FakePage()
    return SimpleNamespace(
        page=page,
        settings=settings,
        dark_mode=False,
        agent=FakeAgent(),
        skill_manager=MobileSkillManager(skills_dir=tmp_path / "skills"),
        memory_provider=MobileMemoryProvider(db_path=tmp_path / "memory.db", encrypt=False),
        gateway_manager=FakeGatewayManager(),
        remote_client=None,
        remote_status=None,
        remote_secret_store=SimpleNamespace(load=lambda: {}),
        remote_model="",
        remote_mode=False,
        content_area=SimpleNamespace(content=None),
        current_view="chat",
        current_session_title="New session",
    )


VIEWS = (
    ("chat", ChatView),
    ("settings", SettingsView),
    ("skills", SkillsView),
    ("memory", MemoryView),
    ("cron", CronView),
    ("gateway", GatewayView),
    ("plugins", PluginsView),
    ("tools", ToolsView),
    ("terminal", TerminalView),
    ("kanban", KanbanView),
    ("sessions", SessionsView),
    ("artifacts", ArtifactsView),
)


@pytest.mark.parametrize("name,view_cls", VIEWS, ids=[name for name, _ in VIEWS])
def test_view_builds_without_error(app, name, view_cls):
    view = view_cls(app)
    root = view.build()
    assert isinstance(root, ft.Control), f"{name}.build() returned {type(root).__name__}"


def test_switch_view_builds_every_destination(app):
    """Mirror HermesMobileApp._switch_view wiring for the primary destinations."""
    from hermes_mobile.main import HermesMobileApp

    hermes = HermesMobileApp.__new__(HermesMobileApp)
    hermes.page = app.page
    hermes.settings = app.settings
    hermes.agent = app.agent
    hermes.skill_manager = app.skill_manager
    hermes.memory_provider = app.memory_provider
    hermes.gateway_manager = app.gateway_manager
    hermes.remote_client = None
    hermes.remote_status = None
    hermes.remote_secret_store = app.remote_secret_store
    hermes.remote_model = ""
    hermes.is_mobile = False  # desktop shell: _update_app_bar_title returns early
    hermes.current_view = "chat"
    hermes.content_area = SimpleNamespace(content=None)

    # Wire every view instance like HermesMobileApp._initialize_components.
    hermes.chat_view = ChatView(hermes)
    hermes.settings_view = SettingsView(hermes)
    hermes.skills_view = SkillsView(hermes)
    hermes.memory_view = MemoryView(hermes)
    hermes.cron_view = CronView(hermes)
    hermes.gateway_view = GatewayView(hermes)
    hermes.plugins_view = PluginsView(hermes)
    hermes.tools_view = ToolsView(hermes)
    hermes.terminal_view = TerminalView(hermes)
    hermes.kanban_view = KanbanView(hermes)
    hermes.sessions_view = SessionsView(hermes)
    hermes.artifacts_view = ArtifactsView(hermes)

    for view_name in (
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
    ):
        hermes._switch_view(view_name)
        assert hermes.content_area.content is not None, f"{view_name} produced no content"
