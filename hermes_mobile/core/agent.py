"""Core Agent Bridge - Adapts Hermes Agent for Mobile"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from hermes_mobile.config.settings import get_settings
from hermes_mobile.core.context_compressor import compress_messages, needs_compression
from hermes_mobile.tools.agent_tools import (
    clarify_tool,
    memory_tool,
    session_search_tool,
)
from hermes_mobile.tools.path_security import validate_and_resolve_path
from hermes_mobile.tools.security import safe_calculate
from hermes_mobile.tools.web_tools import web_extract_tool, web_search_tool

logger = logging.getLogger(__name__)


class ToolCall:
    """Represents a tool call from the model"""

    def __init__(
        self,
        name: str,
        arguments: Dict[str, Any],
        call_id: Optional[str] = None,
    ):
        self.name = name
        self.arguments = arguments
        self.call_id = call_id or str(uuid.uuid4())
        self.result: Optional[Any] = None
        self.error: Optional[str] = None
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "arguments": self.arguments,
            "call_id": self.call_id,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class Message:
    """Represents a chat message"""

    def __init__(
        self,
        role: str,
        content: str,
        tool_calls: Optional[List[ToolCall]] = None,
        tool_call_id: Optional[str] = None,
        name: Optional[str] = None,
    ):
        self.role = role  # user, assistant, system, tool
        self.content = content
        self.tool_calls = tool_calls or []
        self.tool_call_id = tool_call_id
        self.name = name
        self.timestamp = datetime.now()
        self.id = str(uuid.uuid4())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "tool_call_id": self.tool_call_id,
            "name": self.name,
            "timestamp": self.timestamp.isoformat(),
            "id": self.id,
        }

    @classmethod
    def user(cls, content: str) -> "Message":
        return cls("user", content)

    @classmethod
    def assistant(cls, content: str, tool_calls: Optional[List[ToolCall]] = None) -> "Message":
        return cls("assistant", content, tool_calls=tool_calls)

    @classmethod
    def system(cls, content: str) -> "Message":
        return cls("system", content)

    @classmethod
    def tool(cls, content: str, tool_call_id: str, name: str) -> "Message":
        return cls("tool", content, tool_call_id=tool_call_id, name=name)


class MobileAgent:
    """Mobile-adapted Hermes Agent"""

    def __init__(
        self,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        memory_provider: Optional[Any] = None,
        skill_manager: Optional[Any] = None,
        on_tool_call: Optional[Callable[[ToolCall], None]] = None,
        on_tool_result: Optional[Callable[[ToolCall], None]] = None,
        on_message: Optional[Callable[[Message], None]] = None,
    ):
        self.settings = get_settings()
        self.model = model or self.settings.default_model
        self.provider = provider or self.settings.default_provider
        self.system_prompt = system_prompt or self.settings.system_prompt
        self.tools = tools or []
        self.memory_provider = memory_provider
        self.skill_manager = skill_manager

        # Callbacks for UI updates
        self.on_tool_call = on_tool_call
        self.on_tool_result = on_tool_result
        self.on_message = on_message

        # Conversation state
        self.messages: List[Message] = []
        self.session_id = str(uuid.uuid4())
        self.iteration = 0
        self.max_iterations = self.settings.max_iterations

        # Initialize OpenAI-compatible client
        self._client = None
        self._init_client()

    def _init_client(self):
        """Initialize the OpenAI-compatible client"""
        from openai import AsyncOpenAI

        api_key = self._get_api_key()
        base_url = self._get_base_url()

        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=self.settings.request_timeout,
            max_retries=self.settings.max_retries,
        )

    def _get_api_key(self) -> str:
        """Get API key for current provider"""
        if self.provider == "openrouter":
            return self.settings.openrouter_api_key or ""
        elif self.provider == "openai":
            return self.settings.openai_api_key or ""
        elif self.provider == "anthropic":
            return self.settings.anthropic_api_key or ""
        elif self.provider == "gemini":
            return self.settings.gemini_api_key or ""
        return ""

    def _get_base_url(self) -> str:
        """Get base URL for current provider"""
        if self.provider == "openrouter":
            return "https://openrouter.ai/api/v1"
        elif self.provider == "openai":
            return "https://api.openai.com/v1"
        elif self.provider == "anthropic":
            return "https://api.anthropic.com/v1"
        elif self.provider == "gemini":
            return "https://generativelanguage.googleapis.com/v1beta/openai/"
        return "https://openrouter.ai/api/v1"

    def add_message(self, message: Message):
        """Add a message to the conversation"""
        self.messages.append(message)
        if self.on_message:
            self.on_message(message)

    def add_user_message(self, content: str):
        """Add a user message"""
        self.add_message(Message.user(content))

    def add_assistant_message(self, content: str, tool_calls: Optional[List[ToolCall]] = None):
        """Add an assistant message"""
        self.add_message(Message.assistant(content, tool_calls))

    def add_tool_result(self, content: str, tool_call_id: str, name: str):
        """Add a tool result message"""
        self.add_message(Message.tool(content, tool_call_id, name))

    def get_messages_for_api(self) -> List[Dict[str, Any]]:
        """Get messages formatted for API call"""
        messages = [{"role": "system", "content": self.system_prompt}]

        # Add relevant memory context if available
        if self.memory_provider and self.messages:
            context = self.memory_provider.get_relevant_context(
                self.messages[-1].content,
                limit=5,
            )
            if context:
                messages.append(
                    {
                        "role": "system",
                        "content": f"Relevant context from memory:\n{context}",
                    }
                )

        # Add conversation messages
        for msg in self.messages:
            api_msg = {"role": msg.role, "content": msg.content}
            if msg.tool_calls:
                api_msg["tool_calls"] = [
                    {
                        "id": tc.call_id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in msg.tool_calls
                ]
            if msg.tool_call_id:
                api_msg["tool_call_id"] = msg.tool_call_id
            if msg.name:
                api_msg["name"] = msg.name
            messages.append(api_msg)

        return messages

    async def run_conversation(
        self,
        user_input: str,
        stream: bool = True,
    ) -> AsyncGenerator[str, None]:
        """Run a conversation turn with the agent"""
        self.add_user_message(user_input)
        self.iteration = 0

        while self.iteration < self.max_iterations:
            self.iteration += 1

            api_messages = self.get_messages_for_api()
            if needs_compression(api_messages, self.settings.max_tokens):
                self.messages = self._apply_compression()
                api_messages = self.get_messages_for_api()

            try:
                response = await self._call_model(stream=stream)


                if stream:
                    async for chunk in response:
                        if chunk.choices[0].delta.content:
                            yield chunk.choices[0].delta.content
                else:
                    content = response.choices[0].message.content or ""
                    yield content

                # Handle tool calls
                tool_calls = self._extract_tool_calls(response)
                if tool_calls:
                    await self._execute_tool_calls(tool_calls)
                    continue  # Continue conversation with tool results

                # No tool calls, conversation turn complete
                break

            except Exception as e:
                logger.error(f"Error in conversation: {e}")
                yield f"\n\nError: {str(e)}"
                break

        # Save to memory
        if self.memory_provider:
            await self.memory_provider.save_conversation(
                self.session_id,
                self.messages,
            )

    async def _call_model(self, stream: bool = True):
        """Call the model API"""
        messages = self.get_messages_for_api()

        return await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=self.tools if self.tools else None,
            tool_choice="auto" if self.tools else None,
            temperature=self.settings.temperature,
            max_tokens=self.settings.max_tokens,
            stream=stream,
        )

    def _extract_tool_calls(self, response) -> List[ToolCall]:
        """Extract tool calls from model response"""
        tool_calls = []

        if (
            hasattr(response.choices[0].message, "tool_calls")
            and response.choices[0].message.tool_calls
        ):
            for tc in response.choices[0].message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                tool_call = ToolCall(
                    name=tc.function.name,
                    arguments=args,
                    call_id=tc.id,
                )
                tool_calls.append(tool_call)

        return tool_calls

    async def _execute_tool_calls(self, tool_calls: List[ToolCall]):
        """Execute tool calls and add results to conversation"""
        for tool_call in tool_calls:
            tool_call.started_at = datetime.now()

            if self.on_tool_call:
                self.on_tool_call(tool_call)

            try:
                result = await self._execute_tool(tool_call.name, tool_call.arguments)
                tool_call.result = result
                tool_call.completed_at = datetime.now()

                self.add_tool_result(
                    json.dumps(result) if not isinstance(result, str) else result,
                    tool_call.call_id,
                    tool_call.name,
                )

            except Exception as e:
                logger.error(f"Tool {tool_call.name} failed: {e}")
                tool_call.error = str(e)
                tool_call.completed_at = datetime.now()

                self.add_tool_result(
                    f"Error: {str(e)}",
                    tool_call.call_id,
                    tool_call.name,
                )

            if self.on_tool_result:
                self.on_tool_result(tool_call)

    async def _execute_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Execute a tool by name"""
        # Check built-in tools first
        if name in self._builtin_tools:
            return await self._builtin_tools[name](**arguments)

        # Check skills
        if self.skill_manager:
            skill = self.skill_manager.get_skill(name)
            if skill:
                return await skill.execute(**arguments)

        raise ValueError(f"Unknown tool: {name}")

    @property
    def _builtin_tools(self) -> Dict[str, Callable]:
        return {
            "web_search": self._tool_web_search,
            "web_extract": self._tool_web_extract,
            "read_file": self._tool_read_file,
            "write_file": self._tool_write_file,
            "list_files": self._tool_list_files,
            "run_command": self._tool_run_command,
            "get_time": self._tool_get_time,
            "calculate": self._tool_calculate,
            "session_search": self._tool_session_search,
            "memory": self._tool_memory,
            "clarify": self._tool_clarify,
        }

    async def _tool_web_search(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """Search the web using DuckDuckGo."""
        return await web_search_tool(query, max_results=max_results)

    async def _tool_read_file(self, path: str) -> str:
        """Read a file with path security validation."""
        resolved, error = validate_and_resolve_path(path)
        if error:
            return f"Error: {error}"
        try:
            return resolved.read_text()
        except Exception as e:
            return f"Error reading file: {e}"

    async def _tool_write_file(self, path: str, content: str) -> str:
        """Write a file with path security validation."""
        resolved, error = validate_and_resolve_path(path)
        if error:
            return f"Error: {error}"
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content)
            return f"File written to {resolved}"
        except Exception as e:
            return f"Error writing file: {e}"

    async def _tool_list_files(self, path: str = ".") -> List[str]:
        """List files in a directory with path security."""
        if path == ".":
            resolved = Path.cwd()
        else:
            resolved, error = validate_and_resolve_path(path)
            if error:
                return [f"Error: {error}"]
        try:
            return [str(p) for p in resolved.iterdir()]
        except Exception as e:
            return [f"Error: {e}"]

    async def _tool_run_command(self, command: str, cwd: Optional[str] = None) -> Dict[str, Any]:
        """Run a shell command"""
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            return {
                "stdout": stdout.decode(),
                "stderr": stderr.decode(),
                "returncode": proc.returncode,
            }
        except Exception as e:
            return {"error": str(e)}

    async def _tool_get_time(self) -> str:
        """Get current time"""
        return datetime.now().isoformat()

    async def _tool_web_extract(self, urls: List[str], format: str = "text") -> Dict[str, Any]:
        """Extract content from web pages."""
        return await web_extract_tool(urls, format=format)

    async def _tool_session_search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        """Search past conversation sessions."""
        return await session_search_tool(query, limit=limit, memory_provider=self.memory_provider)

    async def _tool_memory(
        self,
        action: str,
        key: Optional[str] = None,
        value: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 5,
    ) -> Dict[str, Any]:
        """Store and retrieve memory entries."""
        return await memory_tool(
            action=action,
            key=key,
            value=value,
            query=query,
            limit=limit,
            memory_provider=self.memory_provider,
        )

    async def _tool_clarify(self, topic: str, context: Optional[str] = None) -> Dict[str, Any]:
        """Get clarification suggestions."""
        return await clarify_tool(topic, context=context)

    async def _tool_calculate(self, expression: str) -> Any:
        """Calculate a mathematical expression safely."""
        return safe_calculate(expression)

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Get tool schemas for the model"""
        schemas = []

        # Built-in tools
        schemas.extend(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "description": "Search the web for information",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "Search query"},
                                "max_results": {"type": "integer", "default": 5},
                            },
                            "required": ["query"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "Read a file from the filesystem",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "File path"},
                            },
                            "required": ["path"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "description": "Write content to a file",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "File path"},
                                "content": {"type": "string", "description": "Content to write"},
                            },
                            "required": ["path", "content"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "list_files",
                        "description": "List files in a directory",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "Directory path",
                                    "default": ".",
                                },
                            },
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "run_command",
                        "description": "Run a shell command",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "command": {"type": "string", "description": "Command to run"},
                                "cwd": {"type": "string", "description": "Working directory"},
                            },
                            "required": ["command"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "get_time",
                        "description": "Get current date and time",
                        "parameters": {"type": "object", "properties": {}},
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "calculate",
                        "description": "Calculate a mathematical expression",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "expression": {"type": "string", "description": "Math expression"},
                            },
                            "required": ["expression"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "web_extract",
                        "description": "Extract text content from web pages",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "urls": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "List of URLs to extract",
                                },
                                "format": {
                                    "type": "string",
                                    "enum": ["text", "markdown"],
                                    "default": "text",
                                },
                            },
                            "required": ["urls"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "session_search",
                        "description": "Search past conversation sessions for relevant context",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "Search query"},
                                "limit": {"type": "integer", "default": 5},
                            },
                            "required": ["query"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "memory",
                        "description": "Store and retrieve information in long-term memory",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "action": {
                                    "type": "string",
                                    "enum": ["store", "retrieve", "search", "list", "delete"],
                                    "description": "Memory action",
                                },
                                "key": {"type": "string", "description": "Memory key"},
                                "value": {"type": "string", "description": "Value to store"},
                                "query": {"type": "string", "description": "Search query"},
                                "limit": {"type": "integer", "default": 5},
                            },
                            "required": ["action"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "clarify",
                        "description": "Get clarification suggestions for ambiguous requests",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "topic": {"type": "string", "description": "Topic to clarify"},
                                "context": {"type": "string", "description": "Additional context"},
                            },
                            "required": ["topic"],
                        },
                    },
                },
            ]
        )

        # Add skill tools
        if self.skill_manager:
            for skill in self.skill_manager.get_active_skills():
                schemas.append(skill.get_schema())

        return schemas

    def set_tools(self, tools: List[Dict[str, Any]]):
        """Set available tools"""
        self.tools = tools

    def clear_conversation(self):
        """Compress conversation to save token space.

        Returns new compressed message list.
        """
        api_messages = self.get_messages_for_api()
        compressed = compress_messages(api_messages, self.settings.max_tokens)
        new_messages = []
        for msg_dict in compressed:
            role = msg_dict["role"]
            content = msg_dict.get("content", "")
            if role == "system":
                new_messages.append(Message.system(content))
            elif role == "user":
                new_messages.append(Message.user(content))
            elif role == "assistant":
                new_messages.append(Message.assistant(content))
            elif role == "tool":
                new_messages.append(Message.tool(
                    content,
                    msg_dict.get("tool_call_id", ""),
                    msg_dict.get("name", "unknown"),
                ))
        self.messages = new_messages
        logger.info("Compressed conversation: %d -> %d messages", len(api_messages), len(new_messages))
        return new_messages

    def clear_conversation(self):
        """Clear conversation history"""
        self.messages = []
        self.session_id = str(uuid.uuid4())
        self.iteration = 0



def create_mobile_agent(
    model: Optional[str] = None,
    provider: Optional[str] = None,
    **kwargs,
) -> MobileAgent:
    """Factory function to create a mobile agent with default configuration"""
    settings = get_settings()

    # Import here to avoid circular imports
    from hermes_mobile.memory.provider import MobileMemoryProvider
    from hermes_mobile.skills.manager import MobileSkillManager

    # Initialize memory provider
    memory_provider = MobileMemoryProvider(
        db_path=settings.get_memory_db_path(),
        encrypt=settings.encrypt_memory,
    )

    # Initialize skill manager
    skill_manager = MobileSkillManager(
        skills_dir=settings.get_skills_dir(),
    )

    agent = MobileAgent(
        model=model or settings.default_model,
        provider=provider or settings.default_provider,
        memory_provider=memory_provider,
        skill_manager=skill_manager,
        **kwargs,
    )

    # Set tools from schemas
    agent.set_tools(agent.get_tool_schemas())

    return agent
