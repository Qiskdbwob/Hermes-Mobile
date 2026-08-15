"""WebView automation engine for the agent browser session.

Wraps ``flet_webview.WebView`` (``webview_flutter``) so the agent gets a real,
JavaScript-capable browser on Android / iOS / macOS / Web: forms, scrolling,
dynamic content. When the control is unavailable (Linux/Windows desktop, or
the package is not installed) the browser session keeps falling back to the
static httpx + BeautifulSoup engine.

Import is lazy so the rest of the app works even where ``flet-webview`` is
missing (e.g. the Python 3.9 / Flet 0.28 CI line).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Platforms flet-webview supports (per its docs: iOS, Android, macOS, Web).
_WEBVIEW_PLATFORMS = {"android", "ios", "macos", "web"}


def _import_webview() -> Any:
    """Import flet_webview (isolated so tests can patch it)."""
    import flet_webview  # noqa: F401

    return flet_webview


def _webview_import_available() -> bool:
    try:
        _import_webview()
        return True
    except Exception:
        return False


def webview_available(page: Any) -> bool:
    """True when the host platform can render the WebView control."""
    if not _webview_import_available():
        return False
    raw = str(
        getattr(getattr(page, "platform", None), "value", getattr(page, "platform", ""))
    ).lower()
    return raw in _WEBVIEW_PLATFORMS


class WebViewEngine:
    """Drives a flet-webview control: navigate, evaluate JS, scroll, type, click."""

    def __init__(self, page: Any):
        self._page = page
        self._control: Optional[Any] = None
        self._container: Optional[Any] = None
        # Created lazily inside async methods: on Python 3.9, asyncio.Event()
        # binds to the current event loop at construction and raises when no
        # loop exists yet (engine is built by UI code outside a running loop).
        self._page_ended: Optional[asyncio.Event] = None
        self._last_error: Optional[str] = None

    @property
    def is_mounted(self) -> bool:
        return self._control is not None

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def build_control(self, url: str = "about:blank") -> Any:
        """Create the WebView control (imports flet_webview lazily).

        Returns None when flet-webview is not installed (e.g. the Python 3.9
        CI line); callers must fall back to the static browser engine.
        """
        try:
            fwv = _import_webview()
        except Exception:
            self._last_error = "flet-webview is not installed"
            return None
        self._control = fwv.WebView(
            url=url,
            expand=True,
            on_page_ended=lambda e: self._on_page_ended(),
            on_web_resource_error=lambda e: self._on_resource_error(e),
        )
        return self._control

    def _on_page_ended(self) -> None:
        event = self._page_ended
        if event is not None:
            event.set()

    def _on_resource_error(self, event: Any) -> None:
        data = getattr(event, "data", None)
        self._last_error = str(data or "web resource error")

    def mount(self, container: Any) -> None:
        """Mount the WebView control inside a container.

        No-op (control stays unmounted) when flet-webview is unavailable, so
        callers can safely fall back to the static browser engine.
        """
        if self._control is None:
            self.build_control()
        if self._control is None:
            return
        self._container = container
        container.content = self._control
        try:
            self._page.update()
        except Exception:
            pass

    def dismount(self) -> None:
        """Detach the control from its container."""
        if self._container is not None and self._control is not None:
            try:
                self._container.content = None
            except Exception:
                pass
        self._container = None
        self._control = None

    # ── Navigation ─────────────────────────────────────────────

    async def navigate(self, url: str, timeout: float = 30.0) -> Dict[str, Any]:
        """Load a URL and wait for the page to finish (bounded wait)."""
        if self._control is None:
            return {"ok": False, "error": "WebView is not mounted"}
        self._page_ended = asyncio.Event()
        self._last_error = None
        try:
            if hasattr(self._control, "load_request"):
                await self._control.load_request(url)
            else:
                self._control.url = url
                try:
                    self._page.update()
                except Exception:
                    pass
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        try:
            await asyncio.wait_for(self._page_ended.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            # The page may still render; the snapshot decides what is usable.
            pass
        self._page_ended = None
        title = await self._safe("get_title", default="")
        current = await self._safe("get_current_url", default=url)
        return {
            "ok": True,
            "title": str(title or ""),
            "url": str(current or url),
            "error": self._last_error,
        }

    async def back(self) -> bool:
        """Go back one history step; returns False when there is no history."""
        if self._control is None:
            return False
        try:
            if await self._control.can_go_back():
                await self._control.go_back()
                return True
        except Exception as exc:
            logger.warning("WebView back failed: %s", exc)
        return False

    async def reload(self) -> bool:
        if self._control is None:
            return False
        try:
            await self._control.reload()
            return True
        except Exception:
            return False

    # ── JS evaluation ───────────────────────────────────────────

    async def evaluate(self, js: str) -> Any:
        """Run JavaScript in the current page and return its value (or None)."""
        if self._control is None:
            return None
        try:
            return await self._control.run_javascript(js)
        except Exception as exc:
            logger.warning("WebView JS failed: %s", exc)
            return None

    async def page_text(self, max_chars: int = 8000) -> str:
        """Extract the rendered page text via JS (works on JS-heavy pages)."""
        raw = await self.evaluate("document.body ? document.body.innerText : ''")
        text = str(raw or "").strip()
        return text[:max_chars]

    async def page_html(self, max_chars: int = 8000) -> str:
        raw = await self.evaluate(
            "document.documentElement ? document.documentElement.outerHTML : ''"
        )
        text = str(raw or "").strip()
        return text[:max_chars]

    # ── Interaction ─────────────────────────────────────────────

    async def scroll(self, direction: str = "down", amount: int = 600) -> bool:
        """Scroll the page. direction: up|down|top|bottom."""
        if self._control is None:
            return False
        direction = str(direction or "down").lower()
        amount = max(1, int(amount or 600))
        try:
            if direction == "top":
                await self._control.scroll_to(0, 0)
            elif direction == "bottom":
                await self._control.scroll_to(0, 999999)
            else:
                sign = -1 if direction in ("up",) else 1
                await self._control.scroll_by(0, sign * amount)
            return True
        except Exception as exc:
            logger.warning("WebView scroll failed: %s", exc)
            return False

    async def click_selector(self, selector: str) -> bool:
        """Click the first element matching a CSS selector via JS."""
        js = (
            "(() => { const el = document.querySelector("
            + json.dumps(str(selector or ""))
            + "); if (!el) return false; el.click(); return true; })()"
        )
        result = await self.evaluate(js)
        return result is not None and result is not False

    async def type_selector(self, selector: str, text: str) -> bool:
        """Set a form field value via JS, firing input/change events."""
        js = (
            "(() => { const el = document.querySelector("
            + json.dumps(str(selector or ""))
            + "); if (!el) return false; el.focus(); "
            + "const proto = (el instanceof HTMLTextAreaElement || "
            + "el instanceof HTMLInputElement) ? HTMLInputElement.prototype "
            + ": HTMLElement.prototype; "
            + "const setter = Object.getOwnPropertyDescriptor(proto, 'value'); "
            + "if (setter && setter.set) setter.set.call(el, "
            + json.dumps(str(text or ""))
            + "); else el.value = "
            + json.dumps(str(text or ""))
            + "; el.dispatchEvent(new Event('input', {bubbles: true})); "
            + "el.dispatchEvent(new Event('change', {bubbles: true})); "
            + "return true; })()"
        )
        result = await self.evaluate(js)
        return result is not None and result is not False

    async def press_key(self, key: str) -> bool:
        """Dispatch a keyboard event for a key like Enter, Escape, Tab."""
        mapping = {
            "enter": "Enter",
            "escape": "Escape",
            "esc": "Escape",
            "tab": "Tab",
            "arrowdown": "ArrowDown",
            "arrowup": "ArrowUp",
        }
        key_name = mapping.get(str(key or "").lower(), str(key or ""))
        js = (
            "(() => { document.dispatchEvent(new KeyboardEvent('keydown', "
            "{key: " + json.dumps(key_name) + ", bubbles: true})); return true; })()"
        )
        result = await self.evaluate(js)
        return result is not None and result is not False

    async def _safe(self, method: str, default: Any = None) -> Any:
        if self._control is None:
            return default
        fn = getattr(self._control, method, None)
        if fn is None:
            return default
        try:
            return await fn()
        except Exception:
            return default
