"""Kanban board tools for Hermes Mobile (desktop parity).

A lightweight, JSON-persisted kanban board so the agent can coordinate tasks
the way it does on desktop: create cards, move them across columns, block/
unblock, comment, and list/see state. Single board per app instance, stored
under the app data dir.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from hermes_mobile.config.settings import get_settings

COLUMNS = ["backlog", "in_progress", "done"]

_lock = threading.Lock()


def _board_file() -> Path:
    path = get_settings().get_data_dir() / "kanban.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_board() -> Dict[str, Any]:
    try:
        f = _board_file()
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"tasks": []}


def _save_board(board: Dict[str, Any]) -> None:
    try:
        _board_file().write_text(
            json.dumps(board, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


def _task_dict(task: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": task["id"],
        "title": task.get("title", ""),
        "description": task.get("description", ""),
        "column": task.get("column", "backlog"),
        "blocked": task.get("blocked", False),
        "block_reason": task.get("block_reason"),
        "comments": task.get("comments", []),
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
    }


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


async def kanban_list_tool(column: Optional[str] = None) -> Dict[str, Any]:
    """List tasks, optionally filtered by column."""
    return _list_impl(column)


def kanban_list_sync(column: Optional[str] = None) -> Dict[str, Any]:
    """Synchronous variant for UI builders (no event loop needed)."""
    return _list_impl(column)


def _list_impl(column: Optional[str]) -> Dict[str, Any]:
    with _lock:
        board = _load_board()
        tasks = board["tasks"]
        if column and column not in COLUMNS:
            return {"error": f"Unknown column '{column}'. Valid: {', '.join(COLUMNS)}"}
        if column:
            tasks = [t for t in tasks if t.get("column") == column]
        return {
            "columns": COLUMNS,
            "tasks": [_task_dict(t) for t in sorted(tasks, key=lambda t: t.get("created_at", ""))],
        }


async def kanban_create_tool(
    title: str,
    description: str = "",
    column: str = "backlog",
) -> Dict[str, Any]:
    """Create a new task card."""
    if not title or not title.strip():
        return {"error": "title is required"}
    if column not in COLUMNS:
        return {"error": f"Unknown column '{column}'. Valid: {', '.join(COLUMNS)}"}
    now = _now()
    task = {
        "id": uuid.uuid4().hex[:8],
        "title": title.strip(),
        "description": description,
        "column": column,
        "blocked": False,
        "comments": [],
        "created_at": now,
        "updated_at": now,
    }
    with _lock:
        board = _load_board()
        board["tasks"].append(task)
        _save_board(board)
    return {"task": _task_dict(task)}


async def kanban_show_tool(task_id: str) -> Dict[str, Any]:
    """Show a single task's full detail."""
    with _lock:
        board = _load_board()
        task = next((t for t in board["tasks"] if t["id"] == task_id), None)
        if task is None:
            return {"error": f"Task not found: {task_id}"}
        return {"task": _task_dict(task)}


async def kanban_move_tool(task_id: str, column: str) -> Dict[str, Any]:
    """Move a task to another column."""
    if column not in COLUMNS:
        return {"error": f"Unknown column '{column}'. Valid: {', '.join(COLUMNS)}"}
    with _lock:
        board = _load_board()
        task = next((t for t in board["tasks"] if t["id"] == task_id), None)
        if task is None:
            return {"error": f"Task not found: {task_id}"}
        task["column"] = column
        task["updated_at"] = _now()
        _save_board(board)
        return {"task": _task_dict(task)}


async def kanban_complete_tool(task_id: str) -> Dict[str, Any]:
    """Move a task to the done column."""
    return await kanban_move_tool(task_id, "done")


async def kanban_block_tool(task_id: str, reason: str = "") -> Dict[str, Any]:
    """Block a task with an optional reason."""
    with _lock:
        board = _load_board()
        task = next((t for t in board["tasks"] if t["id"] == task_id), None)
        if task is None:
            return {"error": f"Task not found: {task_id}"}
        task["blocked"] = True
        if reason:
            task["block_reason"] = reason
        task["updated_at"] = _now()
        _save_board(board)
        return {"task": _task_dict(task)}


async def kanban_unblock_tool(task_id: str) -> Dict[str, Any]:
    """Unblock a task."""
    with _lock:
        board = _load_board()
        task = next((t for t in board["tasks"] if t["id"] == task_id), None)
        if task is None:
            return {"error": f"Task not found: {task_id}"}
        task["blocked"] = False
        task.pop("block_reason", None)
        task["updated_at"] = _now()
        _save_board(board)
        return {"task": _task_dict(task)}


async def kanban_comment_tool(task_id: str, text: str) -> Dict[str, Any]:
    """Add a comment to a task."""
    if not text or not text.strip():
        return {"error": "text is required"}
    with _lock:
        board = _load_board()
        task = next((t for t in board["tasks"] if t["id"] == task_id), None)
        if task is None:
            return {"error": f"Task not found: {task_id}"}
        task.setdefault("comments", []).append(
            {"text": text.strip(), "at": _now()}
        )
        task["updated_at"] = _now()
        _save_board(board)
        return {"task": _task_dict(task)}
