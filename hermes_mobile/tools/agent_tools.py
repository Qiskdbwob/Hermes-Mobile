"""Agent intelligence tools — session search, memory, and clarification.

Adapted from Hermes Desktop tools/session_search_tool.py,
tools/memory_tool.py, and tools/clarify_gateway.py.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

AGENT_TOOLS = {}


def register(name: str):
    def decorator(func):
        AGENT_TOOLS[name] = func
        return func

    return decorator


async def session_search_tool(
    query: str,
    limit: int = 5,
    memory_provider: Optional[Any] = None,
) -> Dict[str, Any]:
    """Search past conversation sessions for relevant information.

    Args:
        query: Search query text
        limit: Maximum number of results
        memory_provider: Optional memory provider instance

    Returns dict with 'sessions' list and 'query'.
    """
    if not memory_provider:
        return {"sessions": [], "query": query, "error": "Memory provider not available"}

    try:
        sessions = await memory_provider.search_sessions(query, limit=limit)
        return {
            "sessions": [
                {
                    "id": s.get("id", ""),
                    "title": s.get("title") or "Untitled",
                    "preview": (s.get("preview") or "")[:200],
                    "timestamp": s.get("timestamp", ""),
                    "message_count": s.get("message_count", 0),
                }
                for s in sessions
            ],
            "query": query,
        }
    except Exception as e:
        return {"sessions": [], "query": query, "error": str(e)}


async def memory_tool(
    action: str,
    key: Optional[str] = None,
    value: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 5,
    memory_provider: Optional[Any] = None,
) -> Dict[str, Any]:
    """Store and retrieve information in long-term memory.

    Actions:
        - 'store': Save key=value pair
        - 'retrieve': Get value by key
        - 'search': Search memory entries
        - 'list': List recent entries
        - 'delete': Delete entry by key

    Args:
        action: One of store, retrieve, search, list, delete
        key: Memory key (for store/retrieve/delete)
        value: Memory value (for store)
        query: Search query (for search)
        limit: Max results (for search/list)
        memory_provider: Memory provider instance
    """
    if not memory_provider:
        return {"error": "Memory provider not available"}

    try:
        if action == "store":
            if not key or not value:
                return {"error": "Key and value required for store"}
            await memory_provider.store_memory(key, value)
            return {"status": "stored", "key": key}

        elif action == "retrieve":
            if not key:
                return {"error": "Key required for retrieve"}
            entry = await memory_provider.get_memory(key)
            return {"key": key, "value": entry} if entry else {"key": key, "value": None}

        elif action == "search":
            if not query:
                return {"error": "Query required for search"}
            entries = await memory_provider.search_memory(query, limit=limit)
            return {"results": entries, "query": query}

        elif action == "list":
            entries = await memory_provider.list_memory(limit=limit)
            return {"entries": entries}

        elif action == "delete":
            if not key:
                return {"error": "Key required for delete"}
            await memory_provider.delete_memory(key)
            return {"status": "deleted", "key": key}

        else:
            return {"error": f"Unknown action: {action}"}

    except Exception as e:
        return {"error": str(e)}


async def clarify_tool(topic: str, context: Optional[str] = None) -> Dict[str, Any]:
    """Provide suggestions for clarifying an ambiguous request.

    This helps the agent frame better follow-up questions when
    the user's intent is unclear.

    Args:
        topic: The topic or question needing clarification
        context: Optional additional context

    Returns suggestions for clarification.
    """
    suggestions = [
        "What specific aspect of this topic are you most interested in?",
        "Could you provide more details about your goal?",
        "Are there any constraints or preferences I should know?",
    ]

    if context:
        suggestions.insert(
            0,
            f"Based on the context provided ({context[:100]}), could you elaborate on...",
        )

    return {
        "topic": topic,
        "suggestions": suggestions,
        "context": context,
    }
