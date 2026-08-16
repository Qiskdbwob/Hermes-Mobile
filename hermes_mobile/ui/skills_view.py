"""Skills View - Skill management interface"""

import logging
import shutil
from pathlib import Path
from typing import Any, Mapping

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

logger = logging.getLogger(__name__)


class SkillsView:
    """Skills management interface"""

    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.skill_manager: MobileSkillManager = app.skill_manager
        self.remote_skills: list[Mapping[str, Any]] = []
        self.remote_loading = False
        self.remote_error = ""
        self._remote_scope = ""

    @property
    def remote_mode(self) -> bool:
        return str(getattr(self.app.settings, "runtime_mode", "local")) == "remote"

    def build(self) -> ft.Control:
        """Build the skills view"""
        dark = self.app.dark_mode
        if self.remote_mode:
            actions = ft.Row(
                [
                    ft.IconButton(
                        icon=ft.Icons.REFRESH,
                        tooltip=t("skills.remote_refresh"),
                        on_click=self._on_refresh_remote,
                        disabled=self.remote_loading,
                    )
                ],
                spacing=0,
                tight=True,
            )
            subtitle = t("skills.remote_subtitle")
        else:
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
            subtitle = t("skills.installed")
        return ft.Column(
            [
                page_header(dark, t("skills.title"), subtitle, actions),
                self._build_skills_list(),
            ],
            expand=True,
            spacing=0,
        )

    def _build_skills_list(self) -> ft.Control:
        """Build the skills list"""
        if self.remote_mode:
            return self._build_remote_skills_list()
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

    def _build_remote_skills_list(self) -> ft.Control:
        if self.remote_loading and not self.remote_skills:
            return ft.Column(
                [
                    ft.ProgressRing(width=26, height=26, stroke_width=2),
                    ft.Text(t("skills.remote_loading")),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                expand=True,
            )
        if self.remote_error and not self.remote_skills:
            return empty_state(
                self.app.dark_mode,
                t("skills.remote_unavailable"),
                self.remote_error,
                ft.Icons.CLOUD_OFF_OUTLINED,
                flat_button(
                    t("skills.retry"),
                    ft.Icons.REFRESH,
                    self._on_refresh_remote,
                    primary=True,
                    dark=self.app.dark_mode,
                ),
            )
        if not self.remote_skills:
            return empty_state(
                self.app.dark_mode,
                t("skills.no_remote"),
                t("skills.no_remote_hint"),
                ft.Icons.EXTENSION_OFF_OUTLINED,
            )
        return ft.ListView(
            controls=[self._build_remote_skill_row(skill) for skill in self.remote_skills],
            padding=ft.Padding.symmetric(horizontal=16),
            spacing=0,
            expand=True,
        )

    def _build_remote_skill_row(self, skill: Mapping[str, Any]) -> ft.Control:
        c = mode_colors(self.app.dark_mode)
        category = str(skill.get("category") or t("skills.remote_category"))
        description = str(skill.get("description") or category)
        return flat_list_row(
            self.app.dark_mode,
            str(skill.get("name") or t("skills.unnamed")),
            description,
            ft.Icon(ft.Icons.EXTENSION_OUTLINED, size=19, color=c["primary"]),
            ft.Text(category, size=11, color=c["muted_foreground"]),
        )

    async def _on_refresh_remote(self, e=None):
        await self.refresh_remote(force=True)

    async def refresh_remote(self, *, force: bool = False) -> None:
        if not self.remote_mode:
            return
        settings = self.app.settings
        scope = (
            f"{str(getattr(settings, 'remote_url', '') or '').rstrip('/')}|"
            f"{str(getattr(settings, 'remote_profile', '') or 'default')}"
        )
        if not force and scope == self._remote_scope and (self.remote_skills or self.remote_error):
            return
        self.remote_loading = True
        self.remote_error = ""
        self._paint_current()
        try:
            client = getattr(self.app, "remote_client", None)
            if client is None or client.state != "open":
                raise RuntimeError("Connect to Hermes Remote to load this profile's skills.")
            self.remote_skills = await client.get_remote_skills()
            self._remote_scope = scope
        except Exception as exc:
            self.remote_error = str(exc).strip() or t("skills.remote_load_error")
        finally:
            self.remote_loading = False
            self._paint_current()

    def _paint_current(self) -> None:
        if getattr(self.app, "current_view", "") != "skills":
            return
        self.app.content_area.content = self.build()
        self.page.update()

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
                            content=t("skills.export"),
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
        name_field = ft.TextField(label=t("skills.skill_name"), hint_text=t("skills.name_hint"))
        desc_field = ft.TextField(label=t("skills.description"), hint_text=t("skills.desc_hint"))

        def create(e):
            name = name_field.value.strip()
            desc = desc_field.value.strip()
            if name:
                self.skill_manager.create_skill_template(name, desc)
                close_dialog(self.page, dialog)
                self._refresh()

        dialog = ft.AlertDialog(
            title=ft.Text(t("skills.create_title")),
            content=ft.Column([name_field, desc_field], tight=True, spacing=12),
            actions=[
                ft.TextButton(
                    t("common.cancel"), on_click=lambda e: close_dialog(self.page, dialog)
                ),
                ft.Button(t("skills.create"), on_click=create),
            ],
        )
        open_dialog(self.page, dialog)

    def _on_install_from_url(self, e):
        """Show install from URL dialog"""
        url_field = ft.TextField(
            label=t("skills.github_url"), hint_text="https://github.com/user/repo"
        )

        async def install(e):
            url = url_field.value.strip()
            if url:
                close_dialog(self.page, dialog)
                # Show loading
                loading = ft.AlertDialog(
                    content=ft.Row(
                        [ft.ProgressRing(), ft.Text(t("skills.installing"))],
                        spacing=12,
                    ),
                )
                open_dialog(self.page, loading)

                skill = await self.skill_manager.install_skill_from_url(url)
                close_dialog(self.page, loading)

                if skill:
                    snack(self.page, t("skills.installed_ok", name=skill.name))
                else:
                    snack(self.page, t("skills.install_failed"), error=True)

                self._refresh()

        dialog = ft.AlertDialog(
            title=ft.Text(t("skills.install_title")),
            content=url_field,
            actions=[
                ft.TextButton(
                    t("common.cancel"), on_click=lambda e: close_dialog(self.page, dialog)
                ),
                ft.Button(t("skills.install"), on_click=install),
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
                ft.Text(t("skills.detail_name", name=skill.name), weight=ft.FontWeight.BOLD),
                ft.Text(t("skills.detail_source", source=skill.source)),
                ft.Text(
                    t(
                        "skills.detail_enabled",
                        value=t("common.yes") if skill.enabled else t("common.no"),
                    )
                ),
                ft.Divider(),
                ft.Text(t("skills.schema_label"), weight=ft.FontWeight.BOLD),
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
            content.controls.append(ft.Text(t("skills.readme"), weight=ft.FontWeight.BOLD))
            content.controls.append(ft.Text(info["readme"], size=12, selectable=True))

        dialog = ft.AlertDialog(
            title=ft.Text(t("skills.skill_title", name=skill.name)),
            content=ft.Container(content=content, width=400, height=500),
            actions=[
                ft.TextButton(t("common.close"), on_click=lambda e: close_dialog(self.page, dialog))
            ],
        )
        open_dialog(self.page, dialog)

    def _export_skill(self, skill):
        """Export a skill package to the app's data dir (exports/).

        Android has no writable "Downloads" without extra permissions; the
        exports dir is app-private and always writable. File and package
        skills are both supported.
        """
        try:
            src = Path(skill.path) if getattr(skill, "path", None) else None
            if src is None or not src.exists():
                snack(self.page, t("skills.export_failed"), error=True)
                return
            export_dir = Path(self.app.settings.get_data_dir()) / "exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            dest = export_dir / skill.name
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            if src.is_file():
                shutil.copy2(src, dest)
            else:
                shutil.copytree(src, dest)
            snack(self.page, t("skills.exported_ok", path=str(dest)))
        except Exception as exc:
            logger.warning("Skill export failed for %r: %s", getattr(skill, "name", "?"), exc)
            snack(self.page, t("skills.export_failed"), error=True)

    def _confirm_remove_skill(self, skill):
        """Confirm skill removal"""

        def remove(e):
            self.skill_manager.remove_skill(skill.name)
            close_dialog(self.page, dialog)
            self._refresh()

        dialog = ft.AlertDialog(
            title=ft.Text(t("skills.remove_title")),
            content=ft.Text(t("skills.remove_confirm", name=skill.name)),
            actions=[
                ft.TextButton(
                    t("common.cancel"), on_click=lambda e: close_dialog(self.page, dialog)
                ),
                ft.Button(t("skills.remove"), color=ft.Colors.ERROR, on_click=remove),
            ],
        )
        open_dialog(self.page, dialog)

    def _refresh(self):
        """Refresh the skills view"""
        self.app.content_area.content = self.build()
        self.page.update()
