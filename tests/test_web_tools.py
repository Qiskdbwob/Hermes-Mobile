"""Tests for web tools (HTML parsing, no network calls)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hermes_mobile.tools.web_tools import (
    web_search_tool,
    web_extract_tool,
    browser_navigate_tool,
    browser_snapshot_tool,
    _clean_html,
    _extract_title,
    _parse_ddg_results,
    MAX_EXTRACT_CHARS,
)


SAMPLE_HTML = """
<html>
<head><title>Test Page</title></head>
<body>
    <h1>Hello World</h1>
    <p>This is a test paragraph.</p>
    <script>alert('bad')</script>
    <style>.hidden { display: none; }</style>
    <nav>Navigation</nav>
    <footer>Footer</footer>
</body>
</html>
"""

SAMPLE_DDG_RESULTS = """
<html>
<body>
    <div class="result">
        <h2><a href="https://example.com">Example</a></h2>
        <a class="result__a" href="https://example.com/link">Example Link</a>
        <span class="result__snippet">This is an example snippet</span>
    </div>
    <div class="result__body">
        <a class="result__a" href="https://example.org">Org</a>
        <div class="result__snippet">Organization snippet</div>
    </div>
</body>
</html>
"""


def _make_http_response(status_code=200, text=SAMPLE_HTML, url="https://example.com"):
    """Create a proper httpx mock response."""
    import httpx
    from httpx import Request, Response

    request = Request("GET", url)
    resp = Response(status_code=status_code, text=text, request=request)
    return resp


class TestCleanHtml:
    def test_removes_scripts_and_styles(self):
        cleaned = _clean_html(SAMPLE_HTML)
        assert "alert" not in cleaned
        assert ".hidden" not in cleaned
        assert "Navigation" not in cleaned
        assert "Footer" not in cleaned

    def test_preserves_content(self):
        cleaned = _clean_html(SAMPLE_HTML)
        assert "Hello World" in cleaned
        assert "test paragraph" in cleaned

    def test_truncates_long_text(self):
        long_html = "<html><body>" + "A" * (MAX_EXTRACT_CHARS + 1000) + "</body></html>"
        cleaned = _clean_html(long_html)
        assert len(cleaned) <= MAX_EXTRACT_CHARS


class TestExtractTitle:
    def test_extracts_title(self):
        assert _extract_title(SAMPLE_HTML) == "Test Page"

    def test_no_title(self):
        assert _extract_title("<html><body>No title</body></html>") == ""

    def test_empty_html(self):
        assert _extract_title("") == ""


class TestParseDdgResults:
    def test_parses_results(self):
        results = _parse_ddg_results(SAMPLE_DDG_RESULTS)
        assert len(results) >= 1

    def test_parsed_fields(self):
        results = _parse_ddg_results(SAMPLE_DDG_RESULTS)
        if results:
            assert "title" in results[0]
            assert "url" in results[0]
            assert "snippet" in results[0]

    def test_empty_html(self):
        assert _parse_ddg_results("") == []

    def test_no_results(self):
        assert _parse_ddg_results("<html><body>No results here</body></html>") == []


class TestWebSearchTool:
    async def test_empty_query(self):
        result = await web_search_tool(query="")
        assert result["results"] == []
        assert "Empty query" in result.get("error", "")

    async def test_whitespace_query(self):
        result = await web_search_tool(query="   ")
        assert "error" in result

    async def test_max_results_clamped(self):
        with patch("hermes_mobile.tools.web_tools.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get = AsyncMock(return_value=_make_http_response(text=SAMPLE_DDG_RESULTS))

            result = await web_search_tool(query="test", max_results=100)
            assert len(result["results"]) <= 10

    async def test_http_error(self):
        with patch("hermes_mobile.tools.web_tools.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get = AsyncMock(return_value=_make_http_response(status_code=403))

            result = await web_search_tool(query="test")
            assert "error" in result

    async def test_timeout(self):
        with patch("hermes_mobile.tools.web_tools.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_client
            from httpx import TimeoutException

            mock_client.get = AsyncMock(side_effect=TimeoutException("Timed out"))

            result = await web_search_tool(query="test")
            assert "timed out" in result.get("error", "").lower()


class TestWebExtractTool:
    async def test_no_urls(self):
        result = await web_extract_tool(urls=[])
        assert "error" in result

    async def test_max_urls_clamped(self):
        with patch("hermes_mobile.tools.web_tools.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get = AsyncMock(return_value=_make_http_response())

            urls = [f"https://example.com/{i}" for i in range(10)]
            result = await web_extract_tool(urls=urls)
            assert len(result["pages"]) <= 5

    async def test_successful_extract(self):
        with patch("hermes_mobile.tools.web_tools.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get = AsyncMock(return_value=_make_http_response(text=SAMPLE_HTML))

            result = await web_extract_tool(urls=["https://example.com"])
            assert len(result["pages"]) == 1
            page = result["pages"][0]
            assert page["url"] == "https://example.com"
            assert "Hello World" in page["content"]


class TestBrowserNavigateTool:
    async def test_empty_url(self):
        result = await browser_navigate_tool(url="")
        assert "error" in result

    async def test_successful_navigate(self):
        with patch("hermes_mobile.tools.web_tools.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get = AsyncMock(
                return_value=_make_http_response(text=SAMPLE_HTML, url="https://example.com")
            )

            result = await browser_navigate_tool(url="https://example.com")
            assert result["url"] == "https://example.com"
            assert "Hello World" in result["content"]
            assert result["title"] == "Test Page"

    async def test_auto_adds_https(self):
        with patch("hermes_mobile.tools.web_tools.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get = AsyncMock(return_value=_make_http_response())

            result = await browser_navigate_tool(url="example.com")
            # Should have added https://
            call_args = mock_client.get.call_args
            assert call_args[0][0].startswith("https://")

    async def test_navigate_http_error(self):
        with patch("hermes_mobile.tools.web_tools.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get = AsyncMock(return_value=_make_http_response(status_code=500))

            result = await browser_navigate_tool(url="https://example.com/error")
            assert "error" in result


class TestBrowserSnapshotTool:
    async def test_snapshot_delegates_to_navigate(self):
        with patch("hermes_mobile.tools.web_tools.browser_navigate_tool") as mock_nav:
            mock_nav.return_value = {
                "url": "https://example.com",
                "title": "Test",
                "content": "Hello",
                "links": [{"text": "Link", "href": "/link"}],
                "status_code": 200,
            }

            result = await browser_snapshot_tool(url="https://example.com")
            assert result["url"] == "https://example.com"
            assert result["title"] == "Test"
            assert result["status_code"] == 200
            mock_nav.assert_called_once_with("https://example.com")

    async def test_snapshot_passes_errors(self):
        with patch("hermes_mobile.tools.web_tools.browser_navigate_tool") as mock_nav:
            mock_nav.return_value = {"error": "Not found"}

            result = await browser_snapshot_tool(url="https://example.com/404")
            assert "error" in result
