"""Regression tests for the gateway security / session isolation hardening.

Covers the audit's P0 remediation items:

- revoked pairing codes can never be approved (and revoking an approved code
  removes authorization immediately);
- allowlist changes persist to .env AND apply to the running process at once;
- gateway sessions are isolated per (platform, chat, user) — no shared mutable
  MobileAgent, no context leak, no interleaving;
- gateway session agents block shell/code tools by default (config-gated
  opt-in via ``allow_sensitive_tools``);
- gateway streaming is progressive: the consumer starts before the model
  stream, so edits happen during generation, not after;
- ``_execute_tool`` enforces ``blocked_tools`` at the execution boundary;
- session finalization captures session identity (no race with
  ``clear_conversation`` resetting the live session_id).
"""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import hermes_mobile.gateway.mobile_gateway as gw
from hermes_mobile.core.agent import Message, MobileAgent
from hermes_mobile.gateway.mobile_gateway import (
    GATEWAY_DEFAULT_BLOCKED,
    GatewayConfig,
    GatewayManager,
    get_pairing_manager,
)

# ═══════════════════════════════════════════════════════════════
# Pairing: revoked codes
# ═══════════════════════════════════════════════════════════════


class TestPairingRevokedApproval:
    @pytest.fixture(autouse=True)
    def _isolate(self, temp_dir):
        original_fn = gw._get_pairing_dir
        gw._get_pairing_dir = lambda: temp_dir / "pairing"
        gw._pairing_manager = None
        yield
        gw._get_pairing_dir = original_fn

    def _pm(self):
        gw._pairing_manager = None
        return get_pairing_manager()

    def test_revoked_code_cannot_be_approved(self):
        pm = self._pm()
        code = pm.request_pairing("telegram", "u1", "U1")
        assert pm.revoke_code(code.code) is True
        assert code.revoked is True
        # Even before expiry, approval must be rejected — previously the code
        # got marked approved while the authorization check still refused it.
        assert pm.approve_code(code.code) is False
        assert code.approved is False
        assert pm.is_user_authorized("telegram", "u1") is False

    def test_approved_then_revoked_user_loses_authorization(self):
        pm = self._pm()
        code = pm.request_pairing("telegram", "u2", "U2")
        assert pm.approve_code(code.code) is True
        assert pm.is_user_authorized("telegram", "u2") is True
        assert pm.revoke_code(code.code) is True
        assert pm.is_user_authorized("telegram", "u2") is False


# ═══════════════════════════════════════════════════════════════
# Allowlist: runtime + persistence sync
# ═══════════════════════════════════════════════════════════════


class TestAllowlistRuntimeSync:
    def test_add_updates_running_process_and_file(self):
        with (
            patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "a"}),
            patch(f"{gw.__name__}.Path") as mock_path,
        ):
            mock_instance = MagicMock()
            mock_instance.exists.return_value = True
            mock_instance.read_text.return_value = "TELEGRAM_ALLOWED_USERS=a"
            mock_path.return_value = mock_instance
            gw._sync_allowlist_add("telegram", "b")
            written = mock_instance.write_text.call_args[0][0]
            assert "TELEGRAM_ALLOWED_USERS=a,b" in written
            # Authorization reads os.environ: the running process must update.
            assert os.environ["TELEGRAM_ALLOWED_USERS"] == "a,b"

    def test_remove_updates_running_process_and_file(self):
        with (
            patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "a,b"}),
            patch(f"{gw.__name__}.Path") as mock_path,
        ):
            mock_instance = MagicMock()
            mock_instance.exists.return_value = True
            mock_instance.read_text.return_value = "TELEGRAM_ALLOWED_USERS=a,b"
            mock_path.return_value = mock_instance
            gw._sync_allowlist_remove("telegram", "a")
            written = mock_instance.write_text.call_args[0][0]
            assert "TELEGRAM_ALLOWED_USERS=b" in written
            assert "a" not in written.split("=", 1)[1].strip()
            assert os.environ["TELEGRAM_ALLOWED_USERS"] == "b"

    def test_remove_does_not_rewrite_when_user_absent(self):
        with (
            patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "a"}),
            patch(f"{gw.__name__}.Path") as mock_path,
        ):
            mock_instance = MagicMock()
            mock_path.return_value = mock_instance
            gw._sync_allowlist_remove("telegram", "nobody")
            mock_instance.write_text.assert_not_called()
            assert os.environ["TELEGRAM_ALLOWED_USERS"] == "a"


