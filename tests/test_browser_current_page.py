"""Tests for the browser session's current-page persistence.

Regression for: the model had no way to re-read the page already open in the
browsing session — every tool call needed a fresh navigate/extract. The new
``browser_current_page`` tool returns the live WebView text, the cached
snapshot, or (last resort) a re-fetch of the current URL.
"""

from types import SimpleNamespace

import pytest

from hermes_mobile.tools.browser_session import BrowserSession, browser_current_page_tool


class FakeWebView:
    """Minimal WebView engine double: is_mounted + JS evaluation."""

    def __init__(self, page_text="", links=None):
        self.is_mounted = True
        self._text = page_text
        self._links = links or []

    async def _safe(self, method, default=None):
        return {"get_current_url": "https://example.com/page", "get_title": "Example"}.get(
            method, default
        )

    async def page_text(self, max_chars=8000):
        return self._text

    async def evaluate(self, js):
        import json

        return json.dumps(self._links)


@pytest.mark.asyncio
class TestBrowserCurrentPage:
    async def test_error_when_nothing_loaded(self):
        session = BrowserSession()
        result = await session.current_page()
        assert "error" in result
        assert "browser_navigate" in result["error"]

    async def test_cached_snapshot_without_refetch(self):
        session = BrowserSession()
        session._current_url = "https://example.com/old"
        session._last_snapshot = {
            "url": "https://example.com/old",
            "title": "Old",
            "content": "cached body",
            "status_code": 200,
        }
        # A re-fetch must never happen when a cached snapshot exists.
        calls = []

        async def _fail_navigate(url):
            calls.append(url)
            return {"error": "should not navigate"}

        session.navigate = _fail_navigate  # type: ignore[method-assign]
        result = await session.current_page()
        assert result["content"] == "cached body"
        assert calls == []

    async def test_webview_active_reextracts_rendered_text(self):
        session = BrowserSession()
        session._current_url = "https://example.com/page"
        session.webview = FakeWebView(
            page_text="Rendered dynamic content",
            links=[{"text": "Home", "href": "https://example.com/"}],
        )
        result = await session.current_page()
        assert result["webview"] is True
        assert result["content"] == "Rendered dynamic content"
        assert result["url"] == "https://example.com/page"
        assert result["links"] == [{"text": "Home", "href": "https://example.com/"}]

    async def test_dead_webview_falls_back_to_cache(self):
        session = BrowserSession()
        session._current_url = "https://example.com/page"
        session._last_snapshot = {
            "url": "https://example.com/page",
            "title": "Cached title",
            "content": "cached body",
            "status_code": 200,
        }
        # WebView platform view died (view switch on Android): page_text is empty.
        session.webview = FakeWebView(page_text="")
        result = await session.current_page()
        assert result["content"] == "cached body"

    async def test_refetches_current_url_when_no_cache(self):
        session = BrowserSession()
        session._current_url = "https://example.com/last"
        navigated = []

        async def _fake_navigate(url):
            navigated.append(url)
            return {"url": url, "title": "Refetched", "content": "body", "status_code": 200}

        session.navigate = _fake_navigate  # type: ignore[method-assign]
        result = await session.current_page()
        assert navigated == ["https://example.com/last"]
        assert result["title"] == "Refetched"

    async def test_tool_delegates_to_shared_session(self, monkeypatch):
        async def _stub_current_page():
            return {"url": "https://example.com", "content": "stub"}

        monkeypatch.setattr(
            "hermes_mobile.tools.browser_session._session",
            SimpleNamespace(current_page=_stub_current_page),
        )
        result = await browser_current_page_tool()
        assert result["content"] == "stub"
