"""Settings View - Application settings"""

import flet as ft

from hermes_mobile.config.settings import get_settings, save_settings
from hermes_mobile.locales import get_locale, set_locale, t
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
        self.settings = get_settings()

    def build(self) -> ft.Control:
        """Build the settings view"""
        dark = self.app.dark_mode

        return page_scaffold(
            [
                section_header(dark, t("settings.ai_provider"), t("settings.ai_provider_hint")),
                self._build_provider_dropdown(),
                self._build_model_dropdown(),
                self._build_api_key_field("OpenRouter", "openrouter_api_key"),
                self._build_api_key_field("OpenAI", "openai_api_key"),
                self._build_api_key_field("Gemini", "gemini_api_key"),
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

    def _build_provider_dropdown(self) -> ft.Control:
        """Build provider dropdown"""
        return ft.Dropdown(
            label="Default Provider",
            value=self.settings.default_provider,
            options=[
                ft.dropdown.Option(key="openrouter", text="OpenRouter"),
                ft.dropdown.Option(key="openai", text="OpenAI"),
                ft.dropdown.Option(key="gemini", text="Google Gemini"),
            ],
            on_select=self._on_provider_change,
        )

    def _build_model_dropdown(self) -> ft.Control:
        """Build model dropdown"""
        return ft.Dropdown(
            label="Default Model",
            value=self.settings.default_model,
            options=[
                ft.dropdown.Option(key="anthropic/claude-3.5-sonnet", text="Claude 3.5 Sonnet"),
                ft.dropdown.Option(key="openai/gpt-4o", text="GPT-4o"),
                ft.dropdown.Option(key="google/gemini-1.5-pro", text="Gemini 1.5 Pro"),
                ft.dropdown.Option(key="anthropic/claude-3-opus", text="Claude 3 Opus"),
                ft.dropdown.Option(key="openai/gpt-4-turbo", text="GPT-4 Turbo"),
            ],
            on_select=self._on_model_change,
        )

    def _build_api_key_field(self, label: str, key: str) -> ft.Control:
        """Build API key field"""
        value = getattr(self.settings, key, "") or ""
        return ft.TextField(
            label=f"{label} API Key",
            value=value,
            password=True,
            can_reveal_password=True,
            on_change=lambda e, k=key: self._on_api_key_change(k, e.control.value),
        )

    # Event handlers
    def _on_provider_change(self, e):
        self.settings.default_provider = e.control.value
        self._save_settings()

    def _on_model_change(self, e):
        self.settings.default_model = e.control.value
        self._save_settings()

    def _on_api_key_change(self, key: str, value: str):
        setattr(self.settings, key, value)
        self._save_settings()

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
        if self.settings.theme == "light":
            self.page.theme_mode = ft.ThemeMode.LIGHT
        elif self.settings.theme == "dark":
            self.page.theme_mode = ft.ThemeMode.DARK
        else:
            self.page.theme_mode = ft.ThemeMode.SYSTEM
        self.page.update()
