"""Tests for web tools (HTML parsing, no network calls)."""

from unittest.mock import AsyncMock, MagicMock, patch

from hermes_mobile.tools.web_tools import (
    MAX_EXTRACT_CHARS,
    _clean_html,
    _extract_title,
    _parse_ddg_results,
    browser_navigate_tool,
    browser_snapshot_tool,
    web_extract_tool,
    web_search_tool,
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

SAMPLE_HTML_WITH_LINKS = """
<html>
<head><title>Link Page</title></head>
<body>
    <a href="/valid">Valid Link</a>
    <a href="#section">Anchor Link</a>
    <a href="javascript:void(0)">JS Link</a>
</body>
</html>
"""
SAMPLE_DDG_WITH_REDIRECT = """
<html>
<body>
    <div class="result">
        <h2 class="result__title"><a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Freal-site.com%2Fpage">Redirect</a></h2>
        <span class="result__snippet">Redirect snippet</span>
    </div>
</body>
</html>
"""

SAMPLE_DDG_NO_LINK = """
<html>
<body>
    <div class="result">
        <h2>No Link Here</h2>
        <span class="result__snippet">Snippet without link</span>
    </div>
</body>
</html>
"""


def _make_http_response(status_code=200, text=SAMPLE_HTML, url="https://example.com"):
    """Create a proper httpx mock response."""
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

    def test_skips_result_without_link(self):
        results = _parse_ddg_results(SAMPLE_DDG_NO_LINK)
        assert len(results) == 0

    def test_handles_ddg_redirect(self):
        results = _parse_ddg_results(SAMPLE_DDG_WITH_REDIRECT)
        assert len(results) == 1
        assert "real-site.com" in results[0]["url"]


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

    async def test_generic_exception(self):
        with patch("hermes_mobile.tools.web_tools.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get = AsyncMock(side_effect=ConnectionError("DNS failure"))

            result = await web_search_tool(query="test")
            assert "error" in result


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

    async def test_extract_http_error(self):
        with patch("hermes_mobile.tools.web_tools.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get = AsyncMock(return_value=_make_http_response(status_code=404))

            result = await web_extract_tool(urls=["https://example.com/404"])
            assert len(result["pages"]) == 1
            assert "HTTP 404" in result["pages"][0].get("error", "")

    async def test_extract_timeout(self):
        with patch("hermes_mobile.tools.web_tools.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_client
            from httpx import TimeoutException

            mock_client.get = AsyncMock(side_effect=TimeoutException("Timed out"))

            result = await web_extract_tool(urls=["https://example.com"])
            assert "timed out" in result["pages"][0].get("error", "").lower()

    async def test_extract_generic_exception(self):
        with patch("hermes_mobile.tools.web_tools.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get = AsyncMock(side_effect=RuntimeError("Unexpected failure"))

            result = await web_extract_tool(urls=["https://example.com"])
            assert "Unexpected failure" in result["pages"][0].get("error", "")

    async def test_extract_non_html_content(self):
        json_response = _make_http_response(
            text='{"status": "ok"}',
        )
        json_response.headers["content-type"] = "application/json"

        with patch("hermes_mobile.tools.web_tools.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get = AsyncMock(return_value=json_response)

            result = await web_extract_tool(urls=["https://api.example.com/data"])
            assert len(result["pages"]) == 1
            assert "status" in result["pages"][0]["content"]

    async def test_extract_html_content_type(self):
        """When content-type includes text/html, _clean_html and _extract_title are used."""
        html_response = _make_http_response(text=SAMPLE_HTML)
        html_response.headers["content-type"] = "text/html; charset=utf-8"

        with patch("hermes_mobile.tools.web_tools.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get = AsyncMock(return_value=html_response)

            result = await web_extract_tool(urls=["https://example.com"])
            assert len(result["pages"]) == 1
            assert "Hello World" in result["pages"][0]["content"]
            assert result["pages"][0]["title"] == "Test Page"


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

            await browser_navigate_tool(url="example.com")
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

    async def test_navigate_timeout(self):
        with patch("hermes_mobile.tools.web_tools.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_client
            from httpx import TimeoutException

            mock_client.get = AsyncMock(side_effect=TimeoutException("Timed out"))

            result = await browser_navigate_tool(url="https://example.com")
            assert "timed out" in result.get("error", "").lower()

    async def test_navigate_generic_exception(self):
        with patch("hermes_mobile.tools.web_tools.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get = AsyncMock(side_effect=ConnectionRefusedError("Connection refused"))

            result = await browser_navigate_tool(url="https://example.com")
            assert "error" in result

    async def test_navigate_filters_links(self):
        """Anchor-only and javascript: links should be excluded."""
        with patch("hermes_mobile.tools.web_tools.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get = AsyncMock(
                return_value=_make_http_response(
                    text=SAMPLE_HTML_WITH_LINKS,
                    url="https://example.com",
                )
            )

            result = await browser_navigate_tool(url="https://example.com")
            links = result.get("links", [])
            hrefs = [link["href"] for link in links]
            assert "/valid" in hrefs
            assert "#section" not in hrefs
            assert "javascript:" not in hrefs


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


class TestSsrFProtection:
    """SSRF guard: never let the agent fetch loopback/private/link-local hosts."""

    def test_blocks_loopback_ip(self):
        from hermes_mobile.tools.web_tools import _blocked_url_error

        err = _blocked_url_error("http://127.0.0.1:8080/admin")
        assert err is not None and "Blocked private" in err

    def test_blocks_cloud_metadata(self):
        from hermes_mobile.tools.web_tools import _blocked_url_error

        err = _blocked_url_error("http://169.254.169.254/latest/meta-data/")
        assert err is not None and "Blocked private" in err

    def test_blocks_private_and_link_local_ip(self):
        from hermes_mobile.tools.web_tools import _blocked_url_error

        for url in ("http://10.0.0.5/secret", "http://192.168.1.10/x", "http://[::1]/"):
            assert _blocked_url_error(url) is not None

    def test_blocks_non_http_scheme(self):
        from hermes_mobile.tools.web_tools import _blocked_url_error

        err = _blocked_url_error("file:///etc/passwd")
        assert err is not None and "scheme" in err

    def test_allows_public_hostname(self):
        from hermes_mobile.tools.web_tools import _blocked_url_error

        # Real DNS resolution; if offline this returns None anyway (not blocked).
        assert _blocked_url_error("https://example.com") is None

    @patch("hermes_mobile.tools.web_tools.socket.getaddrinfo")
    def test_blocks_hostname_resolving_to_private(self, mock_gai):
        import socket

        from hermes_mobile.tools.web_tools import _blocked_url_error

        mock_gai.return_value = [(socket.AF_INET, 1, 6, "", ("192.168.1.50", 0))]
        err = _blocked_url_error("http://internal.example/")
        assert err is not None and "Blocked private" in err

    async def test_navigate_blocks_private_host_before_fetch(self):
        with patch("hermes_mobile.tools.web_tools.httpx.AsyncClient") as mock_cls:
            result = await browser_navigate_tool("http://127.0.0.1/admin")
            assert "error" in result and "Blocked private" in result["error"]
            mock_cls.return_value.__aenter__.return_value.get.assert_not_called()

    async def test_redirect_to_private_is_blocked(self):
        from hermes_mobile.tools.web_tools import _safe_get

        with patch("hermes_mobile.tools.web_tools.httpx.AsyncClient") as mock_cls:
            client = mock_cls.return_value.__aenter__.return_value
            redirect = _make_http_response(status_code=302, url="https://public.example/")
            redirect.headers["location"] = "http://127.0.0.1/admin"
            client.get = AsyncMock(return_value=redirect)

            response, error = await _safe_get(client, "https://public.example/")
            assert response is None
            assert error is not None and "Blocked private" in error
