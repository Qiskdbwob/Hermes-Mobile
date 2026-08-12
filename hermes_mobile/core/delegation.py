"""Subagent delegation for Hermes Mobile.

Allows the main agent to spawn parallel subagent tasks for
independent subtasks (e.g., "search these 3 topics simultaneously").

Inspired by Hermes Desktop agent/async_delegation.py.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from hermes_mobile.config.settings import get_settings
from hermes_mobile.providers import get_provider_profile
from hermes_mobile.tools.web_tools import web_search_tool

logger = logging.getLogger(__name__)

MAX_CONCURRENT_SUBAGENTS = 3
SUBAGENT_TIMEOUT = 60.0


async def _quick_tool_call(
    provider_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    available_tools: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Make a single-turn LLM call for a subagent task."""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if provider_url and "openrouter" in provider_url:
        headers["HTTP-Referer"] = "https://hermes-mobile.app"
        headers["X-Title"] = "Hermes Mobile Subagent"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    body = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 2048,
    }

    if available_tools:
        body["tools"] = available_tools
        body["tool_choice"] = "auto"

    try:
        async with httpx.AsyncClient(timeout=SUBAGENT_TIMEOUT) as client:
            response = await client.post(
                f"{provider_url}/chat/completions",
                headers=headers,
                json=body,
            )

            if response.status_code != 200:
                return f"Subagent error: HTTP {response.status_code}"

            data = response.json()
            choice = data["choices"][0]
            message = choice.get("message", {})

            text = message.get("content", "")
            tool_calls = message.get("tool_calls", [])

            if tool_calls:
                tool_results = []
                for tc in tool_calls:
                    func = tc.get("function", {})
                    name = func.get("name", "")
                    args_str = func.get("arguments", "{}")
                    try:
                        args = __import__("json").loads(args_str)
                    except Exception:
                        args = {}

                    if name == "web_search":
                        result = await web_search_tool(args.get("query", user_prompt))
                        tool_results.append(
                            f"web_search({args.get('query', '')}): "
                            f"{len(result.get('results', []))} results"
                        )

                if tool_results:
                    text = (text or "") + "\n\nTool results:\n" + "\n".join(tool_results)

            return text or "No response from subagent"

    except httpx.TimeoutException:
        return "Subagent timed out"
    except Exception as e:
        return f"Subagent error: {e}"


async def delegate_task(
    task_description: str,
    context: Optional[str] = None,
    agent: Optional[Any] = None,
) -> Dict[str, Any]:
    """Delegate a single task to a subagent.

    Args:
        task_description: What the subagent should do
        context: Optional context/background information
        agent: Optional MobileAgent whose provider/model/API key should drive
            the subagent, keeping delegation consistent with the active route.

    Returns dict with 'result' string and 'task' description.
    """
    if agent is not None:
        provider = agent.provider
        model = agent.model
        get_key = getattr(agent, "_get_api_key", None)
        api_key = get_key() if callable(get_key) else ""
    else:
        settings = get_settings()
        provider = settings.default_provider
        model = settings.default_model

        # Try each env var the provider declares, then fall back to settings attrs
        profile = get_provider_profile(provider)
        api_key = None
        if profile:
            for var in profile.env_vars:
                val = getattr(settings, var.lower(), None) or os.environ.get(var)
                if val:
                    api_key = val
                    break
        if not api_key:
            key_map = {
                "openai": settings.openai_api_key,
                "openrouter": settings.openrouter_api_key,
                "anthropic": settings.anthropic_api_key,
                "gemini": settings.gemini_api_key,
            }
            api_key = key_map.get(provider)

    # Resolve provider URL via provider profiles; reject non-OpenAI-compatible
    # providers instead of posting to an endpoint that does not exist.
    profile = get_provider_profile(provider)
    provider_url = profile.base_url if profile else "https://openrouter.ai/api/v1"
    if profile is not None and profile.api_mode != "chat_completions":
        return {
            "task": task_description,
            "result": f"Subagent error: provider '{provider}' requires the "
            f"{profile.api_mode} API; use OpenRouter.",
        }

    if not api_key:
        return {"task": task_description, "result": "No API key configured for subagent"}

    system_prompt = (
        "You are a helpful subagent. Complete the assigned task concisely and accurately. "
        "Return only the relevant information, no extra commentary."
    )

    user_prompt = task_description
    if context:
        user_prompt = f"Context: {context}\n\nTask: {task_description}"

    tools = [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web for information",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                    },
                    "required": ["query"],
                },
            },
        }
    ]

    result = await _quick_tool_call(
        provider_url=provider_url,
        api_key=api_key,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        available_tools=tools,
    )

    return {"task": task_description, "result": result}


async def delegate_parallel_tasks(
    tasks: List[str],
    context: Optional[str] = None,
    agent: Optional[Any] = None,
) -> Dict[str, Any]:
    """Delegate multiple tasks to subagents, running them in parallel.

    Args:
        tasks: List of task descriptions
        context: Optional shared context for all tasks

    Returns dict with 'results' list and 'summary'.
    """
    if not tasks:
        return {"results": [], "summary": "No tasks provided"}

    tasks = tasks[:MAX_CONCURRENT_SUBAGENTS]

    coroutines = [delegate_task(task, context=context, agent=agent) for task in tasks]
    results = await asyncio.gather(*coroutines, return_exceptions=True)

    processed = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            processed.append({"task": tasks[i], "result": f"Subagent error: {result}"})
        else:
            processed.append(result)

    summary_lines = []
    for r in processed:
        task = r.get("task", "")[:60]
        result_preview = (r.get("result", "") or "")[:120]
        summary_lines.append(f"- {task}: {result_preview}")

    return {
        "results": processed,
        "summary": "\n".join(summary_lines),
        "task_count": len(tasks),
        "completed_count": sum(
            1 for r in processed if "error" not in (r.get("result", "") or "").lower()
        ),
    }
