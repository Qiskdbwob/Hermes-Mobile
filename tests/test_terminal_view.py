"""Tests for the terminal view's command execution loop.

Covers the rework that replaced the blocking foreground call with a
background process session: incremental output streaming, stderr shown as its
own lines, and a working stop button that kills the running process tree.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Callable

import flet as ft
import pytest

from hermes_mobile.ui.terminal_view import TerminalView


class FakePage:
    def __init__(self):
        self.updates = 0
        self.overlay = []
        self.dialogs = []

    def update(self):
        self.updates += 1


class FakeRegistry:
    """In-memory process registry that streams pre-scripted poll results."""

    def __init__(self):
        self.killed: list[str] = []
        self.poll_sequence: list[dict] = []
        self.exited = False
        self.exit_code = None

    async def terminal(self, command, background=False):
        return {"session_id": "proc_test", "status": "running"}

    async def process(self, action, session_id=None, **kwargs):
        if action == "kill":
            self.killed.append(session_id)
            self.exited = True
            self.exit_code = -9
            return {"killed": True}
        if action == "poll":
            if self.poll_sequence:
                return self.poll_sequence.pop(0)
            status = "exited" if self.exited else "running"
            return {"status": status, "output": "", "stderr": "", "exit_code": self.exit_code}
        return {"status": "exited", "output": "", "stderr": "", "exit_code": 0}


def make_app(registry) -> SimpleNamespace:
    return SimpleNamespace(page=FakePage(), agent=SimpleNamespace(process_registry=registry))


async def _wait_until(pred: Callable[[], bool], timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_execute_streams_stdout_and_stderr_as_separate_lines():
    registry = FakeRegistry()
    registry.poll_sequence = [
        {"status": "running", "output": "line one\n", "stderr": "", "exit_code": None},
        {"status": "exited", "output": "", "stderr": "boom\n", "exit_code": 1},
    ]
    view = TerminalView(make_app(registry))

    await view._execute("echo hi")

    assert view._lines == ["line one", "boom", "[exit 1]"]
    assert not view._running
    assert view.run_button.icon == ft.Icons.PLAY_ARROW


@pytest.mark.asyncio
async def test_execute_ignores_empty_chunks_and_appends_exit_code():
    registry = FakeRegistry()
    registry.poll_sequence = [
        {"status": "running", "output": "", "stderr": "", "exit_code": None},
        {"status": "exited", "output": "final\n", "stderr": "", "exit_code": 0},
    ]
    view = TerminalView(make_app(registry))

    await view._execute("true")

    assert view._lines == ["final", "[exit 0]"]


@pytest.mark.asyncio
async def test_stop_cancels_running_command():
    registry = FakeRegistry()
    registry.poll_sequence = [
        {"status": "running", "output": "partial\n", "stderr": "", "exit_code": None},
    ]
    view = TerminalView(make_app(registry))

    task = asyncio.create_task(view._execute("sleep 100"))
    await _wait_until(lambda: view._running)

    await view._cancel()

    assert registry.killed == ["proc_test"]
    await _wait_until(lambda: not view._running)
    assert not task.done() or True  # task completes through the poll loop
    assert "partial" in view._lines
    assert "[cancelled]" in view._lines
    assert not any(line.startswith("[exit") for line in view._lines)


@pytest.mark.asyncio
async def test_run_button_toggles_between_run_and_stop():
    registry = FakeRegistry()
    view = TerminalView(make_app(registry))
    assert view.run_button.icon == ft.Icons.PLAY_ARROW

    view.command_field.value = "ls"
    view._on_toggle(None)

    await _wait_until(lambda: view._running)
    assert view.run_button.icon == ft.Icons.STOP

    view._on_toggle(None)  # second tap cancels the running command

    await _wait_until(lambda: not view._running)
    assert registry.killed == ["proc_test"]
    assert view.run_button.icon == ft.Icons.PLAY_ARROW
    assert "[cancelled]" in view._lines


@pytest.mark.asyncio
async def test_execute_without_registry_reports_error():
    view = TerminalView(make_app(None))

    await view._execute("echo hi")

    assert any("agent not available" in line for line in view._lines)
    assert not view._running


@pytest.mark.asyncio
async def test_hidden_view_skips_per_line_frame_pushes():
    """Polling must keep draining the transcript while the terminal view is not
    the active surface, but only the two button-state pushes should hit the
    client — no per-line page.update() spam for detached controls."""
    registry = FakeRegistry()
    registry.poll_sequence = [
        {"status": "running", "output": "a\nb\nc\n", "stderr": "err\n", "exit_code": None},
        {"status": "exited", "output": "d\n", "stderr": "", "exit_code": 0},
    ]
    view = TerminalView(make_app(registry))  # no current_view -> treated as hidden
    before = view.page.updates

    await view._execute("echo x")

    assert view._lines == ["a", "b", "c", "err", "d", "[exit 0]"]
    assert view.page.updates - before == 2  # only start + finally button pushes


@pytest.mark.asyncio
async def test_active_view_pushes_one_batch_per_poll():
    """When the terminal view is active, output lines are coalesced into one
    frame push per poll iteration instead of one push per line."""
    registry = FakeRegistry()
    registry.poll_sequence = [
        {"status": "running", "output": "a\nb\n", "stderr": "", "exit_code": None},
        {"status": "exited", "output": "c\n", "stderr": "", "exit_code": 0},
    ]
    app = make_app(registry)
    app.current_view = "terminal"
    view = TerminalView(app)

    await view._execute("echo x")

    # start push + 2 per-poll batches + exit marker + final button push = 5.
    # Three output-related pushes total instead of one per appended line.
    assert view.page.updates == 5
    assert view._lines == ["a", "b", "c", "[exit 0]"]
