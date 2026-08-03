"""Structural regression tests for the mobile shell and flat UI contract."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import flet as ft

from hermes_mobile.core.agent import Message
from hermes_mobile.main import HermesMobileApp
from hermes_mobile.ui.chat_view import ChatView
from hermes_mobile.ui.gateway_view import GatewayView
from hermes_mobile.ui.tools_view import ToolsView


class FakePage:
    height = 844
    width = 430
    platform = ft.PagePlatform.ANDROID
    theme_mode = ft.ThemeMode.DARK
    on_resize = None

    def __init__(self):
        self.updates = 0
        self.clean_calls = 0
        self.controls = []

    def update(self):
        self.updates += 1

    def clean(self):
        self.clean_calls += 1
        self.controls.clear()

    def add(self, *controls):
        self.controls.extend(controls)


class FakeAgent:
    def __init__(self):
        self.messages = ["stale"]
        self.tools = []
        self.clears = 0

    def clear_conversation(self):
        self.messages = []
        self.clears += 1

    def set_tools(self, tools):
        self.tools = tools


def fake_app():
    page = FakePage()
    agent = FakeAgent()
    settings = SimpleNamespace(
        default_model="openai/gpt-test",
        default_provider="openai",
        openrouter_api_key="",
        openai_api_key="configured",
        anthropic_api_key="",
        gemini_api_key="",
    )
    app = SimpleNamespace(
        page=page,
        agent=agent,
        settings=settings,
        dark_mode=True,
        destinations=[],
    )
    app._navigate_to = lambda destination: app.destinations.append(destination)
    return app


def walk_controls(control: ft.Control):
    """Walk Flet's dataclass graph without depending on private serializers."""
    seen: set[int] = set()
    stack = [control]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        fields = getattr(type(current), "__dataclass_fields__", {})
        for name in fields:
            try:
                value = getattr(current, name)
            except Exception:
                continue
            if isinstance(value, ft.Control):
                stack.append(value)
            elif isinstance(value, (list, tuple)):
                stack.extend(item for item in value if isinstance(item, ft.Control))


def test_chat_has_single_shell_header_and_desktop_derived_composer():
    app = fake_app()
    view = ChatView(app)

    root = view.build()

    assert isinstance(root, ft.Column)
    assert len(root.controls) == 2  # transcript + composer; app shell owns header
    all_controls = list(walk_controls(root))
    assert not any(isinstance(control, ft.Card) for control in all_controls)
    assert any(
        isinstance(control, ft.Image) and control.src == "nous-girl.jpg" for control in all_controls
    )
    assert view.send_button.bgcolor == "#FFE6CB"


def test_remote_composer_shows_backend_state_and_remote_destinations():
    app = fake_app()
    app.remote_mode = True
    app.remote_model = "openai/gpt-5.6-sol"
    app.remote_client = SimpleNamespace(state="open")
    app.show_remote_sessions = lambda: None
    root = ChatView(app).build()

    texts = [
        control.value
        for control in walk_controls(root)
        if isinstance(control, ft.Text) and control.value
    ]
    assert "gpt-5.6-sol" in texts
    assert "Hermes Remote" not in texts
    assert "Connected to Hermes Remote. Send a message to start." in texts
    assert "Go to Settings > API Key to configure." not in texts

    app.remote_client.state = "closed"
    view = ChatView(app)
    view.build()
    app.remote_client.state = "open"
    view.refresh_welcome()
    refreshed = [
        control.value
        for control in walk_controls(view.chat_list)
        if isinstance(control, ft.Text) and control.value
    ]
    assert "Connected to Hermes Remote. Send a message to start." in refreshed
    assert "Hermes Remote is offline. Open Connections to reconnect." not in refreshed

    view.add_user_message("First turn")
    after_first_turn = [
        control.value
        for control in walk_controls(view.chat_list)
        if isinstance(control, ft.Text) and control.value
    ]
    assert "First turn" in after_first_turn
    assert "Connected to Hermes Remote. Send a message to start." not in after_first_turn


