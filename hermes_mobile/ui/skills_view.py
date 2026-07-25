"""Skills View - Skill management interface"""

import flet as ft

from hermes_mobile.skills.manager import MobileSkillManager
from hermes_mobile.locales import t


class SkillsView:
    """Skills management interface"""

    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.skill_manager: MobileSkillManager = app.skill_manager

    def build(self) -> ft.Control:
        """Build the skills view"""
        return ft.Column(
            [
                # Header
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Text("Skills", size=24, weight=ft.FontWeight.BOLD),
                            ft.IconButton(
                                icon=ft.Icons.ADD,
                                tooltip="Create New Skill",
                                on_click=self._on_create_skill,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.CLOUD_DOWNLOAD,
                                tooltip="Install from URL",
                                on_click=self._on_install_from_url,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    padding=ft.padding.symmetric(horizontal=20, vertical=16),
                ),
                ft.Divider(height=1),
                # Skills list
                ft.Container(
                    content=self._build_skills_list(),
                    expand=True,
                ),
            ],
            expand=True,
        )

    def _build_skills_list(self) -> ft.Control:
        """Build the skills list"""
        skills = self.skill_manager.get_all_skills()

        if not skills:
            return ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.EXTENSION_OFF, size=64, color=ft.Colors.OUTLINE),
                        ft.Text("No skills installed", size=18, color=ft.Colors.OUTLINE),
                        ft.Text(
                            "Create a new skill or install from a URL",
                            color=ft.Colors.OUTLINE,
                        ),
                        ft.ElevatedButton(
                            "Create Skill",
                            icon=ft.Icons.ADD,
                            on_click=self._on_create_skill,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=16,
                ),
                alignment=ft.alignment.center,
                expand=True,
            )

        return ft.ListView(
            controls=[self._build_skill_card(skill) for skill in skills],
            padding=20,
            spacing=12,
        )

    def _build_skill_card(self, skill) -> ft.Control:
        """Build a skill card"""
        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.EXTENSION,
                                    color=ft.Colors.PRIMARY if skill.enabled else ft.Colors.OUTLINE,
                                ),
                                ft.Column(
                                    [
                                        ft.Text(skill.name, weight=ft.FontWeight.BOLD, size=16),
                                        ft.Text(
                                            skill.description or "No description",
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
                                    value=skill.enabled,
                                    on_change=lambda e, s=skill: self._toggle_skill(
                                        s, e.control.value
                                    ),
                                ),
                            ],
                            spacing=12,
                        ),
                        ft.Divider(height=1),
                        ft.Row(
                            [
                                ft.TextButton(
                                    "Details",
                                    icon=ft.Icons.INFO_OUTLINE,
                                    on_click=lambda e, s=skill: self._show_skill_details(s),
                                ),
                                ft.TextButton(
                                    "Export",
                                    icon=ft.Icons.DOWNLOAD,
                                    on_click=lambda e, s=skill: self._export_skill(s),
                                ),
                                ft.TextButton(
                                    "Remove",
                                    icon=ft.Icons.DELETE_OUTLINE,
                                    style=ft.ButtonStyle(color=ft.Colors.ERROR),
                                    on_click=lambda e, s=skill: self._confirm_remove_skill(s),
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

    def _on_create_skill(self, e):
        """Show create skill dialog"""
        name_field = ft.TextField(label="Skill Name", hint_text="my_skill")
        desc_field = ft.TextField(label="Description", hint_text="What does this skill do?")

        def create(e):
            name = name_field.value.strip()
            desc = desc_field.value.strip()
            if name:
                self.skill_manager.create_skill_template(name, desc)
                self.page.close(dialog)
                self._refresh()

        dialog = ft.AlertDialog(
            title=ft.Text("Create New Skill"),
            content=ft.Column([name_field, desc_field], tight=True, spacing=12),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self.page.close(dialog)),
                ft.ElevatedButton("Create", on_click=create),
            ],
        )
        self.page.open(dialog)

    def _on_install_from_url(self, e):
        """Show install from URL dialog"""
        url_field = ft.TextField(label="GitHub URL", hint_text="https://github.com/user/repo")

        async def install(e):
            url = url_field.value.strip()
            if url:
                self.page.close(dialog)
                # Show loading
                loading = ft.AlertDialog(
                    content=ft.Row(
                        [ft.ProgressRing(), ft.Text(" Installing skill...")],
                        spacing=12,
                    ),
                )
                self.page.open(loading)

                skill = await self.skill_manager.install_skill_from_url(url)
                self.page.close(loading)

                if skill:
                    self.page.show_snack_bar(
                        ft.SnackBar(content=ft.Text(f"Installed: {skill.name}"))
                    )
                else:
                    self.page.show_snack_bar(ft.SnackBar(content=ft.Text("Installation failed")))

                self._refresh()

        dialog = ft.AlertDialog(
            title=ft.Text("Install Skill from URL"),
            content=url_field,
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self.page.close(dialog)),
                ft.ElevatedButton("Install", on_click=install),
            ],
        )
        self.page.open(dialog)

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
            actions=[ft.TextButton("Close", on_click=lambda e: self.page.close(dialog))],
        )
        self.page.open(dialog)

    def _export_skill(self, skill):
        """Export skill to downloads"""
        # TODO: Implement export
        self.page.show_snack_bar(ft.SnackBar(content=ft.Text("Export not yet implemented")))

    def _confirm_remove_skill(self, skill):
        """Confirm skill removal"""

        def remove(e):
            self.skill_manager.remove_skill(skill.name)
            self.page.close(dialog)
            self._refresh()

        dialog = ft.AlertDialog(
            title=ft.Text("Remove Skill"),
            content=ft.Text(
                f"Are you sure you want to remove '{skill.name}'? This cannot be undone."
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self.page.close(dialog)),
                ft.ElevatedButton("Remove", color=ft.Colors.ERROR, on_click=remove),
            ],
        )
        self.page.open(dialog)

    def _refresh(self):
        """Refresh the skills view"""
        self.app.content_area.content = self.build()
        self.page.update()
