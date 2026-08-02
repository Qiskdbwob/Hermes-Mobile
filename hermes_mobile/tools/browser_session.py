"""Stateful lightweight browser session for Hermes Mobile.

Desktop parity for browser tools without CDP: a persistent httpx session with
cookies, navigation history (back), link clicking, and image listing. JS-heavy
pages degrade gracefully — the agent gets the static DOM snapshot instead.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

from hermes_mobile.tools.web_tools import USER_AGENT

logger = logging.getLogger(__name__)

TIMEOUT = 15.0
MAX_CONTENT = 8000


class BrowserSession:
    """A single persistent browsing session (one per app process)."""

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._history: List[str] = []
        self._current_url: Optional[str] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=TIMEOUT,
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
            )
        return self._client

    async def navigate(self, url: str) -> Dict[str, Any]:
        """Navigate to a URL, recording history, and return a page snapshot."""
        if not url or not url.strip():
            return {"error": "URL is required"}
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        client = await self._get_client()
        try:
            response = await client.get(url)
            if self._current_url:
                self._history.append(self._current_url)
            self._current_url = str(response.url)
            return self._snapshot(response)
        except httpx.TimeoutException:
            return {"url": url, "error": "Request timed out"}
        except Exception as e:
            return {"url": url, "error": str(e)}

    async def back(self) -> Dict[str, Any]:
        """Navigate to the previous page in history."""
        if not self._history:
            return {"error": "No history to go back to"}
        url = self._history.pop()
        client = await self._get_client()
        try:
            response = await client.get(url)
            self._current_url = str(response.url)
            return self._snapshot(response)
        except Exception as e:
            return {"url": url, "error": str(e)}

    async def click_link(self, href: str) -> Dict[str, Any]:
        """Click a link by href (resolves relative to the current page)."""
        if not href:
            return {"error": "href is required"}
        if self._current_url and href.startswith("/"):
            from urllib.parse import urljoin

            href = urljoin(self._current_url, href)
        return await self.navigate(href)

    async def get_images(self) -> Dict[str, Any]:
        """List images on the current page."""
        if not self._current_url:
            return {"error": "No page loaded"}
        client = await self._get_client()
        try:
            response = await client.get(self._current_url)
            soup = BeautifulSoup(response.text, "lxml")
            images = []
            for img in soup.find_all("img"):
                src = img.get("src") or img.get("data-src") or ""
                alt = img.get("alt", "")[:100]
                if src:
                    images.append({"src": src[:300], "alt": alt})
            return {"url": self._current_url, "images": images[:30]}
        except Exception as e:
            return {"error": str(e)}

    def _snapshot(self, response: httpx.Response) -> Dict[str, Any]:
        if response.status_code != 200:
            return {
                "url": str(response.url),
                "status_code": response.status_code,
                "content": "",
                "error": f"HTTP {response.status_code}",
            }
        soup = BeautifulSoup(response.text, "lxml")
        title = soup.title.get_text(strip=True) if soup.title else ""
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()
        text = "\n".join(
            line.strip() for line in soup.get_text(separator="\n", strip=True).split("\n") if line
        )
        links = [
            {"text": a.get_text(strip=True)[:80], "href": a.get("href", "")[:200]}
            for a in soup.find_all("a", href=True)
            if a.get("href") and not a["href"].startswith(("#", "javascript:"))
        ]
        return {
            "url": str(response.url),
            "title": title,
            "status_code": response.status_code,
            "content": text[:MAX_CONTENT],
            "links": links[:20],
            "content_length": len(text),
        }

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None


# Module-level singleton so the agent keeps one tab-like session.
_session = BrowserSession()


async def browser_back_tool() -> Dict[str, Any]:
    """Go back to the previous page."""
    return await _session.back()


async def browser_click_tool(href: str) -> Dict[str, Any]:
    """Click a link by its href attribute."""
    return await _session.click_link(href)


async def browser_get_images_tool() -> Dict[str, Any]:
    """List images on the current page."""
    return await _session.get_images()
