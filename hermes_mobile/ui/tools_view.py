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
        implemented = self._implemented_names()
        current_names = self._current_tool_names()

        return ft.Column(
            [
                page_header(
                    dark,
                    "Tools",
                    (
                        f"{len(toolsets)} toolsets · {len(implemented)} implementable tools · "
                        f"{len(current_names)} active"
                    ),
                    ft.IconButton(
                        icon=ft.Icons.REFRESH,
                        icon_size=18,
                        tooltip="Refresh",
                        on_click=lambda e: self._refresh(),
                    ),
                ),
                ft.Container(
                    content=self._build_toolsets_list(categories, implemented, current_names),
                    expand=True,
                ),
            ],
            expand=True,
            spacing=0,
        )

    def _implemented_names(self) -> set:
        """Tool names the agent can actually execute (built-ins + skills).

        Toolsets may advertise desktop-only schemas (x_search, browser_scroll,
        computer_use, ...) that have no handler in this mobile build; those must
        never be added to the model's tool list.
        """
        agent = self.agent
        names = set()
        if agent is None:
            return names

        builtins = getattr(agent, "_builtin_tools", None)
        if builtins:
            names.update(name for name in builtins if name)

        skill_manager = getattr(agent, "skill_manager", None)
        if skill_manager is not None:
            try:
                for skill in skill_manager.get_all_skills() or []:
                    skill_name = getattr(skill, "name", "")
                    if skill_name:
                        names.add(skill_name)
            except Exception:
                pass
        return names

    def _current_tool_names(self) -> set:
        """Names of the schemas currently advertised to the model."""
        agent = self.agent
        names = set()
        if agent is None:
            return names
        for schema in getattr(agent, "tools", None) or []:
            fn = schema.get("function", {}) if isinstance(schema, dict) else {}
            name = fn.get("name") if isinstance(fn, dict) else None
            if name:
                names.add(name)
        return names

    def _build_toolsets_list(
        self, categories: dict, implemented: set, current_names: set
    ) -> ft.Control:
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
                controls.append(self._build_toolset_card(name, toolset, implemented, current_names))

            controls.append(ft.Divider(height=16))

        return ft.ListView(
            controls=controls,
            padding=20,
            spacing=8,
        )

    def _build_toolset_card(
        self,
        name: str,
        toolset: dict,
        implemented: set,
        current_names: set,
    ) -> ft.Control:
        """Build a toolset card with an on/off switch reflecting active state."""
        description = toolset.get("description", "")

        resolved = get_toolset(name)
        available = sorted(tool for tool in resolved if tool in implemented)
        dead = [tool for tool in resolved if tool not in implemented]
        enabled = bool(available) and all(tool in current_names for tool in available)
        partial = (
            bool(available) and not enabled and any(tool in current_names for tool in available)
        )

        if dead:
            count_label = f"{len(available)}/{len(resolved)}"
        else:
            count_label = str(len(available))

        c = mode_colors(self.app.dark_mode)
        switch = ft.Switch(
            value=enabled,
            on_change=lambda e, n=name: self._toggle_toolset(n, bool(e.control.value)),
            tooltip=(
                "Toolset active" if enabled else ("Partially active" if partial else "Toolset off")
            ),
        )
        return ft.Container(
            content=flat_list_row(
                self.app.dark_mode,
                name,
                description or "No description",
                leading=ft.Icon(ft.Icons.TERMINAL, size=16, color=c["muted_foreground"]),
                trailing=ft.Row(
                    [
                        ft.Text(
                            count_label,
                            size=10,
                            color=(c["muted_foreground"] if not dead else ft.Colors.ORANGE),
                            font_family=MONO_FONT,
                            tooltip=(
                                f"{len(dead)} tools have no implementation in this "
                                "build (desktop-only)"
                                if dead
                                else None
                            ),
                        ),
                        switch,
                    ],
                    spacing=1,
                    tight=True,
                ),
                on_click=lambda e, n=name: self._show_toolset_details(n),
            ),
            border=ft.Border.only(bottom=ft.BorderSide(1, c["border"])),
        )

    def _toggle_toolset(self, name: str, enable: bool):
        """Enable or disable a toolset for the agent.

        Only tools with a real handler are ever added to the model's tool list;
        desktop-only schemas (x_search, browser_scroll, ...) are skipped.
        """
        agent = self.agent
        if agent is None or not hasattr(agent, "set_tools"):
            snack(self.page, "Agent not available", error=True)
            return

        available = [tool for tool in get_toolset(name) if tool in self._implemented_names()]
        current = list(getattr(agent, "tools", None) or [])
        current_names = {s.get("function", {}).get("name") for s in current if isinstance(s, dict)}

        if enable:
            added = 0
            for schema in get_tool_schemas(available):
                fn = schema.get("function", {})
                tool_name = fn.get("name")
                if tool_name and tool_name not in current_names:
                    current.append(schema)
                    current_names.add(tool_name)
                    added += 1
            agent.set_tools(current)
            snack(
                self.page,
                f"Enabled toolset: {name} ({added} tools added, {len(available) - added} already active)",
            )
        else:
            removed = 0
            kept = []
            for schema in current:
                fn = schema.get("function", {})
                if isinstance(fn, dict) and fn.get("name") in available:
                    removed += 1
                else:
                    kept.append(schema)
            agent.set_tools(kept)
            snack(self.page, f"Disabled toolset: {name} ({removed} tools removed)")
        self._refresh()

    def _show_toolset_details(self, name: str):
        """Show toolset details dialog"""
        toolset = get_all_toolsets().get(name, {})
        resolved_tools = get_toolset(name)
        implemented = self._implemented_names()
        available = sorted(tool for tool in resolved_tools if tool in implemented)

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
                ft.Text(
                    f"Implementable Tools ({len(available)}):",
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Column(
                    [
                        ft.Text(
                            f"  • {tool}", size=11, font_family="monospace", color=ft.Colors.OUTLINE
                        )
                        for tool in sorted(available)
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

    def _refresh(self):
        """Refresh the view"""
        self.app.content_area.content = self.build()
        self.page.update()
