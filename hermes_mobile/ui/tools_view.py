"""Tools View - Toolset management interface"""

import flet as ft

from hermes_mobile.toolsets import (
    get_all_toolsets,
    get_tool_schemas,
    get_toolset,
    list_toolsets_by_category,
)
from hermes_mobile.locales import t


class ToolsView:
    """Tools and toolsets management interface"""

    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.agent = app.agent

    def build(self) -> ft.Control:
        """Build the tools view"""
        toolsets = get_all_toolsets()
        categories = list_toolsets_by_category()

        return ft.Column(
            [
                # Header
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Text("Tools & Toolsets", size=24, weight=ft.FontWeight.BOLD),
                            ft.IconButton(
                                icon=ft.Icons.REFRESH,
                                tooltip="Refresh",
                                on_click=lambda e: self._refresh(),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    padding=ft.padding.symmetric(horizontal=20, vertical=16),
                ),
                ft.Divider(height=1),
                # Toolsets by category
                ft.Container(
                    content=self._build_toolsets_list(categories),
                    expand=True,
                ),
            ],
            expand=True,
        )

    def _build_toolsets_list(self, categories: dict) -> ft.Control:
        """Build the toolsets list grouped by category"""
        controls = []

        for category, toolset_names in sorted(categories.items()):
            controls.append(
                ft.Text(
                    category.replace("_", " ").title(),
                    size=16,
                    weight=ft.FontWeight.BOLD,
                    color=ft.Colors.PRIMARY,
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
        tools = toolset.get("tools", [])
        includes = toolset.get("includes", [])

        # Get resolved tools
        resolved_tools = get_toolset(name)
        tool_count = len(resolved_tools)

        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.BUILD, color=ft.Colors.PRIMARY),
                                ft.Column(
                                    [
                                        ft.Text(name, weight=ft.FontWeight.BOLD, size=16),
                                        ft.Text(
                                            description or "No description",
                                            size=12,
                                            color=ft.Colors.OUTLINE,
                                            max_lines=2,
                                            overflow=ft.TextOverflow.ELLIPSIS,
                                        ),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                ft.Chip(
                                    label=ft.Text(f"{tool_count} tools"),
                                    leading=ft.Icon(ft.Icons.BUILD, size=14),
                                ),
                            ],
                            spacing=12,
                        ),
                        ft.Divider(height=1),
                        ft.Row(
                            [
                                ft.TextButton(
                                    "View Tools",
                                    icon=ft.Icons.LIST,
                                    on_click=lambda e, n=name: self._show_toolset_details(n),
                                ),
                                ft.TextButton(
                                    "Enable",
                                    icon=ft.Icons.CHECK_CIRCLE,
                                    on_click=lambda e, n=name: self._enable_toolset(n),
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
            actions=[ft.TextButton("Close", on_click=lambda e: self.page.close(dialog))],
        )
        self.page.open(dialog)

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
        self.page.show_snack_bar(
            ft.SnackBar(content=ft.Text(f"Enabled toolset: {name} ({len(resolved_tools)} tools)"))
        )

    def _refresh(self):
        """Refresh the view"""
        self.app.content_area.content = self.build()
        self.page.update()
