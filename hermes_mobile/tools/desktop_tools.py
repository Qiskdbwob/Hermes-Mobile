"""Desktop-parity tools for Hermes Mobile.

Bridges capability gaps vs the Hermes Desktop agent core: code execution,
file search/patch, todo tracking, and exposing the built-in skill manager and
cron scheduler as agent tools. All handlers are async and return JSON-serializable
values so they can be fed back into the model loop.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from hermes_mobile.tools.path_security import validate_and_resolve_path

# Skip files larger than this when searching contents (regex scanning a huge
# binary can stall the agent for seconds and exhaust memory).
MAX_FILE_BYTES = 1_048_576  # 1 MiB

# ---------------------------------------------------------------------------
# execute_code — run Python in a sandboxed subprocess with a hard timeout
# ---------------------------------------------------------------------------


async def execute_code_tool(code: str, timeout: int = 60) -> Dict[str, Any]:
    """Execute Python code in a separate subprocess and return stdout/stderr.

    Note: this is a separate process, not a security sandbox — the child runs
    with the same OS privileges (filesystem, network) as the app.
    """
    if not code or not code.strip():
        return {"error": "No code provided"}

    # Never execute on the app's own process: use a throwaway subprocess.
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(code)
        script_path = f.name

    try:
        # Use the running interpreter: on Android the app's bundled Python is
        # reachable via sys.executable, while a bare "python3" is not on PATH.
        proc = await asyncio.create_subprocess_exec(
            sys.executable or "python3",
            script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return {
                "stdout": "",
                "stderr": f"Execution timed out after {timeout}s",
                "returncode": -1,
            }
        return {
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
            "returncode": proc.returncode,
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        try:
            Path(script_path).unlink(missing_ok=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# search_files — regex/glob search inside a directory
# ---------------------------------------------------------------------------


async def search_files_tool(
    pattern: str,
    path: str = ".",
    target: str = "content",
    file_glob: Optional[str] = None,
    limit: int = 50,
    extra_dirs: Optional[List[Path]] = None,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Search file contents (regex) or filenames (glob) under a directory."""
    if target == "files":
        return _search_filenames(pattern, path, limit, extra_dirs, base_dir)
    return _search_content(pattern, path, file_glob, limit, extra_dirs, base_dir)


def _search_content(
    pattern: str,
    path: str,
    file_glob: Optional[str],
    limit: int,
    extra_dirs: Optional[List[Path]] = None,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    base, error = validate_and_resolve_path(path, extra_dirs=extra_dirs, base_dir=base_dir)
    if error:
        return {"error": error}
    assert base is not None
    if not base.is_dir():
        return {"error": f"Not a directory: {path}"}

    try:
        rx = re.compile(pattern)
    except re.error as e:
        return {"error": f"Invalid regex: {e}"}

    glob_rx = re.compile(file_glob) if file_glob else None
    matches: List[Dict[str, Any]] = []
    try:
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith((".", "__"))]
            for fname in files:
                if len(matches) >= limit:
                    break
                if glob_rx and not glob_rx.search(fname):
                    continue
                fpath = Path(root) / fname
                try:
                    if fpath.stat().st_size > MAX_FILE_BYTES:
                        continue
                    text = fpath.read_text(errors="replace")
                except Exception:
                    continue
                for i, line in enumerate(text.splitlines(), start=1):
                    if rx.search(line):
                        matches.append(
                            {
                                "path": str(fpath),
                                "line": i,
                                "content": line[:300],
                            }
                        )
                        if len(matches) >= limit:
                            break
    except Exception as e:
        return {"error": str(e)}
    return {"matches": matches, "count": len(matches)}


def _search_filenames(
    pattern: str,
    path: str,
    limit: int,
    extra_dirs: Optional[List[Path]] = None,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    base, error = validate_and_resolve_path(path, extra_dirs=extra_dirs, base_dir=base_dir)
    if error:
        return {"error": error}
    assert base is not None
    if not base.is_dir():
        return {"error": f"Not a directory: {path}"}

    try:
        rx = re.compile(pattern.replace("*", ".*"))
    except re.error as e:
        return {"error": f"Invalid pattern: {e}"}

    matches: List[str] = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith((".", "__"))]
        for fname in files:
            if len(matches) >= limit:
                break
            if rx.search(fname):
                matches.append(str(Path(root) / fname))
    return {"files": matches, "count": len(matches)}


# ---------------------------------------------------------------------------
# patch — simple find-and-replace file editing
# ---------------------------------------------------------------------------


