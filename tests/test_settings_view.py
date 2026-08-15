from types import SimpleNamespace

import flet as ft
import pytest

from hermes_mobile.config.settings import HermesMobileSettings
from hermes_mobile.locales import get_locale, init
from hermes_mobile.providers import list_local_providers
from hermes_mobile.ui.settings_view import SettingsView


class Page:
    def __init__(self):
        self.updated = 0
        self.overlay = []
        self.dialogs = []

    def update(self):
        self.updated += 1

    def show_dialog(self, dialog):
        dialog.open = True
        self.dialogs.append(dialog)


class Agent:
    def __init__(self):
        self.routes = []

    def reconfigure(self, *, provider, model):
        self.routes.append((provider, model))


class RemoteClient:
    state = "open"

    def __init__(self):
        self.selected = []
        self.disabled = 0

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
            "enabled": False,
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
        self.disabled += 1
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
        for attr in ("value", "text", "label", "content"):
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
    app.theme_applied = []
    app.pet_view = SimpleNamespace(set_activity=lambda state: None)

    def apply_theme(theme):
        app.theme_applied.append(theme)

    async def refresh_pet():
        app.pet_refreshes += 1

    app.apply_theme = apply_theme
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

    assert view.provider_secrets.get_key("deepseek") == ""
    assert view._draft_key("deepseek") == "deep-secret"
    assert (
        "deep-secret" not in app.settings.settings_file().read_text()
        if app.settings.settings_file().exists()
        else True
    )
    assert app.agent.routes == []

    controls = view._build_provider_controls()
    assert all(isinstance(control, ft.Row) for control in controls[:3])
    assert all(control.controls[0].expand for control in controls[:3])
    view._on_tab_change("appearance")
    assert any(value.lower() == "petdex" for value in texts(view.build()))


def test_keyless_provider_keeps_optional_api_key_field_and_shows_endpoint(tmp_path):
    app = make_app(tmp_path)
    view = SettingsView(app)
    view.draft.default_provider = "ollama"

    controls = view._build_provider_controls()

    # The key field must stay available (optional) so the user can type a token
    # when a local gateway requires one.
    password_fields = [
        item
        for control in controls
        for item in walk(control)
        if isinstance(item, ft.TextField) and item.password
    ]
    assert len(password_fields) == 1
    assert any(
        "http://localhost:11434/v1" in label for control in controls for label in texts(control)
    )
    assert any("optional" in label.lower() for control in controls for label in texts(control))


def test_ollama_endpoint_field_editable(tmp_path):
    app = make_app(tmp_path)
    view = SettingsView(app)
    view.draft.default_provider = "ollama"

    controls = view._build_provider_controls()
    fields = [
        item for control in controls for item in walk(control) if isinstance(item, ft.TextField)
    ]
    endpoint = next((f for f in fields if f.label and "Endpoint" in f.label), None)
    assert endpoint is not None
    assert endpoint.value == ""

    endpoint.value = "http://192.168.1.20:11434"
    view._on_ollama_host_change(SimpleNamespace(control=endpoint))

    assert view.draft.ollama_host == "http://192.168.1.20:11434"
    assert view._dirty_count() > 0


@pytest.mark.asyncio
async def test_ollama_endpoint_commit_persists_and_reconfigures(tmp_path):
    app = make_app(tmp_path)
    view = SettingsView(app)
    view.draft.default_provider = "ollama"
    view.draft.default_model = "llama3.1:8b"
    view.draft.ollama_host = "http://192.168.1.20:11434"

    ok = await view._commit_draft()

    assert ok
    assert app.settings.ollama_host == "http://192.168.1.20:11434"
    assert app.agent.routes != []


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

    assert app.settings.default_model == ""
    assert view.draft.default_model == "catalog/first"
    assert app.agent.routes == []


@pytest.mark.asyncio
async def test_remote_settings_use_backend_inventory_without_local_api_fields(tmp_path):
    app = make_app(tmp_path, remote=True)
    view = SettingsView(app)

    await view.refresh_remote_models()
    provider_root = view.build()
    view._on_tab_change("appearance")
    appearance_root = view.build()
    root = ft.Column([provider_root, appearance_root])
    labels = texts(root)

    assert view.remote_providers[0]["slug"] == "openai-codex"
    assert any(value.lower() == "petdex" for value in labels)
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

    assert view._draft_pet == {"active": "pool-dog", "enabled": True}
    assert app.remote_client.selected == []
    assert app.pet_refreshes == 0
    assert await view._commit_draft()
    assert app.remote_client.selected == ["pool-dog"]
    assert app.pet_refreshes == 1
    view._on_tab_change("appearance")
    assert "Pool Dog" in texts(view.build())


