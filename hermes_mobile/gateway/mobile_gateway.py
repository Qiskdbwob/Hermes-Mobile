"""Gateway System - Pairing, Streaming, and Platform Adapters"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from hermes_mobile.config.settings import get_settings
from hermes_mobile.core.agent import MobileAgent, create_mobile_agent
from hermes_mobile.memory.provider import MobileMemoryProvider

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Pairing System (Code-based approval flow)
# ═══════════════════════════════════════════════════════════════

# Unambiguous alphabet -- excludes 0/O, 1/I to prevent confusion
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8

CODE_TTL_SECONDS = 3600  # Codes expire after 1 hour
RATE_LIMIT_SECONDS = 600  # 1 request per user per 10 minutes
LOCKOUT_SECONDS = 3600  # Lockout duration after too many failures

MAX_PENDING_PER_PLATFORM = 3  # Max pending codes per platform
MAX_FAILED_ATTEMPTS = 5  # Failed approvals before lockout


def _get_pairing_dir() -> Path:
    """Resolve pairing directory lazily to avoid Android path issues at import."""
    from hermes_mobile.config.settings import get_settings

    settings = get_settings()
    return Path(settings.data_dir).resolve() / "pairing"


def _allowlist_env_for_platform(platform: str) -> Optional[str]:
    """Return the per-platform allowlist env var name, or None."""
    platform = (platform or "").lower().strip()
    env_map = {
        "telegram": "TELEGRAM_ALLOWED_USERS",
        "discord": "DISCORD_ALLOWED_USERS",
        "whatsapp": "WHATSAPP_ALLOWED_USERS",
        "slack": "SLACK_ALLOWED_USERS",
        "signal": "SIGNAL_ALLOWED_USERS",
        "email": "EMAIL_ALLOWED_USERS",
        "sms": "SMS_ALLOWED_USERS",
    }
    return env_map.get(platform)


def _split_allowlist(raw: str) -> List[str]:
    return [uid.strip() for uid in raw.split(",") if uid.strip()]


def _persist_allowlist(env_var: str, ids: List[str]) -> None:
    """Write the allowlist to BOTH the running process and the .env file.

    One authoritative store: the env var drives authorization, so the in-memory
    value and the persisted file must never diverge. Best-effort on the file
    write (failure is logged, never raised).
    """
    value = ",".join(ids)
    os.environ[env_var] = value
    try:
        env_path = Path(".env")
        if not env_path.exists():
            return
        content = env_path.read_text()
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if line.startswith(f"{env_var}="):
                lines[i] = f"{env_var}={value}"
                break
        else:
            lines.append(f"{env_var}={value}")
        env_path.write_text("\n".join(lines))
    except Exception as exc:
        logger.warning("Failed to persist allowlist %s: %s", env_var, exc)


def _sync_allowlist_add(platform: str, user_id: str) -> None:
    """Add user_id to the platform allowlist env var IF one is configured."""
    env_var = _allowlist_env_for_platform(platform)
    if not env_var:
        return
    current = os.getenv(env_var, "").strip()
    if not current:
        return  # No allowlist configured — leave gateway open
    ids = _split_allowlist(current)
    if "*" in ids or str(user_id) in ids:
        return  # Already covered
    ids.append(str(user_id))
    _persist_allowlist(env_var, ids)


def _sync_allowlist_remove(platform: str, user_id: str) -> None:
    """Remove user_id from the platform allowlist env var IF one is configured."""
    env_var = _allowlist_env_for_platform(platform)
    if not env_var:
        return
    current = os.getenv(env_var, "").strip()
    if not current:
        return
    ids = _split_allowlist(current)
    if str(user_id) not in ids:
        return
    ids.remove(str(user_id))
    _persist_allowlist(env_var, ids)


@dataclass
class PairingCode:
    code: str
    platform: str
    user_id: str
    user_name: str
    created_at: float
    expires_at: float
    approved: bool = False
    approved_at: Optional[float] = None
    revoked: bool = False


class PairingManager:
    """Manages pairing codes for platform authorization."""

    def __init__(self):
        self._lock = threading.RLock()
        _get_pairing_dir().mkdir(parents=True, exist_ok=True)
        self._codes_file = _get_pairing_dir() / "codes.json"
        self._rate_limit_file = _get_pairing_dir() / "rate_limits.json"
        self._lockout_file = _get_pairing_dir() / "lockouts.json"
        self._load()

    def _load(self):
        with self._lock:
            self._codes: Dict[str, PairingCode] = {}
            self._rate_limits: Dict[str, float] = {}
            self._lockouts: Dict[str, float] = {}

            if self._codes_file.exists():
                try:
                    data = json.loads(self._codes_file.read_text())
                    for item in data:
                        code = PairingCode(**item)
                        self._codes[code.code] = code
                except Exception:
                    pass

            if self._rate_limit_file.exists():
                try:
                    self._rate_limits = json.loads(self._rate_limit_file.read_text())
                except Exception:
                    pass

            if self._lockout_file.exists():
                try:
                    self._lockouts = json.loads(self._lockout_file.read_text())
                except Exception:
                    pass

    def _save(self):
        with self._lock:
            # Save codes
            codes_data = []
            for code in self._codes.values():
                codes_data.append(
                    {
                        "code": code.code,
                        "platform": code.platform,
                        "user_id": code.user_id,
                        "user_name": code.user_name,
                        "created_at": code.created_at,
                        "expires_at": code.expires_at,
                        "approved": code.approved,
                        "approved_at": code.approved_at,
                        "revoked": code.revoked,
                    }
                )
            self._codes_file.write_text(json.dumps(codes_data, indent=2))

            # Save rate limits
            self._rate_limit_file.write_text(json.dumps(self._rate_limits))

            # Save lockouts
            self._lockout_file.write_text(json.dumps(self._lockouts))

    def _generate_code(self) -> str:
        return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))

    def _is_rate_limited(self, platform: str, user_id: str) -> bool:
        key = f"{platform}:{user_id}"
        last_request = self._rate_limits.get(key, 0)
        return time.time() - last_request < RATE_LIMIT_SECONDS

    def _is_locked_out(self, platform: str, user_id: str) -> bool:
        key = f"{platform}:{user_id}"
        lockout_until = self._lockouts.get(key, 0)
        return time.time() < lockout_until

    def _record_request(self, platform: str, user_id: str):
        key = f"{platform}:{user_id}"
        self._rate_limits[key] = time.time()
        self._save()

    def _record_failed_attempt(self, platform: str, user_id: str):
        key = f"{platform}:{user_id}"
        # Count failures in codes
        failures = sum(
            1
            for c in self._codes.values()
            if c.platform == platform and c.user_id == user_id and c.revoked and not c.approved
        )
        if failures >= MAX_FAILED_ATTEMPTS:
            self._lockouts[key] = time.time() + LOCKOUT_SECONDS
        self._save()

    def request_pairing(self, platform: str, user_id: str, user_name: str) -> Optional[PairingCode]:
        """Request a new pairing code."""
        platform = platform.lower().strip()

        # Check rate limit
        if self._is_rate_limited(platform, user_id):
            raise ValueError("Rate limited: please wait before requesting another code")

        # Check lockout
        if self._is_locked_out(platform, user_id):
            raise ValueError("Too many failed attempts. Please try again later.")

        # Check pending limit
        pending = sum(
            1
            for c in self._codes.values()
            if c.platform == platform
            and not c.approved
            and not c.revoked
            and c.expires_at > time.time()
        )
        if pending >= MAX_PENDING_PER_PLATFORM:
            raise ValueError(
                f"Too many pending codes for {platform}. Please approve or wait for expiry."
            )

        # Generate code
        code_str = self._generate_code()
        now = time.time()
        code = PairingCode(
            code=code_str,
            platform=platform,
            user_id=user_id,
            user_name=user_name,
            created_at=now,
            expires_at=now + CODE_TTL_SECONDS,
        )

        self._codes[code_str] = code
        self._record_request(platform, user_id)
        self._save()

        return code

    def approve_code(self, code_str: str) -> bool:
        """Approve a pairing code."""
        code = self._codes.get(code_str.upper())
        if not code:
            return False
        if code.revoked:
            # A revoked code can never be approved, even before expiry. Without
            # this, revoke-then-approve left the code marked approved while the
            # authorization check still rejected it (inconsistent state).
            return False
        if code.expires_at < time.time():
            code.revoked = True
            self._save()
            return False
        if code.approved:
            return True

        code.approved = True
        code.approved_at = time.time()
        _sync_allowlist_add(code.platform, code.user_id)
        self._save()
        return True

    def revoke_code(self, code_str: str) -> bool:
        """Revoke a pairing code."""
        code = self._codes.get(code_str.upper())
        if not code:
            return False
        code.revoked = True
        if code.approved:
            _sync_allowlist_remove(code.platform, code.user_id)
        self._record_failed_attempt(code.platform, code.user_id)
        self._save()
        return True

    def get_pending_codes(self, platform: Optional[str] = None) -> List[PairingCode]:
        """Get all pending (unapproved, unexpired) codes."""
        now = time.time()
        codes = [
            c
            for c in self._codes.values()
            if not c.approved and not c.revoked and c.expires_at > now
        ]
        if platform:
            codes = [c for c in codes if c.platform == platform.lower()]
        return sorted(codes, key=lambda c: c.created_at)

    def is_user_authorized(self, platform: str, user_id: str) -> bool:
        """Check if a user is authorized for a platform."""
        platform = platform.lower().strip()

        # Check allowlist env var
        env_var = _allowlist_env_for_platform(platform)
        if env_var:
            allowlist = os.getenv(env_var, "").strip()
            if allowlist:
                ids = _split_allowlist(allowlist)
                if "*" in ids or str(user_id) in ids:
                    return True

        # Check approved pairing codes
        for code in self._codes.values():
            if (
                code.platform == platform
                and code.user_id == str(user_id)
                and code.approved
                and not code.revoked
            ):
                return True

        return False

    def cleanup_expired(self):
        """Remove expired codes."""
        now = time.time()
        expired = [c for c in self._codes.values() if c.expires_at < now]
        for code in expired:
            del self._codes[code.code]
        if expired:
            self._save()


# Global pairing manager
_pairing_manager: Optional[PairingManager] = None


def get_pairing_manager() -> PairingManager:
    global _pairing_manager
    if _pairing_manager is None:
        _pairing_manager = PairingManager()
    return _pairing_manager


# ═══════════════════════════════════════════════════════════════
# Streaming Consumer (Progressive message editing)
# ═══════════════════════════════════════════════════════════════

_DONE = object()
_NEW_SEGMENT = object()
_COMMENTARY = object()
_FLUSH = object()


@dataclass
class StreamConsumerConfig:
    edit_interval: float = 1.0
    buffer_threshold: int = 100
    cursor: str = "▌"
    buffer_only: bool = False
    fresh_message_after: float = 30.0
    transport: str = "edit"  # auto, draft, edit, off
    chat_type: str = ""


class GatewayStreamConsumer:
    """Async consumer that progressively edits a platform message with streamed tokens."""

    def __init__(
        self,
        adapter: Any,
        chat_id: str,
        config: StreamConsumerConfig,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.adapter = adapter
        self.chat_id = chat_id
        self.config = config
        self.metadata = metadata or {}

        self._queue: asyncio.Queue = asyncio.Queue()
        self._buffer = ""
        self._message_id: Optional[str] = None
        self._first_edit = True
        self._flood_strikes = 0
        self._start_time = time.time()
        self._finished = False
        self._current_segment = ""

    def on_delta(self, text: str):
        """Called synchronously from agent worker thread."""
        self._queue.put_nowait(text)

    def on_tool_start(self, tool_name: str, args: Dict[str, Any]):
        """Called when a tool starts."""
        self._queue.put_nowait(_NEW_SEGMENT)
        self._queue.put_nowait(f"🔧 **{tool_name}**\n```json\n{json.dumps(args, indent=2)}\n```")

    def on_tool_result(self, tool_name: str, result: Any, error: Optional[str] = None):
        """Called when a tool completes."""
        if error:
            self._queue.put_nowait(f"❌ **{tool_name} failed**: {error}")
        else:
            result_str = str(result)
            if len(result_str) > 500:
                result_str = result_str[:500] + "..."
            self._queue.put_nowait(f"✅ **{tool_name} completed**\n```\n{result_str}\n```")

    def on_commentary(self, text: str):
        """Called for assistant commentary between tool calls."""
        self._queue.put_nowait(_COMMENTARY)
        self._queue.put_nowait(text)

    def flush_pending_sync(self) -> threading.Event:
        """Block until all queued content before this point is delivered."""
        event = threading.Event()
        self._queue.put_nowait((_FLUSH, event))
        return event

    def finish(self):
        """Signal stream completion."""
        self._queue.put_nowait(_DONE)

    async def run(self):
        """Main consumer loop."""
        while True:
            item = await self._queue.get()

            if item is _DONE:
                await self._finalize()
                break

            elif item is _NEW_SEGMENT or item is _COMMENTARY:
                await self._finalize_segment()
                self._current_segment = ""

            elif isinstance(item, tuple) and item[0] is _FLUSH:
                await self._finalize_segment()
                item[1].set()

            else:
                # Text delta
                self._buffer += item
                self._current_segment += item

                if len(self._buffer) >= self.config.buffer_threshold:
                    await self._edit_message()

        return self._message_id

    async def _edit_message(self):
        if not self._buffer:
            return

        content = self._buffer
        if self.config.cursor and not self._finished:
            content += self.config.cursor

        try:
            if self._first_edit:
                # Send initial message
                self._message_id = await self.adapter.send_message(
                    self.chat_id, content, parse_mode="markdown"
                )
                self._first_edit = False
            else:
                # Edit existing message
                await self.adapter.edit_message(
                    self.chat_id, self._message_id, content, parse_mode="markdown"
                )

            self._buffer = ""
            self._flood_strikes = 0

        except Exception as e:
            logger.error(f"Stream edit failed: {e}")
            self._flood_strikes += 1
            if self._flood_strikes >= 3:
                # Disable progressive edits
                self.config.buffer_only = True

    async def _finalize_segment(self):
        if self._current_segment:
            await self._edit_message()
            self._current_segment = ""

    async def _finalize(self):
        self._finished = True
        await self._finalize_segment()

        # Remove cursor from final message
        if self._message_id and self._buffer:
            final_content = self._buffer
            try:
                await self.adapter.edit_message(
                    self.chat_id, self._message_id, final_content, parse_mode="markdown"
                )
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════
# Platform Adapters (Base)
# ═══════════════════════════════════════════════════════════════


class BasePlatformAdapter:
    """Base class for platform adapters."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.platform_name = "base"

    async def start(self):
        """Start the adapter."""
        pass

    async def stop(self):
        """Stop the adapter."""
        pass

    async def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: Optional[str] = None,
        **kwargs,
    ) -> Optional[str]:
        """Send a message. Returns message ID."""
        raise NotImplementedError

    async def edit_message(
        self,
        chat_id: str,
        message_id: str,
        text: str,
        parse_mode: Optional[str] = None,
    ):
        """Edit a message."""
        raise NotImplementedError

    async def delete_message(self, chat_id: str, message_id: str):
        """Delete a message."""
        pass

    async def handle_update(self, update: Dict[str, Any]):
        """Handle incoming update."""
        pass


