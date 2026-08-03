"""Hermes Mobile - Entry point for Flet build.

On desktop: ``python main.py`` runs ``ft.run(target=main, ...)``.
On Android (serious_python): the Flet runtime imports this module and
calls ``main(page)`` directly; ``__name__`` is never ``"__main__"``
on Android (the runtime handles that bypass).
"""

import os
import traceback


def _write_crash_log(exc: Exception):
    """Write crash details to app data dir for debugging (no adb needed)."""
    try:
        log_dir = os.path.join(os.path.expanduser("~"), "hermes_logs")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "crash.log"), "w") as f:
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=f)
    except Exception:
        pass


# Import the real main function; capture any import-time failure so the
# app shows a diagnostic instead of a silent crash.
main = None
try:
    from hermes_mobile.main import main as _real_main

    main = _real_main
except Exception as _import_err:
    _write_crash_log(_import_err)

    def main(page):  # type: ignore[no-redef]
        """Fallback main that shows the import error on screen."""
        import flet as ft

        page.add(
            ft.SafeArea(
                ft.Column(
                    [
                        ft.Icon(ft.Icons.ERROR, size=48, color=ft.Colors.RED),
                        ft.Text("Failed to start", size=20, weight=ft.FontWeight.BOLD),
                        ft.Container(height=8),
                        ft.Text(
                            str(_import_err)[:500],
                            size=12,
                            selectable=True,
                        ),
                    ],
                )
            )
        )


if __name__ == "__main__":
    import flet as ft

    ft.run(target=main, assets_dir="assets")