def test_tabs_render_only_the_selected_domain_and_preserve_draft(tmp_path):
    app = make_app(tmp_path)
    view = SettingsView(app)

    provider_labels = texts(view.build())
    assert "Default Provider" in provider_labels
    assert "Temperature" not in provider_labels
    assert {"Provider", "Agent", "Memory", "Appearance", "Advanced"}.issubset(set(provider_labels))

    view._on_model_change(SimpleNamespace(control=SimpleNamespace(value="draft/model")))
    view._on_tab_change("agent")
    agent_labels = texts(view.build())

    assert "Temperature" in agent_labels
    assert "Default Provider" not in agent_labels
    assert view.draft.default_model == "draft/model"
    assert app.settings.default_model == "anthropic/claude-3.5-sonnet"
    assert view._dirty_domains() == ["provider"]


@pytest.mark.asyncio
async def test_commit_persists_once_and_reconfigures_once(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    view = SettingsView(app)
    saves = []

    def save(candidate):
        saves.append((candidate.default_model, candidate.temperature))
        return True

    monkeypatch.setattr("hermes_mobile.ui.settings_view.save_settings", save)
    view._on_model_change(SimpleNamespace(control=SimpleNamespace(value="openai/gpt-5")))
    view._on_temperature_change(SimpleNamespace(control=SimpleNamespace(value=0.4)))
    view._on_timeout_change(SimpleNamespace(control=SimpleNamespace(value="20")))
    view._on_api_key_change("openrouter", "staged-secret")

    assert app.settings.default_model == "anthropic/claude-3.5-sonnet"
    assert app.settings.temperature != 0.4
    assert view.provider_secrets.get_key("openrouter") == ""
    assert app.agent.routes == []

    assert await view._commit_draft()
    assert saves == [("openai/gpt-5", 0.4)]
    assert app.settings.default_model == "openai/gpt-5"
    assert app.settings.temperature == 0.4
    assert app.settings.request_timeout == 20
    assert view.provider_secrets.get_key("openrouter") == "staged-secret"
    assert app.agent.routes == [("openrouter", "openai/gpt-5")]
    assert view._dirty_count() == 0


@pytest.mark.asyncio
async def test_failed_commit_rolls_back_settings_and_secret(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    view = SettingsView(app)
    original_model = app.settings.default_model
    save_results = iter([False, True])
    monkeypatch.setattr(
        "hermes_mobile.ui.settings_view.save_settings", lambda candidate: next(save_results)
    )
    view._on_model_change(SimpleNamespace(control=SimpleNamespace(value="broken/model")))
    view._on_api_key_change("openrouter", "must-not-stick")

    assert not await view._commit_draft()
    assert app.settings.default_model == original_model
    assert view.provider_secrets.get_key("openrouter") == ""
    assert app.agent.routes == []
    assert view._dirty_count() == 2


def test_discard_and_save_confirmation_have_no_side_effects(tmp_path):
    app = make_app(tmp_path)
    view = SettingsView(app)
    view.build()
    disabled_style = view._save_button.style
    assert view._save_button.disabled is True
    original_theme = app.settings.theme
    view._on_theme_change(SimpleNamespace(control=SimpleNamespace(value="light")))

    assert app.settings.theme == original_theme
    assert app.theme_applied == []
    assert view._save_button.disabled is False
    assert view._save_button.style != disabled_style
    view._on_save()
    assert len(app.page.dialogs) == 1
    assert "Save settings" in str(app.page.dialogs[0].title.value)
    assert app.settings.theme == original_theme

    view._on_discard()
    assert view.draft.theme == original_theme
    assert view._dirty_count() == 0
    assert app.theme_applied == []


@pytest.mark.asyncio
async def test_appearance_applies_only_after_successful_save(tmp_path):
    init("en")
    try:
        app = make_app(tmp_path)
        view = SettingsView(app)
        view._on_language_change(SimpleNamespace(control=SimpleNamespace(value="pt-br")))
        view._on_theme_change(SimpleNamespace(control=SimpleNamespace(value="light")))

        assert app.settings.language == "en"
        assert app.settings.theme != "light"
        assert get_locale() == "en"
        assert app.theme_applied == []

        assert await view._commit_draft()
        assert app.settings.language == "pt-br"
        assert app.settings.theme == "light"
        assert get_locale() == "pt-br"
        assert app.theme_applied == ["light"]
    finally:
        init("en")
