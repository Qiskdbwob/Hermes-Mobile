"""Dev-only: capture every view as a PNG via flet's take_screenshot.

Usage:
    HERMES_MOBILE_CAPTURE_DIR=/tmp/shots DISPLAY=:99 python scripts/capture_views.py
"""
import asyncio
import os
import sys
from pathlib import Path

import flet as ft

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hermes_mobile.main import HermesMobileApp  # noqa: E402

VIEWS = ["chat", "tools", "memory", "skills", "settings", "cron", "gateway", "plugins"]


async def capture_flow(page: ft.Page):
    outdir = Path(os.environ["HERMES_MOBILE_CAPTURE_DIR"])
    outdir.mkdir(parents=True, exist_ok=True)

    app = HermesMobileApp(page)
    await asyncio.sleep(4)  # let the first frame settle

    for view in VIEWS:
        try:
            app._switch_view(view)
            await asyncio.sleep(1.5)
            data = await page.take_screenshot()
            (outdir / f"{view}.png").write_bytes(data)
            print(f"saved {view}.png ({len(data)} bytes)")
        except Exception as e:
            print(f"FAILED {view}: {e}")

    print("CAPTURE DONE")
    os._exit(0)


def main():
    ft.app(target=capture_flow)


if __name__ == "__main__":
    main()
