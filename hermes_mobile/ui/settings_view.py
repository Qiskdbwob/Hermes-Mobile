"""Settings View - Application settings"""

import flet as ft

from hermes_mobile.config.settings import save_settings
from hermes_mobile.locales import get_locale, set_locale, t
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
    snack,
)


class SettingsView:
    """Settings interface"""

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

    def build(self) -> ft.Control:
        """Build the settings view"""
        dark = self.app.dark_mode

        return page_scaffold(
            [
                section_header(dark, t("settings.ai_provider"), t("settings.ai_provider_hint")),
                *self._build_provider_controls(),
                section_header(dark, t("settings.agent_settings")),
                ft.Row(
                    [
                        ft.Icon(ft.Icons.THERMOSTAT, size=18),
                        ft.Text("Temperature", size=14),
                        ft.Container(expand=True),
                        ft.Text(
                            f"{self.settings.temperature:.1f}",
                            size=13,
                            color=ft.Colors.OUTLINE,
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Slider(
                    min=0.0,
                    max=2.0,
                    value=self.settings.temperature,
                    divisions=20,
                    on_change=self._on_temperature_change,
                ),
                ft.Row(
                    [
                        ft.Icon(ft.Icons.TOKEN, size=18),
                        ft.Text("Max Tokens", size=14),
                        ft.Container(expand=True),
                        ft.Text(str(self.settings.max_tokens), size=13, color=ft.Colors.OUTLINE),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Slider(
                    min=1024,
                    max=32768,
                    value=self.settings.max_tokens,
                    divisions=31,
                    on_change=self._on_max_tokens_change,
                ),
                ft.Switch(
                    label="Stream Responses",
                    value=self.settings.stream_responses,
                    on_change=self._on_stream_change,
                ),
                ft.Switch(
                    label="Show Tool Calls",
                    value=self.settings.show_tool_calls,
                    on_change=self._on_show_tools_change,
                ),
                section_header(dark, "Memory"),
                ft.Switch(
                    label="Enable Memory",
                    value=self.settings.memory_enabled,
                    on_change=self._on_memory_change,
                ),
                ft.Switch(
                    label="Encrypt Memory",
                    value=self.settings.encrypt_memory,
                    on_change=self._on_encrypt_change,
                ),
                ft.TextField(
                    label="Max Memory Entries",
                    value=str(self.settings.max_memory_entries),
                    keyboard_type=ft.KeyboardType.NUMBER,
                    on_change=self._on_max_memory_change,
                ),
                section_header(dark, t("settings.appearance")),
                ft.Dropdown(
                    label="Language",
                    value=get_locale(),
                    options=[
                        ft.dropdown.Option(key="en", text="English"),
                        ft.dropdown.Option(key="pt-br", text="Português"),
                    ],
                    on_select=self._on_language_change,
                ),
                ft.Dropdown(
                    label="Theme",
                    value=self.settings.theme,
                    options=[
                        ft.dropdown.Option(key="system", text="System"),
                        ft.dropdown.Option(key="light", text="Light"),
                        ft.dropdown.Option(key="dark", text="Dark"),
                    ],
                    on_select=self._on_theme_change,
                ),
                *self._build_pet_controls(),
                ft.Row(
                    [
                        ft.Icon(ft.Icons.FORMAT_SIZE, size=18),
                        ft.Text("Font Size", size=14),
                        ft.Container(expand=True),
                        ft.Text(str(self.settings.font_size), size=13, color=ft.Colors.OUTLINE),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Slider(
                    min=12,
                    max=24,
                    value=self.settings.font_size,
                    divisions=12,
                    on_change=self._on_font_size_change,
                ),
                section_header(dark, t("settings.advanced")),
                ft.TextField(
                    label="Request Timeout (s)",
                    value=str(self.settings.request_timeout),
                    keyboard_type=ft.KeyboardType.NUMBER,
                    on_change=self._on_timeout_change,
                ),
                ft.TextField(
                    label="Max Retries",
                    value=str(self.settings.max_retries),
                    keyboard_type=ft.KeyboardType.NUMBER,
                    on_change=self._on_retries_change,
                ),
                flat_button(
                    "Clear All Data",
                    ft.Icons.DELETE_FOREVER,
                    self._on_clear_data,
                    dark,
                    destructive=True,
                ),
            ],
            dark,
        )

    def _build_pet_controls(self) -> list[ft.Control]:
        if str(self.settings.runtime_mode) != "remote":
            return [
                ft.Text(
                    t("settings.pet_local_hint"),
                    size=12,
                    color=ft.Colors.OUTLINE,
                )
            ]
        pets = self.pet_gallery.get("pets") or []
        active = str(self.pet_gallery.get("active") or "")
        enabled = bool(self.pet_gallery.get("enabled"))
        status = self.pet_error or (
            t("settings.pet_loading")
            if self.pet_loading
            else t("settings.pet_count", count=len(pets))
        )
        return [
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
                value=bool(self.settings.pet_roam),
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
        if str(self.settings.runtime_mode) == "remote":
            return self._build_remote_provider_controls()
        profile = get_provider_profile(self.settings.default_provider)
        display = profile.display_name if profile else self.settings.default_provider
        key = self.provider_secrets.get_key(self.settings.default_provider)
        status = self.model_error or (
            t("settings.model_refreshing")
            if self.model_loading
            else t(
                "settings.model_count",
                count=len(self._current_models()),
                state=t("settings.api_saved") if key else t("settings.api_required"),
            )
        )
        return [
            self._build_provider_dropdown(),
            self._build_model_dropdown(),
            self._build_api_key_field(display, self.settings.default_provider),
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
        models = list(self.local_models.get(self.settings.default_provider) or [])
        selected = str(self.settings.default_model or "").strip()
        if selected and selected not in models:
            models.insert(0, selected)
        return models

    def _build_provider_dropdown(self) -> ft.Control:
        """Build provider dropdown"""
        return ft.Dropdown(
            label="Default Provider",
            value=self.settings.default_provider,
            options=[
                ft.dropdown.Option(key=profile.name, text=profile.display_name)
                for profile in self.local_profiles
            ],
            on_select=self._on_provider_change,
        )

    def _build_model_dropdown(self) -> ft.Control:
        """Build model dropdown"""
        return ft.Dropdown(
            label="Default Model",
            value=self.settings.default_model,
            options=[ft.dropdown.Option(key=model, text=model) for model in self._current_models()],
            on_select=self._on_model_change,
        )

    def _build_api_key_field(self, label: str, provider: str) -> ft.Control:
        """Build API key field"""
        return ft.TextField(
            label=f"{label} API Key",
            value=self.provider_secrets.get_key(provider),
            password=True,
            can_reveal_password=True,
            on_change=lambda e, p=provider: self._on_api_key_change(p, e.control.value),
        )

    # Event handlers
    async def _on_provider_change(self, e):
        provider = str(e.control.value or "")
        self.settings.default_provider = provider
        models = list(self.local_models.get(provider) or [])
        if self.settings.default_model not in models and models:
            self.settings.default_model = models[0]
        self.model_error = ""
        self._save_settings()
        self._reconfigure_agent()
        self._paint_current()
        await self.refresh_local_models(force=True)

    def _on_model_change(self, e):
        self.settings.default_model = str(e.control.value or "")
        self._save_settings()
        self._reconfigure_agent()

    def _on_api_key_change(self, provider: str, value: str):
        self.provider_secrets.save_key(provider, value)
        self._reconfigure_agent()

    async def _on_refresh_models(self, e=None):
        await self.refresh_local_models(force=True)

    async def _on_refresh_remote_models(self, e=None):
        await self.refresh_remote_models(force=True)

    async def refresh_local_models(self, *, force: bool = False) -> None:
        if str(self.settings.runtime_mode) == "remote":
            return
        provider = str(self.settings.default_provider)
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
            models = await fetch_provider_models(profile, self.provider_secrets.get_key(provider))
            self.local_models[provider] = models
            self._loaded_provider = provider
            if not str(self.settings.default_model or "").strip() and models:
                self.settings.default_model = models[0]
                self._save_settings()
                self._reconfigure_agent()
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
        self._paint_current()
        try:
            client = getattr(self.app, "remote_client", None)
            if client is None or client.state != "open":
                raise RuntimeError(t("settings.pet_connect"))
            local = await client.get_pet_gallery(local_only=True)
            if isinstance(local, dict):
                self.pet_gallery = local
                self._paint_current()
            full = await client.get_pet_gallery(local_only=False)
            if isinstance(full, dict):
                self.pet_gallery = full
        except Exception as exc:
            self.pet_error = str(exc).strip() or t("settings.pet_unavailable")
        finally:
            self.pet_loading = False
            self._paint_current()

    async def _on_pet_select(self, e) -> None:
        slug = str(e.control.value or "").strip()
        client = getattr(self.app, "remote_client", None)
        if not slug or client is None:
            return
        self.pet_loading = True
        self._paint_current()
        try:
            await client.select_pet(slug)
            refresh = getattr(self.app, "refresh_pet", None)
            if refresh is not None:
                await refresh()
            await self.refresh_pet_gallery(force=True)
        except Exception as exc:
            self.pet_error = str(exc).strip() or t("settings.pet_select_error")
        finally:
            self.pet_loading = False
            self._paint_current()

    async def _on_pet_enabled(self, e) -> None:
        client = getattr(self.app, "remote_client", None)
        if client is None:
            return
        try:
            if e.control.value:
                slug = str(self.pet_gallery.get("active") or "")
                if not slug:
                    raise RuntimeError(t("settings.pet_choose_first"))
                await client.select_pet(slug)
            else:
                await client.disable_pet()
            refresh = getattr(self.app, "refresh_pet", None)
            if refresh is not None:
                await refresh()
            await self.refresh_pet_gallery(force=True)
        except Exception as exc:
            self.pet_error = str(exc).strip() or t("settings.pet_update_error")
            self._paint_current()

    def _on_pet_roam(self, e) -> None:
        self.settings.pet_roam = bool(e.control.value)
        self._save_settings()
        pet = getattr(self.app, "pet_view", None)
        if pet is not None:
            pet.set_activity("idle")

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
        self.settings.temperature = e.control.value
        self._save_settings()

    def _on_max_tokens_change(self, e):
        self.settings.max_tokens = int(e.control.value)
        self._save_settings()

    def _on_stream_change(self, e):
        self.settings.stream_responses = e.control.value
        self._save_settings()

    def _on_show_tools_change(self, e):
        self.settings.show_tool_calls = e.control.value
        self._save_settings()

    def _on_memory_change(self, e):
        self.settings.memory_enabled = e.control.value
        self._save_settings()

    def _on_encrypt_change(self, e):
        self.settings.encrypt_memory = e.control.value
        self._save_settings()

    def _on_max_memory_change(self, e):
        try:
            self.settings.max_memory_entries = int(e.control.value)
            self._save_settings()
        except ValueError:
            pass

    def _on_theme_change(self, e):
        self.settings.theme = e.control.value
        self._save_settings()
        self._apply_theme()

    def _on_font_size_change(self, e):
        self.settings.font_size = int(e.control.value)
        self._save_settings()

    def _on_language_change(self, e):
        set_locale(e.control.value)
        self._save_settings()
        snack(self.page, "Language changed. Restart app to apply.")

    def _on_timeout_change(self, e):
        try:
            self.settings.request_timeout = int(e.control.value)
            self._save_settings()
        except ValueError:
            pass

    def _on_retries_change(self, e):
        try:
            self.settings.max_retries = int(e.control.value)
            self._save_settings()
        except ValueError:
            pass

    def _on_clear_data(self, e):
        """Show confirmation dialog for clearing data"""

        def confirm_clear(e):
            close_dialog(self.page, dialog)
            self._clear_data()
            snack(self.page, "Data cleared")

        dialog = ft.AlertDialog(
            title=ft.Text("Clear All Data"),
            content=ft.Text(
                "This will delete all conversations, memory, and settings. This cannot be undone."
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: close_dialog(self.page, dialog)),
                ft.Button("Clear All", color=ft.Colors.ERROR, on_click=confirm_clear),
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

    def _save_settings(self):
        """Persist settings to disk"""
        save_settings(self.settings)

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
