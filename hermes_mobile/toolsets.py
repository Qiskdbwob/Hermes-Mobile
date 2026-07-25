"""Toolsets System - Complete tool management like Hermes Desktop"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Set


class ToolCategory(Enum):
    WEB = "web"
    TERMINAL = "terminal"
    FILE = "file"
    VISION = "vision"
    IMAGE_GEN = "image_gen"
    VIDEO = "video"
    BROWSER = "browser"
    SKILLS = "skills"
    PLANNING = "planning"
    SPEECH = "speech"
    CODE = "code"
    CRON = "cron"
    SMART_HOME = "smart_home"
    KANBAN = "kanban"
    COMPUTER_USE = "computer_use"
    SESSION = "session"
    CLARIFY = "clarify"


# ═══════════════════════════════════════════════════════════════
# Core Tool Definitions (matching Hermes Desktop)
# ═══════════════════════════════════════════════════════════════

HERMES_CORE_TOOLS = [
    # Web
    "web_search",
    "web_extract",
    "x_search",
    # Terminal + process management
    "terminal",
    "process",
    # File manipulation
    "read_file",
    "write_file",
    "patch",
    "search_files",
    # Vision + image generation
    "vision_analyze",
    "image_generate",
    "video_analyze",
    "video_generate",
    # Skills
    "skills_list",
    "skill_view",
    "skill_manage",
    # Browser automation
    "browser_navigate",
    "browser_snapshot",
    "browser_click",
    "browser_type",
    "browser_scroll",
    "browser_back",
    "browser_press",
    "browser_get_images",
    "browser_vision",
    "browser_console",
    "browser_cdp",
    "browser_dialog",
    # Text-to-speech
    "text_to_speech",
    # Planning & memory
    "todo",
    "memory",
    # Session history search
    "session_search",
    # Clarifying questions
    "clarify",
    # Code execution + delegation
    "execute_code",
    "delegate_task",
    # Cronjob management
    "cronjob",
    # Smart home (gated on HASS_TOKEN)
    "ha_list_entities",
    "ha_get_state",
    "ha_list_services",
    "ha_call_service",
    # Kanban multi-agent coordination
    "kanban_show",
    "kanban_list",
    "kanban_complete",
    "kanban_block",
    "kanban_heartbeat",
    "kanban_comment",
    "kanban_create",
    "kanban_link",
    "kanban_unblock",
    "kanban_attach",
    "kanban_attach_url",
    "kanban_attachments",
    # Computer use (macOS, gated on cua-driver)
    "computer_use",
]


# Webhook-safe tools (constrained for untrusted content)
HERMES_WEBHOOK_SAFE_TOOLS = [
    "web_search",
    "web_extract",
    "vision_analyze",
    "clarify",
]


# ═══════════════════════════════════════════════════════════════
# Toolset Definitions
# ═══════════════════════════════════════════════════════════════

TOOLSETS = {
    # Basic toolsets - individual tool categories
    "web": {
        "description": "Web research and content extraction tools",
        "tools": ["web_search", "web_extract"],
        "includes": [],
        "category": ToolCategory.WEB,
    },
    "search": {
        "description": "Web search only (no content extraction/scraping)",
        "tools": ["web_search"],
        "includes": [],
        "category": ToolCategory.WEB,
    },
    "x_search": {
        "description": "Search X (Twitter) posts and threads via xAI's built-in x_search Responses tool",
        "tools": ["x_search"],
        "includes": [],
        "category": ToolCategory.WEB,
    },
    "vision": {
        "description": "Image analysis and vision tools",
        "tools": ["vision_analyze"],
        "includes": [],
        "category": ToolCategory.VISION,
    },
    "video": {
        "description": "Video analysis and understanding tools",
        "tools": ["video_analyze"],
        "includes": [],
        "category": ToolCategory.VIDEO,
    },
    "image_gen": {
        "description": "Creative generation tools (images)",
        "tools": ["image_generate"],
        "includes": [],
        "category": ToolCategory.IMAGE_GEN,
    },
    "video_gen": {
        "description": "Video generation tools",
        "tools": ["video_generate"],
        "includes": [],
        "category": ToolCategory.VIDEO,
    },
    "terminal": {
        "description": "Terminal and process management tools",
        "tools": ["terminal", "process"],
        "includes": [],
        "category": ToolCategory.TERMINAL,
    },
    "file": {
        "description": "File manipulation tools (read, write, patch, search)",
        "tools": ["read_file", "write_file", "patch", "search_files"],
        "includes": [],
        "category": ToolCategory.FILE,
    },
    "browser": {
        "description": "Full browser automation suite",
        "tools": [
            "browser_navigate",
            "browser_snapshot",
            "browser_click",
            "browser_type",
            "browser_scroll",
            "browser_back",
            "browser_press",
            "browser_get_images",
            "browser_vision",
            "browser_console",
            "browser_cdp",
            "browser_dialog",
        ],
        "includes": [],
        "category": ToolCategory.BROWSER,
    },
    "browser_lite": {
        "description": "Lightweight browser tools (navigate, snapshot, click, type, scroll, back)",
        "tools": [
            "browser_navigate",
            "browser_snapshot",
            "browser_click",
            "browser_type",
            "browser_scroll",
            "browser_back",
        ],
        "includes": [],
        "category": ToolCategory.BROWSER,
    },
    "skills": {
        "description": "Skill management tools",
        "tools": ["skills_list", "skill_view", "skill_manage"],
        "includes": [],
        "category": ToolCategory.SKILLS,
    },
    "planning": {
        "description": "Planning and memory tools",
        "tools": ["todo", "memory"],
        "includes": [],
        "category": ToolCategory.PLANNING,
    },
    "speech": {
        "description": "Text-to-speech tools",
        "tools": ["text_to_speech"],
        "includes": [],
        "category": ToolCategory.SPEECH,
    },
    "code": {
        "description": "Code execution and task delegation",
        "tools": ["execute_code", "delegate_task"],
        "includes": [],
        "category": ToolCategory.CODE,
    },
    "cron": {
        "description": "Cronjob management tools",
        "tools": ["cronjob"],
        "includes": [],
        "category": ToolCategory.CRON,
    },
    "smart_home": {
        "description": "Home Assistant smart home control",
        "tools": ["ha_list_entities", "ha_get_state", "ha_list_services", "ha_call_service"],
        "includes": [],
        "category": ToolCategory.SMART_HOME,
    },
    "kanban": {
        "description": "Kanban multi-agent coordination",
        "tools": [
            "kanban_show",
            "kanban_list",
            "kanban_complete",
            "kanban_block",
            "kanban_heartbeat",
            "kanban_comment",
            "kanban_create",
            "kanban_link",
            "kanban_unblock",
            "kanban_attach",
            "kanban_attach_url",
            "kanban_attachments",
        ],
        "includes": [],
        "category": ToolCategory.KANBAN,
    },
    "computer_use": {
        "description": "Computer use automation (macOS)",
        "tools": ["computer_use"],
        "includes": [],
        "category": ToolCategory.COMPUTER_USE,
    },
    "session": {
        "description": "Session history search",
        "tools": ["session_search"],
        "includes": [],
        "category": ToolCategory.SESSION,
    },
    "clarify": {
        "description": "Clarifying questions tool",
        "tools": ["clarify"],
        "includes": [],
        "category": ToolCategory.CLARIFY,
    },
    # Composite toolsets
    "research": {
        "description": "Deep research with web, browser, and vision",
        "tools": [],
        "includes": ["web", "browser", "vision", "planning"],
        "category": ToolCategory.WEB,
    },
    "development": {
        "description": "Full development environment",
        "tools": [],
        "includes": ["terminal", "file", "code", "browser_lite", "web"],
        "category": ToolCategory.CODE,
    },
    "creative": {
        "description": "Creative generation with images and vision",
        "tools": [],
        "includes": ["image_gen", "vision", "web"],
        "category": ToolCategory.IMAGE_GEN,
    },
    "automation": {
        "description": "Full automation suite",
        "tools": [],
        "includes": ["terminal", "file", "browser", "computer_use", "cron", "smart_home"],
        "category": ToolCategory.TERMINAL,
    },
    "safe": {
        "description": "All tools except terminal for safety",
        "tools": [],
        "includes": [
            "web",
            "browser",
            "vision",
            "image_gen",
            "file",
            "planning",
            "skills",
            "speech",
            "code",
            "cron",
            "smart_home",
            "kanban",
            "session",
            "clarify",
        ],
        "category": ToolCategory.WEB,
    },
    "minimal": {
        "description": "Only web search for basic research",
        "tools": [],
        "includes": ["search"],
        "category": ToolCategory.WEB,
    },
    "full_stack": {
        "description": "Everything available",
        "tools": [],
        "includes": [
            "web",
            "vision",
            "image_gen",
            "video",
            "video_gen",
            "terminal",
            "file",
            "browser",
            "skills",
            "planning",
            "speech",
            "code",
            "cron",
            "smart_home",
            "kanban",
            "computer_use",
            "session",
            "clarify",
            "x_search",
        ],
        "category": ToolCategory.WEB,
    },
}


# ═══════════════════════════════════════════════════════════════
# Toolset Resolution
# ═══════════════════════════════════════════════════════════════


def resolve_toolset(name: str, visited: Optional[Set[str]] = None) -> Set[str]:
    """Resolve a toolset to its complete set of tool names (including included toolsets)."""
    if visited is None:
        visited = set()

    if name in visited:
        return set()  # Circular reference protection

    visited.add(name)

    toolset = TOOLSETS.get(name)
    if not toolset:
        return {name} if name in HERMES_CORE_TOOLS else set()

    result = set(toolset.get("tools", []))

    for included in toolset.get("includes", []):
        result.update(resolve_toolset(included, visited.copy()))

    return result


def get_toolset(name: str) -> List[str]:
    """Get the list of tool names for a toolset (resolved)."""
    return sorted(resolve_toolset(name))


def get_all_toolsets() -> Dict[str, Dict[str, Any]]:
    """Get all toolset definitions."""
    return TOOLSETS.copy()


def validate_toolset(name: str) -> bool:
    """Check if a toolset name is valid."""
    return name in TOOLSETS or name in HERMES_CORE_TOOLS


def get_toolset_info(name: str) -> Optional[Dict[str, Any]]:
    """Get detailed info about a toolset."""
    toolset = TOOLSETS.get(name)
    if not toolset:
        return None

    return {
        "name": name,
        "description": toolset.get("description", ""),
        "tools": toolset.get("tools", []),
        "includes": toolset.get("includes", []),
        "category": toolset.get("category", ToolCategory.WEB).value,
        "resolved_tools": get_toolset(name),
    }


def list_toolsets_by_category() -> Dict[str, List[str]]:
    """List toolsets grouped by category."""
    result: Dict[str, List[str]] = {}
    for name, toolset in TOOLSETS.items():
        category = toolset.get("category", ToolCategory.WEB).value
        if category not in result:
            result[category] = []
        result[category].append(name)
    return result


# ═══════════════════════════════════════════════════════════════
# Tool Schema Definitions (for OpenAI function calling)
# ═══════════════════════════════════════════════════════════════

TOOL_SCHEMAS = {
    "web_search": {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for information",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "default": 10},
                    "recency_days": {
                        "type": "integer",
                        "description": "Limit results to last N days",
                    },
                },
                "required": ["query"],
            },
        },
    },
    "web_extract": {
        "type": "function",
        "function": {
            "name": "web_extract",
            "description": "Extract content from a web page",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to extract"},
                    "format": {
                        "type": "string",
                        "enum": ["markdown", "text", "html"],
                        "default": "markdown",
                    },
                },
                "required": ["url"],
            },
        },
    },
    "terminal": {
        "type": "function",
        "function": {
            "name": "terminal",
            "description": "Execute a command in the terminal",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to execute"},
                    "cwd": {"type": "string", "description": "Working directory"},
                    "timeout": {"type": "integer", "default": 120},
                },
                "required": ["command"],
            },
        },
    },
    "process": {
        "type": "function",
        "function": {
            "name": "process",
            "description": "Manage background processes",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "kill", "output"],
                        "description": "Action to perform",
                    },
                    "pid": {"type": "integer", "description": "Process ID"},
                },
                "required": ["action"],
            },
        },
    },
    "read_file": {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the filesystem",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "encoding": {"type": "string", "default": "utf-8"},
                },
                "required": ["path"],
            },
        },
    },
    "write_file": {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "content": {"type": "string", "description": "Content to write"},
                    "encoding": {"type": "string", "default": "utf-8"},
                },
                "required": ["path", "content"],
            },
        },
    },
    "patch": {
        "type": "function",
        "function": {
            "name": "patch",
            "description": "Apply a patch/diff to a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "diff": {"type": "string", "description": "Unified diff format"},
                },
                "required": ["path", "diff"],
            },
        },
    },
    "search_files": {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search for files matching a pattern",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern"},
                    "root": {"type": "string", "description": "Root directory"},
                    "content": {"type": "string", "description": "Optional content search"},
                },
                "required": ["pattern"],
            },
        },
    },
    "vision_analyze": {
        "type": "function",
        "function": {
            "name": "vision_analyze",
            "description": "Analyze an image with vision model",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_path": {"type": "string", "description": "Path to image file"},
                    "prompt": {"type": "string", "description": "Analysis prompt"},
                    "detail": {
                        "type": "string",
                        "enum": ["low", "high", "auto"],
                        "default": "auto",
                    },
                },
                "required": ["image_path", "prompt"],
            },
        },
    },
    "image_generate": {
        "type": "function",
        "function": {
            "name": "image_generate",
            "description": "Generate an image from a prompt",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Image generation prompt"},
                    "size": {
                        "type": "string",
                        "enum": ["1024x1024", "1792x1024", "1024x1792"],
                        "default": "1024x1024",
                    },
                    "quality": {
                        "type": "string",
                        "enum": ["standard", "hd"],
                        "default": "standard",
                    },
                    "style": {"type": "string", "enum": ["vivid", "natural"], "default": "vivid"},
                },
                "required": ["prompt"],
            },
        },
    },
    "video_analyze": {
        "type": "function",
        "function": {
            "name": "video_analyze",
            "description": "Analyze a video file",
            "parameters": {
                "type": "object",
                "properties": {
                    "video_path": {"type": "string", "description": "Path to video file"},
                    "prompt": {"type": "string", "description": "Analysis prompt"},
                },
                "required": ["video_path", "prompt"],
            },
        },
    },
    "video_generate": {
        "type": "function",
        "function": {
            "name": "video_generate",
            "description": "Generate a video from a prompt",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Video generation prompt"},
                    "duration": {"type": "integer", "default": 5},
                    "aspect_ratio": {"type": "string", "default": "16:9"},
                },
                "required": ["prompt"],
            },
        },
    },
    "browser_navigate": {
        "type": "function",
        "function": {
            "name": "browser_navigate",
            "description": "Navigate browser to a URL",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to navigate to"},
                    "wait_until": {
                        "type": "string",
                        "enum": ["load", "domcontentloaded", "networkidle"],
                        "default": "networkidle",
                    },
                },
                "required": ["url"],
            },
        },
    },
    "browser_snapshot": {
        "type": "function",
        "function": {
            "name": "browser_snapshot",
            "description": "Take a snapshot of the current browser page",
            "parameters": {
                "type": "object",
                "properties": {
                    "format": {"type": "string", "enum": ["png", "jpeg", "pdf"], "default": "png"},
                    "full_page": {"type": "boolean", "default": True},
                },
            },
        },
    },
    "browser_click": {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "Click an element on the page",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector"},
                    "button": {
                        "type": "string",
                        "enum": ["left", "right", "middle"],
                        "default": "left",
                    },
                },
                "required": ["selector"],
            },
        },
    },
    "browser_type": {
        "type": "function",
        "function": {
            "name": "browser_type",
            "description": "Type text into an element",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector"},
                    "text": {"type": "string", "description": "Text to type"},
                    "delay": {"type": "integer", "default": 0},
                },
                "required": ["selector", "text"],
            },
        },
    },
    "browser_scroll": {
        "type": "function",
        "function": {
            "name": "browser_scroll",
            "description": "Scroll the page",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["up", "down"], "default": "down"},
                    "amount": {"type": "integer", "default": 500},
                },
            },
        },
    },
    "browser_back": {
        "type": "function",
        "function": {
            "name": "browser_back",
            "description": "Go back in browser history",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "browser_press": {
        "type": "function",
        "function": {
            "name": "browser_press",
            "description": "Press a key",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Key to press"},
                },
                "required": ["key"],
            },
        },
    },
    "browser_get_images": {
        "type": "function",
        "function": {
            "name": "browser_get_images",
            "description": "Get all images from the page",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "browser_vision": {
        "type": "function",
        "function": {
            "name": "browser_vision",
            "description": "Analyze current page with vision",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Analysis prompt"},
                },
                "required": ["prompt"],
            },
        },
    },
    "browser_console": {
        "type": "function",
        "function": {
            "name": "browser_console",
            "description": "Get browser console logs",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {
                        "type": "string",
                        "enum": ["log", "error", "warn", "info", "debug"],
                        "default": "log",
                    },
                },
            },
        },
    },
    "browser_cdp": {
        "type": "function",
        "function": {
            "name": "browser_cdp",
            "description": "Execute Chrome DevTools Protocol command",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "CDP command"},
                    "params": {"type": "object", "description": "Command parameters"},
                },
                "required": ["command"],
            },
        },
    },
    "browser_dialog": {
        "type": "function",
        "function": {
            "name": "browser_dialog",
            "description": "Handle browser dialogs",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["accept", "dismiss", "get_text"],
                        "default": "accept",
                    },
                    "prompt_text": {"type": "string", "description": "Text for prompt dialog"},
                },
            },
        },
    },
    "text_to_speech": {
        "type": "function",
        "function": {
            "name": "text_to_speech",
            "description": "Convert text to speech",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to speak"},
                    "voice": {"type": "string", "description": "Voice to use"},
                    "speed": {"type": "number", "default": 1.0},
                },
                "required": ["text"],
            },
        },
    },
    "todo": {
        "type": "function",
        "function": {
            "name": "todo",
            "description": "Manage todo list",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add", "update", "complete", "remove", "list", "clear"],
                        "description": "Action to perform",
                    },
                    "id": {"type": "string", "description": "Todo ID"},
                    "content": {"type": "string", "description": "Todo content"},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed"],
                        "default": "pending",
                    },
                },
                "required": ["action"],
            },
        },
    },
    "memory": {
        "type": "function",
        "function": {
            "name": "memory",
            "description": "Manage long-term memory",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["store", "recall", "search", "delete", "list"],
                        "description": "Action to perform",
                    },
                    "key": {"type": "string", "description": "Memory key"},
                    "value": {"type": "string", "description": "Memory value"},
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["action"],
            },
        },
    },
    "session_search": {
        "type": "function",
        "function": {
            "name": "session_search",
            "description": "Search conversation history",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        },
    },
    "clarify": {
        "type": "function",
        "function": {
            "name": "clarify",
            "description": "Ask clarifying question to user",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Question to ask"},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional multiple choice options",
                    },
                },
                "required": ["question"],
            },
        },
    },
    "execute_code": {
        "type": "function",
        "function": {
            "name": "execute_code",
            "description": "Execute code in a sandbox",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Code to execute"},
                    "language": {
                        "type": "string",
                        "enum": ["python", "javascript", "bash"],
                        "default": "python",
                    },
                    "timeout": {"type": "integer", "default": 30},
                },
                "required": ["code"],
            },
        },
    },
    "delegate_task": {
        "type": "function",
        "function": {
            "name": "delegate_task",
            "description": "Delegate a task to another agent",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Task description"},
                    "model": {"type": "string", "description": "Model to use"},
                    "tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tools to enable",
                    },
                },
                "required": ["task"],
            },
        },
    },
    "cronjob": {
        "type": "function",
        "function": {
            "name": "cronjob",
            "description": "Manage cron jobs",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "list", "enable", "disable", "delete", "run_now"],
                        "description": "Action to perform",
                    },
                    "id": {"type": "string", "description": "Job ID"},
                    "name": {"type": "string", "description": "Job name"},
                    "schedule": {"type": "string", "description": "Cron schedule"},
                    "command": {"type": "string", "description": "Command to run"},
                },
                "required": ["action"],
            },
        },
    },
    "ha_list_entities": {
        "type": "function",
        "function": {
            "name": "ha_list_entities",
            "description": "List Home Assistant entities",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Filter by domain"},
                },
            },
        },
    },
    "ha_get_state": {
        "type": "function",
        "function": {
            "name": "ha_get_state",
            "description": "Get Home Assistant entity state",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string", "description": "Entity ID"},
                },
                "required": ["entity_id"],
            },
        },
    },
    "ha_list_services": {
        "type": "function",
        "function": {
            "name": "ha_list_services",
            "description": "List Home Assistant services",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Filter by domain"},
                },
            },
        },
    },
    "ha_call_service": {
        "type": "function",
        "function": {
            "name": "ha_call_service",
            "description": "Call Home Assistant service",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Service domain"},
                    "service": {"type": "string", "description": "Service name"},
                    "entity_id": {"type": "string", "description": "Target entity"},
                    "data": {"type": "object", "description": "Service data"},
                },
                "required": ["domain", "service"],
            },
        },
    },
    "skills_list": {
        "type": "function",
        "function": {
            "name": "skills_list",
            "description": "List available skills",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "skill_view": {
        "type": "function",
        "function": {
            "name": "skill_view",
            "description": "View skill details",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Skill name"},
                },
                "required": ["name"],
            },
        },
    },
    "skill_manage": {
        "type": "function",
        "function": {
            "name": "skill_manage",
            "description": "Manage skills (install, enable, disable, remove)",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["install", "enable", "disable", "remove", "update"],
                        "description": "Action to perform",
                    },
                    "name": {"type": "string", "description": "Skill name"},
                    "source": {"type": "string", "description": "Install source (URL or path)"},
                },
                "required": ["action", "name"],
            },
        },
    },
    "kanban_show": {
        "type": "function",
        "function": {
            "name": "kanban_show",
            "description": "Show kanban board",
            "parameters": {
                "type": "object",
                "properties": {
                    "board_id": {"type": "string", "description": "Board ID"},
                },
            },
        },
    },
    "kanban_list": {
        "type": "function",
        "function": {
            "name": "kanban_list",
            "description": "List kanban boards",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "kanban_create": {
        "type": "function",
        "function": {
            "name": "kanban_create",
            "description": "Create kanban board or task",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["board", "task"],
                        "description": "What to create",
                    },
                    "board_id": {"type": "string", "description": "Board ID"},
                    "title": {"type": "string", "description": "Title"},
                    "description": {"type": "string", "description": "Description"},
                    "column": {"type": "string", "description": "Column name"},
                },
                "required": ["type", "title"],
            },
        },
    },
    "kanban_complete": {
        "type": "function",
        "function": {
            "name": "kanban_complete",
            "description": "Mark kanban task complete",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID"},
                },
                "required": ["task_id"],
            },
        },
    },
    "kanban_block": {
        "type": "function",
        "function": {
            "name": "kanban_block",
            "description": "Block/unblock kanban task",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID"},
                    "blocked": {"type": "boolean", "description": "Block status"},
                    "reason": {"type": "string", "description": "Block reason"},
                },
                "required": ["task_id", "blocked"],
            },
        },
    },
    "kanban_heartbeat": {
        "type": "function",
        "function": {
            "name": "kanban_heartbeat",
            "description": "Send heartbeat for active task",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID"},
                    "progress": {"type": "string", "description": "Progress update"},
                },
                "required": ["task_id"],
            },
        },
    },
    "kanban_comment": {
        "type": "function",
        "function": {
            "name": "kanban_comment",
            "description": "Add comment to kanban task",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID"},
                    "comment": {"type": "string", "description": "Comment text"},
                },
                "required": ["task_id", "comment"],
            },
        },
    },
    "kanban_link": {
        "type": "function",
        "function": {
            "name": "kanban_link",
            "description": "Link kanban tasks",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID"},
                    "related_task_id": {"type": "string", "description": "Related task ID"},
                    "relation": {
                        "type": "string",
                        "enum": ["blocks", "relates", "duplicates"],
                        "default": "relates",
                    },
                },
                "required": ["task_id", "related_task_id"],
            },
        },
    },
    "kanban_unblock": {
        "type": "function",
        "function": {
            "name": "kanban_unblock",
            "description": "Unblock kanban task",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID"},
                },
                "required": ["task_id"],
            },
        },
    },
    "kanban_attach": {
        "type": "function",
        "function": {
            "name": "kanban_attach",
            "description": "Attach file to kanban task",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID"},
                    "file_path": {"type": "string", "description": "File path"},
                },
                "required": ["task_id", "file_path"],
            },
        },
    },
    "kanban_attach_url": {
        "type": "function",
        "function": {
            "name": "kanban_attach_url",
            "description": "Attach URL to kanban task",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID"},
                    "url": {"type": "string", "description": "URL to attach"},
                    "title": {"type": "string", "description": "Link title"},
                },
                "required": ["task_id", "url"],
            },
        },
    },
    "kanban_attachments": {
        "type": "function",
        "function": {
            "name": "kanban_attachments",
            "description": "List kanban task attachments",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID"},
                },
                "required": ["task_id"],
            },
        },
    },
    "computer_use": {
        "type": "function",
        "function": {
            "name": "computer_use",
            "description": "Control computer (macOS)",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["click", "type", "key", "scroll", "screenshot", "move"],
                        "description": "Action to perform",
                    },
                    "x": {"type": "integer", "description": "X coordinate"},
                    "y": {"type": "integer", "description": "Y coordinate"},
                    "text": {"type": "string", "description": "Text to type"},
                    "key": {"type": "string", "description": "Key to press"},
                },
                "required": ["action"],
            },
        },
    },
    "x_search": {
        "type": "function",
        "function": {
            "name": "x_search",
            "description": "Search X (Twitter) posts",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        },
    },
}


def get_tool_schema(name: str) -> Optional[Dict[str, Any]]:
    """Get the OpenAI function schema for a tool."""
    return TOOL_SCHEMAS.get(name)


def get_tool_schemas(names: List[str]) -> List[Dict[str, Any]]:
    """Get schemas for multiple tools."""
    return [schema for name in names if (schema := get_tool_schema(name))]


# ═══════════════════════════════════════════════════════════════
# Toolset Distributions (for data generation)
# ═══════════════════════════════════════════════════════════════

DISTRIBUTIONS = {
    "default": {
        "description": "All available tools, all the time",
        "toolsets": {
            "web": 100,
            "vision": 100,
            "image_gen": 100,
            "terminal": 100,
            "file": 100,
            "browser": 100,
        },
    },
    "image_gen": {
        "description": "Heavy focus on image generation with vision and web support",
        "toolsets": {
            "image_gen": 90,
            "vision": 90,
            "web": 55,
            "terminal": 45,
        },
    },
    "research": {
        "description": "Web research with vision analysis and reasoning",
        "toolsets": {
            "web": 90,
            "browser": 70,
            "vision": 50,
            "terminal": 10,
        },
    },
    "science": {
        "description": "Scientific research with web, terminal, file, and browser",
        "toolsets": {
            "web": 94,
            "terminal": 94,
            "file": 94,
            "vision": 65,
            "browser": 50,
            "image_gen": 15,
        },
    },
    "development": {
        "description": "Terminal, file tools, and reasoning with occasional web lookup",
        "toolsets": {
            "terminal": 80,
            "file": 80,
            "web": 30,
            "vision": 10,
        },
    },
    "safe": {
        "description": "All tools except terminal for safety",
        "toolsets": {
            "web": 80,
            "browser": 70,
            "vision": 60,
            "image_gen": 60,
        },
    },
    "balanced": {
        "description": "Equal probability of all toolsets",
        "toolsets": {
            "web": 50,
            "vision": 50,
            "image_gen": 50,
            "terminal": 50,
            "file": 50,
            "browser": 50,
        },
    },
    "minimal": {
        "description": "Only web tools for basic research",
        "toolsets": {"web": 100},
    },
    "terminal_only": {
        "description": "Terminal and file tools for code execution",
        "toolsets": {"terminal": 100, "file": 100},
    },
    "terminal_web": {
        "description": "Terminal and file tools with web search for docs",
        "toolsets": {"terminal": 100, "file": 100, "web": 100},
    },
    "creative": {
        "description": "Image generation and vision analysis focus",
        "toolsets": {"image_gen": 90, "vision": 90, "web": 30},
    },
    "reasoning": {
        "description": "Heavy research/reasoning with minimal other tools",
        "toolsets": {"web": 90, "file": 60, "terminal": 20},
    },
}


def get_distribution(name: str) -> Optional[Dict[str, Any]]:
    """Get a distribution by name."""
    return DISTRIBUTIONS.get(name)


def list_distributions() -> List[str]:
    """List all available distributions."""
    return list(DISTRIBUTIONS.keys())
