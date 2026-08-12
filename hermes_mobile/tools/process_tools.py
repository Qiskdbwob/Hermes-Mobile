"""Async terminal and background-process registry for Hermes Mobile.

The registry is intentionally per-agent: process handles never leak between
sessions, and every action works with Android's bundled shell when available.
stdout and stderr are captured separately so callers (terminal view, model
tools) can render them distinctly.
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

MAX_OUTPUT_BYTES = 1_000_000

# Finished sessions are kept for a short grace period (so callers can still
# read their output after exit), then evicted to bound memory on-device.
SESSION_RETENTION_SECONDS = 300.0
MAX_SESSIONS = 32


@dataclass
class ProcessSession:
    session_id: str
    command: str
    process: asyncio.subprocess.Process
    started_at: float = field(default_factory=time.monotonic)
    output: bytearray = field(default_factory=bytearray)
    stderr: bytearray = field(default_factory=bytearray)
    poll_cursor: int = 0
    stderr_cursor: int = 0
    reader_tasks: list[asyncio.Task[None]] = field(default_factory=list)

    @property
    def running(self) -> bool:
        return self.process.returncode is None


class MobileProcessRegistry:
    """Track shell processes and expose terminal/process style operations."""

    def __init__(self) -> None:
        self._sessions: dict[str, ProcessSession] = {}

    async def terminal(
        self,
        command: str,
        *,
        cwd: str | None = None,
        timeout: int | None = 180,
        background: bool = False,
    ) -> dict[str, Any]:
        self._prune_sessions()
        if not isinstance(command, str) or not command.strip():
            return {"error": "Command is required"}
        command = command.strip()

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=cwd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=os.name == "posix",
            )
        except Exception as exc:
            return {"error": str(exc)}

        if not background:
            try:
                communicate = process.communicate()
                out, err = (
                    await asyncio.wait_for(communicate, timeout=timeout)
                    if timeout
                    else await communicate
                )
            except asyncio.TimeoutError:
                await self._kill_process_tree(process)
                out, err = await process.communicate()
                return {
                    "output": out.decode(errors="replace"),
                    "stderr": err.decode(errors="replace"),
                    "exit_code": process.returncode,
                    "error": f"Command timed out after {timeout}s",
                }
            return {
                "output": out.decode(errors="replace"),
                "stderr": err.decode(errors="replace"),
                "exit_code": process.returncode,
            }

        session_id = f"proc_{uuid.uuid4().hex[:12]}"
        session = ProcessSession(session_id, command, process)
        self._sessions[session_id] = session
        if process.stdout is not None:
            session.reader_tasks.append(
                asyncio.create_task(self._drain(session, process.stdout, session.output))
            )
        if process.stderr is not None:
            session.reader_tasks.append(
                asyncio.create_task(self._drain(session, process.stderr, session.stderr))
            )
        return {
            "session_id": session_id,
            "pid": process.pid,
            "status": "running",
            "command": command,
        }

    async def process(
        self,
        action: str,
        *,
        session_id: str | None = None,
        data: str | None = None,
        timeout: int | None = None,
        offset: int | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        self._prune_sessions()
        action = action.lower().strip()
        if action == "list":
            return {"sessions": [self._describe(session) for session in self._sessions.values()]}

        if not session_id:
            return {"error": "session_id is required"}
        session = self._sessions.get(session_id)
        if session is None:
            return {"error": f"Unknown process session: {session_id}"}

        if action == "poll":
            await asyncio.sleep(0)
            out = bytes(session.output[session.poll_cursor :]).decode(errors="replace")
            session.poll_cursor = len(session.output)
            err = bytes(session.stderr[session.stderr_cursor :]).decode(errors="replace")
            session.stderr_cursor = len(session.stderr)
            return {**self._describe(session), "output": out, "stderr": err}

        if action == "log":
            lines = bytes(session.output).decode(errors="replace").splitlines()
            start = offset if offset is not None else max(0, len(lines) - limit)
            return {
                **self._describe(session),
                "output": "\n".join(lines[start : start + limit]),
                "offset": start,
                "total_lines": len(lines),
            }

        if action == "wait":
            try:
                waiter = session.process.wait()
                if timeout:
                    await asyncio.wait_for(waiter, timeout=timeout)
                else:
                    await waiter
                if session.reader_tasks:
                    await asyncio.gather(*session.reader_tasks)
            except asyncio.TimeoutError:
                return {**self._describe(session), "timeout": True}
            return {
                **self._describe(session),
                "output": bytes(session.output).decode(errors="replace"),
                "stderr": bytes(session.stderr).decode(errors="replace"),
            }

        if action == "kill":
            if session.running:
                await self._kill_process_tree(session.process)
            if session.reader_tasks:
                await asyncio.gather(*session.reader_tasks)
            return {**self._describe(session), "killed": True}

        if action in {"write", "submit"}:
            if not session.running or session.process.stdin is None:
                return {"error": "Process stdin is not available"}
            payload = data or ""
            if action == "submit":
                payload += "\n"
            session.process.stdin.write(payload.encode())
            await session.process.stdin.drain()
            return {**self._describe(session), "written": len(payload)}

        if action == "close":
            if session.process.stdin and not session.process.stdin.is_closing():
                session.process.stdin.close()
                await session.process.stdin.wait_closed()
            return {**self._describe(session), "stdin_closed": True}

        return {"error": f"Unsupported process action: {action}"}

    @staticmethod
    async def _kill_process_tree(process: asyncio.subprocess.Process) -> None:
        """Terminate the shell and its descendants so pipes cannot outlive it."""
        if process.returncode is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
        await process.wait()

    async def _drain(
        self,
        session: ProcessSession,
        stream: asyncio.StreamReader,
        buffer: bytearray,
    ) -> None:
        """Copy *stream* into *buffer* until EOF, capping total bytes held."""
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            buffer.extend(chunk)
            if len(buffer) > MAX_OUTPUT_BYTES:
                del buffer[: len(buffer) - MAX_OUTPUT_BYTES]
        await session.process.wait()

    def _prune_sessions(self) -> None:
        """Evict finished sessions past retention, then oldest finished over cap."""
        now = time.monotonic()
        for sid, session in list(self._sessions.items()):
            if session.process.returncode is not None and now - session.started_at > (
                SESSION_RETENTION_SECONDS
            ):
                self._evict(sid)
        if len(self._sessions) <= MAX_SESSIONS:
            return
        finished = sorted(
            (
                (sid, session)
                for sid, session in self._sessions.items()
                if session.process.returncode is not None
            ),
            key=lambda kv: kv[1].started_at,
        )
        for sid, _ in finished:
            if len(self._sessions) <= MAX_SESSIONS:
                break
            self._evict(sid)

    def _evict(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        for task in session.reader_tasks:
            if not task.done():
                task.cancel()

    @staticmethod
    def _describe(session: ProcessSession) -> dict[str, Any]:
        return {
            "session_id": session.session_id,
            "pid": session.process.pid,
            "command": session.command,
            "status": "running" if session.running else "exited",
            "exit_code": session.process.returncode,
            "uptime_seconds": round(time.monotonic() - session.started_at, 3),
        }
