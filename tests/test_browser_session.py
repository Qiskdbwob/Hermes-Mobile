"""Tests for the stateful BrowserSession.

Regression coverage for the browser tool unification: browser_navigate_tool
delegates to this session, so back/click/get_images must operate on the same
tab, and every fetch (including redirect hops) must pass the SSRF guard.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from hermes_mobile.tools.browser_session import BrowserSession

HTML_A = """
<html><head><title>Page A</title></head>
<body><h1>Alpha</h1><a href="/b">Go B</a></body></html>
"""

HTML_B = """
<html><head><title>Page B</title></head>
<body><h1>Beta</h1><img src="pic.jpg" alt="Pic"></body></html>
"""


def _resp(status_code=200, text=HTML_A, url="https://example.com/a"):
    from httpx import Request, Response

    return Response(status_code=status_code, text=text, request=Request("GET", url))


@pytest.fixture
def session():
    s = BrowserSession()
    yield s
    s._history.clear()
    s._current_url = None
    s._client = None
    s.webview = None


class FakeWebView:
    """Minimal stand-in for the WebViewEngine used by the session."""

    is_mounted = True

    def __init__(self, page_text="rendered text", links="[]"):
        self._text = page_text
        self._links = links
        self.navigated = []
        self.back_called = 0
        self.scrolls = []
        self.typed = []
        self.clicked = []

    async def navigate(self, url):
        self.navigated.append(url)
        return {"ok": True, "title": "Rendered Title", "url": url}

    async def page_text(self, max_chars=8000):
        return self._text[:max_chars]

    async def evaluate(self, js):
        return self._links

    async def _safe(self, method, default=None):
        if method == "get_current_url":
            return self.navigated[-1] if self.navigated else None
        if method == "get_title":
            return "Rendered Title"
        return default

    async def back(self):
        self.back_called += 1
        return True

    async def scroll(self, direction, amount):
        self.scrolls.append((direction, amount))
        return True

    async def type_selector(self, selector, text):
        self.typed.append((selector, text))
        return True

    async def click_selector(self, selector):
        self.clicked.append(selector)
        return True


def _patch_client():
    patcher = patch("hermes_mobile.tools.browser_session.httpx.AsyncClient")
    mock_cls = patcher.start()
    return patcher, mock_cls.return_value


@pytest.mark.asyncio
async def test_navigate_records_history_and_back_returns_previous(session):
    patcher, client = _patch_client()
    try:
        client.get = AsyncMock(
            side_effect=[
                _resp(text=HTML_A, url="https://example.com/a"),
                _resp(text=HTML_B, url="https://example.com/b"),
                _resp(text=HTML_A, url="https://example.com/a"),
            ]
        )

        first = await session.navigate("https://example.com/a")
        assert first["title"] == "Page A"

        second = await session.navigate("https://example.com/b")
        assert second["title"] == "Page B"
        assert session._history == ["https://example.com/a"]

        back = await session.back()
        assert back["title"] == "Page A"
        assert session._current_url == "https://example.com/a"
        assert session._history == []
    finally:
        patcher.stop()


@pytest.mark.asyncio
async def test_back_without_history_errors(session):
    result = await session.back()
    assert result == {"error": "No history to go back to"}


@pytest.mark.asyncio
async def test_click_resolves_relative_href_against_current_page(session):
    patcher, client = _patch_client()
    try:
        client.get = AsyncMock(
            side_effect=[
                _resp(text=HTML_A, url="https://example.com/a"),
                _resp(text=HTML_B, url="https://example.com/b"),
            ]
        )

        await session.navigate("https://example.com/a")
        clicked = await session.click_link("/b")

        assert clicked["title"] == "Page B"
        assert client.get.call_args_list[1][0][0] == "https://example.com/b"
    finally:
        patcher.stop()


@pytest.mark.asyncio
async def test_get_images_lists_images_on_current_page(session):
    patcher, client = _patch_client()
    try:
        client.get = AsyncMock(
            side_effect=[
                _resp(text=HTML_B, url="https://example.com/b"),
                _resp(text=HTML_B, url="https://example.com/b"),
            ]
        )

        await session.navigate("https://example.com/b")
        result = await session.get_images()

        assert result["url"] == "https://example.com/b"
        assert result["images"] == [{"src": "pic.jpg", "alt": "Pic"}]
    finally:
        patcher.stop()


@pytest.mark.asyncio
async def test_get_images_without_page_errors(session):
    result = await session.get_images()
    assert result == {"error": "No page loaded"}


@pytest.mark.asyncio
async def test_session_navigate_blocks_private_host_before_fetch(session):
    patcher, client = _patch_client()
    try:
        client.get = AsyncMock(return_value=_resp())

        result = await session.navigate("http://127.0.0.1/admin")

        assert "Blocked private" in result.get("error", "")
        client.get.assert_not_called()
    finally:
        patcher.stop()


@pytest.mark.asyncio
async def test_session_click_blocks_private_host_before_fetch(session):
    patcher, client = _patch_client()
    try:
        client.get = AsyncMock(
            side_effect=[
                _resp(text=HTML_A, url="https://example.com/a"),
                _resp(text=HTML_B, url="https://example.com/b"),
            ]
        )

        await session.navigate("https://example.com/a")
        # A malicious page can link to the cloud-metadata host; the guard
        # must block the click before any fetch happens.
        result = await session.click_link("http://169.254.169.254/latest/meta-data/")

        assert "Blocked private" in result.get("error", "")
        assert len(client.get.call_args_list) == 1  # only the initial navigate
    finally:
        patcher.stop()


class TestWebViewIntegration:
    @pytest.mark.asyncio
    async def test_navigate_uses_webview_when_attached(self, session):
        fake = FakeWebView(links='[{"text": "Link", "href": "https://example.com/x"}]')
        session.attach_webview(fake)

        result = await session.navigate("https://example.com")

        assert result["webview"] is True
        assert result["title"] == "Rendered Title"
        assert result["content"] == "rendered text"
        assert result["links"] == [{"text": "Link", "href": "https://example.com/x"}]
        assert fake.navigated == ["https://example.com"]
        assert session._current_url == "https://example.com"
        assert session._history == []

    @pytest.mark.asyncio
    async def test_navigate_falls_back_to_static_when_webview_text_empty(self, session):
        fake = FakeWebView(page_text="")
        session.attach_webview(fake)
        patcher, client = _patch_client()
        try:
            client.get = AsyncMock(return_value=_resp(text=HTML_A, url="https://example.com/a"))

            result = await session.navigate("https://example.com/a")

            assert result["webview"] is False
            assert result["title"] == "Page A"
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_scroll_requires_webview(self, session):
        result = await session.scroll("down", 300)
        assert "WebView browser is not active" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_scroll_with_webview(self, session):
        fake = FakeWebView()
        session.attach_webview(fake)

        result = await session.scroll("down", 300)

        assert result["ok"] is True
        assert fake.scrolls == [("down", 300)]

    @pytest.mark.asyncio
    async def test_type_selector_with_webview(self, session):
        fake = FakeWebView()
        session.attach_webview(fake)

        result = await session.type_selector("input[name=q]", "hello")

        assert result["ok"] is True
        assert fake.typed == [("input[name=q]", "hello")]

    @pytest.mark.asyncio
    async def test_click_selector_with_webview(self, session):
        fake = FakeWebView()
        session.attach_webview(fake)

        result = await session.click_selector("button#go")

        assert result["ok"] is True
        assert fake.clicked == ["button#go"]

    @pytest.mark.asyncio
    async def test_back_uses_webview_history(self, session):
        fake = FakeWebView()
        session.attach_webview(fake)
        await session.navigate("https://example.com/1")
        await session.navigate("https://example.com/2")

        result = await session.back()

        assert fake.back_called == 1
        assert result["webview"] is True
        assert result["url"] == "https://example.com/2"

    @pytest.mark.asyncio
    async def test_detach_falls_back_to_static(self, session):
        fake = FakeWebView()
        session.attach_webview(fake)
        session.detach_webview()
        patcher, client = _patch_client()
        try:
            client.get = AsyncMock(return_value=_resp(text=HTML_A, url="https://example.com/a"))

            result = await session.navigate("https://example.com/a")

            assert "webview" not in result
            assert result["title"] == "Page A"
        finally:
            patcher.stop()
