"""Plugins System - Achievements, Kanban, Security, and more"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from hermes_mobile.config.settings import get_settings

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Plugin Base Classes
# ═══════════════════════════════════════════════════════════════


@dataclass
class PluginManifest:
    name: str
    kind: str  # model-provider, dashboard, tool, skill, etc.
    version: str
    description: str
    author: str = ""
    homepage: str = ""
    license: str = "MIT"
    dependencies: List[str] = field(default_factory=list)
    config_schema: Dict[str, Any] = field(default_factory=dict)


class BasePlugin(ABC):
    """Base class for all plugins."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.enabled = config.get("enabled", True)

    @abstractmethod
    def get_manifest(self) -> PluginManifest:
        """Return plugin manifest."""

    @abstractmethod
    async def initialize(self) -> bool:
        """Initialize plugin. Return True if successful."""

    @abstractmethod
    async def shutdown(self):
        """Shutdown plugin."""

    def get_tools(self) -> List[str]:
        """Return list of tool names this plugin provides."""
        return []

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Return OpenAI function schemas for tools."""
        return []


# ═══════════════════════════════════════════════════════════════
# Plugin Registry
# ═══════════════════════════════════════════════════════════════


class PluginRegistry:
    """Registry for managing plugins."""

    def __init__(self):
        self._plugins: Dict[str, BasePlugin] = {}
        self._manifests: Dict[str, PluginManifest] = {}
        self._plugin_dirs: List[Path] = []

    def add_plugin_dir(self, path: Path):
        """Add a directory to search for plugins."""
        if path not in self._plugin_dirs:
            self._plugin_dirs.append(path)

    def discover_plugins(self) -> List[str]:
        """Discover and load all plugins from plugin directories."""
        loaded = []

        for plugin_dir in self._plugin_dirs:
            if not plugin_dir.exists():
                continue

            for item in plugin_dir.iterdir():
                if not item.is_dir():
                    continue

                manifest_file = item / "plugin.yaml"
                if not manifest_file.exists():
                    continue

                try:
                    import yaml

                    manifest_data = yaml.safe_load(manifest_file.read_text())
                    manifest = PluginManifest(**manifest_data)

                    # Load plugin module
                    init_file = item / "__init__.py"
                    if init_file.exists():
                        import importlib.util

                        spec = importlib.util.spec_from_file_location(
                            f"plugin_{manifest.name}", init_file
                        )
                        if spec and spec.loader:
                            module = importlib.util.module_from_spec(spec)
                            spec.loader.exec_module(module)

                            # Look for plugin class
                            for attr_name in dir(module):
                                attr = getattr(module, attr_name)
                                if (
                                    isinstance(attr, type)
                                    and issubclass(attr, BasePlugin)
                                    and attr is not BasePlugin
                                ):
                                    plugin = attr(self.config.get(manifest.name, {}))
                                    if plugin.enabled:
                                        self._plugins[manifest.name] = plugin
                                        self._manifests[manifest.name] = manifest
                                        loaded.append(manifest.name)
                                    break

                except Exception as e:
                    logger.warning(f"Failed to load plugin {item.name}: {e}")

        return loaded

    def get_plugin(self, name: str) -> Optional[BasePlugin]:
        return self._plugins.get(name)

    def get_manifest(self, name: str) -> Optional[PluginManifest]:
        return self._manifests.get(name)

    def list_plugins(self) -> List[PluginManifest]:
        return list(self._manifests.values())

    def get_all_tools(self) -> List[str]:
        tools = []
        for plugin in self._plugins.values():
            tools.extend(plugin.get_tools())
        return tools

    def get_all_tool_schemas(self) -> List[Dict[str, Any]]:
        schemas = []
        for plugin in self._plugins.values():
            schemas.extend(plugin.get_tool_schemas())
        return schemas

    async def initialize_all(self):
        for plugin in self._plugins.values():
            try:
                await plugin.initialize()
            except Exception as e:
                logger.error(f"Failed to initialize plugin {plugin}: {e}")

    async def shutdown_all(self):
        for plugin in self._plugins.values():
            try:
                await plugin.shutdown()
            except Exception as e:
                logger.error(f"Error shutting down plugin {plugin}: {e}")


# ═══════════════════════════════════════════════════════════════
# Built-in Plugins
# ═══════════════════════════════════════════════════════════════


class AchievementsPlugin(BasePlugin):
    """Achievements system for gamification."""

    def get_manifest(self) -> PluginManifest:
        return PluginManifest(
            name="achievements",
            kind="dashboard",
            version="1.0.0",
            description="Achievement tracking and gamification",
            author="Hermes Mobile Team",
        )

    async def initialize(self) -> bool:
        logger.info("Achievements plugin initialized")
        return True

    async def shutdown(self):
        pass

    def get_tools(self) -> List[str]:
        return ["achievements_list", "achievements_unlock", "achievements_progress"]

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "achievements_list",
                    "description": "List all achievements and progress",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "achievements_unlock",
                    "description": "Unlock an achievement",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "achievement_id": {"type": "string", "description": "Achievement ID"},
                        },
                        "required": ["achievement_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "achievements_progress",
                    "description": "Get progress for an achievement",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "achievement_id": {"type": "string", "description": "Achievement ID"},
                        },
                        "required": ["achievement_id"],
                    },
                },
            },
        ]


class KanbanPlugin(BasePlugin):
    """Kanban board for task management."""

    def get_manifest(self) -> PluginManifest:
        return PluginManifest(
            name="kanban",
            kind="dashboard",
            version="1.0.0",
            description="Kanban board for multi-agent coordination",
            author="Hermes Mobile Team",
        )

    async def initialize(self) -> bool:
        logger.info("Kanban plugin initialized")
        return True

    async def shutdown(self):
        pass

    def get_tools(self) -> List[str]:
        return [
            "kanban_show",
            "kanban_list",
            "kanban_create",
            "kanban_complete",
            "kanban_block",
            "kanban_heartbeat",
            "kanban_comment",
            "kanban_link",
            "kanban_unblock",
            "kanban_attach",
            "kanban_attach_url",
            "kanban_attachments",
        ]

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        # These are already defined in toolsets.py
        return []


class SecurityGuidancePlugin(BasePlugin):
    """Security guidance and patterns."""

    def get_manifest(self) -> PluginManifest:
        return PluginManifest(
            name="security-guidance",
            kind="tool",
            version="1.0.0",
            description="Security best practices and vulnerability patterns",
            author="Hermes Mobile Team",
        )

    async def initialize(self) -> bool:
        logger.info("Security guidance plugin initialized")
        return True

    async def shutdown(self):
        pass

    def get_tools(self) -> List[str]:
        return ["security_scan", "security_advice", "security_patterns"]

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "security_scan",
                    "description": "Scan code for security issues",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Path to scan"},
                            "language": {"type": "string", "description": "Programming language"},
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "security_advice",
                    "description": "Get security advice for a topic",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "topic": {"type": "string", "description": "Security topic"},
                        },
                        "required": ["topic"],
                    },
                },
            },
        ]


# ═══════════════════════════════════════════════════════════════
# Global Registry
# ═══════════════════════════════════════════════════════════════

_plugin_registry: Optional[PluginRegistry] = None


def get_plugin_registry() -> PluginRegistry:
    global _plugin_registry
    if _plugin_registry is None:
        _plugin_registry = PluginRegistry()

        # Add default plugin directories
        settings = get_settings()
        _plugin_registry.add_plugin_dir(Path(settings.data_dir) / "plugins")
        _plugin_registry.add_plugin_dir(Path(__file__).parent.parent / "plugins")

        # Register built-in plugins
        _plugin_registry._plugins["achievements"] = AchievementsPlugin({})
        _plugin_registry._plugins["kanban"] = KanbanPlugin({})
        _plugin_registry._plugins["security-guidance"] = SecurityGuidancePlugin({})

        _plugin_registry._manifests["achievements"] = _plugin_registry._plugins[
            "achievements"
        ].get_manifest()
        _plugin_registry._manifests["kanban"] = _plugin_registry._plugins["kanban"].get_manifest()
        _plugin_registry._manifests["security-guidance"] = _plugin_registry._plugins[
            "security-guidance"
        ].get_manifest()

    return _plugin_registry
