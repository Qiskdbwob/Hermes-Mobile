"""Shared fixtures for Hermes Mobile tests."""

import os
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from hermes_mobile.config.settings import HermesMobileSettings, get_settings, reload_settings
from hermes_mobile.memory.provider import MobileMemoryProvider
from hermes_mobile.tools.path_security import get_allowed_directories


@pytest.fixture(autouse=True)
def _reset_settings() -> Generator:
    """Reset settings singleton before each test."""
    yield
    reload_settings()


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory for test data."""
    with tempfile.TemporaryDirectory(prefix="hermes_test_") as d:
        yield Path(d)


@pytest.fixture
def test_settings(temp_dir: Path) -> HermesMobileSettings:
    """Return settings configured for a temp data dir."""
    s = reload_settings()
    s.data_dir = str(temp_dir)
    s.memory_enabled = True
    s.memory_db_path = str(temp_dir / "test_memory.db")
    s.encrypt_memory = False  # Disable encryption for deterministic tests
    s.skills_enabled = True
    s.skills_dir = str(temp_dir / "skills")
    s.cron_enabled = False
    s.gateway_enabled = False
    s.debug = True
    return get_settings()


@pytest.fixture
def memory_provider(temp_dir: Path) -> Generator[MobileMemoryProvider, None, None]:
    """Provide a clean MemoryProvider for each test."""
    db_path = temp_dir / "memory.db"
    mp = MobileMemoryProvider(db_path=db_path, encrypt=False)
    try:
        yield mp
    finally:
        mp.close()