# ═══════════════════════════════════════════════════════════════
# Gateway session isolation + sensitive-tool policy
# ═══════════════════════════════════════════════════════════════


class TestGatewaySessionIsolation:
    @patch(f"{gw.__name__}.create_mobile_agent")
    async def test_distinct_sessions_get_distinct_agents(self, mock_agent):
        mock_agent.side_effect = lambda **kwargs: MagicMock()
        manager = GatewayManager(GatewayConfig(enabled=False))
        s1 = await manager._get_session("telegram", "chat1", "userA")
        s2 = await manager._get_session("telegram", "chat2", "userB")
        assert s1 is not s2
        assert s1.agent is not s2.agent
        # Same (platform, chat, user) reuses the cached session.
        s1_again = await manager._get_session("telegram", "chat1", "userA")
        assert s1_again is s1

    @patch(f"{gw.__name__}.create_mobile_agent")
    async def test_sensitive_tools_blocked_by_default(self, mock_agent):
        manager = GatewayManager(GatewayConfig(enabled=False))
        await manager._get_session("telegram", "chat1", "userA")
        blocked = mock_agent.call_args.kwargs.get("blocked_tools")
        assert GATEWAY_DEFAULT_BLOCKED.issubset(blocked)
        assert {"terminal", "process", "execute_code"}.issubset(blocked)

    @patch(f"{gw.__name__}.create_mobile_agent")
    async def test_allow_sensitive_tools_removes_blocklist(self, mock_agent):
        manager = GatewayManager(GatewayConfig(enabled=False, allow_sensitive_tools=True))
        await manager._get_session("telegram", "chat1", "userA")
        assert mock_agent.call_args.kwargs.get("blocked_tools") is None

    async def test_real_session_agents_have_isolated_state(self, test_settings, memory_provider):
        manager = GatewayManager(GatewayConfig(enabled=False))
        manager.memory_provider = memory_provider
        a = manager._create_session_agent()
        b = manager._create_session_agent()
        assert a is not b
        assert a.session_id != b.session_id
        a.add_user_message("secret from user A")
        assert len(a.messages) == 1
        assert len(b.messages) == 0
        assert a._workspace is b._workspace


# ═══════════════════════════════════════════════════════════════
# Progressive streaming
# ═══════════════════════════════════════════════════════════════


class _RecordingAdapter:
    def __init__(self):
        self.sent_messages = []
        self.edited_messages = []

    async def send_message(self, chat_id, text, parse_mode=None, **kwargs):
        self.sent_messages.append((chat_id, text))
        return f"msg_{len(self.sent_messages)}"

    async def edit_message(self, chat_id, message_id, text, parse_mode=None):
        self.edited_messages.append((chat_id, message_id, text))


