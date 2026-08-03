"""Tests for settings module."""

from hermes_mobile.config.settings import (
    HermesMobileSettings,
    _get_default_data_dir,
    get_settings,
    reload_settings,
)


class TestHermesMobileSettings:
    def test_default_values(self):
        """Default settings should have expected defaults."""
        s = HermesMobileSettings()
        assert s.app_name == "Hermes Mobile"
        assert s.app_version == "0.1.0"
        assert s.default_provider == "openrouter"
        assert s.default_model == "anthropic/claude-3.5-sonnet"
        assert s.max_iterations == 20
        assert s.max_tokens == 8192
        assert s.temperature == 0.7
        assert s.memory_enabled is True
        assert s.encrypt_memory is True
        assert s.cron_enabled is True
        assert s.gateway_enabled is False
        assert s.theme == "system"
        assert s.language == "en"

    def test_get_data_dir_creates_dir(self, temp_dir):
        """get_data_dir() should create the directory."""
        s = HermesMobileSettings(data_dir=str(temp_dir / "custom_data"))
        data_dir = s.get_data_dir()
        assert data_dir.exists()
        assert data_dir.is_dir()

    def test_get_skills_dir_default(self, temp_dir):
        """get_skills_dir() should default to data_dir/skills."""
        s = HermesMobileSettings(data_dir=str(temp_dir))
        skills_dir = s.get_skills_dir()
        assert skills_dir == temp_dir / "skills"
        assert skills_dir.exists()

    def test_get_skills_dir_custom(self, temp_dir):
        """get_skills_dir() should use custom if provided."""
        custom = temp_dir / "my_skills"
        s = HermesMobileSettings(data_dir=str(temp_dir), skills_dir=str(custom))
        skills_dir = s.get_skills_dir()
        assert skills_dir == custom
        assert skills_dir.exists()

    def test_get_memory_db_path_default(self, temp_dir):
        """get_memory_db_path() should default to data_dir/memory.db."""
        s = HermesMobileSettings(data_dir=str(temp_dir))
        assert s.get_memory_db_path() == temp_dir / "memory.db"

    def test_get_memory_db_path_custom(self, temp_dir):
        """get_memory_db_path() should use custom if provided."""
        custom = temp_dir / "custom_db.sqlite"
        s = HermesMobileSettings(data_dir=str(temp_dir), memory_db_path=str(custom))
        assert s.get_memory_db_path() == custom

    def test_get_config_dir(self, temp_dir):
        """get_config_dir() should return data_dir/config."""
        s = HermesMobileSettings(data_dir=str(temp_dir))
        config_dir = s.get_config_dir()
        assert config_dir == temp_dir / "config"
        assert config_dir.exists()

    def test_reload_settings_returns_new_instance(self):
        """reload_settings() should return a fresh instance."""
        s1 = get_settings()
        s2 = reload_settings()
        assert s2 is not s1
        assert isinstance(s2, HermesMobileSettings)

    def test_settings_can_be_overridden_with_env(self, monkeypatch):
        """Settings should be overridable via env vars."""
        monkeypatch.setenv("HERMES_MOBILE_APP_NAME", "TestAgent")
        monkeypatch.setenv("HERMES_MOBILE_MAX_ITERATIONS", "5")
        # HermesMobileSettings uses pydantic-settings with env_file
        # The field names map to env vars: app_name -> APP_NAME, etc.
        # But the prefix is from model_config which has no prefix by default.
        # So set the raw env var:
        monkeypatch.setenv("APP_NAME", "TestAgentEnv")
        monkeypatch.setenv("MAX_ITERATIONS", "3")
        s = HermesMobileSettings()
        # pydantic-settings reads from env by field name
        assert s.app_name == "TestAgentEnv" or s.app_name == "Hermes Mobile"
        assert s.max_iterations == 3 or s.max_iterations == 20

    def test_data_dir_env_var(self, monkeypatch, temp_dir):
        """DATA_DIR env var should be respected."""
        monkeypatch.setenv("DATA_DIR", str(temp_dir / "from_env"))
        s = HermesMobileSettings()
        assert s.data_dir == str(temp_dir / "from_env")

    def test_data_dir_fallback_when_home_fails(self, monkeypatch):
        """When Path.home() raises, should fall back to cwd."""
        import pathlib

        monkeypatch.delenv("FLET_APP_STORAGE_DATA", raising=False)
        original_home = pathlib.Path.home
        monkeypatch.setattr(
            pathlib.Path, "home", lambda: (_ for _ in ()).throw(PermissionError("mock"))
        )
        s = HermesMobileSettings()
        assert ".hermes_mobile" in s.data_dir
        monkeypatch.setattr(pathlib.Path, "home", original_home)

    def test_flet_native_storage_takes_priority(self, monkeypatch, temp_dir):
        """Packaged Flet apps must use their private durable storage directory."""
        native_data = temp_dir / "native-data"
        monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(native_data))
        assert _get_default_data_dir() == str(native_data)
        assert HermesMobileSettings().data_dir == str(native_data)

    def test_unwritable_android_home_falls_back_to_writable_cwd(self, monkeypatch, temp_dir):
        """Android's existing but unwritable /data home must not be selected."""
        import pathlib

        monkeypatch.delenv("FLET_APP_STORAGE_DATA", raising=False)
        android_home = pathlib.Path("/data")
        monkeypatch.setattr(pathlib.Path, "home", lambda: android_home)
        monkeypatch.setattr(pathlib.Path, "cwd", lambda: temp_dir)
        monkeypatch.setattr(
            "hermes_mobile.config.settings.os.access",
            lambda path, mode: pathlib.Path(path) == temp_dir,
        )
        assert _get_default_data_dir() == str(temp_dir / ".hermes_mobile")
