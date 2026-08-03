"""Tests for isolated MobileAgent delegation."""

from __future__ import annotations

import asyncio

import pytest

from hermes_mobile.core.agent import MobileAgent, ToolCall


@pytest.mark.asyncio
async def test_delegate_task_uses_isolated_child_and_blocks_recursion(monkeypatch):
    parent = MobileAgent()
    children: list[MobileAgent] = []

    async def fake_run(child, prompt, stream=True):
        children.append(child)
        assert stream is True
        assert "Context:\nshared" in prompt
        if child.on_tool_call:
            child.on_tool_call(ToolCall("web_search", {"query": "proof"}))
        yield "evidence"

    monkeypatch.setattr(MobileAgent, "run_conversation", fake_run)

    result = await parent._tool_delegate_task("audit release", context="shared")

    assert result["status"] == "completed"
    assert result["content"] == "evidence"
    assert result["tool_calls"] == ["web_search"]
    assert len(children) == 1
    child = children[0]
    assert child is not parent
    assert child.process_registry is not parent.process_registry
    assert child.memory_provider is None
    assert {"delegate_task", "delegate_tasks", "clarify", "cronjob", "memory"}.isdisjoint(
        child._builtin_tools
    )
    child_schemas = {schema["function"]["name"] for schema in child.get_tool_schemas()}
    assert {"delegate_task", "delegate_tasks", "clarify", "cronjob", "memory"}.isdisjoint(
        child_schemas
    )


@pytest.mark.asyncio
async def test_delegate_tasks_runs_three_children_concurrently(monkeypatch):
    parent = MobileAgent()
    active = 0
    peak_active = 0

    async def fake_run(child, prompt, stream=True):
        nonlocal active, peak_active
        active += 1
        peak_active = max(peak_active, active)
        await asyncio.sleep(0.03)
        active -= 1
        yield prompt.rsplit("\n", 1)[-1]

    monkeypatch.setattr(MobileAgent, "run_conversation", fake_run)

    result = await parent._tool_delegate_tasks(["one", "two", "three"], context="ctx")

    assert result["status"] == "completed"
    assert result["mode"] == "parallel"
    assert peak_active == 3
    assert [item["content"] for item in result["results"]] == ["one", "two", "three"]


@pytest.mark.asyncio
async def test_delegate_tasks_rejects_empty_or_excessive_fanout():
    agent = MobileAgent()

    assert "error" in await agent._tool_delegate_tasks([])
    assert "error" in await agent._tool_delegate_tasks(["1", "2", "3", "4"])
