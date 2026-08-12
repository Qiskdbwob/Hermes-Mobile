"""Media tools for Hermes Mobile (desktop parity).

vision_analyze: ask a vision-capable model about an image (URL or local path).
image_generate: create an image from a prompt through the configured provider's
OpenAI-compatible /images/generations endpoint (OpenRouter/OpenAI support it).

Both resolve the model, endpoint and API key from the *active* provider so they
stay consistent with the main conversation, and degrade gracefully when the
active provider cannot serve the request.
"""

from __future__ import annotations

import base64
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from hermes_mobile.config.settings import get_settings

logger = logging.getLogger(__name__)

# Local images bigger than this are rejected before being base64-inlined
# (a huge payload would blow the request budget and cost real money).
MAX_IMAGE_BYTES = 5 * 1024 * 1024

# Vision-capable model per provider. Only providers whose OpenAI-compatible
# endpoint accepts OpenAI-style image_url content parts are listed.
VISION_MODELS: Dict[str, str] = {
    "openrouter": "openai/gpt-4o-mini",
    "openai": "gpt-4o-mini",
    "google": "gemini-1.5-flash",
    "together": "meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo",
}

# Providers with an OpenAI-compatible /images/generations endpoint.
IMAGE_MODELS: Dict[str, str] = {
    "openrouter": "openai/gpt-image-1",
    "openai": "gpt-image-1",
}


def _is_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _image_content(image_url: str) -> Dict[str, Any]:
    """Build an OpenAI-style image_url content part (URL or base64 local file)."""
    if _is_url(image_url):
        return {"type": "image_url", "image_url": {"url": image_url}}
    # Local path: read and inline as base64 data URL (caller has validated it).
    try:
        data = Path(image_url).read_bytes()
    except Exception as e:
        return {"type": "text", "text": f"<could not read image {image_url}: {e}>"}
    if len(data) > MAX_IMAGE_BYTES:
        return {
            "type": "text",
            "text": f"<image {image_url} is {len(data) / (1024 * 1024):.1f} MiB, "
            f"above the {MAX_IMAGE_BYTES // (1024 * 1024)} MiB limit>",
        }
    import mimetypes

    mime = mimetypes.guess_type(image_url)[0] or "image/png"
    b64 = base64.b64encode(data).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


async def vision_analyze_tool(
    image_url: str,
    question: str = "Describe this image in detail.",
    agent: Optional[Any] = None,
) -> Dict[str, Any]:
    """Analyze an image with a vision-capable model through the agent's client."""
    if agent is None or agent._client is None:
        reason = getattr(agent, "_client_error", None) or (
            "AI provider not configured (add an API key in Settings)."
        )
        return {"error": reason}
    if not image_url:
        return {"error": "image_url is required"}

    profile = getattr(agent, "_get_provider_profile", lambda: None)()
    provider_name = getattr(profile, "name", "") if profile else ""
    if not profile or not getattr(profile, "supports_vision", False):
        return {"error": f"Provider '{provider_name or 'unknown'}' does not support vision"}
    model = VISION_MODELS.get(provider_name)
    if not model:
        return {
            "error": f"No vision model configured for provider "
            f"'{provider_name or 'unknown'}' (use OpenRouter for vision)."
        }

    # Local paths must stay inside the file sandbox (same rules as read_file).
    resolved_image = image_url
    if not _is_url(image_url):
        from hermes_mobile.tools.path_security import validate_and_resolve_path

        ws = getattr(agent, "_workspace", None)
        resolved, error = validate_and_resolve_path(
            image_url,
            extra_dirs=[ws] if ws is not None else None,
            base_dir=ws if ws is not None else None,
        )
        if error:
            return {"error": f"Image path blocked: {error}"}
        resolved_image = str(resolved)

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                _image_content(resolved_image),
            ],
        }
    ]

    try:
        client = agent._require_client()
        response = await client.chat.completions.create(
            model=model,
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
    """Generate an image via the active provider's image endpoint."""
    if not prompt or not prompt.strip():
        return {"error": "prompt is required"}

    profile = agent._get_provider_profile() if agent is not None else None
    provider_name = getattr(profile, "name", "") if profile else ""
    model = IMAGE_MODELS.get(provider_name)
    if not model:
        return {
            "error": f"Provider '{provider_name or 'unknown'}' does not expose an "
            "image generation endpoint (use OpenRouter)."
        }

    base_url = agent._get_base_url() if agent is not None else "https://openrouter.ai/api/v1"
    api_key = agent._get_api_key() if agent is not None else ""
    if not api_key:
        return {"error": "No API key configured for the active provider."}

    url = base_url.rstrip("/") + "/images/generations"

    payload = {
        "model": model,
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
                try:
                    out_dir = get_settings().get_data_dir() / "generated"
                    out_dir.mkdir(parents=True, exist_ok=True)
                    out_path = out_dir / f"image_{uuid.uuid4().hex[:12]}.png"
                    out_path.write_bytes(base64.b64decode(item["b64_json"]))
                    return {"saved_path": str(out_path), "bytes": out_path.stat().st_size}
                except Exception as e:
                    return {"error": f"Failed to save generated image: {e}"}
            return {"error": "Unexpected response shape"}
    except httpx.TimeoutException:
        return {"error": "Image generation timed out"}
    except Exception as e:
        return {"error": str(e)}
