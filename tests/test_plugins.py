"""Tests for the plugins system."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import flet as ft
import pytest
import yaml

from hermes_mobile.plugins import (
    AchievementsPlugin,
    BasePlugin,
    KanbanPlugin,
    PluginManifest,
    PluginRegistry,
    SecurityGuidancePlugin,
    get_plugin_registry,
)


class TestPluginManifest:
    def test_creates_with_required_fields(self):
        m = PluginManifest(name="test", kind="tool", version="1.0", description="desc")
        assert m.name == "test"
        assert m.kind == "tool"
        assert m.version == "1.0"
        assert m.description == "desc"

    def test_defaults(self):
        m = PluginManifest(name="x", kind="y", version="0.1", description="z")
        assert m.author == ""
        assert m.homepage == ""
        assert m.license == "MIT"
        assert m.dependencies == []
        assert m.config_schema == {}


class DummyPlugin(BasePlugin):
    """Test plugin for testing BasePlugin."""

    def get_manifest(self):
        return PluginManifest(name="dummy", kind="tool", version="1.0", description="Dummy plugin")

    async def initialize(self):
        return True

    async def shutdown(self):
        pass


class TestBasePlugin:
    def test_abstract_methods(self):
        with pytest.raises(TypeError):
            BasePlugin({})

    def test_default_tools_empty(self):
        plugin = DummyPlugin({"enabled": True})
        assert plugin.get_tools() == []
        assert plugin.get_tool_schemas() == []

    def test_enabled_by_default(self):
        plugin = DummyPlugin({})
        assert plugin.enabled is True

    def test_disabled_via_config(self):
        plugin = DummyPlugin({"enabled": False})
        assert plugin.enabled is False

    def test_get_manifest(self):
        plugin = DummyPlugin({})
        m = plugin.get_manifest()
        assert m.name == "dummy"


class TestPluginRegistry:
    def test_empty_registry(self):
        registry = PluginRegistry()
        assert registry.list_plugins() == []

    def test_get_plugin_nonexistent(self):
        registry = PluginRegistry()
        assert registry.get_plugin("nope") is None
        assert registry.get_manifest("nope") is None

    def test_add_plugin_dir(self, temp_dir):
        registry = PluginRegistry()
        registry.add_plugin_dir(temp_dir)
        assert temp_dir in registry._plugin_dirs

    def test_register_and_get_plugin(self):
        registry = PluginRegistry()
        plugin = DummyPlugin({})
        registry._plugins["dummy"] = plugin
        registry._manifests["dummy"] = plugin.get_manifest()

        assert registry.get_plugin("dummy") is plugin
        assert registry.get_manifest("dummy").name == "dummy"

    def test_list_plugins(self):
        registry = PluginRegistry()
        plugin = DummyPlugin({})
        registry._plugins["dummy"] = plugin
        registry._manifests["dummy"] = plugin.get_manifest()

        plugins = registry.list_plugins()
        assert len(plugins) == 1
        assert plugins[0].name == "dummy"

    def test_get_all_tools(self):
        registry = PluginRegistry()
        plugin = AchievementsPlugin({})
        registry._plugins["achievements"] = plugin

        tools = registry.get_all_tools()
        assert len(tools) == 3
        assert "achievements_list" in tools

    def test_get_all_tool_schemas(self):
        registry = PluginRegistry()
        plugin = AchievementsPlugin({})
        registry._plugins["achievements"] = plugin

        schemas = registry.get_all_tool_schemas()
        assert len(schemas) == 3
        assert schemas[0]["function"]["name"] == "achievements_list"

    async def test_initialize_all(self):
        registry = PluginRegistry()
        plugin = DummyPlugin({})
        registry._plugins["dummy"] = plugin
        await registry.initialize_all()
        assert True  # No crash

    async def test_shutdown_all(self):
        registry = PluginRegistry()
        plugin = DummyPlugin({})
        registry._plugins["dummy"] = plugin
        await registry.shutdown_all()
        assert True  # No crash

    def test_discover_plugins_from_directory(self, temp_dir):
        plugin_dir = temp_dir / "plugins"
        plugin_dir.mkdir()

        pkg_dir = plugin_dir / "my_plugin"
        pkg_dir.mkdir()

        manifest = {
            "name": "my_plugin",
            "kind": "tool",
            "version": "1.0.0",
            "description": "My test plugin",
        }
        (pkg_dir / "plugin.yaml").write_text(yaml.dump(manifest))

        init_code = """
from hermes_mobile.plugins import BasePlugin, PluginManifest
class MyPlugin(BasePlugin):
    def get_manifest(self):
        return PluginManifest(name="my_plugin", kind="tool", version="1.0", description="x")
    async def initialize(self): return True
    async def shutdown(self): pass
