"""Tests for the Tools view: on/off toggles and dead-tool filtering.

Desktop-only schemas (x_search, browser_scroll, ...) are advertised in the
toolsets taxonomy but have no handler in this mobile build. Enabling such a
toolset must never add those schemas to the model's tool list, and the view
must show the real active state per toolset.
"""

from types import SimpleNamespace
from unittest.mock import patch

import flet as ft

from hermes_mobile.ui.tools_view import ToolsView


class FakePage:
    platform = ft.PagePlatform.ANDROID
    width = 430
    theme_mode = ft.ThemeMode.DARK

    def __init__(self):
        self.updates = 0
        self.overlay = []

    def update(self):
        self.updates += 1


class FakeAgent:
    def __init__(self, builtins):
        self._builtin_tools = dict(builtins)
        self.tools = []
        self.skill_manager = None

    def set_tools(self, tools):
        self.tools = list(tools)


def make_view(builtins):
    app = SimpleNamespace(
        page=FakePage(),
        agent=FakeAgent(builtins),
        dark_mode=True,
        content_area=SimpleNamespace(content=None),
    )
    return ToolsView(app), app


def walk(control):
    yield control
    content = getattr(control, "content", None)
    if content is not None and not isinstance(content, str):
        yield from walk(content)
    for child in getattr(control, "controls", []) or []:
        yield from walk(child)


def texts(control):
    values = []
    for item in walk(control):
        for attr in ("value", "text", "label", "content", "tooltip"):
            value = getattr(item, attr, None)
            if isinstance(value, str):
                values.append(value)
    return values


class TestDeadToolFiltering:
    def test_enabling_x_search_toolset_adds_nothing(self):
        """x_search has no handler: enabling its toolset must not advertise it."""
        view, app = make_view(builtins={"web_search": None, "read_file": None})

        view._toggle_toolset("x_search", True)

        assert app.agent.tools == []
        # A snack still informs the user nothing was added.
        assert len(app.page.overlay) == 1

    def test_enabling_web_toolset_adds_only_implemented_tools(self):
        view, app = make_view(builtins={"web_search": None, "read_file": None})

        view._toggle_toolset("web", True)

        names = {t["function"]["name"] for t in app.agent.tools}
        # Only web_search has a handler in this fake; web_extract is filtered out.
        assert names == {"web_search"}

    def test_toggle_off_removes_only_that_toolsets_tools(self):
        view, app = make_view(builtins={"web_search": None, "read_file": None, "write_file": None})
        # Start with the agent's full built-in tool list advertised.
        app.agent.tools = [
            {"type": "function", "function": {"name": "web_search"}},
            {"type": "function", "function": {"name": "read_file"}},
            {"type": "function", "function": {"name": "write_file"}},
        ]

        view._toggle_toolset("web", False)

        names = {t["function"]["name"] for t in app.agent.tools}
        assert "web_search" not in names
        assert "read_file" in names
        assert "write_file" in names


class TestPersistedToggles:
    def test_apply_persisted_disables_saved_toolsets(self):
        view, app = make_view(builtins={"web_search": None, "read_file": None, "write_file": None})
        app.agent.tools = [
            {"type": "function", "function": {"name": "web_search"}},
            {"type": "function", "function": {"name": "read_file"}},
        ]
        app.settings = SimpleNamespace(toolset_toggles={"web": False})

        view.apply_persisted()

        names = {t["function"]["name"] for t in app.agent.tools}
        assert "web_search" not in names
        assert "read_file" in names

    def test_toggle_persists_choice(self):
        view, app = make_view(builtins={"web_search": None})
        app.settings = SimpleNamespace(toolset_toggles={})

        with patch("hermes_mobile.ui.tools_view.save_settings") as mock_save:
            view._toggle_toolset("web", False)

        assert app.settings.toolset_toggles == {"web": False}
        mock_save.assert_called_once()


class TestToolsetCardState:
    def test_x_search_card_shows_zero_available_and_switch_off(self):
        view, _ = make_view(builtins={"web_search": None})

        root = view.build()
        all_texts = texts(root)
        assert any("0/1" in value for value in all_texts)

        switches = [item for item in walk(root) if isinstance(item, ft.Switch)]
        assert switches
        assert all(not switch.value for switch in switches)

    def test_enabled_toolset_shows_switch_on(self):
        view, app = make_view(builtins={"web_search": None, "read_file": None, "write_file": None})
        # Simulate the startup state: built-ins are already advertised.
        app.agent.tools = [
            {"type": "function", "function": {"name": "web_search"}},
            {"type": "function", "function": {"name": "web_extract"}},
            {"type": "function", "function": {"name": "read_file"}},
            {"type": "function", "function": {"name": "write_file"}},
        ]

        root = view.build()
        switches = [item for item in walk(root) if isinstance(item, ft.Switch)]
        assert switches
        assert any(switch.value for switch in switches)
