"""Durable composer draft and queue state.

This is intentionally client-side: Hermes Remote owns sessions and turns, but
Android/mobile owns the current composer draft and local follow-up queue.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterable


class ComposerStateStore:
    """Small atomic JSON store for composer drafts and queued text turns."""

    def __init__(self, config_dir: Path):
        self.path = config_dir / "composer-state.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(*parts: object) -> str:
        """Build a stable, non-empty state key from runtime/session parts."""
        cleaned = [str(p or "").strip() for p in parts]
        return "|".join(p or "_" for p in cleaned)

    def _read(self) -> dict:
        try:
            if not self.path.exists():
                return {"drafts": {}, "queues": {}}
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {"drafts": {}, "queues": {}}
            drafts = data.get("drafts") if isinstance(data.get("drafts"), dict) else {}
            queues = data.get("queues") if isinstance(data.get("queues"), dict) else {}
            return {"drafts": drafts, "queues": queues}
        except Exception:
            return {"drafts": {}, "queues": {}}

    def _write(self, data: dict) -> None:
        fd = -1
        tmp = ""
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        try:
            fd, tmp = tempfile.mkstemp(prefix="composer-state-", dir=self.path.parent)
            os.write(fd, payload)
            os.fchmod(fd, 0o600)
            os.close(fd)
            fd = -1
            os.replace(tmp, self.path)
            tmp = ""
        finally:
            if fd >= 0:
                os.close(fd)
            if tmp:
                try:
                    os.unlink(tmp)
                except FileNotFoundError:
                    pass

    def load_draft(self, key: str) -> str:
        value = self._read()["drafts"].get(key, "")
        return value if isinstance(value, str) else ""

    def save_draft(self, key: str, text: str) -> None:
        data = self._read()
        drafts = data["drafts"]
        if text:
            drafts[key] = text
        else:
            drafts.pop(key, None)
        self._write(data)

    def load_queue(self, key: str) -> list[str]:
        value = self._read()["queues"].get(key, [])
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()]

    def save_queue(self, key: str, queue: Iterable[str]) -> None:
        data = self._read()
        queues = data["queues"]
        cleaned = [str(item).strip() for item in queue if str(item).strip()]
        if cleaned:
            queues[key] = cleaned[:50]
        else:
            queues.pop(key, None)
        self._write(data)

    def enqueue(self, key: str, text: str) -> list[str]:
        queue = self.load_queue(key)
        queue.append(text.strip())
        self.save_queue(key, queue)
        return queue

    def pop_next(self, key: str) -> str | None:
        queue = self.load_queue(key)
        if not queue:
            return None
        item = queue.pop(0)
        self.save_queue(key, queue)
        return item
