"""Media tools for Hermes Mobile (desktop parity).

vision_analyze: ask a vision-capable model about an image (URL or local path).
image_generate: create an image from a prompt through the configured provider's
OpenAI-compatible /images/generations endpoint (OpenRouter/OpenAI support it).

Both degrade gracefully when the active provider has no key.
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from hermes_mobile.config.settings import get_settings

# Default vision model used when the provider's own fallback list is not
# vision-capable or is ambiguous. Kept cheap: gpt-4o-mini handles images.
VISION_MODEL = "openai/gpt-4o-mini"
IMAGE_MODEL = "openai/gpt-image-1"


def _is_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _image_content(image_url: str) -> Dict[str, Any]:
    """Build an OpenAI-style image_url content part (URL or base64 local file)."""
    if _is_url(image_url):
        return {"type": "image_url", "image_url": {"url": image_url}}
    # Local path: read and inline as base64 data URL.
    try:
        data = Path(image_url).read_bytes()
        import mimetypes

        mime = mimetypes.guess_type(image_url)[0] or "image/png"
        b64 = base64.b64encode(data).decode()
        return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
    except Exception as e:
        return {"type": "text", "text": f"<could not read image {image_url}: {e}>"}


async def vision_analyze_tool(
    image_url: str,
    question: str = "Describe this image in detail.",
    agent: Optional[Any] = None,
) -> Dict[str, Any]:
    """Analyze an image with a vision-capable model through the agent's client."""
    if agent is None or agent._client is None:
        return {"error": "AI provider not configured (add an API key in Settings)."}
    if not image_url:
        return {"error": "image_url is required"}

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                _image_content(image_url),
            ],
        }
    ]

    try:
        client = agent._require_client()
        response = await client.chat.completions.create(
            model=VISION_MODEL,
            messages=messages,
            max_tokens=1024,
        )
        return {"analysis": response.choices[0].message.content or ""}
    except Exception as e:
        return {"error": str(e)}


async def image_generate_tool(
    prompt: str,
    agent: Optional[Any] = None,
) -> Dict[str, Any]:
    """Generate an image via the provider's OpenAI-compatible image endpoint."""
    settings = get_settings()
    api_key = (
        settings.openrouter_api_key
        or settings.openai_api_key
        or settings.anthropic_api_key
        or settings.gemini_api_key
    )
    if not api_key:
        return {"error": "No API key configured for image generation."}
    if not prompt or not prompt.strip():
        return {"error": "prompt is required"}

    base_url = agent._get_base_url() if agent is not None else "https://openrouter.ai/api/v1"
    url = base_url.rstrip("/") + "/images/generations"

    payload = {
        "model": IMAGE_MODEL,
        "prompt": prompt,
        "n": 1,
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
            data = resp.json()
            items = data.get("data") or []
            if not items:
                return {"error": "No image returned"}
            item = items[0]
            if item.get("url"):
                return {"url": item["url"]}
            if item.get("b64_json"):
                return {"b64_json": item["b64_json"][:200] + "…"}
            return {"error": "Unexpected response shape"}
    except httpx.TimeoutException:
        return {"error": "Image generation timed out"}
    except Exception as e:
        return {"error": str(e)}
