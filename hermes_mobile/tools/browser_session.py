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

from hermes_mobile.tools.web_tools import USER_AGENT, _safe_get

logger = logging.getLogger(__name__)

TIMEOUT = 15.0
MAX_CONTENT = 8000


class BrowserSession:
    """A single persistent browsing session (one per app process)."""

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._history: List[str] = []
        self._current_url: Optional[str] = None
        # Optional WebView automation engine (see webview_engine.py). When a
        # WebView is mounted (Browser view), navigation and interaction use the
        # real JS-capable browser; otherwise the static engine is used.
        self.webview: Optional[Any] = None

    def attach_webview(self, engine: Any) -> None:
        """Attach a mounted WebView engine (Browser view)."""
        self.webview = engine

    def detach_webview(self) -> None:
        """Drop the WebView engine and go back to the static engine."""
        self.webview = None

    def _webview_active(self) -> bool:
        return self.webview is not None and getattr(self.webview, "is_mounted", False)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=TIMEOUT,
                headers={"User-Agent": USER_AGENT},
            )
        return self._client

    async def navigate(self, url: str) -> Dict[str, Any]:
        """Navigate to a URL, recording history, and return a page snapshot.

        Every hop is validated by the shared SSRF guard (no loopback/private
        hosts, redirects checked one at a time).
        """
        if not url or not url.strip():
            return {"error": "URL is required"}
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        if self._webview_active():
            return await self._navigate_webview(url)

        client = await self._get_client()
        response, error = await _safe_get(client, url)
        if error:
            return {"url": url, "error": error}
        if response is None:
            return {"url": url, "error": "No response"}
        if self._current_url:
            self._history.append(self._current_url)
        self._current_url = str(response.url)
        return self._snapshot(response)

    async def _navigate_webview(self, url: str) -> Dict[str, Any]:
        """Navigate inside the mounted WebView and extract the rendered page.

        Falls back to the static engine when the WebView returns no usable text
        (e.g. the page blocked JS evaluation or failed to render).
        """
        result = await self.webview.navigate(url)
        if not result.get("ok"):
            return {"url": url, "error": result.get("error", "WebView navigation failed")}
        if self._current_url:
            self._history.append(self._current_url)
        self._current_url = result.get("url") or url

        text = await self.webview.page_text(MAX_CONTENT)
        title = str(result.get("title") or "")
        if not text:
            # WebView rendered nothing usable: fall back to the static engine.
            client = await self._get_client()
            response, error = await _safe_get(client, url)
            if not error and response is not None:
                snapshot = self._snapshot(response)
                snapshot["webview"] = False
                return snapshot
            return {
                "url": self._current_url,
                "title": title,
                "content": "",
                "error": "Page rendered no readable text",
            }

        links = await self._webview_links()
        return {
            "url": self._current_url,
            "title": title,
            "status_code": 200,
            "content": text,
            "links": links,
            "content_length": len(text),
            "webview": True,
        }

    async def _webview_links(self, limit: int = 20) -> List[Dict[str, str]]:
        js = (
            "JSON.stringify(Array.from(document.querySelectorAll('a[href]'))"
            ".filter(a => !a.href.startsWith('#') && !a.href.startsWith('javascript:'))"
            ".slice(0, " + str(limit) + ").map(a => ({text: "
            "(a.innerText || a.textContent || '').trim().slice(0,80), href: a.href})))"
        )
        raw = await self.webview.evaluate(js)
        if not raw:
            return []
        try:
            import json

            items = json.loads(str(raw))
        except Exception:
            return []
        return [
            {"text": str(item.get("text") or ""), "href": str(item.get("href") or "")}
            for item in items
            if isinstance(item, dict)
        ][:limit]

    async def back(self) -> Dict[str, Any]:
        """Navigate to the previous page in history."""
        if self._webview_active() and self.webview:
            if await self.webview.back():
                current = await self.webview._safe("get_current_url", default=None)
                if current and (not self._history or self._history[-1] != current):
                    self._history.append(current)
                self._current_url = current or self._current_url
                text = await self.webview.page_text(MAX_CONTENT)
                title = await self.webview._safe("get_title", default="")
                return {
                    "url": self._current_url,
                    "title": str(title or ""),
                    "status_code": 200,
                    "content": text,
                    "content_length": len(text),
                    "webview": True,
                }
            return {"error": "WebView has no back history"}

        if not self._history:
            return {"error": "No history to go back to"}
        url = self._history.pop()
        client = await self._get_client()
        response, error = await _safe_get(client, url)
        if error:
            self._history.append(url)  # keep it retryable on transient failure
            return {"url": url, "error": error}
        if response is None:
            self._history.append(url)
            return {"url": url, "error": "No response"}
        self._current_url = str(response.url)
        return self._snapshot(response)

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
        response, error = await _safe_get(client, self._current_url)
        if error:
            return {"url": self._current_url, "error": error}
        if response is None:
            return {"url": self._current_url, "error": "No response"}
        try:
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

    async def scroll(self, direction: str = "down", amount: int = 600) -> Dict[str, Any]:
        """Scroll the active WebView (static engine has no scrolling)."""
        if not self._webview_active():
            return {
                "error": "WebView browser is not active — open the Browser view to enable "
                "real web automation (scroll, forms, JS pages)",
            }
        ok = await self.webview.scroll(direction, amount)
        return {"ok": ok, "direction": direction, "amount": amount}

    async def type_selector(self, selector: str, text: str) -> Dict[str, Any]:
        """Type into a form field via the active WebView."""
        if not self._webview_active():
            return {
                "error": "WebView browser is not active — open the Browser view to enable "
                "real web automation (scroll, forms, JS pages)",
            }
        ok = await self.webview.type_selector(selector, text)
        return {"ok": ok, "selector": selector, "typed": len(str(text))}

    async def click_selector(self, selector: str) -> Dict[str, Any]:
        """Click an element by CSS selector via the active WebView."""
        if not self._webview_active():
            return {
                "error": "WebView browser is not active — open the Browser view to enable "
                "real web automation (scroll, forms, JS pages)",
            }
        ok = await self.webview.click_selector(selector)
        return {"ok": ok, "selector": selector}

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


async def browser_scroll_tool(direction: str = "down", amount: int = 600) -> Dict[str, Any]:
    """Scroll the WebView page (up/down/top/bottom)."""
    return await _session.scroll(direction, amount)


async def browser_type_tool(selector: str, text: str) -> Dict[str, Any]:
    """Type text into a form field (WebView) by CSS selector."""
    return await _session.type_selector(selector, text)


async def browser_click_selector_tool(selector: str) -> Dict[str, Any]:
    """Click an element by CSS selector (WebView)."""
    return await _session.click_selector(selector)
