"""Plugins View - Plugin management interface"""

from pathlib import Path

import flet as ft

from hermes_mobile.config.settings import get_settings
from hermes_mobile.plugins import get_plugin_registry
from hermes_mobile.ui.common import close_dialog, open_dialog


class PluginsView:
    """Plugins management interface"""

    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.plugin_registry = get_plugin_registry()

    def build(self) -> ft.Control:
        """Build the plugins view"""
        return ft.Column(
            [
                # Header
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Text("Plugins", size=24, weight=ft.FontWeight.BOLD),
                            ft.Row(
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
                                spacing=8,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    padding=ft.Padding.symmetric(horizontal=20, vertical=16),
                ),
                ft.Divider(height=1),
                # Plugin list
                ft.Container(
                    content=self._build_plugin_list(),
                    padding=ft.Padding.symmetric(horizontal=20, vertical=16),
                    expand=True,
                ),
            ],
            expand=True,
        )

    def _build_plugin_list(self) -> ft.Control:
        """Build the plugin list"""
        plugins = self.plugin_registry.list_plugins()

        return ft.ListView(
            controls=[self._build_plugin_card(plugin) for plugin in plugins]
            or [
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(ft.Icons.PLUGIN, size=48, color=ft.Colors.OUTLINE),
                            ft.Text("No plugins installed", size=16, color=ft.Colors.OUTLINE),
                            ft.Text(
                                "Add plugins to ~/.hermes_mobile/plugins/", color=ft.Colors.OUTLINE
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=12,
                    ),
                    alignment=ft.Alignment.CENTER,
                    padding=40,
                )
            ],
            spacing=12,
            expand=True,
        )

    def _build_plugin_card(self, manifest) -> ft.Control:
        """Build a plugin card"""
        plugin = self.plugin_registry.get_plugin(manifest.name)
        enabled = plugin.enabled if plugin else True

        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.EXTENSION, color=ft.Colors.PRIMARY),
                                ft.Column(
                                    [
                                        ft.Text(manifest.name, weight=ft.FontWeight.BOLD, size=16),
                                        ft.Text(
                                            manifest.description,
                                            size=12,
                                            color=ft.Colors.OUTLINE,
                                            max_lines=2,
                                            overflow=ft.TextOverflow.ELLIPSIS,
                                        ),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                ft.Switch(
                                    value=enabled,
                                    on_change=lambda e, m=manifest: self._toggle_plugin(
                                        m, e.control.value
                                    ),
                                ),
                            ],
                            spacing=12,
                        ),
                        ft.Divider(height=1),
                        ft.Row(
                            [
                                ft.Text(f"v{manifest.version}", size=11, color=ft.Colors.OUTLINE),
                                ft.Text(f"by {manifest.author}", size=11, color=ft.Colors.OUTLINE)
                                if manifest.author
                                else ft.Container(),
                                ft.Text(f"Kind: {manifest.kind}", size=11, color=ft.Colors.OUTLINE),
                            ],
                            alignment=ft.MainAxisAlignment.START,
                            spacing=16,
                        ),
                        ft.Divider(height=1),
                        ft.Row(
                            [
                                ft.TextButton(
                                    "Details",
                                    icon=ft.Icons.INFO_OUTLINE,
                                    on_click=lambda e, m=manifest: self._show_plugin_details(m),
                                ),
                                ft.TextButton(
                                    "Tools",
                                    icon=ft.Icons.BUILD,
                                    on_click=lambda e, m=manifest: self._show_plugin_tools(m),
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.END,
                        ),
                    ],
                    spacing=8,
                ),
                padding=16,
            ),
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
