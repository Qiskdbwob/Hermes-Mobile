"""UI regression tests for the P1-P3 front-end fixes.

Covers:
- The chat model picker opens a BottomSheet through ``page.show_dialog`` and
  no longer references ``ft.Icons.NONE`` / ``page.show_bottom_sheet``
  (both missing on Flet 0.86, which crashed the handler silently).
- ``/model`` and the model picker persist the selection via save_settings.
- Cron "Run now" executes off the UI thread and refreshes on the event loop.
- The gateway toggle persists ``gateway_enabled`` to settings.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, cast

import flet as ft
import pytest

from hermes_mobile.config.settings import HermesMobileSettings
from hermes_mobile.main import HermesMobileApp
from hermes_mobile.ui.cron_view import CronView
from hermes_mobile.ui.gateway_view import GatewayView


class FakePage:
    width = 430
    height = 844
    theme_mode = ft.ThemeMode.DARK

    def __init__(self):
        self.overlay = []
        self.dialogs = []
        self.updates = 0

    def update(self):
        self.updates += 1

    def show_dialog(self, dialog):
        self.dialogs.append(dialog)


def test_model_picker_opens_bottom_sheet_without_crashing():
    """Regression: ft.Icons.NONE and page.show_bottom_sheet do not exist on
    Flet 0.86; both previously raised inside the handler, so tapping the
    model pill did nothing."""
    page = FakePage()
    app = cast(Any, HermesMobileApp.__new__(HermesMobileApp))
    app.page = page  # page.theme_mode=DARK feeds the read-only dark_mode property
    app.remote_model = ""  # settings.runtime_mode defaults to local
    app.settings = SimpleNamespace(default_model="openai/gpt-4o", default_provider="openai")

    app._show_model_picker()

    assert len(page.dialogs) == 1
    assert isinstance(page.dialogs[0], ft.BottomSheet)
    assert page.updates >= 0  # no exception raised


@pytest.mark.asyncio
async def test_model_switch_persists_settings(tmp_path):
    """Regression: /model and the picker mutated settings in memory only."""
    page = FakePage()
    app = cast(Any, HermesMobileApp.__new__(HermesMobileApp))
    app.page = page  # page.theme_mode=DARK feeds the read-only dark_mode property
    app.remote_client = None  # settings.runtime_mode defaults to local
    app.settings = HermesMobileSettings(data_dir=str(tmp_path))
    app.agent = SimpleNamespace(model=None)

    await app._apply_model_switch("openai/gpt-4o")

    assert app.settings.default_model == "openai/gpt-4o"
    persisted = json.loads(app.settings.settings_file().read_text(encoding="utf-8"))
    assert persisted["default_model"] == "openai/gpt-4o"
    assert any(isinstance(control, ft.SnackBar) for control in page.overlay)


@pytest.mark.asyncio
async def test_cron_run_job_now_executes_and_refreshes_on_loop(monkeypatch):
    """Regression: run-now used a bare threading.Thread that mutated Flet
    controls from a non-UI thread."""
    import hermes_mobile.ui.cron_view as cron_view

    executed = []

    def fake_run(job_id):
        executed.append(job_id)
        return SimpleNamespace(status="success", duration=1.2)

    monkeypatch.setattr(cron_view, "run_job_now", fake_run)
    monkeypatch.setattr(cron_view, "get_ticker_status", lambda: {"running": True, "interval": 60})
    monkeypatch.setattr(cron_view, "list_jobs", lambda: [])

    page = FakePage()
    app = SimpleNamespace(
        page=page,
        dark_mode=True,
        content_area=SimpleNamespace(content=None),
    )
    view = CronView(app)
    job = SimpleNamespace(id="job-1")

    await view._run_job_now_async(job)

    assert executed == ["job-1"]
    assert app.content_area.content is not None  # _refresh ran
    assert any(isinstance(control, ft.SnackBar) for control in page.overlay)


@pytest.mark.asyncio
async def test_gateway_toggle_persists_gateway_enabled(tmp_path):
    """Regression: toggling the messaging gateway only mutated the in-memory
    config and reverted on restart."""
    settings = HermesMobileSettings(data_dir=str(tmp_path))
    page = FakePage()
    events = []

    class FakeGatewayManager:
        config = SimpleNamespace(enabled=False, port=8080, platforms=[], pairing_enabled=True)
        _running = False

        async def start(self):
            events.append("start")

        async def stop(self):
            events.append("stop")

    app = SimpleNamespace(
        page=page,
        settings=settings,
        dark_mode=True,
        remote_mode=False,
        remote_client=None,
        remote_status=None,
        remote_secret_store=SimpleNamespace(load=lambda: {}),
        gateway_manager=FakeGatewayManager(),
        chat_view=None,
        content_area=SimpleNamespace(content=None),
        current_view="messaging",
    )
    view = GatewayView(app)
    view.build()

    view._toggle_gateway(True)
    await asyncio.sleep(0)

    assert settings.gateway_enabled is True
    persisted = json.loads(settings.settings_file().read_text(encoding="utf-8"))
    assert persisted["gateway_enabled"] is True
    assert events == ["start"]
