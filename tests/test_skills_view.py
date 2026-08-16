from types import SimpleNamespace
from unittest.mock import patch

import pytest

from hermes_mobile.config.settings import HermesMobileSettings
from hermes_mobile.ui.skills_view import SkillsView


class Page:
    def __init__(self):
        self.updated = 0

    def update(self):
        self.updated += 1


class RemoteClient:
    state = "open"

    async def get_remote_skills(self):
        return [
            {"name": "github", "description": "", "category": "GitHub"},
            {"name": "memory", "description": "", "category": "General"},
        ]


def _text_values(control):
    values = []
    value = getattr(control, "value", None)
    if isinstance(value, str):
        values.append(value)
    content = getattr(control, "content", None)
    if content is not None and not isinstance(content, str):
        values.extend(_text_values(content))
    for child in getattr(control, "controls", []) or []:
        values.extend(_text_values(child))
    return values


def make_app(tmp_path, client):
    return SimpleNamespace(
        page=Page(),
        settings=HermesMobileSettings(
            data_dir=str(tmp_path),
            runtime_mode="remote",
            remote_url="https://hermes.example.test",
            remote_profile="default",
        ),
        dark_mode=True,
        skill_manager=SimpleNamespace(get_all_skills=lambda: []),
        remote_client=client,
        current_view="skills",
        content_area=SimpleNamespace(content=None),
    )


@pytest.mark.asyncio
async def test_remote_skills_are_loaded_from_backend_catalog(tmp_path):
    app = make_app(tmp_path, RemoteClient())
    view = SkillsView(app)

    await view.refresh_remote()

    assert [row["name"] for row in view.remote_skills] == ["github", "memory"]
    assert "github" in _text_values(view.build())
    assert "memory" in _text_values(view.build())
    assert view.remote_error == ""


@pytest.mark.asyncio
async def test_remote_skills_offline_state_is_explicit(tmp_path):
    app = make_app(tmp_path, None)
    view = SkillsView(app)

    await view.refresh_remote()

    assert view.remote_skills == []
    assert "Connect to Hermes Remote" in view.remote_error
    assert "Remote skills unavailable" in _text_values(view.build())


def test_export_skill_copies_package_to_exports_dir(tmp_path):
    skill_dir = tmp_path / "skills" / "my_skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "main.py").write_text("async def execute(query): return query")
    (skill_dir / "skill.yaml").write_text("name: my_skill")

    app = make_app(tmp_path, None)
    view = SkillsView(app)
    skill = SimpleNamespace(name="my_skill", path=str(skill_dir))

    with patch("hermes_mobile.ui.skills_view.snack") as mock_snack:
        view._export_skill(skill)

    dest = tmp_path / "exports" / "my_skill"
    assert (dest / "main.py").read_text() == "async def execute(query): return query"
    assert (dest / "skill.yaml").exists()
    mock_snack.assert_called_once()
    assert "exports" in str(mock_snack.call_args[0][1])


def test_export_skill_missing_source_reports_error(tmp_path):
    app = make_app(tmp_path, None)
    view = SkillsView(app)
    skill = SimpleNamespace(name="ghost", path=str(tmp_path / "nope"))

    with patch("hermes_mobile.ui.skills_view.snack") as mock_snack:
        view._export_skill(skill)

    mock_snack.assert_called_once()
    assert mock_snack.call_args.kwargs.get("error") is True
