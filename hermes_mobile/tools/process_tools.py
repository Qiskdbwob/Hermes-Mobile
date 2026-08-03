"""Async terminal and background-process registry for Hermes Mobile.

The registry is intentionally per-agent: process handles never leak between
sessions, and every action works with Android's bundled shell when available.
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


@dataclass
class ProcessSession:
    session_id: str
    command: str
    process: asyncio.subprocess.Process
    started_at: float = field(default_factory=time.monotonic)
    output: bytearray = field(default_factory=bytearray)
    poll_cursor: int = 0
    reader_task: asyncio.Task[None] | None = None

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
        if not isinstance(command, str) or not command.strip():
            return {"error": "Command is required"}
        command = command.strip()

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=cwd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=os.name == "posix",
            )
        except Exception as exc:
            return {"error": str(exc)}

        if not background:
            try:
                communicate = process.communicate()
                output, _ = (
                    await asyncio.wait_for(communicate, timeout=timeout)
                    if timeout
                    else await communicate
                )
            except TimeoutError:
                await self._kill_process_tree(process)
                output, _ = await process.communicate()
                return {
                    "output": output.decode(errors="replace"),
                    "exit_code": process.returncode,
                    "error": f"Command timed out after {timeout}s",
                }
            return {
                "output": output.decode(errors="replace"),
                "exit_code": process.returncode,
            }

        session_id = f"proc_{uuid.uuid4().hex[:12]}"
        session = ProcessSession(session_id, command, process)
        self._sessions[session_id] = session
        session.reader_task = asyncio.create_task(self._drain_output(session))
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
        action = action.lower().strip()
        if action == "list":
            return {
                "sessions": [self._describe(session) for session in self._sessions.values()]
            }

        if not session_id:
            return {"error": "session_id is required"}
        session = self._sessions.get(session_id)
        if session is None:
            return {"error": f"Unknown process session: {session_id}"}

        if action == "poll":
            await asyncio.sleep(0)
            chunk = bytes(session.output[session.poll_cursor :]).decode(errors="replace")
            session.poll_cursor = len(session.output)
            return {**self._describe(session), "output": chunk}

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
                if session.reader_task:
                    await session.reader_task
            except TimeoutError:
                return {**self._describe(session), "timeout": True}
            return {
                **self._describe(session),
                "output": bytes(session.output).decode(errors="replace"),
            }

        if action == "kill":
            if session.running:
                await self._kill_process_tree(session.process)
            if session.reader_task:
                await session.reader_task
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

    async def _drain_output(self, session: ProcessSession) -> None:
        stream = session.process.stdout
        if stream is None:
            return
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            session.output.extend(chunk)
            if len(session.output) > MAX_OUTPUT_BYTES:
                overflow = len(session.output) - MAX_OUTPUT_BYTES
                del session.output[:overflow]
                session.poll_cursor = max(0, session.poll_cursor - overflow)
        await session.process.wait()

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