# ═══════════════════════════════════════════════════════════════
# Gateway Manager
# ═══════════════════════════════════════════════════════════════


@dataclass
class GatewayConfig:
    enabled: bool = False
    port: int = 8080
    platforms: List[str] = field(default_factory=list)
    allowed_users: Dict[str, List[str]] = field(default_factory=dict)
    pairing_enabled: bool = True
    streaming_enabled: bool = True
    # Gateway sessions are a remote/untrusted input boundary. By default the
    # shell/code-execution tools are blocked for gateway users; an operator can
    # explicitly opt in per deployment. Enforced both at schema advertisement
    # (blocked_tools) and at the execution boundary in _execute_tool().
    allow_sensitive_tools: bool = False
    max_sessions: int = 32
    session_idle_ttl: float = 3600.0


@dataclass
class GatewaySession:
    """One isolated agent + serialization lock per (platform, chat, user)."""

    key: str
    agent: MobileAgent
    lock: asyncio.Lock
    last_used: float


# Tools that execute code/shell or install code. Blocked for gateway sessions
# unless GatewayConfig.allow_sensitive_tools is explicitly enabled.
GATEWAY_DEFAULT_BLOCKED = frozenset(
    {"terminal", "process", "execute_code", "cronjob", "skill_manage"}
)


