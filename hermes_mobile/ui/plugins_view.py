"""Plugins View - Plugin management interface"""

from pathlib import Path

import flet as ft

from hermes_mobile.config.settings import get_settings
from hermes_mobile.plugins import get_plugin_registry
from hermes_mobile.ui.common import (
    close_dialog,
    empty_state,
    flat_list_row,
    open_dialog,
    page_header,
)


class PluginsView:
    """Plugins management interface"""

    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.plugin_registry = get_plugin_registry()

    def build(self) -> ft.Control:
        """Build the plugins view"""
        actions = ft.Row(
            [
                ft.IconButton(
                    icon=ft.Icons.REFRESH,
                    tooltip="Refresh",
                    on_click=lambda e: self._refresh(),
                ),
                ft.IconButton(
                    icon=ft.Icons.FOLDER_OPEN,
                    tooltip="Open Plugin Directory",
                    on_click=lambda e: self._open_plugin_dir(),
                ),
            ],
            spacing=0,
        )
        plugins = self.plugin_registry.list_plugins()
        return ft.Column(
            [
                page_header(
                    self.app.dark_mode,
                    "Plugins",
                    f"{len(plugins)} installed extensions",
                    actions,
                ),
                ft.Container(content=self._build_plugin_list(plugins), expand=True),
            ],
            expand=True,
            spacing=0,
        )

    def _build_plugin_list(self, plugins=None) -> ft.Control:
        """Build the plugin list"""
        plugins = plugins if plugins is not None else self.plugin_registry.list_plugins()

        controls = [self._build_plugin_card(plugin) for plugin in plugins]
        if not controls:
            return empty_state(
                self.app.dark_mode,
                "No plugins installed",
                "Add plugins to the mobile plugin directory.",
                ft.Icons.EXTENSION_OFF,
            )
        return ft.ListView(
            controls=controls,
            padding=ft.Padding.symmetric(horizontal=12),
            spacing=0,
            expand=True,
        )

    def _build_plugin_card(self, manifest) -> ft.Control:
        """Build a dense plugin row with overflow actions."""
        plugin = self.plugin_registry.get_plugin(manifest.name)
        enabled = plugin.enabled if plugin else True
        metadata = f"v{manifest.version}"
        if manifest.author:
            metadata += f" · {manifest.author}"
        metadata += f" · {manifest.kind}"
        subtitle = f"{manifest.description}\n{metadata}"
        actions = ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT,
            tooltip="Plugin actions",
            items=[
                ft.PopupMenuItem(
                    content=ft.Text("Details"),
                    on_click=lambda e, m=manifest: self._show_plugin_details(m),
                ),
                ft.PopupMenuItem(
                    content=ft.Text("Tools"),
                    on_click=lambda e, m=manifest: self._show_plugin_tools(m),
                ),
            ],
        )
        trailing = ft.Row(
            [
                ft.Switch(
                    value=enabled,
                    on_change=lambda e, m=manifest: self._toggle_plugin(m, e.control.value),
                ),
                actions,
            ],
            spacing=0,
            tight=True,
        )
        return flat_list_row(
            self.app.dark_mode,
            manifest.name,
            subtitle,
            ft.Icon(ft.Icons.EXTENSION, size=18, color=ft.Colors.PRIMARY),
            trailing,
        )

    def _toggle_plugin(self, manifest, enabled: bool):
        """Toggle plugin enabled state"""
        plugin = self.plugin_registry.get_plugin(manifest.name)
        if plugin:
            plugin.enabled = enabled
            if enabled:
                import asyncio

                asyncio.create_task(plugin.initialize())
            else:
                import asyncio

                asyncio.create_task(plugin.shutdown())
            self._refresh()

    def _show_plugin_details(self, manifest):
        """Show plugin details dialog"""
        plugin = self.plugin_registry.get_plugin(manifest.name)

        content = ft.Column(
            [
                ft.Text(f"Name: {manifest.name}", weight=ft.FontWeight.BOLD),
                ft.Text(f"Version: {manifest.version}"),
                ft.Text(f"Kind: {manifest.kind}"),
                ft.Text(f"Author: {manifest.author}"),
                ft.Text(f"Description: {manifest.description}"),
                ft.Divider(),
                ft.Text("Dependencies:", weight=ft.FontWeight.BOLD),
                ft.Text(", ".join(manifest.dependencies) if manifest.dependencies else "None"),
                ft.Divider(),
                ft.Text("Tools:", weight=ft.FontWeight.BOLD),
                ft.Text(", ".join(plugin.get_tools()) if plugin else "None"),
            ],
            spacing=8,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
        )

        dialog = ft.AlertDialog(
            title=ft.Text(f"Plugin: {manifest.name}"),
            content=ft.Container(content=content, width=400, height=400),
            actions=[ft.TextButton("Close", on_click=lambda e: close_dialog(self.page, dialog))],
        )
        open_dialog(self.page, dialog)

    def _show_plugin_tools(self, manifest):
        """Show plugin tools dialog"""
        plugin = self.plugin_registry.get_plugin(manifest.name)
        tools = plugin.get_tool_schemas() if plugin else []

        content = ft.Column(
            [
                ft.Text(f"Tools provided by {manifest.name}:", weight=ft.FontWeight.BOLD),
                ft.Divider(),
                ft.Column(
                    [
                        ft.ListTile(
                            title=ft.Text(tool["function"]["name"]),
                            subtitle=ft.Text(
                                tool["function"]["description"][:100] + "..."
                                if len(tool["function"]["description"]) > 100
                                else tool["function"]["description"]
                            ),
                        )
                        for tool in tools
                    ]
                    or [ft.Text("No tools provided", color=ft.Colors.OUTLINE)],
                    spacing=4,
                    scroll=ft.ScrollMode.AUTO,
                ),
            ],
            spacing=8,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
        )

        dialog = ft.AlertDialog(
            title=ft.Text(f"Tools: {manifest.name}"),
            content=ft.Container(content=content, width=500, height=400),
            actions=[ft.TextButton("Close", on_click=lambda e: close_dialog(self.page, dialog))],
        )
        open_dialog(self.page, dialog)

    def _open_plugin_dir(self):
        """Open plugin directory"""
        import subprocess
        import sys

        plugin_dir = (
            self.plugin_registry._plugin_dirs[0]
            if self.plugin_registry._plugin_dirs
            else Path(get_settings().data_dir) / "plugins"
        )
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", str(plugin_dir)])
            elif sys.platform == "win32":
                subprocess.run(["explorer", str(plugin_dir)])
            else:
                subprocess.run(["xdg-open", str(plugin_dir)])
        except Exception:
            pass

    def _refresh(self):
        """Refresh the view"""
        self.app.content_area.content = self.build()
        self.page.update()
