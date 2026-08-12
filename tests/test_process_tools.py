"""Regression tests for terminal and background process management."""

from __future__ import annotations

import asyncio

import pytest

from hermes_mobile.core.agent import MobileAgent
from hermes_mobile.tools.process_tools import MobileProcessRegistry


@pytest.mark.asyncio
async def test_terminal_foreground_returns_output_and_exit_code():
    registry = MobileProcessRegistry()

    result = await registry.terminal("printf 'hello'")

    assert result == {"output": "hello", "stderr": "", "exit_code": 0}


@pytest.mark.asyncio
async def test_terminal_foreground_captures_stderr_separately():
    registry = MobileProcessRegistry()

    result = await registry.terminal("printf 'out'; printf 'err' >&2")

    assert result["output"] == "out"
    assert result["stderr"] == "err"
    assert result["exit_code"] == 0


@pytest.mark.asyncio
async def test_terminal_foreground_timeout_kills_process():
    registry = MobileProcessRegistry()

    result = await registry.terminal("sleep 5", timeout=1)

    assert "timed out after 1s" in result["error"]
    assert result["exit_code"] is not None


@pytest.mark.asyncio
async def test_background_process_poll_wait_and_log():
    registry = MobileProcessRegistry()
    started = await registry.terminal(
        "printf 'first\\n'; sleep 0.05; printf 'second\\n'",
        background=True,
    )
    session_id = started["session_id"]

    assert started["status"] == "running"
    await asyncio.sleep(0.02)
    first_poll = await registry.process("poll", session_id=session_id)
    assert "first" in first_poll["output"]

    waited = await registry.process("wait", session_id=session_id, timeout=2)
    assert waited["status"] == "exited"
    assert waited["exit_code"] == 0
    assert "second" in waited["output"]

    log = await registry.process("log", session_id=session_id, limit=10)
    assert log["output"].splitlines() == ["first", "second"]


@pytest.mark.asyncio
async def test_background_process_submit_and_close_stdin():
    registry = MobileProcessRegistry()
    started = await registry.terminal("read line; printf 'got:%s\\n' \"$line\"", background=True)
    session_id = started["session_id"]

    submitted = await registry.process("submit", session_id=session_id, data="answer")
    assert submitted["written"] == len("answer\n")

    waited = await registry.process("wait", session_id=session_id, timeout=2)
    assert waited["exit_code"] == 0
    assert "got:answer" in waited["output"]


@pytest.mark.asyncio
async def test_background_process_captures_stderr_separately():
    registry = MobileProcessRegistry()
    started = await registry.terminal(
        "printf 'o1'; printf 'e1' >&2; sleep 0.05; printf 'o2'; printf 'e2' >&2",
        background=True,
    )
    session_id = started["session_id"]

    awaited = await registry.process("wait", session_id=session_id, timeout=2)

    assert "o1" in awaited["output"] and "o2" in awaited["output"]
    assert "e1" in awaited["stderr"] and "e2" in awaited["stderr"]
    assert awaited["exit_code"] == 0


@pytest.mark.asyncio
async def test_background_process_kill_and_list():
    registry = MobileProcessRegistry()
    started = await registry.terminal("sleep 30", background=True)
    session_id = started["session_id"]

    listed = await registry.process("list")
    assert listed["sessions"][0]["session_id"] == session_id

    killed = await registry.process("kill", session_id=session_id)
    assert killed["killed"] is True
    assert killed["status"] == "exited"
    assert killed["exit_code"] is not None


@pytest.mark.asyncio
async def test_finished_sessions_are_evicted_after_retention(monkeypatch):
    import hermes_mobile.tools.process_tools as process_tools

    monkeypatch.setattr(process_tools, "SESSION_RETENTION_SECONDS", 0.0)
    registry = MobileProcessRegistry()
    # Keep the process alive long enough for wait() to run before it exits,
    # otherwise the prune inside wait() evicts it first (retention is 0).
    started = await registry.terminal("sleep 0.2 && printf 'done'", background=True)
    session_id = started["session_id"]

    awaited = await registry.process("wait", session_id=session_id, timeout=2)
    assert awaited["exit_code"] == 0

    await registry.process("list")  # prune runs on every registry call
    listed = await registry.process("list")
    assert all(s["session_id"] != session_id for s in listed["sessions"])


@pytest.mark.asyncio
async def test_session_cap_evicts_oldest_finished(monkeypatch):
    import hermes_mobile.tools.process_tools as process_tools

    monkeypatch.setattr(process_tools, "MAX_SESSIONS", 1)
    registry = MobileProcessRegistry()

    first = await registry.terminal("printf 'a'", background=True)
    await registry.process("wait", session_id=first["session_id"], timeout=2)

    second = await registry.terminal("printf 'b'", background=True)
    listed = await registry.process("list")
    ids = [s["session_id"] for s in listed["sessions"]]

    assert first["session_id"] not in ids
    assert second["session_id"] in ids


def test_agent_advertises_only_wired_terminal_process_tools():
    agent = MobileAgent()
    schemas = {schema["function"]["name"] for schema in agent.get_tool_schemas()}
    handlers = set(agent._builtin_tools)

    assert {"terminal", "process"} <= schemas
    # run_command was a redundant duplicate of terminal: not advertised to the
    # model (saves tokens on every API call) nor exposed as a builtin handler.
    assert "run_command" not in schemas
    assert "run_command" not in handlers
    assert schemas == handlers
