"""Hermes Mobile Configuration Management"""

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _get_default_data_dir() -> str:
    """Get the default data directory, handling Android sandbox paths"""
    try:
        home = Path.home()
        if home and home.exists():
            return str(home / ".hermes_mobile")
    except Exception:
        pass
    return str(Path.cwd() / ".hermes_mobile")


class HermesMobileSettings(BaseSettings):
    """Main settings for Hermes Mobile app"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App settings
    app_name: str = "Hermes Mobile"
    app_version: str = "0.1.0"
    debug: bool = False

    # Data directory
    data_dir: str = Field(default_factory=_get_default_data_dir)

    # AI Provider settings
    default_provider: str = "openrouter"
    openrouter_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None

    # Model settings
    default_model: str = "anthropic/claude-3.5-sonnet"
    fallback_models: list[str] = [
        "openai/gpt-4o",
        "anthropic/claude-3.5-sonnet",
        "google/gemini-1.5-pro",
    ]

    # Agent settings
    max_iterations: int = 20
    max_tokens: int = 8192
    temperature: float = 0.7
    system_prompt: str = """You are Hermes, a helpful AI assistant running on a mobile device.
You have access to various tools and can help with a wide range of tasks.
Be concise but thorough. Use tools when appropriate."""

    # Memory settings
    memory_enabled: bool = True
    memory_db_path: Optional[str] = None
    max_memory_entries: int = 10000
    memory_ttl_days: int = 30

    # Skills settings
    skills_enabled: bool = True
    skills_dir: Optional[str] = None
    auto_install_skills: bool = False

    # Cron/Scheduler settings
    cron_enabled: bool = True
    cron_check_interval_seconds: int = 60

    # Gateway settings
    gateway_enabled: bool = False
    gateway_port: int = 8080
    push_notifications_enabled: bool = True

    # UI settings
    theme: str = "system"  # light, dark, system
    language: str = "en"
    font_size: int = 16
    show_tool_calls: bool = True
    stream_responses: bool = True

    # Network settings
    request_timeout: int = 120
    max_retries: int = 3
    retry_delay: float = 1.0

    # Security
    encrypt_memory: bool = True
    biometric_auth: bool = False
    auto_lock_minutes: int = 5

    def get_data_dir(self) -> Path:
        """Get the data directory as a Path object"""
        path = Path(self.data_dir).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_skills_dir(self) -> Path:
        """Get the skills directory as a Path object"""
        if self.skills_dir:
            path = Path(self.skills_dir).expanduser()
        else:
            path = self.get_data_dir() / "skills"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_memory_db_path(self) -> Path:
        """Get the memory database path"""
        if self.memory_db_path:
            return Path(self.memory_db_path).expanduser()
        return self.get_data_dir() / "memory.db"

    def get_config_dir(self) -> Path:
        """Get the config directory"""
        path = self.get_data_dir() / "config"
        path.mkdir(parents=True, exist_ok=True)
        return path


# Global settings instance
settings = HermesMobileSettings()


def get_settings() -> HermesMobileSettings:
    """Get the global settings instance"""
    return settings


def reload_settings() -> HermesMobileSettings:
    """Reload settings from environment"""
    global settings
    settings = HermesMobileSettings()
    return settings
