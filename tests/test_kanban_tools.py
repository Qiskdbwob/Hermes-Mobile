"""Tests for the kanban board tools."""

import pytest

from hermes_mobile.tools import kanban_tools


@pytest.fixture
def isolated_board(tmp_path, monkeypatch):
    """Point the kanban board file at a temp location per test."""
    monkeypatch.setattr(kanban_tools, "_board_file", lambda: tmp_path / "kanban.json")


@pytest.mark.asyncio
async def test_create_and_show(isolated_board):
    r = await kanban_tools.kanban_create_tool("task one", "desc", column="backlog")
    assert r["task"]["column"] == "backlog"
    tid = r["task"]["id"]
    shown = await kanban_tools.kanban_show_tool(tid)
    assert shown["task"]["title"] == "task one"
    assert shown["task"]["description"] == "desc"


@pytest.mark.asyncio
async def test_create_requires_title(isolated_board):
    r = await kanban_tools.kanban_create_tool("   ")
    assert "title" in r["error"]


@pytest.mark.asyncio
async def test_create_rejects_bad_column(isolated_board):
    r = await kanban_tools.kanban_create_tool("x", column="nope")
    assert "Unknown column" in r["error"]


@pytest.mark.asyncio
async def test_move_complete_block_flow(isolated_board):
    r = await kanban_tools.kanban_create_tool("flow")
    tid = r["task"]["id"]

    moved = await kanban_tools.kanban_move_tool(tid, "in_progress")
    assert moved["task"]["column"] == "in_progress"

    blocked = await kanban_tools.kanban_block_tool(tid, "waiting")
    assert blocked["task"]["blocked"] is True
    assert blocked["task"]["block_reason"] == "waiting"

    unblocked = await kanban_tools.kanban_unblock_tool(tid)
    assert unblocked["task"]["blocked"] is False

    done = await kanban_tools.kanban_complete_tool(tid)
    assert done["task"]["column"] == "done"


@pytest.mark.asyncio
async def test_comment(isolated_board):
    r = await kanban_tools.kanban_create_tool("commentable")
    tid = r["task"]["id"]
    commented = await kanban_tools.kanban_comment_tool(tid, "first")
    assert len(commented["task"]["comments"]) == 1
    assert commented["task"]["comments"][0]["text"] == "first"
    # empty comment refused
    bad = await kanban_tools.kanban_comment_tool(tid, "  ")
    assert "text" in bad["error"]


@pytest.mark.asyncio
async def test_list_filter_and_missing(isolated_board):
    await kanban_tools.kanban_create_tool("a", column="backlog")
    await kanban_tools.kanban_create_tool("b", column="done")
    all_tasks = await kanban_tools.kanban_list_tool()
    assert len(all_tasks["tasks"]) == 2
    done = await kanban_tools.kanban_list_tool(column="done")
    assert len(done["tasks"]) == 1
    assert done["tasks"][0]["title"] == "b"

    missing = await kanban_tools.kanban_show_tool("does-not-exist")
    assert "not found" in missing["error"]
