"""Global animated petdex mascot for the mobile shell."""

from __future__ import annotations

import asyncio
import base64
import binascii
import struct
from typing import Any, Mapping, Optional

import flet as ft

_PET_FRAME_MAX_WIDTH = 76.0
_PET_FRAME_MAX_HEIGHT = 84.0
_STATE_ALIASES = {
    "run": ("run", "running-in-place", "running-right", "running-left"),
    "wave": ("wave", "hello"),
    "waiting": ("waiting", "idle"),
    "review": ("review", "idle"),
}


def image_dimensions(data: bytes) -> tuple[int, int]:
    """Read PNG/WebP dimensions without adding Pillow to the APK."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP" and len(data) >= 25:
        chunk = data[12:16]
        if chunk == b"VP8X" and len(data) >= 30:
            return (
                1 + int.from_bytes(data[24:27], "little"),
                1 + int.from_bytes(data[27:30], "little"),
            )
        if chunk == b"VP8L" and data[20] == 0x2F:
            bits = int.from_bytes(data[21:25], "little")
            return (1 + (bits & 0x3FFF), 1 + ((bits >> 14) & 0x3FFF))
    return (0, 0)


class MobilePet:
    """Thin Flet renderer for Desktop's profile-scoped pet.info payload."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.page = app.page
        self.info: Mapping[str, Any] = {}
        self.state = "idle"
        self._image: Optional[ft.Image] = None
        self._frame_w = 1
        self._frame_h = 1
        self._scale = 1.0
        self._frame = 0
        self._direction = 1
        self._x = 12.0
        self._task: Optional[asyncio.Task] = None
        self._flash_task: Optional[asyncio.Task] = None
        self.layer = ft.Container(
            width=92,
            height=98,
            left=self._x,
            bottom=62,
            alignment=ft.Alignment.BOTTOM_CENTER,
            visible=False,
            tooltip="Hermes pet",
        )

    def build(self) -> ft.Control:
        return self.layer

    def set_info(self, info: Mapping[str, Any]) -> bool:
        if not info.get("enabled"):
            self.hide()
            return False
        try:
            raw = base64.b64decode(str(info.get("spritesheetBase64") or ""), validate=True)
            frame_w = max(1, int(info.get("frameW") or 192))
            frame_h = max(1, int(info.get("frameH") or 208))
        except (ValueError, TypeError, binascii.Error):
            self.hide()
            return False
        natural_w, natural_h = image_dimensions(raw)
        state_rows = info.get("stateRows") or ["idle"]
        row_count = max(1, len(state_rows) if isinstance(state_rows, list) else 1)
        if natural_w <= 0 or natural_h <= 0:
            counts = info.get("framesByRow") or info.get("framesByState") or {}
            columns = max(
                [int(info.get("framesPerState") or 1)]
                + [int(value or 0) for value in counts.values()]
                if isinstance(counts, Mapping)
                else [1]
            )
            natural_w = frame_w * max(1, columns)
            natural_h = frame_h * row_count
        self.info = info
        self._frame_w = frame_w
        self._frame_h = frame_h
        self._scale = min(_PET_FRAME_MAX_WIDTH / frame_w, _PET_FRAME_MAX_HEIGHT / frame_h)
        draw_w = frame_w * self._scale
        draw_h = frame_h * self._scale
        self._image = ft.Image(
            src=raw,
            width=natural_w * self._scale,
            height=natural_h * self._scale,
            fit=ft.BoxFit.FILL,
            filter_quality=ft.FilterQuality.NONE,
            gapless_playback=True,
            left=0,
            top=0,
            semantics_label=str(info.get("displayName") or "Hermes pet"),
        )
        self.layer.content = ft.Stack(
            [self._image],
            width=draw_w,
            height=draw_h,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
        self.layer.tooltip = str(info.get("displayName") or "Hermes pet")
        self.layer.visible = True
        self._frame = 0
        self._apply_frame()
        self._ensure_task()
        return True

    def set_activity(self, state: str) -> None:
        self.state = str(state or "idle")
        self._frame = 0

    def flash_activity(self, state: str, duration: float = 1.6) -> None:
        self.set_activity(state)
        if self._flash_task is not None and not self._flash_task.done():
            self._flash_task.cancel()

        async def clear() -> None:
            try:
                await asyncio.sleep(duration)
                self.set_activity("idle")
            except asyncio.CancelledError:
                raise

        try:
            self._flash_task = asyncio.get_running_loop().create_task(clear())
        except RuntimeError:
            self._flash_task = None

    def hide(self) -> None:
        self.layer.visible = False
        self.info = {}
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
        flash_task = self._flash_task
        self._flash_task = None
        if flash_task is not None and not flash_task.done():
            flash_task.cancel()

    def _ensure_task(self) -> None:
        if self._task is not None and not self._task.done():
            return
        try:
            self._task = asyncio.get_running_loop().create_task(self._animate())
        except RuntimeError:
            self._task = None

    def _state_row(self, state: str) -> int:
        rows = self.info.get("stateRows") or ["idle"]
        if not isinstance(rows, list):
            return 0
        for candidate in _STATE_ALIASES.get(state, (state,)):
            if candidate in rows:
                return rows.index(candidate)
        return rows.index("idle") if "idle" in rows else 0

    def _frame_count(self, state: str) -> int:
        counts = self.info.get("framesByState") or {}
        if isinstance(counts, Mapping):
            for candidate in _STATE_ALIASES.get(state, (state,)):
                value = counts.get(candidate)
                if value:
                    return max(1, int(value))
        return max(1, int(self.info.get("framesPerState") or 1))

    def _apply_frame(self) -> None:
        if self._image is None:
            return
        roam = bool(getattr(self.app.settings, "pet_roam", True)) and self.state == "idle"
        state = "run" if roam else self.state
        count = self._frame_count(state)
        self._frame %= count
        self._image.left = -(self._frame * self._frame_w * self._scale)
        self._image.top = -(self._state_row(state) * self._frame_h * self._scale)
        moved = False
        if roam:
            width = max(120.0, float(getattr(self.page, "width", 360) or 360))
            self._x += 2.2 * self._direction
            limit = max(12.0, width - float(self.layer.width or 92) - 12.0)
            if self._x >= limit:
                self._x = limit
                self._direction = -1
            elif self._x <= 12.0:
                self._x = 12.0
                self._direction = 1
            self.layer.left = self._x
            moved = True
        try:
            self._image.update()
            if moved:
                self.layer.update()
        except (AssertionError, RuntimeError, AttributeError):
            # Tests and pre-mount refreshes configure controls before they are
            # attached to a Page. The next mounted frame carries this state.
            pass
        self._frame = (self._frame + 1) % count

    async def _animate(self) -> None:
        try:
            while self.layer.visible and self.info:
                self._apply_frame()
                count = self._frame_count(self.state)
                loop_ms = max(240.0, float(self.info.get("loopMs") or 900))
                await asyncio.sleep(max(0.08, loop_ms / max(1, count) / 1000.0))
        except asyncio.CancelledError:
            raise
        finally:
            self._task = None
