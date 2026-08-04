from types import SimpleNamespace

import pytest

from hermes_mobile.config.settings import HermesMobileSettings
from hermes_mobile.providers import list_local_providers
from hermes_mobile.ui.settings_view import SettingsView


class Page:
    def __init__(self):
        self.updated = 0

    def update(self):
        self.updated += 1


class Agent:
    def __init__(self):
        self.routes = []

    def reconfigure(self, *, provider, model):
        self.routes.append((provider, model))


class RemoteClient:
    state = "open"

    def __init__(self):
        self.selected = []

    async def get_model_options(self, *, refresh=False):
        return {
            "providers": [
                {
                    "slug": "openai-codex",
                    "name": "OpenAI Codex",
                    "is_current": True,
                    "models": ["gpt-5.6-sol"],
                }
            ]
        }

    async def get_pet_gallery(self, *, local_only=False):
        return {
            "enabled": True,
            "active": "pool-dog",
            "pets": [
                {
                    "slug": "pool-dog",
                    "displayName": "Pool Dog",
                    "installed": local_only,
                }
            ],
        }

    async def select_pet(self, slug):
        self.selected.append(slug)
        return {"ok": True, "slug": slug}

    async def disable_pet(self):
        return {"ok": True}


def walk(control):
    yield control
    content = getattr(control, "content", None)
    if content is not None and not isinstance(content, str):
        yield from walk(content)
    for child in getattr(control, "controls", []) or []:
        yield from walk(child)


def texts(control):
    values = []
    for item in walk(control):
        for attr in ("value", "text", "label"):
            value = getattr(item, attr, None)
            if isinstance(value, str):
                values.append(value)
        for option in getattr(item, "options", []) or []:
            if isinstance(getattr(option, "text", None), str):
                values.append(option.text)
    return values


def make_app(tmp_path, *, remote=False):
    settings = HermesMobileSettings(
        data_dir=str(tmp_path),
        runtime_mode="remote" if remote else "local",
        default_provider="openrouter",
        default_model="anthropic/claude-3.5-sonnet",
    )
    app = SimpleNamespace(
        page=Page(),
        settings=settings,
        dark_mode=True,
        remote_model="gpt-5.6-sol" if remote else "",
        remote_client=RemoteClient() if remote else None,
        agent=Agent(),
        current_view="settings",
        content_area=SimpleNamespace(content=None),
    )
    app.pet_refreshes = 0

    async def refresh_pet():
        app.pet_refreshes += 1

    app.refresh_pet = refresh_pet
    return app


def test_local_settings_are_registry_driven_and_keys_use_encrypted_store(tmp_path):
    app = make_app(tmp_path)
    view = SettingsView(app)

    provider_dropdown = view._build_provider_dropdown()
    assert [option.key for option in provider_dropdown.options] == [
        profile.name for profile in list_local_providers()
    ]

    view._on_api_key_change("deepseek", "deep-secret")

    assert view.provider_secrets.get_key("deepseek") == "deep-secret"
    assert (
        "deep-secret" not in app.settings.settings_file().read_text()
        if app.settings.settings_file().exists()
        else True
    )
    assert app.agent.routes[-1] == ("openrouter", "anthropic/claude-3.5-sonnet")


@pytest.mark.asyncio
async def test_model_inventory_refresh_never_rewrites_configured_model(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    view = SettingsView(app)

    async def catalog(profile, api_key):
        return ["catalog/first", "catalog/second"]

    monkeypatch.setattr("hermes_mobile.ui.settings_view.fetch_provider_models", catalog)
    await view.refresh_local_models(force=True)

    assert app.settings.default_model == "anthropic/claude-3.5-sonnet"
    assert view._current_models()[0] == "anthropic/claude-3.5-sonnet"
    assert app.agent.routes == []


@pytest.mark.asyncio
async def test_model_inventory_sets_default_only_when_configuration_is_empty(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    app.settings.default_model = ""
    view = SettingsView(app)

    async def catalog(profile, api_key):
        return ["catalog/first", "catalog/second"]

    monkeypatch.setattr("hermes_mobile.ui.settings_view.fetch_provider_models", catalog)
    await view.refresh_local_models(force=True)

    assert app.settings.default_model == "catalog/first"
    assert app.agent.routes[-1] == ("openrouter", "catalog/first")


@pytest.mark.asyncio
async def test_remote_settings_use_backend_inventory_without_local_api_fields(tmp_path):
    app = make_app(tmp_path, remote=True)
    view = SettingsView(app)

    await view.refresh_remote_models()
    root = view.build()
    labels = texts(root)

    assert view.remote_providers[0]["slug"] == "openai-codex"
    assert "OpenAI Codex" in labels
    assert "gpt-5.6-sol" in labels
    assert not any("API Key" in value for value in labels)
    assert any("owned by the connected Hermes profile" in value for value in labels)


@pytest.mark.asyncio
async def test_remote_petdex_loads_selects_and_refreshes_global_pet(tmp_path):
    app = make_app(tmp_path, remote=True)
    view = SettingsView(app)

    await view.refresh_pet_gallery()
    event = SimpleNamespace(control=SimpleNamespace(value="pool-dog"))
    await view._on_pet_select(event)

    assert view.pet_gallery["active"] == "pool-dog"
    assert app.remote_client.selected == ["pool-dog"]
    assert app.pet_refreshes == 1
    assert "Pool Dog" in texts(view.build())
