"""Plugins View - Plugin management interface"""

from pathlib import Path

import flet as ft

from hermes_mobile.config.settings import get_settings, save_settings
from hermes_mobile.locales import t
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
                    tooltip=t("plugins.refresh"),
                    on_click=lambda e: self._refresh(),
                ),
                ft.IconButton(
                    icon=ft.Icons.FOLDER_OPEN,
                    tooltip=t("plugins.open_dir"),
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
                    t("plugins.title"),
                    t("plugins.count", count=len(plugins)),
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
                t("plugins.no_plugins"),
                t("plugins.plugin_dir_hint"),
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
            tooltip=t("plugins.actions"),
            items=[
                ft.PopupMenuItem(
                    content=ft.Text(t("plugins.details")),
                    on_click=lambda e, m=manifest: self._show_plugin_details(m),
                ),
                ft.PopupMenuItem(
                    content=ft.Text(t("plugins.tools")),
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
        """Toggle plugin enabled state (persisted across restarts)"""
        plugin = self.plugin_registry.get_plugin(manifest.name)
        if not plugin:
            return
        plugin.enabled = enabled
        import asyncio

        async def _apply():
            try:
                if enabled:
                    await plugin.initialize()
                else:
                    await plugin.shutdown()
            except Exception:
                pass

        try:
            asyncio.get_running_loop().create_task(_apply())
        except RuntimeError:
            pass  # No event loop (tests/startup): state still persisted below
        try:
            settings = self.app.settings
            toggles = dict(getattr(settings, "plugin_toggles", None) or {})
            toggles[manifest.name] = enabled
            settings.plugin_toggles = toggles
            save_settings(settings)
        except Exception:
            pass
        self._refresh()

    def _show_plugin_details(self, manifest):
        """Show plugin details dialog"""
        plugin = self.plugin_registry.get_plugin(manifest.name)

        content = ft.Column(
            [
                ft.Text(t("plugins.field_name", value=manifest.name), weight=ft.FontWeight.BOLD),
                ft.Text(t("plugins.field_version", value=manifest.version)),
                ft.Text(t("plugins.field_kind", value=manifest.kind)),
                ft.Text(t("plugins.field_author", value=manifest.author)),
                ft.Text(t("plugins.field_description", value=manifest.description)),
                ft.Divider(),
                ft.Text(t("plugins.dependencies"), weight=ft.FontWeight.BOLD),
                ft.Text(
                    ", ".join(manifest.dependencies) if manifest.dependencies else t("plugins.none")
                ),
                ft.Divider(),
                ft.Text(t("plugins.tools_label"), weight=ft.FontWeight.BOLD),
                ft.Text(", ".join(plugin.get_tools()) if plugin else t("plugins.none")),
            ],
            spacing=8,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
        )

        dialog = ft.AlertDialog(
            title=ft.Text(t("plugins.plugin_title", name=manifest.name)),
            content=ft.Container(content=content, width=400, height=400),
            actions=[
                ft.TextButton(t("common.close"), on_click=lambda e: close_dialog(self.page, dialog))
            ],
        )
        open_dialog(self.page, dialog)

    def _show_plugin_tools(self, manifest):
        """Show plugin tools dialog"""
        plugin = self.plugin_registry.get_plugin(manifest.name)
        tools = plugin.get_tool_schemas() if plugin else []

        content = ft.Column(
            [
                ft.Text(t("plugins.tools_provided", name=manifest.name), weight=ft.FontWeight.BOLD),
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
                    or [ft.Text(t("plugins.no_tools"), color=ft.Colors.OUTLINE)],
                    spacing=4,
                    scroll=ft.ScrollMode.AUTO,
                ),
            ],
            spacing=8,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
        )

        dialog = ft.AlertDialog(
            title=ft.Text(t("plugins.tools_title", name=manifest.name)),
            content=ft.Container(content=content, width=500, height=400),
            actions=[
                ft.TextButton(t("common.close"), on_click=lambda e: close_dialog(self.page, dialog))
            ],
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
