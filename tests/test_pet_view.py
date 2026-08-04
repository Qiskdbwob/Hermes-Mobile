import asyncio
import base64
from types import SimpleNamespace

import flet as ft
import pytest

from hermes_mobile.ui.pet_view import MobilePet, image_dimensions

_TINY_PNG = base64.b64encode(
    base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAF/gL+Xw0Y5QAAAABJRU5ErkJggg=="
    )
).decode("ascii")


class Page:
    width = 360

    def __init__(self):
        self.updated = 0

    def update(self):
        self.updated += 1


def make_pet(*, roam=True):
    app = SimpleNamespace(page=Page(), settings=SimpleNamespace(pet_roam=roam))
    return MobilePet(app)


def payload():
    return {
        "enabled": True,
        "displayName": "Pool Dog",
        "spritesheetBase64": _TINY_PNG,
        "frameW": 1,
        "frameH": 1,
        "framesPerState": 2,
        "framesByState": {"idle": 1, "run": 2, "wave": 1, "failed": 1},
        "stateRows": ["idle", "run", "wave", "failed"],
        "loopMs": 240,
    }


def test_mobile_pet_clips_sprite_and_roams_inside_mobile_width():
    pet = make_pet(roam=True)

    assert pet.set_info(payload()) is True
    assert pet.layer.visible is True
    assert pet.layer.tooltip == "Pool Dog"
    assert isinstance(pet.layer.content, ft.Stack)
    assert pet.layer.content.clip_behavior == ft.ClipBehavior.HARD_EDGE

    initial_x = pet.layer.left
    pet.set_activity("idle")
    pet._apply_frame()

    assert pet.layer.left > initial_x
    assert pet._image.top == -pet._scale


def test_desktop_state_aliases_share_row_and_frame_metadata():
    pet = make_pet(roam=False)
    info = payload()
    info["stateRows"] = ["idle", "running-in-place", "hello"]
    info["framesByState"] = {"idle": 1, "running-in-place": 4, "hello": 3}
    pet.set_info(info)

    assert pet._state_row("run") == 1
    assert pet._frame_count("run") == 4
    assert pet._state_row("wave") == 2
    assert pet._frame_count("wave") == 3


def test_mobile_pet_rejects_invalid_or_disabled_payload():
    pet = make_pet()

    assert pet.set_info({"enabled": True, "spritesheetBase64": "not-base64"}) is False
    assert pet.layer.visible is False
    assert pet.set_info({"enabled": False}) is False


@pytest.mark.asyncio
async def test_pet_reaction_decays_back_to_idle():
    pet = make_pet(roam=False)
    pet.set_info(payload())

    pet.flash_activity("wave", duration=0.01)
    assert pet.state == "wave"
    await asyncio.sleep(0.02)

    assert pet.state == "idle"
    pet.hide()


def test_pet_sheet_dimensions_support_png_and_webp_without_pillow():
    png = base64.b64decode(_TINY_PNG)
    assert image_dimensions(png) == (1, 1)
    webp = b"RIFF" + b"\x00" * 4 + b"WEBPVP8L" + b"\x00" * 4 + bytes.fromhex("2fffc5d301")
    assert image_dimensions(webp) == (1536, 1872)
