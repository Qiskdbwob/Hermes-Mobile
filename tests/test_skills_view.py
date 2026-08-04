from types import SimpleNamespace

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
