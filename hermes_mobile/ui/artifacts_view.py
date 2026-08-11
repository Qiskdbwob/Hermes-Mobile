"""Project-scoped Workspace and artifact browser for Hermes Mobile.

The previous view walked the entire application data directory. Besides being
confusing, that exposed transport credentials and scheduler state as if they
were user artifacts. The Workspace surface now mirrors Desktop's authority
model: a named project owns the working directory; only files inside that
project are browsable.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, List, Mapping, Optional

import flet as ft

from hermes_mobile.tools.project_tools import is_safe_project_name, resolve_project_directory
from hermes_mobile.ui.common import (
    MONO_FONT,
    close_dialog,
    empty_state,
    flat_button,
    open_dialog,
    page_header,
    section_label,
    snack,
)
from hermes_mobile.ui.theme import mode_colors

logger = logging.getLogger(__name__)

_MAX_FILES = 200
_MAX_PREVIEW = 12_000
_IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
_CODE_EXTENSIONS = {
    ".css",
    ".go",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".py",
    ".rs",
    ".sh",
    ".sql",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".xml",
    ".yaml",
    ".yml",
}
_DOC_EXTENSIONS = {".docx", ".md", ".pdf", ".rst", ".txt"}
_DATA_EXTENSIONS = {".csv", ".jsonl", ".parquet", ".tsv", ".xlsx"}
_MEDIA_EXTENSIONS = _IMAGE_EXTENSIONS | {".m4a", ".mov", ".mp3", ".mp4", ".wav"}
_PRIVATE_NAMES = {".credential-key", "credentials.bin"}


class ArtifactsView:
    """Mobile-first project switcher, file index, filters, and previews."""

    def __init__(self, app):
        self.app = app
        self.page = app.page
        # Renderer state belongs to this app instance. Using global
        # ``get_settings`` here previously made tests and alternate profiles
        # point at the wrong workspace.
        self.settings = app.settings
        self._query = ""
        self._active_kind = "all"
        self._body: Optional[ft.Container] = None
        self._search_field: Optional[ft.TextField] = None
        self.remote_projects: list[Mapping[str, Any]] = []
        self.remote_active_id: Optional[str] = None
        self.remote_project: Optional[Mapping[str, Any]] = None
        self.remote_loading = False
        self.remote_error = ""

    @property
    def projects_dir(self) -> Path:
        path = self.settings.get_data_dir() / "projects"
        if path.is_symlink():
            raise ValueError("Unsafe projects directory")
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def active_project(self) -> Optional[str]:
        marker = self.settings.get_data_dir() / "config" / "current_project.txt"
        try:
            name = marker.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        try:
            project = resolve_project_directory(self.projects_dir, name)
        except ValueError:
            return None
        if project is not None:
            return name
        return None

    @property
    def workspace(self) -> Path:
        """Return the active project root, never the private application root."""
        name = self.active_project
        return self.projects_dir / name if name else self.projects_dir

    def _project_names(self) -> List[str]:
        try:
            root = self.projects_dir
            return sorted(
                path.name
                for path in root.iterdir()
                if resolve_project_directory(root, path.name) is not None
            )
        except (OSError, ValueError):
            return []

    def build(self) -> ft.Control:
        dark = self.app.dark_mode
        remote = self._remote_connected()
        project = self.active_project
        if remote:
            subtitle = "Projects, repositories, and sessions from Hermes Remote"
        else:
            subtitle = (
                f"{project} · project files and agent outputs"
                if project
                else "Choose where Hermes should work"
            )
        action = ft.IconButton(
            icon=ft.Icons.REFRESH,
            icon_size=18,
            tooltip="Refresh workspace",
            on_click=lambda e: (
                asyncio.create_task(self.refresh_remote()) if remote else self._refresh()
            ),
        )
        body = self._build_remote_body() if remote else self._build_body()
        self._body = ft.Container(content=body, expand=True)
        return ft.Column(
            [page_header(dark, "Workspace", subtitle, action), self._body],
            expand=True,
            spacing=0,
        )

    def _remote_connected(self) -> bool:
        client = getattr(self.app, "remote_client", None)
        return bool(
            getattr(self.app, "remote_mode", False)
            and client is not None
            and getattr(client, "state", "") == "open"
        )

    def _build_remote_body(self) -> ft.Control:
        if self.remote_loading and not self.remote_projects and not self.remote_project:
            return self._remote_loading_state()
        if self.remote_error:
            return empty_state(
                self.app.dark_mode,
                "Could not load Remote workspaces",
                self.remote_error,
                ft.Icons.CLOUD_OFF_OUTLINED,
                flat_button(
                    "Try again",
                    ft.Icons.REFRESH,
                    lambda e: asyncio.create_task(self.refresh_remote()),
                    self.app.dark_mode,
                ),
            )
        if self.remote_project is not None:
            return self._build_remote_project_detail(self.remote_project)
        if not self.remote_projects:
            return empty_state(
                self.app.dark_mode,
                "No Remote workspaces yet",
                "Start a session inside a project or repository on Hermes Desktop and it will appear here.",
                ft.Icons.WORKSPACES_OUTLINED,
                flat_button(
                    "Refresh",
                    ft.Icons.REFRESH,
                    lambda e: asyncio.create_task(self.refresh_remote()),
                    self.app.dark_mode,
                ),
                branded=True,
            )

        total_sessions = sum(self._project_count(project) for project in self.remote_projects)
        controls: List[ft.Control] = [
            ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            "Remote workspaces",
                            size=19,
                            weight=ft.FontWeight.W_700,
                        ),
                        ft.Text(
                            "Open a project to see its repositories, branches, and conversation history.",
                            size=12,
                            color=mode_colors(self.app.dark_mode)["muted_foreground"],
                        ),
                    ],
                    spacing=3,
                ),
                padding=ft.Padding.only(top=6, bottom=3),
            ),
            section_label(
                self.app.dark_mode,
                "Projects",
                f"{len(self.remote_projects)} · {total_sessions} sessions",
            ),
        ]
        controls.extend(self._build_remote_project_row(project) for project in self.remote_projects)
        return ft.ListView(
            controls=controls,
            padding=ft.Padding.symmetric(horizontal=16, vertical=12),
            spacing=8,
            expand=True,
        )

    def _remote_loading_state(self) -> ft.Control:
        c = mode_colors(self.app.dark_mode)
        controls: List[ft.Control] = [
            section_label(self.app.dark_mode, "Syncing Remote workspaces")
        ]
        for index in range(5):
            controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Container(width=38, height=38, bgcolor=c["muted"], border_radius=9),
                            ft.Column(
                                [
                                    ft.Container(
                                        width=150 + index * 15,
                                        height=9,
                                        bgcolor=c["muted"],
                                        border_radius=4,
                                    ),
                                    ft.Container(
                                        width=215 - index * 8,
                                        height=7,
                                        bgcolor=c["muted"],
                                        border_radius=4,
                                    ),
                                ],
                                spacing=8,
                                expand=True,
                            ),
                        ],
                        spacing=10,
                    ),
                    padding=ft.Padding.symmetric(vertical=11),
                    border=ft.Border.only(bottom=ft.BorderSide(1, c["border"])),
                )
            )
        return ft.ListView(
            controls=controls,
            padding=ft.Padding.symmetric(horizontal=16, vertical=16),
            spacing=0,
            expand=True,
        )

    async def refresh_remote(self) -> None:
        client = getattr(self.app, "remote_client", None)
        if client is None or getattr(client, "state", "") != "open":
            self.remote_error = "Hermes Remote is offline. Reconnect from Connections."
            self._refresh_remote_body()
            return
        self.remote_loading = True
        self.remote_error = ""
        self.remote_project = None
        self._refresh_remote_body()
        try:
            result = await client.get_projects_tree()
            projects = result.get("projects") if isinstance(result, Mapping) else []
            self.remote_projects = (
                [item for item in projects if isinstance(item, Mapping)]
                if isinstance(projects, list)
                else []
            )
            active = result.get("active_id") if isinstance(result, Mapping) else None
            self.remote_active_id = str(active) if active else None
        except Exception as exc:
            self.remote_projects = []
            self.remote_error = str(exc)
        finally:
            self.remote_loading = False
            self._refresh_remote_body()

    async def _enter_remote_project(self, project_id: str) -> None:
        client = getattr(self.app, "remote_client", None)
        if client is None:
            return
        self.remote_loading = True
        self.remote_error = ""
        self._refresh_remote_body()
        try:
            project = await client.get_project_sessions(project_id)
            if project is None:
                raise RuntimeError("This workspace is no longer available")
            self.remote_project = project
        except Exception as exc:
            self.remote_error = str(exc)
        finally:
            self.remote_loading = False
            self._refresh_remote_body()

    def _refresh_remote_body(self) -> None:
        if self._body is not None:
            self._body.content = self._build_remote_body()
            try:
                self.page.update()
            except Exception:
                logger.debug("Could not update Remote workspaces", exc_info=True)

    @staticmethod
    def _project_count(project: Mapping[str, Any]) -> int:
        try:
            return int(project.get("sessionCount") or 0)
        except (TypeError, ValueError):
            return 0

    def _build_remote_project_row(self, project: Mapping[str, Any]) -> ft.Control:
        c = mode_colors(self.app.dark_mode)
        project_id = str(project.get("id") or "")
        label = str(project.get("label") or "Workspace")
        repos = project.get("repos") if isinstance(project.get("repos"), list) else []
        count = self._project_count(project)
        active = project_id == self.remote_active_id
        previews = (
            project.get("previewSessions")
            if isinstance(project.get("previewSessions"), list)
            else []
        )
        preview_titles = [
            str(item.get("title") or item.get("preview") or "Untitled session")
            for item in previews[:2]
            if isinstance(item, Mapping)
        ]
        if preview_titles:
            description = " · ".join(preview_titles)
        elif active:
            description = "Active project"
        elif project.get("isAuto"):
            description = "Automatically discovered workspace"
        else:
            description = "Named workspace"
        status = ft.Container(
            content=ft.Text(
                "ACTIVE",
                size=8,
                weight=ft.FontWeight.W_700,
                color=c["success"],
                font_family=MONO_FONT,
            ),
            padding=ft.Padding.symmetric(horizontal=5, vertical=2),
            border=ft.Border.all(1, c["success"]),
            border_radius=4,
            visible=active,
        )
        return ft.Container(
            content=ft.Row(
                [
                    self._file_lead(
                        ft.Icons.HOME_WORK_OUTLINED if active else ft.Icons.FOLDER_OUTLINED,
                        "folder",
                    ),
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text(
                                        label,
                                        size=14,
                                        weight=ft.FontWeight.W_600,
                                        max_lines=1,
                                        overflow=ft.TextOverflow.ELLIPSIS,
                                        expand=True,
                                    ),
                                    status,
                                ],
                                spacing=6,
                            ),
                            ft.Text(
                                description,
                                size=10.5,
                                color=c["muted_foreground"],
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ft.Text(
                                f"{self._counted(len(repos), 'repository')} · "
                                f"{self._counted(count, 'session')}",
                                size=9,
                                color=c["muted_foreground"],
                                font_family=MONO_FONT,
                            ),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, size=18, color=c["muted_foreground"]),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=8, vertical=9),
            bgcolor=c["accent"] if active else None,
            border=ft.Border.only(
                left=ft.BorderSide(3, c["primary"] if active else c["background"]),
                bottom=ft.BorderSide(1, c["border"]),
            ),
            border_radius=7,
            ink=True,
            on_click=lambda e, value=project_id: asyncio.create_task(
                self._enter_remote_project(value)
            ),
        )

    def _build_remote_project_detail(self, project: Mapping[str, Any]) -> ft.Control:
        c = mode_colors(self.app.dark_mode)
        label = str(project.get("label") or "Workspace")
        repos = project.get("repos") if isinstance(project.get("repos"), list) else []
        controls: List[ft.Control] = [
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.ARROW_BACK, size=18, color=c["muted_foreground"]),
                        ft.Text("All workspaces", size=12, color=c["muted_foreground"]),
                    ],
                    spacing=8,
                ),
                padding=ft.Padding.symmetric(horizontal=6, vertical=8),
                border_radius=7,
                ink=True,
                on_click=lambda e: self._leave_remote_project(),
            ),
            ft.Text(label, size=20, weight=ft.FontWeight.W_700, color=c["foreground"]),
            ft.Text(
                f"{self._counted(len(repos), 'repository')} · "
                f"{self._counted(self._project_count(project), 'session')}",
                size=11,
                color=c["muted_foreground"],
            ),
        ]
        for repo in repos:
            if not isinstance(repo, Mapping):
                continue
            repo_label = str(repo.get("label") or "Repository")
            controls.append(
                ft.Container(
                    content=section_label(
                        self.app.dark_mode,
                        repo_label,
                        self._counted(int(repo.get("sessionCount") or 0), "session"),
                    ),
                    padding=ft.Padding.only(top=14, bottom=3),
                )
            )
            groups = repo.get("groups") if isinstance(repo.get("groups"), list) else []
            if not groups:
                controls.append(
                    ft.Text(
                        "No sessions in this repository yet",
                        size=11,
                        color=c["muted_foreground"],
                    )
                )
            for group in groups:
                if isinstance(group, Mapping):
                    controls.extend(self._build_remote_lane(group))
        return ft.ListView(
            controls=controls,
            padding=ft.Padding.symmetric(horizontal=16, vertical=10),
            spacing=5,
            expand=True,
        )

    def _build_remote_lane(self, group: Mapping[str, Any]) -> List[ft.Control]:
        c = mode_colors(self.app.dark_mode)
        label = str(group.get("label") or "main")
        sessions = group.get("sessions") if isinstance(group.get("sessions"), list) else []
        controls: List[ft.Control] = [
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(
                            ft.Icons.HOME_OUTLINED if group.get("isHome") else ft.Icons.CALL_SPLIT,
                            size=14,
                            color=c["muted_foreground"],
                        ),
                        ft.Text(
                            label,
                            size=11,
                            weight=ft.FontWeight.W_600,
                            color=c["muted_foreground"],
                            expand=True,
                        ),
                        ft.Text(
                            str(len(sessions)),
                            size=9,
                            color=c["muted_foreground"],
                            font_family=MONO_FONT,
                        ),
                    ],
                    spacing=7,
                ),
                padding=ft.Padding.only(left=7, right=7, top=8, bottom=4),
            )
        ]
        controls.extend(
            self._build_remote_session_row(item) for item in sessions if isinstance(item, Mapping)
        )
        return controls

    def _build_remote_session_row(self, item: Mapping[str, Any]) -> ft.Control:
        c = mode_colors(self.app.dark_mode)
        session_id = str(item.get("id") or "")
        title = str(item.get("title") or item.get("preview") or "Untitled session")
        source = str(item.get("source") or "Hermes").replace("_", " ").title()
        try:
            count = int(item.get("message_count") or 0)
        except (TypeError, ValueError):
            count = 0
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.CHAT_BUBBLE_OUTLINE, size=15, color=c["muted_foreground"]),
                    ft.Column(
                        [
                            ft.Text(
                                title,
                                size=12.5,
                                weight=ft.FontWeight.W_500,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ft.Text(
                                f"{source} · {self._counted(count, 'message')}",
                                size=9.5,
                                color=c["muted_foreground"],
                            ),
                        ],
                        spacing=1,
                        expand=True,
                    ),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, size=16, color=c["muted_foreground"]),
                ],
                spacing=9,
            ),
            padding=ft.Padding.only(left=10, right=4, top=7, bottom=7),
            border=ft.Border.only(bottom=ft.BorderSide(1, c["border"])),
            border_radius=6,
            ink=True,
            on_click=lambda e, sid=session_id, name=title: asyncio.create_task(
                self.app.resume_remote_session(sid, name)
            ),
        )

    def _leave_remote_project(self) -> None:
        self.remote_project = None
        self.remote_error = ""
        self._refresh_remote_body()

    @staticmethod
    def _counted(count: int, singular: str) -> str:
        return f"{count} {singular if count == 1 else singular + 's'}"

    def _build_body(self) -> ft.Control:
        if not self.active_project:
            return self._build_project_picker()

        files = self._visible_files()
        controls: List[ft.Control] = [
            self._build_workspace_switcher(),
            self._build_search(),
            self._build_filters(),
            self._build_summary(),
        ]
        if not files:
            message = (
                "No files match this search. Try another name or filter."
                if self._query or self._active_kind != "all"
                else "Files Hermes creates in this project will appear here."
            )
            controls.append(
                empty_state(
                    self.app.dark_mode,
                    "No workspace files",
                    message,
                    ft.Icons.FOLDER_OPEN_OUTLINED,
                )
            )
        else:
            controls.extend(self._build_file_groups(files))
        return ft.ListView(
            controls=controls,
            padding=ft.Padding.only(left=14, right=14, top=12, bottom=24),
            spacing=12,
            expand=True,
        )

    def _build_project_picker(self) -> ft.Control:
        projects = self._project_names()
        if not projects:
            return empty_state(
                self.app.dark_mode,
                "Create your first workspace",
                "A workspace keeps each project, its files, and new chats in one clear place.",
                ft.Icons.WORKSPACES_OUTLINED,
                flat_button(
                    "New workspace",
                    ft.Icons.ADD,
                    lambda e: self._show_new_project_dialog(),
                    self.app.dark_mode,
                    primary=True,
                ),
                branded=True,
            )

        c = mode_colors(self.app.dark_mode)
        rows = [self._build_project_row(name, self.projects_dir / name) for name in projects]
        return ft.ListView(
            controls=[
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                "Choose a workspace",
                                size=19,
                                weight=ft.FontWeight.W_700,
                                color=c["foreground"],
                            ),
                            ft.Text(
                                "Hermes will scope new files and chats to the selected project.",
                                size=12,
                                color=c["muted_foreground"],
                            ),
                        ],
                        spacing=3,
                    ),
                    padding=ft.Padding.only(top=8, bottom=4),
                ),
                section_label(self.app.dark_mode, "Your workspaces", str(len(projects))),
                *rows,
                ft.Container(height=4),
                flat_button(
                    "New workspace",
                    ft.Icons.ADD,
                    lambda e: self._show_new_project_dialog(),
                    self.app.dark_mode,
                    primary=True,
                ),
            ],
            padding=ft.Padding.symmetric(horizontal=16, vertical=12),
            spacing=8,
            expand=True,
        )

    def _build_project_row(self, name: str, path: Path) -> ft.Control:
        c = mode_colors(self.app.dark_mode)
        try:
            count = sum(1 for item in path.rglob("*") if item.is_file())
        except OSError:
            count = 0
        return ft.Container(
            content=ft.Row(
                [
                    self._file_lead(ft.Icons.FOLDER_OUTLINED, "folder"),
                    ft.Column(
                        [
                            ft.Text(
                                name,
                                size=14,
                                weight=ft.FontWeight.W_600,
                                color=c["foreground"],
                            ),
                            ft.Text(
                                f"{count} file{'s' if count != 1 else ''}",
                                size=11,
                                color=c["muted_foreground"],
                            ),
                        ],
                        spacing=1,
                        expand=True,
                    ),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, size=18, color=c["muted_foreground"]),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=10, vertical=9),
            border=ft.Border.only(bottom=ft.BorderSide(1, c["border"])),
            border_radius=ft.BorderRadius.all(7),
            ink=True,
            on_click=lambda e, project=name: self._switch_project(project),
        )

    def _build_workspace_switcher(self) -> ft.Control:
        c = mode_colors(self.app.dark_mode)
        project = self.active_project or "Workspace"
        menu_items = [
            ft.PopupMenuItem(
                icon=ft.Icons.FOLDER_OUTLINED,
                content=name,
                on_click=lambda e, value=name: self._switch_project(value),
            )
            for name in self._project_names()
        ]
        menu_items.append(
            ft.PopupMenuItem(
                icon=ft.Icons.ADD,
                content="New workspace",
                on_click=lambda e: self._show_new_project_dialog(),
            )
        )
        return ft.Container(
            content=ft.Row(
                [
                    self._file_lead(ft.Icons.WORKSPACES_OUTLINED, "folder"),
                    ft.Column(
                        [
                            ft.Text(
                                project,
                                size=14,
                                weight=ft.FontWeight.W_600,
                                color=c["foreground"],
                            ),
                            ft.Text(
                                "Active workspace",
                                size=10,
                                color=c["muted_foreground"],
                            ),
                        ],
                        spacing=0,
                        expand=True,
                    ),
                    ft.PopupMenuButton(
                        icon=ft.Icons.SWAP_HORIZ,
                        tooltip="Switch workspace",
                        items=menu_items,
                    ),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            bgcolor=c["card"],
            border=ft.Border.all(1, c["border"]),
            border_radius=ft.BorderRadius.all(9),
        )

    def _build_search(self) -> ft.Control:
        c = mode_colors(self.app.dark_mode)
        self._search_field = ft.TextField(
            value=self._query,
            hint_text="Search this workspace",
            prefix_icon=ft.Icons.SEARCH,
            border=ft.InputBorder.NONE,
            text_size=13,
            content_padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            on_change=self._on_search,
        )
        return ft.Container(
            content=self._search_field,
            bgcolor=c["input"],
            border=ft.Border.all(1, c["border"]),
            border_radius=ft.BorderRadius.all(9),
        )

    def _build_filters(self) -> ft.Control:
        labels = (
            ("all", "All"),
            ("code", "Code"),
            ("docs", "Docs"),
            ("data", "Data"),
            ("media", "Media"),
        )
        return ft.ListView(
            controls=[self._filter_pill(key, label) for key, label in labels],
            horizontal=True,
            height=38,
            spacing=7,
        )

    def _filter_pill(self, key: str, label: str) -> ft.Control:
        c = mode_colors(self.app.dark_mode)
        selected = self._active_kind == key
        return ft.Container(
            content=ft.Text(
                label,
                size=11,
                weight=ft.FontWeight.W_600 if selected else ft.FontWeight.W_500,
                color=c["primary_foreground"] if selected else c["muted_foreground"],
            ),
            height=34,
            padding=ft.Padding.symmetric(horizontal=12, vertical=7),
            bgcolor=c["primary"] if selected else None,
            border=ft.Border.all(1, c["primary"] if selected else c["border"]),
            border_radius=ft.BorderRadius.all(18),
            ink=True,
            on_click=lambda e, value=key: self._set_kind(value),
        )

    def _build_summary(self) -> ft.Control:
        c = mode_colors(self.app.dark_mode)
        files = self._list_files()
        total = 0
        folders = set()
        for path in files:
            try:
                total += path.stat().st_size
            except OSError:
                pass
            parent = path.relative_to(self.workspace).parent
            if str(parent) != ".":
                folders.add(str(parent))
        return ft.Row(
            [
                section_label(self.app.dark_mode, "Files", str(len(files))),
                ft.Container(expand=True),
                ft.Text(
                    f"{len(folders)} folders · {self._fmt_size(total)}",
                    size=10,
                    color=c["muted_foreground"],
                    font_family=MONO_FONT,
                ),
            ],
            spacing=8,
        )

    def _build_file_groups(self, files: List[Path]) -> List[ft.Control]:
        grouped = {}
        for path in files:
            parent = path.relative_to(self.workspace).parent
            label = "Project root" if str(parent) == "." else str(parent)
            grouped.setdefault(label, []).append(path)
        controls: List[ft.Control] = []
        for label, paths in grouped.items():
            controls.append(section_label(self.app.dark_mode, label, str(len(paths))))
            controls.extend(self._build_file_row(path) for path in paths)
        return controls

    def _list_files(self) -> List[Path]:
        if not self.active_project:
            return []
        try:
            workspace = self.workspace.resolve(strict=True)
            files = [
                path
                for path in self.workspace.rglob("*")
                if path.is_file()
                and not path.is_symlink()
                and path.resolve(strict=True).is_relative_to(workspace)
                and path.name not in _PRIVATE_NAMES
                and not path.name.startswith(".env")
                and "__pycache__" not in path.parts
                and ".git" not in path.parts
                and path.suffix.lower() not in {".key", ".pyc"}
            ]
            files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
            return files[:_MAX_FILES]
        except (OSError, ValueError) as exc:
            logger.warning("Workspace listing failed: %s", exc)
            return []

    def _visible_files(self) -> List[Path]:
        query = self._query.strip().lower()
        files = []
        for path in self._list_files():
            if self._active_kind != "all" and self._kind_for(path) != self._active_kind:
                continue
            rel = str(path.relative_to(self.workspace)).lower()
            if query and query not in rel:
                continue
            files.append(path)
        return files

    def _build_file_row(self, path: Path) -> ft.Control:
        c = mode_colors(self.app.dark_mode)
        rel = path.relative_to(self.workspace)
        try:
            stat = path.stat()
            size = stat.st_size
            mtime = datetime.fromtimestamp(stat.st_mtime)
        except OSError:
            size = 0
            mtime = datetime.now()
        parent = str(rel.parent)
        location = "Project root" if parent == "." else parent
        return ft.Container(
            content=ft.Row(
                [
                    self._file_lead(self._icon_for(path), self._kind_for(path)),
                    ft.Column(
                        [
                            ft.Text(
                                path.name,
                                size=13,
                                weight=ft.FontWeight.W_600,
                                color=c["foreground"],
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ft.Text(
                                f"{location} · {self._fmt_size(size)} · {mtime.strftime('%b %d, %H:%M')}",
                                size=10,
                                color=c["muted_foreground"],
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, size=17, color=c["muted_foreground"]),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=8, vertical=8),
            border=ft.Border.only(bottom=ft.BorderSide(1, c["border"])),
            border_radius=ft.BorderRadius.all(6),
            ink=True,
            on_click=lambda e, selected=path: self._preview(selected),
        )

    def _file_lead(self, icon, kind: str) -> ft.Control:
        c = mode_colors(self.app.dark_mode)
        colors = {
            "code": c["primary"],
            "docs": c["foreground"],
            "data": c["success"],
            "media": c["ring"],
            "folder": c["primary"],
        }
        return ft.Container(
            content=ft.Icon(icon, size=18, color=colors.get(kind, c["muted_foreground"])),
            width=36,
            height=36,
            alignment=ft.Alignment.CENTER,
            bgcolor=c["muted"],
            border_radius=ft.BorderRadius.all(8),
        )

    def _preview(self, path: Path):
        c = mode_colors(self.app.dark_mode)
        try:
            workspace = self.workspace.resolve(strict=True)
            if path.is_symlink():
                raise ValueError("symlink")
            resolved = path.resolve(strict=True)
            if not resolved.is_file() or not resolved.is_relative_to(workspace):
                raise ValueError("outside workspace")
            rel = resolved.relative_to(workspace)
            path = resolved
        except (OSError, ValueError):
            snack(self.page, "This file is outside the active workspace.", error=True)
            return

        if path.suffix.lower() in _IMAGE_EXTENSIONS:
            try:
                preview = ft.Image(
                    src=path.read_bytes(),
                    fit=ft.BoxFit.CONTAIN,
                    filter_quality=ft.FilterQuality.HIGH,
                )
            except OSError as exc:
                preview = ft.Text(f"Could not read image: {exc}", color=c["destructive"])
        else:
            try:
                # Read at most _MAX_PREVIEW bytes; reading the whole file first
                # made previewing a large video/audio/binary file load it all
                # into memory (OOM risk on Android) before truncating.
                with open(path, "rb") as handle:
                    raw = handle.read(_MAX_PREVIEW)
                text = raw.decode("utf-8", errors="replace")
                if len(raw) >= _MAX_PREVIEW or path.stat().st_size > _MAX_PREVIEW:
                    text += "\n… (preview truncated)"
            except OSError as exc:
                text = f"Could not read file: {exc}"
            preview = ft.Text(
                text,
                size=11,
                font_family=MONO_FONT,
                color=c["foreground"],
                selectable=True,
            )

        width = max(280, min(620, (getattr(self.page, "width", 430) or 430) - 32))
        height = max(320, min(620, (getattr(self.page, "height", 844) or 844) - 220))
        dialog = ft.AlertDialog(
            title=ft.Column(
                [
                    ft.Text(path.name, size=16, weight=ft.FontWeight.W_700),
                    ft.Text(str(rel), size=10, color=c["muted_foreground"]),
                ],
                spacing=2,
            ),
            content=ft.Container(
                content=ft.ListView([preview], padding=8),
                width=width,
                height=height,
                bgcolor=c["input"],
                border=ft.Border.all(1, c["border"]),
                border_radius=ft.BorderRadius.all(8),
            ),
            actions=[ft.TextButton("Close", on_click=lambda e: close_dialog(self.page, dialog))],
        )
        open_dialog(self.page, dialog)

    def _show_new_project_dialog(self):
        field = ft.TextField(label="Workspace name", autofocus=True)

        def create(e):
            raw = str(field.value or "").strip()
            safe = "".join(char for char in raw if char.isalnum() or char in "-_ ").strip()
            if not safe:
                field.error_text = "Use letters or numbers"
                self.page.update()
                return
            path = self.projects_dir / safe
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                snack(self.page, f"Could not create workspace: {exc}", error=True)
                return
            close_dialog(self.page, dialog)
            self._switch_project(safe)

        dialog = ft.AlertDialog(
            title=ft.Text("New workspace"),
            content=ft.Column(
                [
                    ft.Text(
                        "Create a project-scoped home for files and new chats.",
                        size=12,
                    ),
                    field,
                ],
                tight=True,
                spacing=12,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: close_dialog(self.page, dialog)),
                ft.TextButton("Create", on_click=create),
            ],
        )
        open_dialog(self.page, dialog)

    def _switch_project(self, name: str):
        if not is_safe_project_name(name):
            snack(self.page, "Invalid workspace name", error=True)
            return
        project = resolve_project_directory(self.projects_dir, name)
        if project is None:
            snack(self.page, f"Workspace not found: {name}", error=True)
            return
        marker = self.settings.get_data_dir() / "config" / "current_project.txt"
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(name, encoding="utf-8")
        except OSError as exc:
            snack(self.page, f"Could not switch workspace: {exc}", error=True)
            return
        if getattr(self.app, "agent", None) is not None:
            self.app.agent._workspace = project
        self._query = ""
        self._active_kind = "all"
        self._refresh()
        snack(self.page, f"Workspace switched to {name}")

    def _on_search(self, event):
        self._query = str(event.control.value or "")
        self._refresh_body()

    def _set_kind(self, kind: str):
        self._active_kind = kind
        self._refresh_body()

    def _refresh_body(self):
        if self._body is not None:
            self._body.content = self._build_body()
            self.page.update()

    def _refresh(self):
        if getattr(self.app, "content_area", None) is not None:
            self.app.content_area.content = self.build()
            self.page.update()

    @staticmethod
    def _kind_for(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in _CODE_EXTENSIONS:
            return "code"
        if suffix in _DOC_EXTENSIONS:
            return "docs"
        if suffix in _DATA_EXTENSIONS:
            return "data"
        if suffix in _MEDIA_EXTENSIONS:
            return "media"
        return "other"

    @staticmethod
    def _icon_for(path: Path):
        kind = ArtifactsView._kind_for(path)
        return {
            "code": ft.Icons.CODE,
            "docs": ft.Icons.DESCRIPTION_OUTLINED,
            "data": ft.Icons.TABLE_CHART_OUTLINED,
            "media": ft.Icons.IMAGE_OUTLINED,
        }.get(kind, ft.Icons.INSERT_DRIVE_FILE_OUTLINED)

    @staticmethod
    def _fmt_size(size: float) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
