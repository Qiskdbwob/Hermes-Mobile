"""Regression tests for the project-scoped mobile Workspace surface."""

from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pytest

from hermes_mobile.config.settings import HermesMobileSettings
from hermes_mobile.ui.artifacts_view import ArtifactsView


class FakePage:
    width = 430
    height = 844
    overlay = []

    def update(self):
        pass


def walk_controls(control: ft.Control):
    seen = set()
    stack = [control]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        fields = set(getattr(type(current), "__dataclass_fields__", {}))
        fields.update({"controls", "content", "leading", "trailing", "title", "subtitle", "label"})
        for name in fields:
            try:
                value = getattr(current, name)
            except Exception:
                continue
            if isinstance(value, ft.Control):
                stack.append(value)
            elif isinstance(value, (list, tuple)):
                stack.extend(item for item in value if isinstance(item, ft.Control))


def make_app(tmp_path):
    settings = HermesMobileSettings(data_dir=str(tmp_path))
    return SimpleNamespace(
        page=FakePage(),
        settings=settings,
        dark_mode=True,
        content_area=SimpleNamespace(content=None),
        agent=SimpleNamespace(_workspace=None),
    )


def texts(root):
    return [
        str(control.value)
        for control in walk_controls(root)
        if isinstance(control, ft.Text) and control.value
    ]


def test_workspace_is_project_scoped_and_never_exposes_private_app_state(tmp_path):
    app = make_app(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.json").write_text("private")
    (tmp_path / "remote").mkdir()
    (tmp_path / "remote" / "credentials.bin").write_bytes(b"private")
    project = tmp_path / "projects" / "alpha"
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.py").write_text("print('safe')")
    (tmp_path / "config" / "current_project.txt").write_text("alpha")

    view = ArtifactsView(app)
    files = view._list_files()
    root = view.build()
    labels = texts(root)

    assert view.workspace == project
    assert [path.name for path in files] == ["main.py"]
    assert any("alpha" in label for label in labels)
    assert any("main.py" in label for label in labels)
    assert not any("settings.json" in label or "credentials.bin" in label for label in labels)
    assert not any(isinstance(control, ft.Card) for control in walk_controls(root))


def test_workspace_without_active_project_shows_project_picker_not_internal_files(tmp_path):
    app = make_app(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.json").write_text("private")
    (tmp_path / "projects" / "alpha").mkdir(parents=True)
    (tmp_path / "projects" / "beta").mkdir(parents=True)

    root = ArtifactsView(app).build()
    labels = texts(root)

    assert "Choose a workspace" in labels
    assert "alpha" in labels
    assert "beta" in labels
    assert not any("settings.json" in label for label in labels)


def test_tampered_project_marker_cannot_escape_projects_directory(tmp_path):
    app = make_app(tmp_path)
    config = tmp_path / "config"
    config.mkdir()
    (config / "settings.json").write_text("PRIVATE-CONFIG")
    (config / "current_project.txt").write_text("../config")
    (tmp_path / "projects").mkdir()

    view = ArtifactsView(app)

    assert view.active_project is None
    assert view._list_files() == []
    assert "settings.json" not in texts(view.build())


def test_workspace_ignores_file_and_directory_symlinks(tmp_path):
    app = make_app(tmp_path)
    config = tmp_path / "config"
    config.mkdir()
    (config / "secret.txt").write_text("TOP-SECRET")
    project = tmp_path / "projects" / "alpha"
    project.mkdir(parents=True)
    (config / "current_project.txt").write_text("alpha")
    (project / "linked-file.txt").symlink_to(config / "secret.txt")
    (project / "linked-directory").symlink_to(config, target_is_directory=True)
    (project / "safe.txt").write_text("SAFE")

    view = ArtifactsView(app)
    files = view._list_files()

    assert [path.name for path in files] == ["safe.txt"]
    assert view._preview(project / "linked-file.txt") is None


def test_workspace_filters_and_search_match_visible_project_files(tmp_path):
    app = make_app(tmp_path)
    project = tmp_path / "projects" / "alpha"
    project.mkdir(parents=True)
    (project / "main.py").write_text("print('x')")
    (project / "notes.md").write_text("notes")
    config = tmp_path / "config"
    config.mkdir()
    (config / "current_project.txt").write_text("alpha")
    view = ArtifactsView(app)

    view._active_kind = "code"
    assert [path.name for path in view._visible_files()] == ["main.py"]

    view._active_kind = "all"
    view._query = "notes"
    assert [path.name for path in view._visible_files()] == ["notes.md"]


@pytest.mark.asyncio
async def test_remote_workspace_uses_authoritative_project_tree_and_hydrated_lanes(tmp_path):
    app = make_app(tmp_path)
    calls = []

    class RemoteClient:
        state = "open"

        async def get_projects_tree(self):
            calls.append("tree")
            return {
                "active_id": "project-a",
                "projects": [
                    {
                        "id": "project-a",
                        "label": "Project A",
                        "sessionCount": 2,
                        "repos": [{"label": "repo", "sessionCount": 2}],
                        "previewSessions": [{"title": "Recent task"}],
                    }
                ],
            }

        async def get_project_sessions(self, project_id):
            calls.append(("project", project_id))
            return {
                "id": project_id,
                "label": "Project A",
                "sessionCount": 2,
                "repos": [
                    {
                        "label": "repo",
                        "sessionCount": 2,
                        "groups": [
                            {
                                "label": "main",
                                "isHome": True,
                                "sessions": [
                                    {
                                        "id": "session-a",
                                        "title": "Implement feature",
                                        "source": "desktop",
                                        "message_count": 12,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }

    app.remote_mode = True
    app.remote_client = RemoteClient()
    app.resume_remote_session = lambda session_id, title: None
    view = ArtifactsView(app)
    root = view.build()

    await view.refresh_remote()
    assert "Project A" in texts(view._body.content)
    assert "Recent task" in texts(view._body.content)
    assert "1 repository · 2 sessions" in texts(view._body.content)

    await view._enter_remote_project("project-a")
    labels = texts(view._body.content)
    assert "REPO" in labels
    assert "main" in labels
    assert "Implement feature" in labels
    assert calls == ["tree", ("project", "project-a")]
    assert root is not None
