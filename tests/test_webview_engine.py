"""Tests for the WebView automation engine (flet-webview wrapper)."""

import sys
from types import SimpleNamespace

import flet as ft
import pytest

import hermes_mobile.tools.webview_engine as wv
from hermes_mobile.tools.webview_engine import WebViewEngine


class FakePage:
    platform = ft.PagePlatform.ANDROID

    def __init__(self):
        self.updates = 0

    def update(self):
        self.updates += 1


class FakeContainer:
    def __init__(self):
        self.content = None


class FakeControl:
    """Records calls like the real flet_webview.WebView async methods."""

    def __init__(self):
        self.loaded = []
        self.js = []
        self.scrolls = []
        self.scroll_tos = []
        self.reloads = 0
        self.back_count = 0
        self.can_back = True
        self.title = "Fake Title"
        self.current_url = "https://example.com/initial"
        self.js_result = "fake result"

    async def load_request(self, url):
        self.loaded.append(url)

    async def run_javascript(self, js):
        self.js.append(js)
        return self.js_result

    async def scroll_by(self, x, y):
        self.scrolls.append((x, y))

    async def scroll_to(self, x, y):
        self.scroll_tos.append((x, y))

    async def reload(self):
        self.reloads += 1

    async def can_go_back(self):
        return self.can_back

    async def go_back(self):
        self.back_count += 1

    async def get_title(self):
        return self.title

    async def get_current_url(self):
        return self.current_url


@pytest.fixture
def engine():
    page = FakePage()
    eng = WebViewEngine(page)
    eng._control = FakeControl()
    return eng


class TestAvailability:
    def test_available_on_android_when_import_works(self, monkeypatch):
        monkeypatch.setattr(wv, "_webview_import_available", lambda: True)
        assert wv.webview_available(FakePage()) is True

    def test_unavailable_when_package_missing(self, monkeypatch):
        monkeypatch.setattr(wv, "_webview_import_available", lambda: False)
        assert wv.webview_available(FakePage()) is False

    def test_unavailable_on_linux(self, monkeypatch):
        monkeypatch.setattr(wv, "_webview_import_available", lambda: True)
        page = SimpleNamespace(platform=ft.PagePlatform.LINUX)
        assert wv.webview_available(page) is False


class TestNavigate:
    async def test_loads_url_and_reports_title(self, engine):
        result = await engine.navigate("https://example.com", timeout=0.05)

        assert result["ok"] is True
        assert result["title"] == "Fake Title"
        assert engine._control.loaded == ["https://example.com"]

    async def test_returns_error_when_not_mounted(self):
        eng = WebViewEngine(FakePage())
        result = await eng.navigate("https://example.com")
        assert result["ok"] is False
        assert "not mounted" in result["error"]


class TestInteraction:
    async def test_scroll_down(self, engine):
        assert await engine.scroll("down", 300) is True
        assert engine._control.scrolls == [(0, 300)]

    async def test_scroll_up_negates(self, engine):
        await engine.scroll("up", 200)
        assert engine._control.scrolls == [(0, -200)]

    async def test_scroll_top_uses_scroll_to(self, engine):
        await engine.scroll("top")
        assert engine._control.scroll_tos == [(0, 0)]

    async def test_click_selector_builds_js(self, engine):
        engine._control.js_result = True
        assert await engine.click_selector("button#go") is True
        assert '"button#go"' in engine._control.js[-1]

    async def test_type_selector_builds_js(self, engine):
        engine._control.js_result = True
        assert await engine.type_selector("input[name=q]", "hello") is True
        js = engine._control.js[-1]
        assert "input[name=q]" in js
        assert '"hello"' in js

    async def test_press_enter(self, engine):
        engine._control.js_result = True
        assert await engine.press_key("enter") is True
        assert "Enter" in engine._control.js[-1]

    async def test_page_text(self, engine):
        text = await engine.page_text()
        assert text == "fake result"

    async def test_back(self, engine):
        assert await engine.back() is True
        assert engine._control.back_count == 1

    async def test_back_no_history(self, engine):
        engine._control.can_back = False
        assert await engine.back() is False


class FakeWebView:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeWebViewModule:
    WebView = FakeWebView


def _raise_import_error():
    raise ImportError("flet-webview not installed")


class TestMount:
    def test_mount_attaches_control(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "flet_webview", FakeWebViewModule())
        page = FakePage()
        eng = WebViewEngine(page)
        container = FakeContainer()
        eng.mount(container)
        assert eng.is_mounted is True
        assert container.content is eng._control
        assert page.updates >= 1

    def test_dismount_detaches(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "flet_webview", FakeWebViewModule())
        eng = WebViewEngine(FakePage())
        container = FakeContainer()
        eng.mount(container)
        eng.dismount()
        assert eng.is_mounted is False
        assert container.content is None

    def test_mount_graceful_when_package_missing(self, monkeypatch):
        monkeypatch.setattr(wv, "_import_webview", _raise_import_error)
        monkeypatch.setattr(wv, "_webview_import_available", lambda: False)
        eng = WebViewEngine(FakePage())
        container = FakeContainer()
        eng.mount(container)
        assert eng.is_mounted is False
        assert container.content is None
        assert "not installed" in (eng.last_error or "")
