"""Tools View - Toolset management interface"""

import flet as ft

from hermes_mobile.toolsets import (
    get_all_toolsets,
    get_tool_schemas,
    get_toolset,
    list_toolsets_by_category,
)
from hermes_mobile.ui.common import (
    MONO_FONT,
    close_dialog,
    flat_list_row,
    open_dialog,
    page_header,
    section_label,
    snack,
)
from hermes_mobile.ui.theme import mode_colors


class ToolsView:
    """Tools and toolsets management interface"""

    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.agent = app.agent

    def build(self) -> ft.Control:
        """Build the tools view"""
        dark = self.app.dark_mode
        toolsets = get_all_toolsets()
        categories = list_toolsets_by_category()

        return ft.Column(
            [
                page_header(
                    dark,
                    "Tools",
                    f"{len(toolsets)} toolsets · {sum(len(get_toolset(name)) for name in toolsets)} resolved tools",
                    ft.IconButton(
                        icon=ft.Icons.REFRESH,
                        icon_size=18,
                        tooltip="Refresh",
                        on_click=lambda e: self._refresh(),
                    ),
                ),
                ft.Container(content=self._build_toolsets_list(categories), expand=True),
            ],
            expand=True,
            spacing=0,
        )

    def _build_toolsets_list(self, categories: dict) -> ft.Control:
        """Build the toolsets list grouped by category"""
        controls = []

        for category, toolset_names in sorted(categories.items()):
            controls.append(
                section_label(
                    self.app.dark_mode,
                    category.replace("_", " "),
                    str(len(toolset_names)),
                )
            )

            for name in sorted(toolset_names):
                toolset = get_all_toolsets().get(name, {})
                controls.append(self._build_toolset_card(name, toolset))

            controls.append(ft.Divider(height=16))

        return ft.ListView(
            controls=controls,
            padding=20,
            spacing=8,
        )

    def _build_toolset_card(self, name: str, toolset: dict) -> ft.Control:
        """Build a toolset card"""
        description = toolset.get("description", "")

        # Get resolved tools
        resolved_tools = get_toolset(name)
        tool_count = len(resolved_tools)

        c = mode_colors(self.app.dark_mode)
        return ft.Container(
            content=flat_list_row(
                self.app.dark_mode,
                name,
                description or "No description",
                leading=ft.Icon(ft.Icons.TERMINAL, size=16, color=c["muted_foreground"]),
                trailing=ft.Row(
                    [
                        ft.Text(
                            str(tool_count),
                            size=10,
                            color=c["muted_foreground"],
                            font_family=MONO_FONT,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.ADD,
                            icon_size=17,
                            tooltip="Enable toolset",
                            on_click=lambda e, n=name: self._enable_toolset(n),
                        ),
                    ],
                    spacing=1,
                    tight=True,
                ),
                on_click=lambda e, n=name: self._show_toolset_details(n),
            ),
            border=ft.Border.only(bottom=ft.BorderSide(1, c["border"])),
        )

    def _show_toolset_details(self, name: str):
        """Show toolset details dialog"""
        toolset = get_all_toolsets().get(name, {})
        resolved_tools = get_toolset(name)

        content = ft.Column(
            [
                ft.Text(f"Toolset: {name}", weight=ft.FontWeight.BOLD, size=18),
                ft.Text(
                    toolset.get("description", "No description"), size=14, color=ft.Colors.OUTLINE
                ),
                ft.Divider(),
                ft.Text("Direct Tools:", weight=ft.FontWeight.BOLD),
                ft.Column(
                    [
                        ft.Text(f"  • {tool}", size=12, font_family="monospace")
                        for tool in toolset.get("tools", [])
                    ]
                    or [ft.Text("  (none)", size=12, color=ft.Colors.OUTLINE)],
                    spacing=2,
                ),
                ft.Divider(),
                ft.Text("Included Toolsets:", weight=ft.FontWeight.BOLD),
                ft.Column(
                    [
                        ft.Text(f"  • {inc}", size=12, font_family="monospace")
                        for inc in toolset.get("includes", [])
                    ]
                    or [ft.Text("  (none)", size=12, color=ft.Colors.OUTLINE)],
                    spacing=2,
                ),
                ft.Divider(),
                ft.Text(f"Resolved Tools ({len(resolved_tools)}):", weight=ft.FontWeight.BOLD),
                ft.Column(
                    [
                        ft.Text(
                            f"  • {tool}", size=11, font_family="monospace", color=ft.Colors.OUTLINE
                        )
                        for tool in sorted(resolved_tools)
                    ],
                    spacing=1,
                    scroll=ft.ScrollMode.AUTO,
                ),
            ],
            spacing=8,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
        )

        dialog = ft.AlertDialog(
            title=ft.Text(f"Toolset: {name}"),
            content=ft.Container(content=content, width=400, height=500),
            actions=[ft.TextButton("Close", on_click=lambda e: close_dialog(self.page, dialog))],
        )
        open_dialog(self.page, dialog)

    def _enable_toolset(self, name: str):
        """Enable a toolset for the agent"""
        # Get resolved tools and update agent
        resolved_tools = get_toolset(name)
        schemas = get_tool_schemas(list(resolved_tools))

        # Add to agent's existing tools
        current_tools = self.agent.tools or []
        tool_names = {t["function"]["name"] for t in current_tools}

        for schema in schemas:
            if schema["function"]["name"] not in tool_names:
                current_tools.append(schema)

        self.agent.set_tools(current_tools)
        snack(self.page, f"Enabled toolset: {name} ({len(resolved_tools)} tools)")

    def _refresh(self):
        """Refresh the view"""
        self.app.content_area.content = self.build()
        self.page.update()
