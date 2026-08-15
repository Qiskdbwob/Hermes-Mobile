"""Browser view — hosts the WebView used by the agent's browser tools.

Opening this view mounts a real WebView (flet-webview / webview_flutter) and
attaches it to the agent's BrowserSession. From then on, browser_navigate /
browser_back / browser_click / browser_scroll / browser_type run against a
real, JavaScript-capable browser. On platforms without WebView support the
view explains the fallback (static httpx engine) instead.
"""

from __future__ import annotations

import asyncio

import flet as ft

from hermes_mobile.tools.webview_engine import WebViewEngine, webview_available
from hermes_mobile.ui.common import flat_button, page_header
from hermes_mobile.ui.theme import mode_colors


class BrowserView:
    """WebView surface for agent-driven web automation."""

    def __init__(self, app):
        self.app = app
        self.page = app.page
        self._engine: WebViewEngine | None = None

    def _ensure_engine(self) -> WebViewEngine:
        if self._engine is None:
            self._engine = WebViewEngine(self.page)
        return self._engine

    @staticmethod
    def _schedule(coro) -> None:
        try:
            asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            coro.close()

    def _agent_session(self):
        agent = getattr(self.app, "agent", None)
        return getattr(agent, "browser_session", None)

    def build(self) -> ft.Control:
        dark = self.app.dark_mode
        c = mode_colors(dark)
        engine = self._ensure_engine()
        available = webview_available(self.page)
        session = self._agent_session()

        container = ft.Container(expand=True)

        if not available:
            if session is not None:
                session.detach_webview()
            container.content = ft.Column(
                [
                    ft.Icon(ft.Icons.PUBLIC_OFF, size=40, color=ft.Colors.OUTLINE),
                    ft.Text(
                        "WebView is not supported on this platform.",
                        size=14,
                        weight=ft.FontWeight.W_600,
                        color=c["foreground"],
                    ),
                    ft.Text(
                        "The agent browser still works with the static engine "
                        "(HTML fetch + parsing, no JavaScript).",
                        size=12,
                        color=ft.Colors.OUTLINE,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=8,
                expand=True,
            )
        else:
            engine.mount(container)
            if session is not None:
                session.attach_webview(engine)

        url_field = ft.TextField(
            hint_text="https://example.com",
            dense=True,
            expand=True,
            height=40,
            border_radius=8,
            on_submit=lambda e: self._go(engine, url_field),
        )
        toolbar = ft.Row(
            [
                ft.IconButton(
                    icon=ft.Icons.ARROW_BACK,
                    icon_size=18,
                    icon_color=c["foreground"],
                    tooltip="Back",
                    on_click=lambda e: self._back(engine),
                ),
                url_field,
                ft.IconButton(
                    icon=ft.Icons.REFRESH,
                    icon_size=18,
                    icon_color=c["foreground"],
                    tooltip="Reload",
                    on_click=lambda e: self._reload(engine),
                ),
                flat_button(
                    "Go",
                    ft.Icons.SEARCH,
                    lambda e: self._go(engine, url_field),
                    dark,
                ),
            ],
            spacing=4,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        return ft.Column(
            [
                page_header(
                    dark,
                    "Browser",
                    "WebView automation for the agent",
                    None,
                ),
                ft.Container(toolbar, padding=ft.Padding.only(left=12, right=12, bottom=4)),
                container,
            ],
            expand=True,
            spacing=0,
        )

    def _go(self, engine: WebViewEngine, url_field: ft.TextField) -> None:
        url = str(url_field.value or "").strip()
        if not url:
            return
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        self._schedule(engine.navigate(url))

    def _back(self, engine: WebViewEngine) -> None:
        self._schedule(engine.back())

    def _reload(self, engine: WebViewEngine) -> None:
        self._schedule(engine.reload())