def test_connections_surface_separates_remote_from_messaging_gateway():
    app = fake_app()
    app.remote_mode = True
    app.remote_model = ""
    app.remote_client = SimpleNamespace(state="open")
    app.remote_status = SimpleNamespace(version="0.19.1")
    app.remote_secret_store = SimpleNamespace(load=lambda: {}, save=lambda **kwargs: None)
    app.settings.runtime_mode = "remote"
    app.settings.remote_url = "http://100.98.210.62:9119"
    app.settings.remote_auth_mode = "basic"
    app.settings.remote_username = "joao"
    app.settings.remote_profile = ""
    app.settings.remote_allow_insecure = False
    app.settings.save = lambda: None
    app.gateway_manager = SimpleNamespace(
        _running=False,
        config=SimpleNamespace(
            enabled=False,
            port=8080,
            platforms={},
            pairing_enabled=True,
        ),
    )
    root = GatewayView(app).build()

    texts = [
        str(control.value)
        for control in walk_controls(root)
        if isinstance(control, ft.Text) and control.value
    ]
    assert "HERMES REMOTE" in texts
    assert "MESSAGING GATEWAY" in texts
    assert "Hermes 0.19.1" in texts
    assert not any(isinstance(control, ft.Card) for control in walk_controls(root))
    assert not any(isinstance(control, ft.ElevatedButton) for control in walk_controls(root))


def test_new_session_clears_ui_and_agent_synchronously():
    app = fake_app()
    view = ChatView(app)
    view.build()
    view.messages.append(Message.user("stale"))
    view.chat_list.controls.append(ft.Text("stale"))

    view.clear_chat()

    assert view.messages == []
    assert app.agent.messages == []
    assert app.agent.clears == 1
    assert len(view.chat_list.controls) == 1  # fresh branded welcome state


def test_busy_state_prevents_duplicate_turns_and_recovers():
    app = fake_app()
    view = ChatView(app)

    view.set_busy(True)
    assert view.input_field.disabled is True
    # Match Desktop: the composer is locked but the send affordance stays
    # available as an explicit interrupt button.
    assert view.send_button.disabled is False
    assert view.send_button.icon == ft.Icons.STOP_ROUNDED

    view.set_busy(False)
    assert view.input_field.disabled is False
    assert view.send_button.disabled is False
    assert view.send_button.icon == ft.Icons.ARROW_UPWARD


def test_tools_surface_uses_flat_rows_not_material_cards():
    app = fake_app()
    root = ToolsView(app).build()

    assert not any(isinstance(control, ft.Card) for control in walk_controls(root))


def test_switch_view_builds_only_requested_surface():
    app = cast(Any, HermesMobileApp.__new__(HermesMobileApp))
    calls: list[str] = []

    def view(name: str):
        return SimpleNamespace(build=lambda: calls.append(name) or ft.Text(name))

    app.chat_view = view("chat")
    app.tools_view = view("tools")
    app.memory_view = view("memory")
    app.skills_view = view("skills")
    app.gateway_view = view("gateway")
    app.artifacts_view = view("artifacts")
    app.cron_view = view("cron")
    app.plugins_view = view("plugins")
    app.terminal_view = view("terminal")
    app.kanban_view = view("kanban")
    app.settings_view = view("settings")
    app.content_area = SimpleNamespace(content=None)
    app.page = FakePage()
    app._update_app_bar_title = lambda name: None

    app._switch_view("tools")

    assert calls == ["tools"]
    assert isinstance(app.content_area.content, ft.Text)


def test_operational_destination_is_reachable_outside_bottom_bar():
    app = cast(Any, HermesMobileApp.__new__(HermesMobileApp))
    app._views = list(HermesMobileApp.MOBILE_VIEWS)
    app.page = FakePage()
    app.nav = SimpleNamespace(selected_index=0)
    switched: list[str] = []
    app._switch_view = switched.append

    app._navigate_to("terminal")

    assert switched == ["terminal"]
    assert app.nav.selected_index == 0


def test_android_enum_selects_mobile_shell():
    app = cast(Any, HermesMobileApp.__new__(HermesMobileApp))
    app.page = FakePage()
    app.settings = SimpleNamespace(theme="system")

    app._setup_page()

    assert app.is_mobile is True
    assert app.page.on_resize == app._on_page_resize


def test_resize_crossing_breakpoint_rebuilds_shell_and_preserves_view():
    app = cast(Any, HermesMobileApp.__new__(HermesMobileApp))
    app.page = FakePage()
    app.page.platform = ft.PagePlatform.LINUX
    app.is_mobile = False
    app.chat_view = object()
    app.current_view = "tools"
    rebuilt: list[bool] = []
    switched: list[str] = []
    app._build_ui = lambda: rebuilt.append(app.is_mobile)
    app._switch_view = switched.append
    event = SimpleNamespace(width=430)

    app._on_page_resize(event)

    assert app.is_mobile is True
    assert rebuilt == [True]
    assert switched == ["tools"]
    assert app.page.clean_calls == 1
    assert app.page.updates == 1