class GatewayManager:
    """Manages the gateway for messaging platforms."""

    def __init__(self, config: GatewayConfig):
        self.config = config
        self.settings = get_settings()
        self.adapters: Dict[str, BasePlatformAdapter] = {}
        self.memory_provider: Optional[MobileMemoryProvider] = None
        self.pairing_manager = get_pairing_manager()
        self._running = False
        self._tasks: List[asyncio.Task] = []
        # Per-session agent state. A single mutable MobileAgent shared across
        # users would leak conversation context, session ids, workspaces and
        # process registries between users. Each session owns its own agent.
        self._sessions: Dict[str, GatewaySession] = {}
        self._session_registry_lock = threading.Lock()

    async def initialize(self):
        """Initialize gateway components."""
        # Initialize memory provider (shared by all gateway session agents so
        # the on-device SQLite stays single-connection).
        self.memory_provider = MobileMemoryProvider(
            db_path=self.settings.get_memory_db_path(),
            encrypt=self.settings.encrypt_memory,
        )

        # Initialize pairing manager
        self.pairing_manager.cleanup_expired()

        logger.info("Gateway initialized")

    def _create_session_agent(self) -> MobileAgent:
        """Build an isolated agent for one gateway session.

        No approval_callback is wired: there is no interactive approver on the
        gateway. Instead the sensitive-tool decision is an explicit operator
        policy at the config layer, and blocked_tools is enforced at the
        execution boundary in _execute_tool().
        """
        blocked: Optional[set[str]] = None
        if not self.config.allow_sensitive_tools:
            blocked = set(GATEWAY_DEFAULT_BLOCKED)
        return create_mobile_agent(
            memory_provider=self.memory_provider,
            blocked_tools=blocked,
        )

    async def _get_session(self, platform: str, chat_id: str, user_id: str) -> GatewaySession:
        """Return the isolated agent session for (platform, chat, user).

        Sessions are cached up to max_sessions and evicted when idle past
        session_idle_ttl. Agent construction is cheap (lazy client); the heavy
        memory provider is shared and owned by the manager.
        """
        key = f"{platform}:{chat_id}:{user_id}"
        now = time.time()

        with self._session_registry_lock:
            existing = self._sessions.get(key)
            if existing is not None:
                existing.last_used = now
                return existing

            # Evict idle sessions first, then the LRU when at capacity.
            idle = [
                k
                for k, s in self._sessions.items()
                if now - s.last_used > self.config.session_idle_ttl
            ]
            for k in idle:
                self._sessions.pop(k, None)
            while len(self._sessions) >= max(1, self.config.max_sessions):
                oldest_key = min(self._sessions, key=lambda k: self._sessions[k].last_used)
                self._sessions.pop(oldest_key, None)

        agent = self._create_session_agent()
        session = GatewaySession(
            key=key,
            agent=agent,
            lock=asyncio.Lock(),
            last_used=now,
        )

        with self._session_registry_lock:
            # Another coroutine may have created this key while we built the
            # agent; prefer the existing session and drop the duplicate agent.
            existing = self._sessions.get(key)
            if existing is not None:
                existing.last_used = now
                return existing
            self._sessions[key] = session
        return session

    async def start(self):
        """Start the gateway."""
        if not self.config.enabled:
            logger.info("Gateway disabled in config")
            return

        await self.initialize()
        self._running = True

        # Start platform adapters
        for platform in self.config.platforms:
            await self._start_platform(platform)

        # Start background tasks
        self._tasks.append(asyncio.create_task(self._cleanup_loop()))

        logger.info(f"Gateway started on port {self.config.port}")

    async def stop(self):
        """Stop the gateway."""
        self._running = False

        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        for adapter in self.adapters.values():
            await adapter.stop()

        with self._session_registry_lock:
            self._sessions.clear()

        if self.memory_provider:
            self.memory_provider.close()

        logger.info("Gateway stopped")

    async def _start_platform(self, platform: str):
        """Start a platform adapter."""
        if platform == "telegram":
            from hermes_mobile.gateway.telegram_adapter import TelegramAdapter

            # Env var wins (classic desktop/server flow); the in-app Messaging
            # settings store is the fallback so the token entered on device
            # works without a .env file.
            token = os.getenv("TELEGRAM_BOT_TOKEN", "")
            if not token:
                from hermes_mobile.remote.secrets import GatewaySecretStore

                token = GatewaySecretStore(self.settings.get_data_dir()).get_token()
            if not token:
                logger.warning(
                    "TELEGRAM_BOT_TOKEN not set (env or Messaging settings), "
                    "skipping Telegram adapter"
                )
                return
            adapter = TelegramAdapter(token=token, on_message=self.handle_message)
            self.adapters[platform] = adapter
            await adapter.start()
        else:
            logger.info("Platform %s adapter not yet implemented", platform)

    async def _cleanup_loop(self):
        """Periodic cleanup."""
        while self._running:
            try:
                self.pairing_manager.cleanup_expired()
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
            await asyncio.sleep(300)  # Every 5 minutes

    async def handle_message(
        self,
        platform: str,
        chat_id: str,
        user_id: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Handle incoming message from a platform."""
        # Check authorization
        if not self.pairing_manager.is_user_authorized(platform, user_id):
            # Request pairing
            try:
                code = self.pairing_manager.request_pairing(
                    platform, user_id, (metadata or {}).get("user_name", "Unknown")
                )
            except ValueError as exc:
                # Rate-limited / locked out: don't leak details, don't crash the
                # adapter's update loop.
                logger.warning("Pairing request rejected for %s/%s: %s", platform, user_id, exc)
                return
            if code:
                await self._send_pairing_message(platform, chat_id, code)
            return

        # Find adapter
        adapter = self.adapters.get(platform)
        if not adapter:
            logger.error(f"No adapter for platform: {platform}")
            return

        # Isolated agent per (platform, chat, user); concurrent messages to the
        # same session are serialized so conversation state cannot interleave.
        session = await self._get_session(platform, chat_id, user_id)
        agent = session.agent

        # Create stream consumer
        config = StreamConsumerConfig(
            transport="edit",
            chat_type=metadata.get("chat_type", "") if metadata else "",
        )

        consumer = GatewayStreamConsumer(adapter, chat_id, config, metadata)
        # Start the consumer BEFORE the model stream so progressive edits happen
        # during generation instead of after the whole response has finished.
        consumer_task = asyncio.create_task(consumer.run())

        try:
            async with session.lock:
                async for chunk in agent.run_conversation(text, stream=True):
                    consumer.on_delta(chunk)

                consumer.finish()
            await consumer_task

        except Exception as e:
            logger.error(f"Error handling message: {e}")
            try:
                consumer.finish()
                await consumer_task
            except Exception:
                pass
            await adapter.send_message(chat_id, f"Error: {str(e)}")

    async def _send_pairing_message(self, platform: str, chat_id: str, code: PairingCode):
        """Send pairing code message."""
        adapter = self.adapters.get(platform)
        if not adapter:
            return

        message = (
            f"🔐 **Authorization Required**\n\n"
            f"Please approve this device using the code:\n\n"
            f"**{code.code}**\n\n"
            f"Code expires in 1 hour. Use `/approve {code.code}` in the Hermes CLI."
        )

        await adapter.send_message(chat_id, message, parse_mode="markdown")


# ═══════════════════════════════════════════════════════════════
# CLI Commands for Pairing
# ═══════════════════════════════════════════════════════════════


def cli_approve(code: str) -> bool:
    """CLI command to approve a pairing code."""
    manager = get_pairing_manager()
    return manager.approve_code(code)


def cli_revoke(code: str) -> bool:
    """CLI command to revoke a pairing code."""
    manager = get_pairing_manager()
    return manager.revoke_code(code)


def cli_list_pending(platform: Optional[str] = None) -> List[PairingCode]:
    """CLI command to list pending pairing codes."""
    manager = get_pairing_manager()
    return manager.get_pending_codes(platform)


def cli_pairing_status(platform: str, user_id: str) -> bool:
    """CLI command to check pairing status."""
    manager = get_pairing_manager()
    return manager.is_user_authorized(platform, user_id)
