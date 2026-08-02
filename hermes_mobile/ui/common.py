"""Shared UI helpers for Hermes Mobile.

Small primitives used across views so the "nous" contract stays in one place:
flat sections with hairline dividers, snack bars, and dialogs using the
current Flet API (page.overlay / page.show_dialog).
"""

from __future__ import annotations

from typing import Any, List

import flet as ft

from hermes_mobile.ui.theme import mode_colors


def snack(page: ft.Page, text: str, error: bool = False):
    """Show a themed snack bar."""
    c = mode_colors(getattr(page, "theme_mode", None) == ft.ThemeMode.DARK)
    content = ft.Text(text, color=c["foreground"] if not error else c["destructive"])
    sb = ft.SnackBar(
        content=content,
        bgcolor=c["popover"],
        behavior=ft.SnackBarBehavior.FLOATING,
        elevation=0,
    )
    sb.open = True
    page.overlay.append(sb)
    page.update()


def open_dialog(page: ft.Page, dialog: ft.AlertDialog):
    """Open a dialog using the current Flet API."""
    page.show_dialog(dialog)


def close_dialog(page: ft.Page, dialog: ft.AlertDialog):
    """Close a dialog using the current Flet API."""
    dialog.open = False
    page.update()


def section_header(dark: bool, title: str, subtitle: str = "") -> ft.Control:
    """Flat section header: title + optional subtitle, hairline below."""
    c = mode_colors(dark)
    controls: List[ft.Control] = [
        ft.Text(
            title,
            size=17,
            weight=ft.FontWeight.W_700,
            color=c["foreground"],
        ),
    ]
    if subtitle:
        controls.append(
            ft.Text(
                subtitle,
                size=12,
                color=c["muted_foreground"],
            )
        )
    controls.append(ft.Container(height=2))
    return ft.Column(
        [
            *controls,
            ft.Container(
                height=1,
                bgcolor=c["border"],
                border_radius=ft.BorderRadius.all(1),
            ),
        ],
        spacing=2,
    )


def hairline(dark: bool) -> ft.Container:
    """A 1px hairline in the current border color."""
    return ft.Container(height=1, bgcolor=mode_colors(dark)["border"])


def page_scaffold(controls: List[ft.Control], dark: bool, padding: int = 16) -> ft.Control:
    """Standard scrollable page body with flat styling."""
    return ft.ListView(
        controls=controls,
        padding=ft.Padding.all(padding),
        spacing=18,
    )


def flat_button(
    text: str,
    icon: Any,
    on_click,
    dark: bool,
    destructive: bool = False,
) -> ft.Control:
    """Flat action button consistent with the nous surface."""
    c = mode_colors(dark)
    return ft.ElevatedButton(
        text,
        icon=icon,
        on_click=on_click,
        style=ft.ButtonStyle(
            color=c["destructive"] if destructive else c["foreground"],
            bgcolor=c["card"],
            elevation=0,
            shape=ft.RoundedRectangleBorder(radius=10),
            side=ft.BorderSide(
                1, c["destructive"] if destructive else c["border"]
            ),
        ),
    )