"""
        (pkg_dir / "__init__.py").write_text(init_code)

        registry = PluginRegistry()
        registry.config = {"my_plugin": {}}
        registry.add_plugin_dir(plugin_dir)

        loaded = registry.discover_plugins()
        assert len(loaded) > 0
        assert "my_plugin" in loaded

    def test_discover_without_manual_config(self, temp_dir):
        """discover_plugins works out of the box — the registry provides its own
        config dict instead of requiring callers to set `registry.config`."""
        plugin_dir = temp_dir / "plugins"
        plugin_dir.mkdir()

        pkg_dir = plugin_dir / "my_plugin"
        pkg_dir.mkdir()

        manifest = {
            "name": "my_plugin",
            "kind": "tool",
            "version": "1.0.0",
            "description": "My test plugin",
        }
        (pkg_dir / "plugin.yaml").write_text(yaml.dump(manifest))

        init_code = """
from hermes_mobile.plugins import BasePlugin, PluginManifest
class MyPlugin(BasePlugin):
    def get_manifest(self):
        return PluginManifest(name="my_plugin", kind="tool", version="1.0", description="x")
    async def initialize(self): return True
    async def shutdown(self): pass
"""
        (pkg_dir / "__init__.py").write_text(init_code)

        registry = PluginRegistry()
        registry.add_plugin_dir(plugin_dir)

        loaded = registry.discover_plugins()
        assert "my_plugin" in loaded
        assert registry.get_plugin("my_plugin") is not None

    def test_discover_skips_missing_manifest(self, temp_dir):
        plugin_dir = temp_dir / "plugins"
        plugin_dir.mkdir()
        (plugin_dir / "no_manifest").mkdir()

        registry = PluginRegistry()
        registry.add_plugin_dir(plugin_dir)
        loaded = registry.discover_plugins()
        assert loaded == []

    def test_discover_handles_nonexistent_dir(self):
        registry = PluginRegistry()
        registry.add_plugin_dir(Path("/nonexistent"))
        loaded = registry.discover_plugins()
        assert loaded == []

    def test_discover_skips_files_in_dir(self, temp_dir):
        plugin_dir = temp_dir / "plugins"
        plugin_dir.mkdir()
        (plugin_dir / "regular_file.txt").write_text("not a plugin")
        (plugin_dir / "no_init_dir").mkdir()
        manifest = {
            "name": "no_init",
            "kind": "tool",
            "version": "1.0",
            "description": "No init file",
        }
        (plugin_dir / "no_init_dir" / "plugin.yaml").write_text(yaml.dump(manifest))
        registry = PluginRegistry()
        registry.config = {}
        registry.add_plugin_dir(plugin_dir)
        loaded = registry.discover_plugins()
        assert "no_init" not in loaded  # Has plugin.yaml but no __init__.py

    def test_discover_handles_load_error(self, temp_dir):
        plugin_dir = temp_dir / "plugins"
        plugin_dir.mkdir()
        pkg_dir = plugin_dir / "broken"
        pkg_dir.mkdir()
        (pkg_dir / "plugin.yaml").write_text("invalid: yaml: : broken: :")
        (pkg_dir / "__init__.py").write_text("print('hello')")
        registry = PluginRegistry()
        registry.config = {}
        registry.add_plugin_dir(plugin_dir)
        loaded = registry.discover_plugins()
        assert "broken" not in loaded


class TestBuiltinPluginsErrorHandling:
    async def test_initialize_all_error(self):
        class FailingPlugin(BasePlugin):
            def get_manifest(self):
                return PluginManifest(name="fail", kind="tool", version="1", description="Fail")

            async def initialize(self):
                raise RuntimeError("Init failed")

            async def shutdown(self):
                pass

        registry = PluginRegistry()
        registry._plugins["fail"] = FailingPlugin({})
        registry._manifests["fail"] = FailingPlugin({}).get_manifest()
        await registry.initialize_all()
        assert True  # No crash

    async def test_shutdown_all_error(self):
        class FailingPlugin(BasePlugin):
            def get_manifest(self):
                return PluginManifest(name="fail", kind="tool", version="1", description="Fail")

            async def initialize(self):
                return True

            async def shutdown(self):
                raise RuntimeError("Shutdown failed")

        registry = PluginRegistry()
        registry._plugins["fail"] = FailingPlugin({})
        registry._manifests["fail"] = FailingPlugin({}).get_manifest()
        await registry.shutdown_all()
        assert True  # No crash


class TestAchievementsPlugin:
    def test_get_manifest(self):
        plugin = AchievementsPlugin({})
        m = plugin.get_manifest()
        assert m.name == "achievements"
        assert m.kind == "dashboard"

    async def test_initialize(self):
        plugin = AchievementsPlugin({})
        assert await plugin.initialize() is True

    async def test_shutdown(self):
        plugin = AchievementsPlugin({})
        await plugin.shutdown()
        assert True

    def test_get_tools(self):
        plugin = AchievementsPlugin({})
        tools = plugin.get_tools()
        assert "achievements_list" in tools
        assert "achievements_unlock" in tools
        assert len(tools) == 3

    def test_get_tool_schemas(self):
        plugin = AchievementsPlugin({})
        schemas = plugin.get_tool_schemas()
        assert len(schemas) == 3
        names = [s["function"]["name"] for s in schemas]
        assert "achievements_list" in names
        assert "achievements_unlock" in names


class TestKanbanPlugin:
    def test_get_manifest(self):
        plugin = KanbanPlugin({})
        m = plugin.get_manifest()
        assert m.name == "kanban"
        assert m.kind == "dashboard"

    async def test_initialize(self):
        plugin = KanbanPlugin({})
        assert await plugin.initialize() is True

    def test_get_tools(self):
        plugin = KanbanPlugin({})
        tools = plugin.get_tools()
        assert "kanban_show" in tools
        assert "kanban_create" in tools
        assert len(tools) == 12

    def test_get_tool_schemas(self):
        plugin = KanbanPlugin({})
        schemas = plugin.get_tool_schemas()
        assert schemas == []  # Defined in toolsets.py, not here

    async def test_shutdown(self):
        plugin = KanbanPlugin({})
        await plugin.shutdown()


class TestSecurityGuidancePlugin:
    def test_get_manifest(self):
        plugin = SecurityGuidancePlugin({})
        m = plugin.get_manifest()
        assert m.name == "security-guidance"
        assert m.kind == "tool"

    async def test_initialize(self):
        plugin = SecurityGuidancePlugin({})
        assert await plugin.initialize() is True

    def test_get_tools(self):
        plugin = SecurityGuidancePlugin({})
        tools = plugin.get_tools()
        assert len(tools) == 3
        assert "security_scan" in tools

    def test_get_tool_schemas(self):
        plugin = SecurityGuidancePlugin({})
        schemas = plugin.get_tool_schemas()
        assert len(schemas) >= 2
        names = [s["function"]["name"] for s in schemas]
        assert "security_scan" in names
        assert "security_advice" in names

    async def test_shutdown(self):
        plugin = SecurityGuidancePlugin({})
        await plugin.shutdown()


class TestGetPluginRegistry:
    def test_returns_singleton(self):
        registry = get_plugin_registry()
        assert registry is get_plugin_registry()

    def test_registry_runs_discovery(self, monkeypatch):
        """get_plugin_registry must invoke discovery for external plugins."""
        import hermes_mobile.plugins as plugins_mod

        calls = []
        monkeypatch.setattr(
            plugins_mod.PluginRegistry,
            "discover_plugins",
            lambda self: calls.append(1) or [],
        )
        monkeypatch.setattr(plugins_mod, "_plugin_registry", None)

        get_plugin_registry()
        assert calls == [1]

    def test_has_builtin_plugins(self):
        registry = get_plugin_registry()
        assert registry.get_plugin("achievements") is not None
        assert registry.get_plugin("kanban") is not None
        assert registry.get_plugin("security-guidance") is not None

    def test_builtin_manifests(self):
        registry = get_plugin_registry()
        assert registry.get_manifest("achievements").name == "achievements"
        assert registry.get_manifest("kanban").name == "kanban"
        assert registry.get_manifest("security-guidance").name == "security-guidance"


class TestPluginsViewTogglePersistence:
    def _make_view(self):
        from hermes_mobile.ui.plugins_view import PluginsView

        class FakePage:
            platform = ft.PagePlatform.ANDROID
            width = 430
            theme_mode = ft.ThemeMode.DARK

            def __init__(self):
                self.overlay = []
                self.updates = 0

            def update(self):
                self.updates += 1

        class FakeSettings:
            plugin_toggles = {}

        app = SimpleNamespace(
            page=FakePage(),
            settings=FakeSettings(),
            content_area=SimpleNamespace(content=None),
            dark_mode=True,
        )
        return PluginsView(app), app

    def test_toggle_persists_choice(self):
        view, app = self._make_view()
        registry = get_plugin_registry()
        manifest = registry.get_manifest("kanban")
        plugin = registry.get_plugin("kanban")
        plugin.enabled = True

        with patch("hermes_mobile.ui.plugins_view.save_settings") as mock_save:
            view._toggle_plugin(manifest, False)

        assert app.settings.plugin_toggles == {"kanban": False}
        mock_save.assert_called_once()
        assert plugin.enabled is False
        plugin.enabled = True  # restore singleton state for other tests
