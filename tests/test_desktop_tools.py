"""Tests for desktop-parity tools (execute_code, search_files, patch, project)."""

import pathlib

import pytest

from hermes_mobile.tools.desktop_tools import (
    execute_code_tool,
    patch_tool,
    search_files_tool,
    todo_tool,
)
from hermes_mobile.tools.project_tools import (
    project_create_tool,
    project_list_tool,
    project_switch_tool,
)


@pytest.fixture
def allow_tmp(monkeypatch, tmp_path):
    """Let the path-security sandbox accept tmp_path (file tools are sandboxed)."""
    from hermes_mobile.tools import path_security as ps

    monkeypatch.setattr(
        ps,
        "get_allowed_directories",
        lambda: [tmp_path, pathlib.Path.cwd()],
    )


@pytest.mark.asyncio
async def test_execute_code_returns_stdout():
    result = await execute_code_tool("print(6*7)")
    assert result["stdout"].strip() == "42"
    assert result["returncode"] == 0


@pytest.mark.asyncio
async def test_execute_code_timeout():
    result = await execute_code_tool("import time; time.sleep(5)", timeout=1)
    assert "timed out" in result["stderr"]


@pytest.mark.asyncio
async def test_execute_code_requires_code():
    result = await execute_code_tool("   ")
    assert "No code" in result["error"]


@pytest.mark.asyncio
async def test_search_files_content(tmp_path, allow_tmp):
    (tmp_path / "sample.py").write_text("def main():\n    pass\n")
    (tmp_path / "other.txt").write_text("nothing here")
    result = await search_files_tool("def main", path=str(tmp_path))
    assert result["count"] == 1
    assert result["matches"][0]["path"].endswith("sample.py")


@pytest.mark.asyncio
async def test_search_files_invalid_regex(tmp_path, allow_tmp):
    result = await search_files_tool("([", path=str(tmp_path))
    assert "Invalid regex" in result["error"]


@pytest.mark.asyncio
async def test_patch_replaces_once(tmp_path, allow_tmp):
    f = tmp_path / "file.txt"
    f.write_text("hello world\n")
    result = await patch_tool(str(f), "hello", "hi")
    assert result["replaced"] == 1
    assert f.read_text() == "hi world\n"
    # replace_all=False with multiple matches is refused
    f.write_text("hello world\nhello again\n")
    result2 = await patch_tool(str(f), "hello", "hi")
    assert "replace_all" in result2["error"]
    assert result2["matches"] == 2


@pytest.mark.asyncio
async def test_patch_replace_all(tmp_path, allow_tmp):
    f = tmp_path / "file.txt"
    f.write_text("hello world\nhello again\n")
    result = await patch_tool(str(f), "hello", "hi", replace_all=True)
    assert result["replaced"] == 2
    assert f.read_text() == "hi world\nhi again\n"


@pytest.mark.asyncio
async def test_patch_missing_file(tmp_path, allow_tmp):
    result = await patch_tool(str(tmp_path / "nope.txt"), "x", "y")
    assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_todo_actions():
    await todo_tool("add", content="first")
    await todo_tool("add", content="second")
    listed = await todo_tool("list")
    assert len(listed["items"]) == 2
    first_id = listed["items"][0]["id"]
    updated = await todo_tool("update", item_id=first_id, status="completed")
    assert updated["item"]["status"] == "completed"
    removed = await todo_tool("remove", item_id=first_id)
    assert removed["removed"] is True
    assert len(removed["items"]) == 1


@pytest.mark.asyncio
async def test_project_flow(tmp_path, monkeypatch):
    # Point the projects dir at a temp location via data dir
    from hermes_mobile.config import settings as settings_module

    monkeypatch.setattr(
        settings_module,
        "get_settings",
        lambda: _FakeSettings(tmp_path),
    )
    # Re-import module-level paths are computed lazily via get_settings()
    created = await project_create_tool("alpha")
    assert created["ok"] is True
    switched = await project_switch_tool("alpha")
    assert switched["ok"] is True
    listed = await project_list_tool()
    assert "alpha" in listed["projects"]
    assert listed["current"] == "alpha"


class _FakeSettings:
    """Minimal settings stub pointing the data dir at tmp_path."""

    def __init__(self, tmp_path):
        self._dir = pathlib.Path(tmp_path)

    def get_data_dir(self):
        return self._dir
