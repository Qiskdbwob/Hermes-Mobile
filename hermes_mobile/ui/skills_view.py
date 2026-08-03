"""Skills View - Skill management interface"""

import flet as ft

from hermes_mobile.locales import t
from hermes_mobile.skills.manager import MobileSkillManager
from hermes_mobile.ui.common import (
    close_dialog,
    empty_state,
    flat_button,
    flat_list_row,
    open_dialog,
    page_header,
    snack,
)
from hermes_mobile.ui.theme import mode_colors


class SkillsView:
    """Skills management interface"""

    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.skill_manager: MobileSkillManager = app.skill_manager

    def build(self) -> ft.Control:
        """Build the skills view"""
        dark = self.app.dark_mode
        actions = ft.Row(
            [
                ft.IconButton(
                    icon=ft.Icons.ADD,
                    tooltip=t("skills.create_skill"),
                    on_click=self._on_create_skill,
                ),
                ft.IconButton(
                    icon=ft.Icons.CLOUD_DOWNLOAD_OUTLINED,
                    tooltip=t("skills.install_from_url"),
                    on_click=self._on_install_from_url,
                ),
            ],
            spacing=0,
            tight=True,
        )
        return ft.Column(
            [
                page_header(dark, t("skills.title"), t("skills.installed"), actions),
                self._build_skills_list(),
            ],
            expand=True,
            spacing=0,
        )

    def _build_skills_list(self) -> ft.Control:
        """Build the skills list"""
        skills = self.skill_manager.get_all_skills()

        if not skills:
            return empty_state(
                self.app.dark_mode,
                t("skills.no_skills"),
                t("skills.no_skills_hint"),
                ft.Icons.EXTENSION_OFF_OUTLINED,
                flat_button(
                    t("skills.create_skill"),
                    ft.Icons.ADD,
                    self._on_create_skill,
                    primary=True,
                    dark=self.app.dark_mode,
                ),
            )

        return ft.ListView(
            controls=[self._build_skill_card(skill) for skill in skills],
            padding=ft.Padding.symmetric(horizontal=16),
            spacing=0,
            expand=True,
        )

    def _build_skill_card(self, skill) -> ft.Control:
        """Build a skill card"""
        c = mode_colors(self.app.dark_mode)
        actions = ft.Row(
            [
                ft.Switch(
                    value=skill.enabled,
                    on_change=lambda e, s=skill: self._toggle_skill(s, e.control.value),
                ),
                ft.PopupMenuButton(
                    icon=ft.Icons.MORE_VERT,
                    icon_color=c["muted_foreground"],
                    items=[
                        ft.PopupMenuItem(
                            icon=ft.Icons.INFO_OUTLINE,
                            content=t("skills.details"),
                            on_click=lambda e, s=skill: self._show_skill_details(s),
                        ),
                        ft.PopupMenuItem(
                            icon=ft.Icons.DOWNLOAD_OUTLINED,
                            content="Export",
                            on_click=lambda e, s=skill: self._export_skill(s),
                        ),
                        ft.PopupMenuItem(
                            icon=ft.Icons.DELETE_OUTLINE,
                            content=t("skills.remove"),
                            on_click=lambda e, s=skill: self._confirm_remove_skill(s),
                        ),
                    ],
                ),
            ],
            spacing=0,
            tight=True,
        )
        return flat_list_row(
            self.app.dark_mode,
            skill.name,
            skill.description or t("skills.no_description"),
            ft.Icon(
                ft.Icons.EXTENSION_OUTLINED,
                size=19,
                color=c["primary"] if skill.enabled else c["muted_foreground"],
            ),
            actions,
            lambda e, s=skill: self._show_skill_details(s),
        )

    def _on_create_skill(self, e):
        """Show create skill dialog"""
        name_field = ft.TextField(label="Skill Name", hint_text="my_skill")
        desc_field = ft.TextField(label="Description", hint_text="What does this skill do?")

        def create(e):
            name = name_field.value.strip()
            desc = desc_field.value.strip()
            if name:
                self.skill_manager.create_skill_template(name, desc)
                close_dialog(self.page, dialog)
                self._refresh()

        dialog = ft.AlertDialog(
            title=ft.Text("Create New Skill"),
            content=ft.Column([name_field, desc_field], tight=True, spacing=12),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: close_dialog(self.page, dialog)),
                ft.Button("Create", on_click=create),
            ],
        )
        open_dialog(self.page, dialog)

    def _on_install_from_url(self, e):
        """Show install from URL dialog"""
        url_field = ft.TextField(label="GitHub URL", hint_text="https://github.com/user/repo")

        async def install(e):
            url = url_field.value.strip()
            if url:
                close_dialog(self.page, dialog)
                # Show loading
                loading = ft.AlertDialog(
                    content=ft.Row(
                        [ft.ProgressRing(), ft.Text(" Installing skill...")],
                        spacing=12,
                    ),
                )
                open_dialog(self.page, loading)

                skill = await self.skill_manager.install_skill_from_url(url)
                close_dialog(self.page, loading)

                if skill:
                    snack(self.page, f"Installed: {skill.name}")
                else:
                    snack(self.page, "Installation failed")

                self._refresh()

        dialog = ft.AlertDialog(
            title=ft.Text("Install Skill from URL"),
            content=url_field,
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: close_dialog(self.page, dialog)),
                ft.Button("Install", on_click=install),
            ],
        )
        open_dialog(self.page, dialog)

    def _toggle_skill(self, skill, enabled: bool):
        """Toggle skill enabled state"""
        if enabled:
            self.skill_manager.enable_skill(skill.name)
        else:
            self.skill_manager.disable_skill(skill.name)
        self._refresh()

    def _show_skill_details(self, skill):
        """Show skill details dialog"""
        info = self.skill_manager.get_skill_info(skill.name)

        content = ft.Column(
            [
                ft.Text(f"Name: {skill.name}", weight=ft.FontWeight.BOLD),
                ft.Text(f"Source: {skill.source}"),
                ft.Text(f"Enabled: {'Yes' if skill.enabled else 'No'}"),
                ft.Divider(),
                ft.Text("Schema:", weight=ft.FontWeight.BOLD),
                ft.Text(
                    str(skill.schema),
                    size=12,
                    font_family="monospace",
                    selectable=True,
                ),
            ],
            spacing=8,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
        )

        if info and info.get("readme"):
            content.controls.append(ft.Divider())
            content.controls.append(ft.Text("README:", weight=ft.FontWeight.BOLD))
            content.controls.append(ft.Text(info["readme"], size=12, selectable=True))

        dialog = ft.AlertDialog(
            title=ft.Text(f"Skill: {skill.name}"),
            content=ft.Container(content=content, width=400, height=500),
            actions=[ft.TextButton("Close", on_click=lambda e: close_dialog(self.page, dialog))],
        )
        open_dialog(self.page, dialog)

    def _export_skill(self, skill):
        """Export skill to downloads"""
        # TODO: Implement export
        snack(self.page, "Export not yet implemented")

    def _confirm_remove_skill(self, skill):
        """Confirm skill removal"""

        def remove(e):
            self.skill_manager.remove_skill(skill.name)
            close_dialog(self.page, dialog)
            self._refresh()

        dialog = ft.AlertDialog(
            title=ft.Text("Remove Skill"),
            content=ft.Text(
                f"Are you sure you want to remove '{skill.name}'? This cannot be undone."
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: close_dialog(self.page, dialog)),
                ft.Button("Remove", color=ft.Colors.ERROR, on_click=remove),
            ],
        )
        open_dialog(self.page, dialog)

    def _refresh(self):
        """Refresh the skills view"""
        self.app.content_area.content = self.build()
        self.page.update()
