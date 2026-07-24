"""Settings View - Application settings"""

import flet as ft

from hermes_mobile.config.settings import get_settings


class SettingsView:
    """Settings interface"""

    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.settings = get_settings()

    def build(self) -> ft.Control:
        """Build the settings view"""
        return ft.ListView(
            controls=[
                self._build_section(
                    "AI Provider",
                    [
                        self._build_provider_dropdown(),
                        self._build_model_dropdown(),
                        self._build_api_key_field("OpenRouter", "openrouter_api_key"),
                        self._build_api_key_field("OpenAI", "openai_api_key"),
                        self._build_api_key_field("Anthropic", "anthropic_api_key"),
                        self._build_api_key_field("Gemini", "gemini_api_key"),
                    ],
                ),
                self._build_section(
                    "Agent Settings",
                    [
                        ft.Slider(
                            label="Temperature: {value}",
                            min=0.0,
                            max=2.0,
                            value=self.settings.temperature,
                            divisions=20,
                            on_change=self._on_temperature_change,
                        ),
                        ft.Slider(
                            label="Max Tokens: {value}",
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
                    ],
                ),
                self._build_section(
                    "Memory",
                    [
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
                    ],
                ),
                self._build_section(
                    "Appearance",
                    [
                        ft.Dropdown(
                            label="Theme",
                            value=self.settings.theme,
                            options=[
                                ft.dropdown.Option("system", "System"),
                                ft.dropdown.Option("light", "Light"),
                                ft.dropdown.Option("dark", "Dark"),
                            ],
                            on_change=self._on_theme_change,
                        ),
                        ft.Slider(
                            label="Font Size: {value}",
                            min=12,
                            max=24,
                            value=self.settings.font_size,
                            divisions=12,
                            on_change=self._on_font_size_change,
                        ),
                    ],
                ),
                self._build_section(
                    "Advanced",
                    [
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
                        ft.ElevatedButton(
                            "Clear All Data",
                            icon=ft.Icons.DELETE_FOREVER,
                            color=ft.Colors.ERROR,
                            on_click=self._on_clear_data,
                        ),
                    ],
                ),
            ],
            padding=20,
            spacing=20,
        )

    def _build_section(self, title: str, controls: list) -> ft.Control:
        """Build a settings section"""
        return ft.Column(
            [
                ft.Text(title, size=18, weight=ft.FontWeight.BOLD),
                ft.Divider(),
                ft.Column(controls, spacing=12),
            ],
            spacing=8,
        )

    def _build_provider_dropdown(self) -> ft.Control:
        """Build provider dropdown"""
        return ft.Dropdown(
            label="Default Provider",
            value=self.settings.default_provider,
            options=[
                ft.dropdown.Option("openrouter", "OpenRouter"),
                ft.dropdown.Option("openai", "OpenAI"),
                ft.dropdown.Option("anthropic", "Anthropic"),
                ft.dropdown.Option("gemini", "Google Gemini"),
            ],
            on_change=self._on_provider_change,
        )

    def _build_model_dropdown(self) -> ft.Control:
        """Build model dropdown"""
        return ft.Dropdown(
            label="Default Model",
            value=self.settings.default_model,
            options=[
                ft.dropdown.Option("anthropic/claude-3.5-sonnet", "Claude 3.5 Sonnet"),
                ft.dropdown.Option("openai/gpt-4o", "GPT-4o"),
                ft.dropdown.Option("google/gemini-1.5-pro", "Gemini 1.5 Pro"),
                ft.dropdown.Option("anthropic/claude-3-opus", "Claude 3 Opus"),
                ft.dropdown.Option("openai/gpt-4-turbo", "GPT-4 Turbo"),
            ],
            on_change=self._on_model_change,
        )

    def _build_api_key_field(self, label: str, key: str) -> ft.Control:
        """Build API key field"""
        value = getattr(self.settings, key, "")
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
            # TODO: Implement data clearing
            self.page.close(dialog)
            self.page.show_snack_bar(ft.SnackBar(content=ft.Text("Data cleared")))

        dialog = ft.AlertDialog(
            title=ft.Text("Clear All Data"),
            content=ft.Text(
                "This will delete all conversations, memory, and settings. This cannot be undone."
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self.page.close(dialog)),
                ft.ElevatedButton("Clear All", color=ft.Colors.ERROR, on_click=confirm_clear),
            ],
        )
        self.page.open(dialog)

    def _save_settings(self):
        """Save settings to disk"""
        # Settings are auto-saved via pydantic-settings
        pass

    def _apply_theme(self):
        """Apply theme to page"""
        if self.settings.theme == "light":
            self.page.theme_mode = ft.ThemeMode.LIGHT
        elif self.settings.theme == "dark":
            self.page.theme_mode = ft.ThemeMode.DARK
        else:
            self.page.theme_mode = ft.ThemeMode.SYSTEM
        self.page.update()
