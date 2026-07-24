"""Internationalization (i18n) for Hermes Mobile.

Supports English (en) and Portuguese (pt-br).
Falls back to English keys when translations are missing.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_LOCALE_DIR = Path(__file__).parent
_DEFAULT_LOCALE = "en"
_AVAILABLE_LOCALES = ("en", "pt-br")
_translations: dict = {}
_current_locale: str = _DEFAULT_LOCALE


def _load_locale(locale: str) -> dict:
    path = _LOCALE_DIR / f"{locale}.json"
    if not path.exists():
        logger.warning("Locale file not found: %s", path)
        return {}

    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to load locale %s: %s", locale, e)
        return {}


def init(locale: Optional[str] = None) -> None:
    global _current_locale, _translations

    if locale and locale in _AVAILABLE_LOCALES:
        _current_locale = locale
    else:
        _current_locale = _DEFAULT_LOCALE

    _translations = _load_locale(_current_locale)
    logger.info("i18n initialized: %s (%d keys)", _current_locale, _count_keys(_translations))


def set_locale(locale: str) -> bool:
    global _current_locale, _translations

    if locale not in _AVAILABLE_LOCALES:
        logger.warning("Unsupported locale: %s", locale)
        return False

    _current_locale = locale
    _translations = _load_locale(locale)
    return True


def get_locale() -> str:
    return _current_locale


def available_locales() -> tuple[str, ...]:
    return _AVAILABLE_LOCALES


def t(key: str, **kwargs) -> str:
    """Translate a dotted key path. Falls back to key if missing."""
    fallback = _load_locale("en") if _current_locale != "en" else {}

    parts = key.split(".")
    value = _translations
    fb_value = fallback

    for part in parts:
        if isinstance(value, dict):
            value = value.get(part, "")
        else:
            value = ""

        if isinstance(fb_value, dict):
            fb_value = fb_value.get(part, "")
        else:
            fb_value = ""

    result = value or fb_value or key

    if kwargs:
        try:
            result = result.format(**kwargs)
        except (KeyError, ValueError):
            pass

    return result


def _count_keys(d: dict, prefix: str = "") -> int:
    count = 0
    for k, v in d.items():
        if isinstance(v, dict):
            count += _count_keys(v, f"{prefix}{k}.")
        else:
            count += 1
    return count


def translate_dict(data: dict, locale: Optional[str] = None) -> dict:
    if locale and locale != _current_locale:
        old_locale = _current_locale
        set_locale(locale)
        result = _translate_dict(data)
        set_locale(old_locale)
        return result
    return _translate_dict(data)


def _translate_dict(data: dict) -> dict:
    result = {}
    for k, v in data.items():
        if isinstance(v, str) and "." in v and not v.startswith("{"):
            translated = t(v)
            result[k] = translated if translated != v else v
        elif isinstance(v, dict):
            result[k] = _translate_dict(v)
        elif isinstance(v, list):
            result[k] = [t(item) if isinstance(item, str) and "." in item else item for item in v]
        else:
            result[k] = v
    return result


init()
