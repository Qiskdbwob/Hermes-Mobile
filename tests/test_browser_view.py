"""Tests for the Browser view (WebView surface for agent automation)."""

from types import SimpleNamespace

import flet as ft

from hermes_mobile.ui.browser_view import BrowserView


class FakePage:
    platform = ft.PagePlatform.ANDROID

    def __init__(self):
        self.overlay = []
        self.updated = 0

    def update(self):
        self.updated += 1


class FakeSession:
    def __init__(self):
        self.attached = None

    def attach_webview(self, engine):
        self.attached = engine

    def detach_webview(self):
        self.attached = None


class FakeAgent:
    def __init__(self):
        self.browser_session = FakeSession()


class FakeApp:
    def __init__(self):
        self.page = FakePage()
        self.agent = FakeAgent()
        self.dark_mode = True


def test_build_attaches_webview_engine_on_supported_platform(monkeypatch):
    monkeypatch.setattr("hermes_mobile.ui.browser_view.webview_available", lambda page: True)
    monkeypatch.setattr(
        "hermes_mobile.ui.browser_view.WebViewEngine.build_control",
        lambda self, url="about:blank": SimpleNamespace(),
    )
    app = FakeApp()
    view = BrowserView(app)

    root = view.build()

    assert root is not None
    assert app.agent.browser_session.attached is not None
    assert view._engine is not None


def test_build_detaches_and_shows_note_when_unavailable(monkeypatch):
    monkeypatch.setattr("hermes_mobile.ui.browser_view.webview_available", lambda page: False)
    app = FakeApp()
    view = BrowserView(app)

    root = view.build()

    assert root is not None
    assert app.agent.browser_session.attached is None
