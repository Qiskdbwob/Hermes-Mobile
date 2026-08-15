"""Settings View - Application settings"""

import flet as ft

from hermes_mobile.config.settings import save_settings
from hermes_mobile.locales import set_locale, t
from hermes_mobile.providers import (
    fetch_provider_models,
    get_provider_profile,
    list_local_providers,
)
from hermes_mobile.remote.secrets import ProviderSecretStore
from hermes_mobile.ui.common import (
    close_dialog,
    flat_button,
    open_dialog,
    page_scaffold,
    section_header,
    section_label,
    snack,
)
from hermes_mobile.ui.theme import mode_colors


class SettingsView:
    """Settings interface"""

    EDITABLE_FIELDS = (
        "default_provider",
        "default_model",
        "temperature",
        "max_tokens",
        "stream_responses",
        "show_tool_calls",
        "language",
        "theme",
        "pet_roam",
        "request_timeout",
        "max_retries",
    )
    TAB_FIELDS = {
        "provider": {"default_provider", "default_model"},
        "agent": {"temperature", "max_tokens", "stream_responses", "show_tool_calls"},
        "memory": set(),
        "appearance": {"language", "theme", "pet_roam"},
        "advanced": {"request_timeout", "max_retries"},
    }
    TAB_SPECS = (
        ("provider", "settings.tab_provider", ft.Icons.HUB_OUTLINED),
        ("agent", "settings.tab_agent", ft.Icons.TUNE),
        ("memory", "settings.tab_memory", ft.Icons.MEMORY),
        ("appearance", "settings.tab_appearance", ft.Icons.PALETTE_OUTLINED),
        ("advanced", "settings.tab_advanced", ft.Icons.SECURITY_OUTLINED),
    )

    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.settings = app.settings
        self.provider_secrets = ProviderSecretStore(self.settings.get_data_dir())
        self.local_profiles = list_local_providers()
        self.local_models = {
            profile.name: list(profile.fallback_models) for profile in self.local_profiles
        }
        self.model_loading = False
        self.model_error = ""
        self.remote_providers = []
        self._loaded_provider = ""
        self.pet_gallery = {"enabled": False, "active": "", "pets": []}
        self.pet_loading = False
        self.pet_error = ""
        self.active_tab = "provider"
        self._action_bar = None
        self._pending_label = None
        self._save_button = None
        self._discard_button = None
        self._key_baseline: dict[str, str] = {}
        self._draft_keys: dict[str, str] = {}
        self._pet_baseline = {"active": "", "enabled": False}
        self._draft_pet = dict(self._pet_baseline)
        self._reset_draft()

    def _settings_snapshot(self) -> dict[str, object]:
        return {field: getattr(self.settings, field) for field in self.EDITABLE_FIELDS}

    def _reset_draft(self) -> None:
        self.draft = self.settings.model_copy(deep=True)
        self._baseline = self._settings_snapshot()
        self._key_baseline = {}
        self._draft_keys = {}
        active = str(self.pet_gallery.get("active") or "")
        enabled = bool(self.pet_gallery.get("enabled"))
        self._pet_baseline = {"active": active, "enabled": enabled}
        self._draft_pet = dict(self._pet_baseline)

    def _sync_external_settings(self) -> None:
        if not self._dirty_count() and self._settings_snapshot() != self._baseline:
            self._reset_draft()

    def _draft_key(self, provider: str) -> str:
        provider = str(provider).strip().lower()
        if provider not in self._key_baseline:
            value = self.provider_secrets.get_key(provider)
            self._key_baseline[provider] = value
            self._draft_keys[provider] = value
        return self._draft_keys[provider]

    def _dirty_fields(self) -> set[str]:
        return {
            field
            for field in self.EDITABLE_FIELDS
            if getattr(self.draft, field) != self._baseline.get(field)
        }

    def _pet_is_dirty(self) -> bool:
        return self._draft_pet != self._pet_baseline

    def _dirty_count(self) -> int:
        key_changes = sum(
            self._draft_keys.get(provider, "") != value
            for provider, value in self._key_baseline.items()
        )
        pet_changes = sum(
            self._draft_pet.get(field) != self._pet_baseline.get(field)
            for field in ("active", "enabled")
        )
        return len(self._dirty_fields()) + key_changes + pet_changes

    def _dirty_domains(self) -> list[str]:
        changed = self._dirty_fields()
        domains = [key for key, fields in self.TAB_FIELDS.items() if changed & fields]
        if (
            any(
                self._draft_keys.get(provider, "") != value
                for provider, value in self._key_baseline.items()
            )
            and "provider" not in domains
        ):
            domains.append("provider")
        if self._pet_is_dirty() and "appearance" not in domains:
            domains.append("appearance")
        return domains

    def _mark_draft_changed(self) -> None:
        if self._action_bar is None:
            return
        dirty_count = self._dirty_count()
        if self._pending_label is not None:
            self._pending_label.value = (
                t("settings.pending_count", count=dirty_count)
                if dirty_count
                else t("settings.pending_none")
            )
        for button in (self._discard_button, self._save_button):
            if button is not None:
                button.disabled = not bool(dirty_count)
        if self._save_button is not None:
            self._save_button.style = self._save_action_style(bool(dirty_count))
        try:
            self._action_bar.update()
        except (AssertionError, AttributeError, RuntimeError):
            pass

    def _on_tab_change(self, tab: str) -> None:
        if tab not in self.TAB_FIELDS or tab == self.active_tab:
            return
        self.active_tab = tab
        self._paint_current()

    def build(self) -> ft.Control:
        """Build a tabbed, transactional settings workspace."""
        self._sync_external_settings()
        dark = self.app.dark_mode
        colors = mode_colors(dark)
        body = page_scaffold(self._build_active_tab(), dark)
        body.expand = True
        return ft.Column(
            [
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                t("settings.title"),
                                size=26,
                                weight=ft.FontWeight.W_700,
                                color=colors["foreground"],
                            ),
                            ft.Text(
                                t("settings.staged_hint"),
                                size=12,
                                color=colors["muted_foreground"],
                            ),
                        ],
                        spacing=2,
                    ),
                    padding=ft.Padding.only(left=16, right=16, top=16, bottom=10),
                ),
                self._build_tab_strip(),
                body,
                self._build_action_bar(),
            ],
            spacing=0,
            expand=True,
        )

    def _build_active_tab(self) -> list[ft.Control]:
        builders = {
            "provider": self._build_provider_tab,
            "agent": self._build_agent_tab,
            "memory": self._build_memory_tab,
            "appearance": self._build_appearance_tab,
            "advanced": self._build_advanced_tab,
        }
        return builders.get(self.active_tab, self._build_provider_tab)()

    def _build_provider_tab(self) -> list[ft.Control]:
        dark = self.app.dark_mode
        return [
            section_header(dark, t("settings.ai_provider"), t("settings.ai_provider_hint")),
            *self._build_provider_controls(),
        ]

    def _build_agent_tab(self) -> list[ft.Control]:
        dark = self.app.dark_mode
        return [
            section_header(dark, t("settings.agent_settings"), t("settings.agent_hint")),
            self._value_row(
                ft.Icons.THERMOSTAT, t("settings.temperature"), f"{self.draft.temperature:.1f}"
            ),
            ft.Slider(
                min=0.0,
                max=2.0,
                value=self.draft.temperature,
                divisions=20,
                label="{value}",
                on_change=self._on_temperature_change,
            ),
            self._value_row(ft.Icons.TOKEN, t("settings.max_tokens"), str(self.draft.max_tokens)),
            ft.Slider(
                min=1024,
                max=32768,
                value=self.draft.max_tokens,
                divisions=31,
                label="{value}",
                on_change=self._on_max_tokens_change,
            ),
            ft.Switch(
                label=t("settings.stream_responses"),
                value=self.draft.stream_responses,
                on_change=self._on_stream_change,
            ),
            ft.Switch(
                label=t("settings.show_tool_calls"),
                value=self.draft.show_tool_calls,
                on_change=self._on_show_tools_change,
            ),
        ]

    def _build_memory_tab(self) -> list[ft.Control]:
        dark = self.app.dark_mode
        provider = getattr(self.app, "memory_provider", None)
        return [
            section_header(dark, t("settings.memory"), t("settings.memory_hint")),
            self._value_row(
                ft.Icons.STORAGE_OUTLINED,
                t("settings.memory_storage"),
                t("settings.memory_available")
                if provider is not None
                else t("settings.memory_unavailable"),
            ),
            self._value_row(
                ft.Icons.LOCK_OUTLINE,
                t("settings.memory_encryption"),
                t("settings.memory_encryption_on")
                if self.settings.encrypt_memory
                else t("settings.memory_encryption_off"),
            ),
            ft.Text(
                t("settings.memory_managed_hint"),
                size=12,
                color=mode_colors(dark)["muted_foreground"],
            ),
            flat_button(
                t("settings.open_memory"),
                ft.Icons.ARROW_FORWARD,
                self._on_open_memory,
                dark,
            ),
        ]

    def _build_appearance_tab(self) -> list[ft.Control]:
        dark = self.app.dark_mode
        return [
            section_header(dark, t("settings.appearance"), t("settings.appearance_hint")),
            ft.Dropdown(
                label=t("settings.language"),
                value=self.draft.language,
                options=[
                    ft.dropdown.Option(key="en", text="English"),
                    ft.dropdown.Option(key="pt-br", text="Português"),
                ],
                on_select=self._on_language_change,
            ),
            ft.Dropdown(
                label=t("settings.theme"),
                value=self.draft.theme,
                options=[
                    ft.dropdown.Option(key="system", text=t("settings.system")),
                    ft.dropdown.Option(key="light", text=t("settings.light")),
                    ft.dropdown.Option(key="dark", text=t("settings.dark")),
                ],
                on_select=self._on_theme_change,
            ),
            *self._build_pet_controls(),
        ]

    def _build_advanced_tab(self) -> list[ft.Control]:
        dark = self.app.dark_mode
        return [
            section_header(dark, t("settings.advanced"), t("settings.advanced_hint")),
            ft.TextField(
                label=t("settings.request_timeout"),
                value=str(self.draft.request_timeout),
                keyboard_type=ft.KeyboardType.NUMBER,
                on_change=self._on_timeout_change,
            ),
            ft.TextField(
                label=t("settings.max_retries"),
                value=str(self.draft.max_retries),
                keyboard_type=ft.KeyboardType.NUMBER,
                on_change=self._on_retries_change,
            ),
            ft.Container(height=4),
            section_label(dark, t("settings.danger_zone")),
            ft.Text(
                t("settings.clear_data_hint"),
                size=12,
                color=mode_colors(dark)["muted_foreground"],
            ),
            flat_button(
                t("settings.clear_data"),
                ft.Icons.DELETE_FOREVER,
                self._on_clear_data,
                dark,
                destructive=True,
            ),
        ]

    def _value_row(self, icon, label: str, value: str) -> ft.Control:
        return ft.Row(
            [
                ft.Icon(icon, size=18),
                ft.Text(label, size=14),
                ft.Container(expand=True),
                ft.Text(value, size=13, color=mode_colors(self.app.dark_mode)["muted_foreground"]),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _build_tab_strip(self) -> ft.Control:
        colors = mode_colors(self.app.dark_mode)
        dirty_domains = set(self._dirty_domains())
        tabs = []
        for key, label_key, icon in self.TAB_SPECS:
            active = key == self.active_tab
            label = t(label_key) + (" •" if key in dirty_domains else "")
            tabs.append(
                ft.Button(
                    content=label,
                    icon=icon,
                    tooltip=t(label_key),
                    on_click=lambda e, tab=key: self._on_tab_change(tab),
                    elevation=0,
                    style=ft.ButtonStyle(
                        color=colors["primary"] if active else colors["muted_foreground"],
                        bgcolor=colors["accent"] if active else None,
                        side=ft.BorderSide(1, colors["primary"] if active else colors["border"]),
                        shape=ft.RoundedRectangleBorder(radius=7),
                    ),
                )
            )
        return ft.Container(
            content=ft.Row(tabs, spacing=8, run_spacing=8, wrap=True),
            padding=ft.Padding.symmetric(horizontal=16, vertical=8),
            border=ft.Border.only(bottom=ft.BorderSide(1, colors["border"])),
        )

    def _build_action_bar(self) -> ft.Control:
        dark = self.app.dark_mode
        colors = mode_colors(dark)
        dirty_count = self._dirty_count()
        self._pending_label = ft.Text(
            t("settings.pending_count", count=dirty_count)
            if dirty_count
            else t("settings.pending_none"),
            size=11,
            color=colors["muted_foreground"],
        )
        self._discard_button = flat_button(
            t("settings.discard"), ft.Icons.RESTART_ALT, self._on_discard, dark
        )
        self._save_button = flat_button(
            t("settings.save_changes"), ft.Icons.SAVE_OUTLINED, self._on_save, dark, primary=True
        )
        self._save_button.style = self._save_action_style(bool(dirty_count))
        for button in (self._discard_button, self._save_button):
            button.disabled = not bool(dirty_count)
            button.expand = True
        self._action_bar = ft.Container(
            content=ft.Column(
                [
                    self._pending_label,
                    ft.Row([self._discard_button, self._save_button], spacing=10),
                ],
                spacing=6,
            ),
            padding=ft.Padding.only(left=16, right=16, top=9, bottom=10),
            bgcolor=colors["sidebar"],
            border=ft.Border.only(top=ft.BorderSide(1, colors["sidebar_border"])),
        )
        return self._action_bar

    def _save_action_style(self, enabled: bool) -> ft.ButtonStyle:
        colors = mode_colors(self.app.dark_mode)
        background = colors["primary"] if enabled else colors["muted"]
        foreground = colors["primary_foreground"] if enabled else colors["muted_foreground"]
        border = colors["primary"] if enabled else colors["border"]
        return ft.ButtonStyle(
            color=foreground,
            bgcolor=background,
            shape=ft.RoundedRectangleBorder(radius=7),
            side=ft.BorderSide(1, border),
        )

    def _build_pet_controls(self) -> list[ft.Control]:
        dark = self.app.dark_mode
        colors = mode_colors(dark)
        title = section_label(dark, t("settings.pet_title"))
        if str(self.draft.runtime_mode) != "remote":
            return [
                title,
                ft.Row(
                    [
                        ft.Icon(ft.Icons.PETS_OUTLINED, size=20, color=colors["muted_foreground"]),
                        ft.Text(
                            t("settings.pet_local_hint"),
                            size=12,
                            color=colors["muted_foreground"],
                            expand=True,
                        ),
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ]
        pets = self.pet_gallery.get("pets") or []
        active = str(self._draft_pet.get("active") or "")
        enabled = bool(self._draft_pet.get("enabled"))
        status = self.pet_error or (
            t("settings.pet_loading")
            if self.pet_loading
            else t("settings.pet_count", count=len(pets))
        )
        return [
            title,
            ft.Dropdown(
                label=t("settings.pet_label"),
                value=active if active else None,
                options=[
                    ft.dropdown.Option(
                        key=str(item.get("slug") or ""),
                        text=str(item.get("displayName") or item.get("slug") or "Pet"),
                    )
                    for item in pets
                    if isinstance(item, dict) and item.get("slug")
                ],
                on_select=self._on_pet_select,
            ),
            ft.Switch(label=t("settings.pet_show"), value=enabled, on_change=self._on_pet_enabled),
            ft.Switch(
                label=t("settings.pet_roam"),
                value=bool(self.draft.pet_roam),
                on_change=self._on_pet_roam,
            ),
            ft.Row(
                [
                    flat_button(
                        t("settings.pet_refresh"),
                        ft.Icons.PETS,
                        self._on_refresh_pet_gallery,
                        self.app.dark_mode,
                    ),
                    ft.Text(status, size=11, color=ft.Colors.OUTLINE, expand=True),
                ]
            ),
        ]

    def _build_provider_controls(self) -> list[ft.Control]:
        if str(self.draft.runtime_mode) == "remote":
            return self._build_remote_provider_controls()
        profile = get_provider_profile(self.draft.default_provider)
        display = profile.display_name if profile else self.draft.default_provider
        keyless = profile is not None and not profile.requires_api_key
        key = self._draft_key(self.draft.default_provider)
        status = self.model_error or (
            t("settings.model_refreshing")
            if self.model_loading
            else t(
                "settings.model_count",
                count=len(self._current_models()),
                state=t("settings.api_saved")
                if key
                else (t("settings.api_optional") if keyless else t("settings.api_required")),
            )
        )
        provider = self._build_provider_dropdown()
        model = self._build_model_dropdown()
        # The key field is always present: even keyless runtimes (Ollama) may
        # sit behind a gateway that requires a token, so the user must be able
        # to type one. For keyless providers it is optional and the endpoint is
        # shown as a hint.
        api_key = self._build_api_key_field(display, self.draft.default_provider)
        for control in (provider, model, api_key):
            control.expand = True
        rows = [
            ft.Row([provider], spacing=0),
            ft.Row([model], spacing=0),
            ft.Row([api_key], spacing=0),
            ft.Row(
                [
                    flat_button(
                        t("settings.refresh_models"),
                        ft.Icons.REFRESH,
                        self._on_refresh_models,
                        self.app.dark_mode,
                        primary=True,
                    ),
                    ft.Text(status, size=11, color=ft.Colors.OUTLINE, expand=True),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        ]
        if keyless:
            url = profile.resolve_base_url() if profile else ""
            rows.insert(
                3,
                ft.Row(
                    [
                        ft.Text(
                            t("settings.api_optional_hint", url=url),
                            size=11,
                            color=ft.Colors.OUTLINE,
                        )
                    ],
                    spacing=0,
                ),
            )
        return rows

    def _build_remote_provider_controls(self) -> list[ft.Control]:
        rows = [row for row in self.remote_providers if isinstance(row, dict)]
        current = next((row for row in rows if row.get("is_current")), None)
        provider = str((current or {}).get("name") or (current or {}).get("slug") or "Remote")
        model = str(getattr(self.app, "remote_model", "") or t("settings.remote_model_placeholder"))
        status = self.model_error or (
            t("settings.remote_model_loading")
            if self.model_loading
            else t(
                "settings.remote_model_count",
                count=sum(len(row.get("models") or []) for row in rows),
            )
        )
        return [
            ft.TextField(label=t("settings.provider"), value=provider, read_only=True),
            ft.TextField(label=t("settings.model"), value=model, read_only=True),
            ft.Text(
                t("settings.remote_authority"),
                size=12,
                color=ft.Colors.OUTLINE,
            ),
            ft.Row(
                [
                    flat_button(
                        t("settings.refresh_remote_models"),
                        ft.Icons.REFRESH,
                        self._on_refresh_remote_models,
                        self.app.dark_mode,
                        primary=True,
                    ),
                    ft.Text(status, size=11, color=ft.Colors.OUTLINE, expand=True),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        ]

    def _current_models(self) -> list[str]:
        models = list(self.local_models.get(self.draft.default_provider) or [])
        selected = str(self.draft.default_model or "").strip()
        if selected and selected not in models:
            models.insert(0, selected)
        return models

    def _build_provider_dropdown(self) -> ft.Control:
        """Build provider dropdown"""
        return ft.Dropdown(
            label=t("settings.default_provider"),
            value=self.draft.default_provider,
            options=[
                ft.dropdown.Option(key=profile.name, text=profile.display_name)
                for profile in self.local_profiles
            ],
            on_select=self._on_provider_change,
        )

    def _build_model_dropdown(self) -> ft.Control:
        """Build model dropdown"""
        return ft.Dropdown(
            label=t("settings.default_model"),
            value=self.draft.default_model,
            options=[ft.dropdown.Option(key=model, text=model) for model in self._current_models()],
            on_select=self._on_model_change,
        )

    def _build_api_key_field(self, label: str, provider: str) -> ft.Control:
        """Build API key field"""
        return ft.TextField(
            label=t("settings.provider_api_key", provider=label),
            value=self._draft_key(provider),
            password=True,
            can_reveal_password=True,
            on_change=lambda e, p=provider: self._on_api_key_change(p, e.control.value),
        )

    # Event handlers
    async def _on_provider_change(self, e):
        provider = str(e.control.value or "")
        self.draft.default_provider = provider
        models = list(self.local_models.get(provider) or [])
        if self.draft.default_model not in models and models:
            self.draft.default_model = models[0]
        self.model_error = ""
        self._paint_current()
        await self.refresh_local_models(force=True)

    def _on_model_change(self, e):
        self.draft.default_model = str(e.control.value or "")
        self._mark_draft_changed()

    def _on_api_key_change(self, provider: str, value: str):
        provider = str(provider).strip().lower()
        self._draft_key(provider)
        self._draft_keys[provider] = str(value or "")
        self._mark_draft_changed()

    async def _on_refresh_models(self, e=None):
        await self.refresh_local_models(force=True)

    async def _on_refresh_remote_models(self, e=None):
        await self.refresh_remote_models(force=True)

    async def refresh_local_models(self, *, force: bool = False) -> None:
        if str(self.draft.runtime_mode) == "remote":
            return
        provider = str(self.draft.default_provider)
        if not force and provider == self._loaded_provider:
            return
        profile = get_provider_profile(provider)
        if profile is None:
            self.model_error = t("settings.unknown_provider", provider=provider)
            self._paint_current()
            return
        self.model_loading = True
        self.model_error = ""
        self._paint_current()
        try:
            models = await fetch_provider_models(profile, self._draft_key(provider))
            self.local_models[provider] = models
            self._loaded_provider = provider
            if not str(self.draft.default_model or "").strip() and models:
                self.draft.default_model = models[0]
        except Exception as exc:
            self.model_error = t("settings.model_catalog_unavailable", error=exc)
        finally:
            self.model_loading = False
            self._paint_current()

    async def refresh_remote_models(self, *, force: bool = False) -> None:
        if str(self.settings.runtime_mode) != "remote":
            return
        if not force and self.remote_providers:
            return
        self.model_loading = True
        self.model_error = ""
        self._paint_current()
        try:
            client = getattr(self.app, "remote_client", None)
            if client is None or client.state != "open":
                raise RuntimeError(t("settings.remote_models_connect"))
            payload = await client.get_model_options(refresh=force)
            providers = payload.get("providers") if isinstance(payload, dict) else None
            self.remote_providers = providers if isinstance(providers, list) else []
        except Exception as exc:
            self.model_error = str(exc).strip() or t("settings.remote_models_unavailable")
        finally:
            self.model_loading = False
            self._paint_current()

    async def _on_refresh_pet_gallery(self, e=None):
        await self.refresh_pet_gallery(force=True)

    async def refresh_pet_gallery(self, *, force: bool = False) -> None:
        if str(self.settings.runtime_mode) != "remote":
            return
        if not force and self.pet_gallery.get("pets"):
            return
        self.pet_loading = True
        self.pet_error = ""
        preserve_draft = self._pet_is_dirty()
        self._paint_current()
        try:
            client = getattr(self.app, "remote_client", None)
            if client is None or client.state != "open":
                raise RuntimeError(t("settings.pet_connect"))
            local = await client.get_pet_gallery(local_only=True)
            if isinstance(local, dict):
                self.pet_gallery = local
                if not preserve_draft:
                    self._pet_baseline = {
                        "active": str(local.get("active") or ""),
                        "enabled": bool(local.get("enabled")),
                    }
                    self._draft_pet = dict(self._pet_baseline)
                self._paint_current()
            full = await client.get_pet_gallery(local_only=False)
            if isinstance(full, dict):
                self.pet_gallery = full
                if not preserve_draft:
                    self._pet_baseline = {
                        "active": str(full.get("active") or ""),
                        "enabled": bool(full.get("enabled")),
                    }
                    self._draft_pet = dict(self._pet_baseline)
        except Exception as exc:
            self.pet_error = str(exc).strip() or t("settings.pet_unavailable")
        finally:
            self.pet_loading = False
            self._paint_current()

    async def _on_pet_select(self, e) -> None:
        slug = str(e.control.value or "").strip()
        if not slug:
            return
        self._draft_pet["active"] = slug
        self._draft_pet["enabled"] = True
        self._mark_draft_changed()

    async def _on_pet_enabled(self, e) -> None:
        enabled = bool(e.control.value)
        if enabled and not str(self._draft_pet.get("active") or ""):
            self.pet_error = t("settings.pet_choose_first")
            self._paint_current()
            return
        self.pet_error = ""
        self._draft_pet["enabled"] = enabled
        self._mark_draft_changed()

    def _on_pet_roam(self, e) -> None:
        self.draft.pet_roam = bool(e.control.value)
        self._mark_draft_changed()

    def _reconfigure_agent(self) -> None:
        agent = getattr(self.app, "agent", None)
        if agent is not None and hasattr(agent, "reconfigure"):
            agent.reconfigure(
                provider=self.settings.default_provider,
                model=self.settings.default_model,
            )

    def _paint_current(self) -> None:
        if getattr(self.app, "current_view", "") != "settings":
            return
        self.app.content_area.content = self.build()
        self.page.update()

    def _on_temperature_change(self, e):
        self.draft.temperature = float(e.control.value)
        self._mark_draft_changed()

    def _on_max_tokens_change(self, e):
        self.draft.max_tokens = int(e.control.value)
        self._mark_draft_changed()

    def _on_stream_change(self, e):
        self.draft.stream_responses = bool(e.control.value)
        self._mark_draft_changed()

    def _on_show_tools_change(self, e):
        self.draft.show_tool_calls = bool(e.control.value)
        self._mark_draft_changed()

    def _on_theme_change(self, e):
        self.draft.theme = str(e.control.value or "system")
        self._mark_draft_changed()

    def _on_language_change(self, e):
        self.draft.language = str(e.control.value or "en")
        self._mark_draft_changed()

    def _on_timeout_change(self, e):
        try:
            self.draft.request_timeout = int(e.control.value)
            self._mark_draft_changed()
        except ValueError:
            pass

    def _on_retries_change(self, e):
        try:
            self.draft.max_retries = int(e.control.value)
            self._mark_draft_changed()
        except ValueError:
            pass

    def _on_discard(self, e=None) -> None:
        if not self._dirty_count():
            return
        self._reset_draft()
        self._paint_current()
        snack(self.page, t("settings.discarded"))

    def _on_open_memory(self, e=None) -> None:
        switch_view = getattr(self.app, "_switch_view", None)
        if callable(switch_view):
            switch_view("memory")

    def _on_save(self, e=None) -> None:
        domains = self._dirty_domains()
        if not domains:
            return
        labels = [t(f"settings.tab_{domain}") for domain in domains]

        async def confirm_save(event):
            close_dialog(self.page, dialog)
            await self._commit_draft()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(t("settings.confirm_title")),
            content=ft.Column(
                [
                    ft.Text(t("settings.confirm_body")),
                    ft.Text(
                        t("settings.confirm_domains", domains=", ".join(labels)),
                        weight=ft.FontWeight.W_600,
                    ),
                    ft.Text(
                        t("settings.confirm_runtime"),
                        size=12,
                        color=mode_colors(self.app.dark_mode)["muted_foreground"],
                    ),
                ],
                tight=True,
                spacing=10,
            ),
            actions=[
                ft.TextButton(
                    t("settings.cancel"), on_click=lambda event: close_dialog(self.page, dialog)
                ),
                ft.Button(t("settings.save_changes"), on_click=confirm_save),
            ],
        )
        open_dialog(self.page, dialog)

    async def _apply_remote_pet_state(self, state: dict[str, object]) -> None:
        client = getattr(self.app, "remote_client", None)
        if client is None or getattr(client, "state", "") != "open":
            raise RuntimeError(t("settings.pet_connect"))
        if bool(state.get("enabled")):
            slug = str(state.get("active") or "")
            if not slug:
                raise RuntimeError(t("settings.pet_choose_first"))
            await client.select_pet(slug)
        else:
            await client.disable_pet()

    async def _commit_draft(self) -> bool:
        changed_fields = self._dirty_fields()
        changed_keys = {
            provider: self._draft_keys.get(provider, "")
            for provider, baseline in self._key_baseline.items()
            if self._draft_keys.get(provider, "") != baseline
        }
        pet_changed = self._pet_is_dirty()
        if not changed_fields and not changed_keys and not pet_changed:
            return True

        previous_settings = {field: getattr(self.settings, field) for field in changed_fields}
        previous_keys = {provider: self._key_baseline[provider] for provider in changed_keys}
        pet_applied = False
        try:
            if pet_changed:
                await self._apply_remote_pet_state(self._draft_pet)
                pet_applied = True
            for field in changed_fields:
                setattr(self.settings, field, getattr(self.draft, field))
            for provider, value in changed_keys.items():
                self.provider_secrets.save_key(provider, value)
            if not save_settings(self.settings):
                raise RuntimeError(t("settings.save_failed"))
        except Exception as exc:
            for field, value in previous_settings.items():
                setattr(self.settings, field, value)
            for provider, value in previous_keys.items():
                try:
                    self.provider_secrets.save_key(provider, value)
                except Exception:
                    pass
            save_settings(self.settings)
            if pet_applied:
                try:
                    await self._apply_remote_pet_state(self._pet_baseline)
                except Exception:
                    pass
            snack(self.page, t("settings.save_error", error=exc), error=True)
            return False

        route_changed = bool(
            changed_fields & {"default_provider", "default_model", "request_timeout", "max_retries"}
            or changed_keys
        )
        appearance_changed = bool(changed_fields & {"language", "theme"})
        roam_changed = "pet_roam" in changed_fields
        runtime_errors = []
        try:
            if route_changed:
                self._reconfigure_agent()
        except Exception as exc:
            runtime_errors.append(str(exc))
        try:
            if roam_changed:
                pet = getattr(self.app, "pet_view", None)
                if pet is not None:
                    pet.set_activity("idle")
            if pet_changed:
                refresh = getattr(self.app, "refresh_pet", None)
                if refresh is not None:
                    await refresh()
                await self.refresh_pet_gallery(force=True)
        except Exception as exc:
            runtime_errors.append(str(exc))
        try:
            if "language" in changed_fields:
                set_locale(self.settings.language)
        except Exception as exc:
            runtime_errors.append(str(exc))
        self._reset_draft()
        try:
            if appearance_changed:
                self._apply_theme()
            else:
                self._paint_current()
        except Exception as exc:
            runtime_errors.append(str(exc))
        if runtime_errors:
            snack(self.page, t("settings.saved_restart"), error=True)
        else:
            snack(self.page, t("settings.saved"))
        return True

    def _on_clear_data(self, e):
        """Show confirmation dialog for clearing data"""

        def confirm_clear(e):
            close_dialog(self.page, dialog)
            self._clear_data()
            self._reset_draft()
            snack(self.page, t("settings.data_cleared"))

        dialog = ft.AlertDialog(
            title=ft.Text(t("settings.clear_data")),
            content=ft.Text(t("settings.clear_confirm")),
            actions=[
                ft.TextButton(
                    t("settings.cancel"), on_click=lambda e: close_dialog(self.page, dialog)
                ),
                ft.Button(t("settings.clear_all"), color=ft.Colors.ERROR, on_click=confirm_clear),
            ],
        )
        open_dialog(self.page, dialog)

    def _clear_data(self):
        """Actually clear conversations, memory and persisted settings."""
        self.provider_secrets.clear()
        try:
            from hermes_mobile.memory.provider import MobileMemoryProvider

            provider = MobileMemoryProvider(
                db_path=self.settings.get_memory_db_path(),
                encrypt=self.settings.encrypt_memory,
            )
            provider.clear_all()
            provider.close()
        except Exception:
            pass
        try:
            sf = self.settings.settings_file()
            if sf.exists():
                sf.unlink()
        except Exception:
            pass

    def _apply_theme(self):
        """Apply theme to page"""
        apply_theme = getattr(self.app, "apply_theme", None)
        if callable(apply_theme):
            apply_theme(self.settings.theme)
            return
        if self.settings.theme == "light":
            self.page.theme_mode = ft.ThemeMode.LIGHT
        elif self.settings.theme == "dark":
            self.page.theme_mode = ft.ThemeMode.DARK
        else:
            self.page.theme_mode = ft.ThemeMode.SYSTEM
        self.page.update()
