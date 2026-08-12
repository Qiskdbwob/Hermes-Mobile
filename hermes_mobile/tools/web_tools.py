"""Web search, content extraction, and browser tools for Hermes Mobile.

Uses httpx with DuckDuckGo HTML search as the primary search backend
(free, no API key required). Browser tools use httpx + BeautifulSoup
for lightweight page navigation without CDP.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)

SEARCH_TIMEOUT = 15.0
EXTRACT_TIMEOUT = 20.0
MAX_EXTRACT_CHARS = 8000
MAX_REDIRECTS = 3


# ═══════════════════════════════════════════════════════════════
# SSRF guards — never let the agent fetch loopback/private hosts
# ═══════════════════════════════════════════════════════════════


def _blocked_url_error(url: str) -> Optional[str]:
    """Return an error string when *url* is unsafe (bad scheme or private host).

    Rejects non-http(s) schemes and hosts that resolve to loopback, private,
    link-local, reserved, multicast or unspecified addresses (cloud metadata
    at 169.254.169.254 and LAN services included). Hostnames are resolved at
    validation time; DNS rebinding between check and fetch is outside this
    guard's scope.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"Unsupported URL scheme: {parsed.scheme or 'none'}"
    host = parsed.hostname
    if not host:
        return "URL has no host"

    try:
        ip = ipaddress.ip_address(host)
        addresses = {str(ip)}
    except ValueError:
        # Hostname: resolve and check every address it can reach.
        try:
            infos = socket.getaddrinfo(host, None)
        except (socket.gaierror, OSError):
            return None  # Let the fetch fail naturally if DNS is broken.
        addresses = {info[4][0] for info in infos}

    for raw in addresses:
        try:
            addr = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
        ):
            return f"Blocked private/internal address: {host}"
    return None


async def _safe_get(
    client: httpx.AsyncClient,
    url: str,
) -> Tuple[Optional[httpx.Response], Optional[str]]:
    """GET *url* with an SSRF check and bounded manual redirects.

    Redirects are followed one hop at a time so every target URL is validated
    (auto-follow would silently redirect into private hosts). Returns
    (response, None) or (None, error).
    """
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        error = _blocked_url_error(current)
        if error:
            return None, error
        try:
            response = await client.get(
                current,
                headers={"User-Agent": USER_AGENT},
                follow_redirects=False,
            )
        except httpx.TimeoutException:
            return None, "Request timed out"
        except Exception as exc:  # noqa: BLE001 - surfaced to the model as text
            return None, str(exc)
        if response.is_redirect:
            location = response.headers.get("location")
            if not location:
                return response, None
            current = urljoin(str(response.url), location)
            continue
        return response, None
    return None, "Too many redirects"


# ═══════════════════════════════════════════════════════════════
# HTML helpers
# ═══════════════════════════════════════════════════════════════


def _clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:MAX_EXTRACT_CHARS]


def _extract_title(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    if soup.title:
        return soup.title.get_text(strip=True)
    return ""


# ═══════════════════════════════════════════════════════════════
# Web Search (DuckDuckGo HTML)
# ═══════════════════════════════════════════════════════════════


def _parse_ddg_results(html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    results = []

    for result in soup.select(".result, .result__body, article[data-testid='result']"):
        title_el = result.select_one("h2, .result__title, a[data-testid='result-title-a']")
        link_el = result.select_one("a[data-testid='result-title-a'], .result__url, a.result__a")
        snippet_el = result.select_one(
            ".result__snippet, .result__body, span[data-testid='result-snippet']"
        )

        title = title_el.get_text(strip=True) if title_el else ""
        link = link_el.get("href", "") if link_el else ""
        snippet = snippet_el.get_text(strip=True) if snippet_el else ""

        if not link:
            continue

        parsed = urlparse(link)
        if parsed.netloc == "duckduckgo.com" and parsed.path == "/l/":
            params = parse_qs(parsed.query)
            link = params.get("uddg", [link])[0]

        if title or snippet:
            results.append(
                {
                    "title": title,
                    "url": link,
                    "snippet": snippet,
                }
            )

    return results[:10]


async def web_search_tool(query: str, max_results: int = 5) -> Dict[str, Any]:
    """Search the web using DuckDuckGo HTML search."""
    if not query or not query.strip():
        return {"results": [], "query": query, "error": "Empty query"}

    max_results = max(1, min(max_results, 10))

    try:
        async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
            response = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query.strip()},
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
            )

            if response.status_code != 200:
                return {
                    "results": [],
                    "query": query,
                    "error": f"Search returned status {response.status_code}",
                }

            results = _parse_ddg_results(response.text)

            return {
                "results": results[:max_results],
                "query": query,
                "total_found": len(results),
            }

    except httpx.TimeoutException:
        return {"results": [], "query": query, "error": "Search timed out"}
    except Exception as e:
        logger.error("web_search_tool error: %s", e)
        return {"results": [], "query": query, "error": str(e)}


# ═══════════════════════════════════════════════════════════════
# Web Extract
# ═══════════════════════════════════════════════════════════════


async def web_extract_tool(
    urls: List[str],
    format: str = "text",
    max_chars: int = MAX_EXTRACT_CHARS,
) -> Dict[str, Any]:
    """Extract content from web pages."""
    if not urls:
        return {"pages": [], "error": "No URLs provided"}

    results = []

    async with httpx.AsyncClient(timeout=EXTRACT_TIMEOUT) as client:
        for url in urls[:5]:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            response, error = await _safe_get(client, url)
            if error:
                results.append({"url": url, "content": "", "error": error})
                continue
            if response is None:
                results.append({"url": url, "content": "", "error": "No response"})
                continue

            if response.status_code != 200:
                results.append(
                    {
                        "url": url,
                        "content": "",
                        "error": f"HTTP {response.status_code}",
                    }
                )
                continue

            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type:
                results.append(
                    {
                        "url": url,
                        "content": response.text[:max_chars],
                    }
                )
                continue

            text = _clean_html(response.text)
            results.append(
                {
                    "url": url,
                    "content": text[:max_chars],
                    "title": _extract_title(response.text),
                }
            )

    return {"pages": results}


# ═══════════════════════════════════════════════════════════════
# Browser Tools (lightweight, no CDP)
# ═══════════════════════════════════════════════════════════════


async def browser_navigate_tool(url: str) -> Dict[str, Any]:
    """Navigate to a URL and return page content (stateful session).

    Delegates to the shared BrowserSession so navigation history, link
    clicking and image listing stay consistent with this call (back/click/
    get_images operate on the same tab). SSRF validation applies to every
    hop inside the session.
    """
    from hermes_mobile.tools.browser_session import _session

    return await _session.navigate(url)


async def browser_snapshot_tool(url: str) -> Dict[str, Any]:
    """Return a structured text snapshot of a web page."""
    result = await browser_navigate_tool(url)
    if "error" in result:
        return result

    return {
        "url": result["url"],
        "title": result["title"],
        "content": result["content"],
        "links": result.get("links", [])[:10],
        "status_code": result["status_code"],
    }