async def patch_tool(
    path: str,
    old_string: str,
    new_string: str = "",
    replace_all: bool = False,
    extra_dirs: Optional[List[Path]] = None,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Replace old_string with new_string in a file (like the desktop patch tool)."""
    resolved, error = validate_and_resolve_path(path, extra_dirs=extra_dirs, base_dir=base_dir)
    if error:
        return {"error": error}
    if not resolved.exists():
        return {"error": f"File not found: {path}"}

    try:
        text = resolved.read_text(encoding="utf-8")
        count = text.count(old_string)
        if count == 0:
            return {"error": "old_string not found in file", "matches": 0}
        if count > 1 and not replace_all:
            return {
                "error": f"old_string found {count} times; pass replace_all=true to replace all",
                "matches": count,
            }
        new_text = (
            text.replace(old_string, new_string)
            if replace_all
            else text.replace(old_string, new_string, 1)
        )
        resolved.write_text(new_text, encoding="utf-8")
        return {"path": str(resolved), "replaced": count if replace_all else 1}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# todo — in-memory task list for the agent
# ---------------------------------------------------------------------------


class _TodoStore:
    def __init__(self):
        self.items: List[Dict[str, Any]] = []
        self._next_id = 1

    def add(self, content: str) -> Dict[str, Any]:
        item = {"id": self._next_id, "content": content, "status": "pending"}
        self._next_id += 1
        self.items.append(item)
        return item

    def update(self, item_id: int, status: str) -> Optional[Dict[str, Any]]:
        for item in self.items:
            if item["id"] == item_id:
                item["status"] = status
                return item
        return None

    def remove(self, item_id: int) -> bool:
        before = len(self.items)
        self.items = [i for i in self.items if i["id"] != item_id]
        return len(self.items) < before

    def list(self) -> List[Dict[str, Any]]:
        return list(self.items)


_todo_store = _TodoStore()


async def todo_tool(
    action: str,
    item_id: Optional[int] = None,
    content: Optional[str] = None,
    status: str = "pending",
) -> Dict[str, Any]:
    """Manage a simple task list (add/update/remove/list)."""
    action = action.lower()
    if action == "add":
        if not content:
            return {"error": "content required for add"}
        item = _todo_store.add(content)
        return {"item": item, "items": _todo_store.list()}
    if action == "update":
        if item_id is None:
            return {"error": "item_id required for update"}
        item = _todo_store.update(item_id, status)
        return {"item": item, "items": _todo_store.list()}
    if action == "remove":
        if item_id is None:
            return {"error": "item_id required for remove"}
        removed = _todo_store.remove(item_id)
        return {"removed": removed, "items": _todo_store.list()}
    if action == "list":
        return {"items": _todo_store.list()}
    return {"error": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# Skill tools — expose the mobile skill manager
# ---------------------------------------------------------------------------


async def skills_list_tool(skill_manager: Any) -> Dict[str, Any]:
    """List installed skills."""
    if skill_manager is None:
        return {"error": "Skill manager not available"}
    return {
        "skills": [
            {"name": s.name, "description": s.description, "active": s.active}
            for s in skill_manager.get_all_skills()
        ]
    }


async def skill_view_tool(name: str, skill_manager: Any) -> Dict[str, Any]:
    """View a skill's metadata and schema."""
    if skill_manager is None:
        return {"error": "Skill manager not available"}
    skill = skill_manager.get_skill(name)
    if skill is None:
        return {"error": f"Skill not found: {name}"}
    return {"name": skill.name, "description": skill.description, "schema": skill.schema}


async def skill_manage_tool(
    action: str,
    name: str,
    skill_manager: Any,
    url: Optional[str] = None,
) -> Dict[str, Any]:
    """Enable, disable, remove or install a skill."""
    if skill_manager is None:
        return {"error": "Skill manager not available"}
    action = action.lower()
    if action == "enable":
        return {"ok": skill_manager.enable_skill(name)}
    if action == "disable":
        return {"ok": skill_manager.disable_skill(name)}
    if action == "remove":
        return {"ok": skill_manager.remove_skill(name)}
    if action == "install":
        if not url:
            return {"error": "url required for install"}
        skill = await skill_manager.install_skill_from_url(url)
        return {"ok": skill is not None, "name": skill.name if skill else None}
    return {"error": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# Cron tools — expose the built-in scheduler
# ---------------------------------------------------------------------------


async def cronjob_tool(action: str, job_id: Optional[str] = None) -> Dict[str, Any]:
    """List, run, pause or resume cron jobs."""
    from hermes_mobile.cron import scheduler as sched

    action = action.lower()
    if action == "list":
        jobs = sched.list_jobs()
        return {
            "jobs": [
                {
                    "id": j.id,
                    "name": j.name,
                    "schedule": j.schedule,
                    "enabled": j.enabled,
                    "last_run": (
                        j.last_run.isoformat() if hasattr(j.last_run, "isoformat") else j.last_run
                    ),
                }
                for j in jobs
            ]
        }
    if action == "run":
        if not job_id:
            return {"error": "job_id required for run"}
        output = sched.run_job_now(job_id)
        return {"job_id": job_id, "output": output.to_markdown()[:2000]}
    if action == "pause":
        if not job_id:
            return {"error": "job_id required for pause"}
        return {"ok": sched.disable_job(job_id)}
    if action == "resume":
        if not job_id:
            return {"error": "job_id required for resume"}
        return {"ok": sched.enable_job(job_id)}
    return {"error": f"Unknown action: {action}"}
