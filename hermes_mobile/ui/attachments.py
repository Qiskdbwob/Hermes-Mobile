"""Safe lightweight chat attachments for Hermes Mobile.

This is client-side prompt assembly, not a fake backend upload. Text files are
inlined with strict limits. Images and other binaries are copied to app-private
storage and surfaced as local paths so the agent can use tools such as
``vision_analyze`` when appropriate.
"""

from __future__ import annotations

import mimetypes
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_ATTACHMENT_BYTES = 10 * 1_048_576
MAX_INLINE_TEXT_CHARS = 120_000
MAX_ATTACHMENTS_PER_TURN = 5

_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".toml",
    ".xml",
    ".html",
    ".htm",
    ".css",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".py",
    ".sh",
    ".sql",
    ".log",
}

_BLOCKED_EXTENSIONS = {
    ".apk",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".app",
    ".ipa",
}


@dataclass(frozen=True)
class PendingAttachment:
    id: str
    name: str
    mime_type: str
    byte_count: int
    kind: str
    content: str = ""
    local_path: str = ""
    truncated: bool = False


def safe_attachment_name(value: str | None) -> str:
    """Return a display/storage-safe filename without trusting picker input."""
    raw = Path(str(value or "attachment")).name.strip() or "attachment"
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "_", raw).strip(" .")
    return cleaned[:96] or "attachment"


def _guess_mime(name: str, explicit: str = "") -> str:
    explicit = str(explicit or "").lower().split(";")[0].strip()
    if explicit and explicit != "application/octet-stream":
        return explicit
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def _is_text(name: str, mime_type: str, data: bytes) -> bool:
    suffix = Path(name).suffix.lower()
    if mime_type.startswith(("audio/", "image/", "video/")):
        return False
    if mime_type.startswith("text/") or suffix in _TEXT_EXTENSIONS:
        return True
    sample = data[:4096]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _persist_binary(storage_dir: Path, name: str, data: bytes) -> str:
    attachment_dir = storage_dir / "attachments"
    attachment_dir.mkdir(parents=True, exist_ok=True)
    destination = attachment_dir / f"{uuid.uuid4().hex[:12]}-{name}"
    destination.write_bytes(data)
    try:
        os.chmod(destination, 0o600)
    except OSError:
        pass
    return str(destination)


def _read_picker_bytes(file: Any) -> tuple[str, bytes, str]:
    name = safe_attachment_name(getattr(file, "name", None) or getattr(file, "path", None))
    suffix = Path(name).suffix.lower()
    if suffix in _BLOCKED_EXTENSIONS:
        raise ValueError(f"Blocked attachment type: {suffix}")
    raw = getattr(file, "bytes", None)
    if raw:
        data = bytes(raw)
    else:
        path = getattr(file, "path", None)
        if not path:
            raise ValueError(f"Could not read {name}: picker returned no file data")
        src = Path(path).expanduser()
        data = src.read_bytes()
    if not data:
        raise ValueError(f"{name} is empty")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"{name} is too large; max is {MAX_ATTACHMENT_BYTES // 1_048_576} MiB")
    mime_type = _guess_mime(name, str(getattr(file, "mime_type", "") or ""))
    return name, data, mime_type


def attachment_from_picker_file(file: Any, storage_dir: Path) -> PendingAttachment:
    """Convert a Flet FilePickerFile-like object into a bounded attachment."""
    name, data, mime_type = _read_picker_bytes(file)
    if _is_text(name, mime_type, data):
        text = data.decode("utf-8", errors="replace")
        truncated = len(text) > MAX_INLINE_TEXT_CHARS
        if truncated:
            text = text[:MAX_INLINE_TEXT_CHARS]
        return PendingAttachment(
            id=uuid.uuid4().hex,
            name=name,
            mime_type=mime_type,
            byte_count=len(data),
            kind="text",
            content=text,
            truncated=truncated,
        )
    local_path = _persist_binary(storage_dir, name, data)
    kind = "image" if mime_type.startswith("image/") else "binary"
    return PendingAttachment(
        id=uuid.uuid4().hex,
        name=name,
        mime_type=mime_type,
        byte_count=len(data),
        kind=kind,
        local_path=local_path,
    )


def attachments_to_prompt_context(attachments: list[PendingAttachment]) -> str:
    """Render selected attachments into a prompt-safe context block."""
    if not attachments:
        return ""
    blocks: list[str] = ["Attached files for this turn:"]
    for item in attachments[:MAX_ATTACHMENTS_PER_TURN]:
        header = (
            f"name={item.name!r} mime={item.mime_type!r} bytes={item.byte_count} kind={item.kind!r}"
        )
        if item.kind == "text":
            suffix = "\n[truncated at mobile inline limit]" if item.truncated else ""
            blocks.append(f"\n<attachment {header}>\n{item.content}{suffix}\n</attachment>")
        elif item.kind == "image":
            blocks.append(
                f"\n<attachment {header} local_path={item.local_path!r}>\n"
                "Image saved locally. If visual analysis is needed, call vision_analyze with this local_path.\n"
                "</attachment>"
            )
        else:
            blocks.append(
                f"\n<attachment {header} local_path={item.local_path!r}>\n"
                "Binary file saved locally. Use an appropriate file/tool only if needed; do not assume its contents.\n"
                "</attachment>"
            )
    return "\n".join(blocks)


def copy_path_attachment(path: Path, storage_dir: Path) -> PendingAttachment:
    """Test/helper path for non-picker attachments."""

    class Picked:
        pass

    picked = Picked()
    picked.name = path.name
    picked.path = str(path)
    picked.bytes = None
    return attachment_from_picker_file(picked, storage_dir)
