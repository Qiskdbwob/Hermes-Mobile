import flet as ft

from hermes_mobile.ui.common import snack


class Page:
    def __init__(self, *, width=430, platform="android"):
        self.width = width
        self.platform = platform
        self.theme_mode = ft.ThemeMode.LIGHT
        self.overlay = []
        self.updated = 0

    def update(self):
        self.updated += 1


def test_mobile_snackbar_clears_bottom_navigation():
    page = Page()

    snack(page, "Reconnect from Connections", error=True)

    snackbar = page.overlay[-1]
    assert isinstance(snackbar, ft.SnackBar)
    assert snackbar.margin.bottom == 96
    assert snackbar.content.value == "Reconnect from Connections"
    assert page.updated == 1


def test_desktop_snackbar_uses_compact_edge_margin():
    page = Page(width=1200, platform="linux")

    snack(page, "Saved")

    assert page.overlay[-1].margin.bottom == 12


def test_repeated_snacks_do_not_accumulate_in_overlay():
    """Flet never removes dismissed SnackBars from page.overlay, so the helper
    must close and drop the previous one before mounting the next — otherwise
    the control tree grows for the whole session (memory creep on Android)."""
    page = Page()

    snack(page, "First")
    snack(page, "Second")
    snack(page, "Third", error=True)

    snackbars = [control for control in page.overlay if isinstance(control, ft.SnackBar)]
    assert len(snackbars) == 1
    assert snackbars[0].content.value == "Third"
    assert page.updated == 3