class TestProgressiveStreaming:
    @pytest.fixture(autouse=True)
    def _isolate_pairing_dir(self, temp_dir):
        original_fn = gw._get_pairing_dir
        gw._get_pairing_dir = lambda: temp_dir / "pairing"
        yield
        gw._get_pairing_dir = original_fn

    @patch(f"{gw.__name__}.create_mobile_agent")
    @patch(f"{gw.__name__}.MobileMemoryProvider")
    async def test_consumer_edits_during_generation(self, mock_memory, mock_agent, temp_dir):
        gw._pairing_manager = None
        manager = GatewayManager(GatewayConfig(enabled=False))
        manager.pairing_manager = get_pairing_manager()
        code = manager.pairing_manager.request_pairing("telegram", "auth_user", "Test")
        manager.pairing_manager.approve_code(code.code)

        adapter = _RecordingAdapter()
        manager.adapters = {"telegram": adapter}

        async def stream(user_input, stream=True):
            # One big chunk pushes the buffer over the threshold (100).
            yield "x" * 120
            # While the producer is still streaming, the consumer task must
            # already have delivered the message. Previously the consumer only
            # ran after the whole stream finished.
            for _ in range(50):
                if adapter.sent_messages:
                    break
                await asyncio.sleep(0.01)
            assert adapter.sent_messages, "consumer must send during generation"
            yield "y" * 40
            yield "z" * 40

        mock_agent_instance = MagicMock()
        mock_agent_instance.run_conversation = MagicMock(side_effect=stream)
        mock_agent.return_value = mock_agent_instance

        await manager.handle_message("telegram", "chat_1", "auth_user", "hello", {})
        assert adapter.sent_messages


# ═══════════════════════════════════════════════════════════════
# Execution boundary for blocked tools
# ═══════════════════════════════════════════════════════════════


class TestExecutionBoundary:
    async def test_blocked_tool_raises_permission_error(self):
        agent = MobileAgent(blocked_tools={"terminal"})
        with pytest.raises(PermissionError, match="blocked"):
            await agent._execute_tool("terminal", {"command": "echo hi"})

    async def test_blocked_tool_never_reaches_builtin_or_skill(self):
        agent = MobileAgent(blocked_tools={"web_search"})
        skill = SimpleNamespace(execute=AsyncMock(return_value="ran"))
        agent.skill_manager = SimpleNamespace(get_skill=lambda name: skill)
        with pytest.raises(PermissionError, match="blocked"):
            await agent._execute_tool("web_search", {"query": "x"})
        skill.execute.assert_not_awaited()

    async def test_unblocked_tool_still_runs(self):
        agent = MobileAgent(blocked_tools={"terminal"})
        with patch.object(agent, "_tool_get_time", new=AsyncMock(return_value="now")):
            result = await agent._execute_tool("get_time", {})
        assert result == "now"


# ═══════════════════════════════════════════════════════════════
# Session finalization race
# ═══════════════════════════════════════════════════════════════


class TestFinalizationRace:
    async def test_schedule_finalize_writes_old_session_id(self, memory_provider):
        ag = MobileAgent(memory_provider=memory_provider)
        ag.add_user_message("Remember my project uses Postgres")
        ag.add_assistant_message("Noted.")
        old_session_id = ag.session_id

        loop = asyncio.get_running_loop()
        tasks = []
        original_create_task = loop.create_task

        def capture(coro):
            task = original_create_task(coro)
            tasks.append(task)
            return task

        loop.create_task = capture
        try:
            # The finalize task only starts on a later loop iteration, so the
            # patch must stay active while we await it.
            with patch.object(
                ag, "_summarize_with_llm", new=AsyncMock(return_value="LLM: project uses Postgres")
            ):
                ag.clear_conversation()
                assert tasks, "finalize task must be scheduled"
                await asyncio.wait(tasks)
        finally:
            loop.create_task = original_create_task

        # The summary belongs to the OLD session, never the new live one.
        assert ag.session_id != old_session_id
        assert await memory_provider.get_session_summary(old_session_id) == (
            "LLM: project uses Postgres"
        )
        assert await memory_provider.get_session_summary(ag.session_id) is None

    async def test_deferred_finalize_does_not_touch_live_session(self, memory_provider):
        await memory_provider.save_conversation("old-s", [Message.user("hi")])
        ag = MobileAgent(memory_provider=memory_provider)
        live_sid = ag.session_id
        with patch.object(ag, "_summarize_with_llm", new=AsyncMock(return_value="LLM old")):
            await ag._finalize_session_from_messages(
                "old-s", await memory_provider.get_conversation("old-s")
            )
        # No session_id swapping on the live agent.
        assert ag.session_id == live_sid
        assert await memory_provider.get_session_summary("old-s") == "LLM old"
