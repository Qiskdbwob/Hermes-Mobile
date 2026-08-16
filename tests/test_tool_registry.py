"""Regression tests for the audit's P1/P2 remediation batch:

- tool registry is a single source of truth (HERMES_CORE_TOOLS reconciled with
  the implemented handlers + explicit unimplemented/mobile-addition sets);
- skill installation (code install) requires explicit human approval at the
  execution boundary, and is denied outright without a callback;
- search_files_tool runs the filesystem scan in a worker thread, not the
  event loop;
- memory provider write paths are serialized across threads.
"""

import asyncio
import threading

import pytest

from hermes_mobile.core.agent import MobileAgent
from hermes_mobile.toolsets import (
    HERMES_CORE_TOOLS,
    HERMES_MOBILE_ADDITIONS,
    HERMES_UNIMPLEMENTED_TOOLS,
    registry_integrity,
)

# ═══════════════════════════════════════════════════════════════
# Tool registry reconciliation
# ═══════════════════════════════════════════════════════════════


class TestToolRegistry:
    def test_registry_is_single_source_of_truth(self):
        agent = MobileAgent()
        implemented = set(agent._builtin_tools.keys())

        report = registry_integrity(implemented)

        # Nothing declared is missing a handler unless it is EXPLICITLY listed
        # as intentionally unimplemented; nothing implemented is undeclared
        # unless it is EXPLICITLY listed as a mobile addition.
        assert report["declared_without_handler"] == []
        assert report["implemented_but_undeclared"] == []
        assert report["unimplemented_but_implemented"] == []

        # The explicit sets exactly explain the diff vs the taxonomy.
        assert set(HERMES_CORE_TOOLS) - implemented == set(HERMES_UNIMPLEMENTED_TOOLS)
        assert implemented - set(HERMES_CORE_TOOLS) == set(HERMES_MOBILE_ADDITIONS)

    def test_unimplemented_tools_never_advertised(self):
        agent = MobileAgent()
        schemas = agent.get_tool_schemas()
        names = {schema["function"]["name"] for schema in schemas}
        assert names.isdisjoint(HERMES_UNIMPLEMENTED_TOOLS)

    def test_every_implemented_tool_has_schema(self):
        agent = MobileAgent()
        schemas = {schema["function"]["name"] for schema in agent.get_tool_schemas()}
        assert set(agent._builtin_tools.keys()) == schemas


# ═══════════════════════════════════════════════════════════════
# Skill installation approval
# ═══════════════════════════════════════════════════════════════


class TestSkillInstallApproval:
    async def test_install_denied_without_callback(self):
        agent = MobileAgent()
        with pytest.raises(PermissionError, match="user approval"):
            await agent._execute_tool(
                "skill_manage", {"action": "install", "name": "x", "url": "https://example.com/x"}
            )

    async def test_install_rejected_when_user_denies(self):
        from unittest.mock import AsyncMock

        agent = MobileAgent(approval_callback=AsyncMock(return_value=False))
        with pytest.raises(PermissionError, match="not approved"):
            await agent._execute_tool(
                "skill_manage", {"action": "install", "name": "x", "url": "https://example.com/x"}
            )

    async def test_install_runs_after_approval(self):
        from unittest.mock import AsyncMock, patch

        agent = MobileAgent(approval_callback=AsyncMock(return_value=True))
        with patch.object(agent, "_tool_skill_manage", new=AsyncMock(return_value={"ok": True})):
            result = await agent._execute_tool(
                "skill_manage", {"action": "install", "name": "x", "url": "https://example.com/x"}
            )
        assert result == {"ok": True}

    async def test_non_install_actions_not_gated(self):
        from unittest.mock import AsyncMock, patch

        agent = MobileAgent()  # no callback at all
        with patch.object(agent, "_tool_skill_manage", new=AsyncMock(return_value={"ok": True})):
            result = await agent._execute_tool("skill_manage", {"action": "list"})
        assert result == {"ok": True}


# ═══════════════════════════════════════════════════════════════
# File search off the event loop
# ═══════════════════════════════════════════════════════════════


class TestSearchFilesThread:
    async def test_content_search_offloaded_to_thread(self, monkeypatch, tmp_path):
        import hermes_mobile.tools.desktop_tools as dt

        (tmp_path / "a.txt").write_text("hello world")

        calls = []
        original_to_thread = asyncio.to_thread

        async def fake_to_thread(fn, *args, **kwargs):
            calls.append(fn)
            return await original_to_thread(fn, *args, **kwargs)

        monkeypatch.setattr(dt.asyncio, "to_thread", fake_to_thread)

        result = await dt.search_files_tool(
            "hello", path=str(tmp_path), extra_dirs=[tmp_path], base_dir=tmp_path
        )
        assert result["count"] == 1
        assert calls == [dt._search_content]

    async def test_filename_search_offloaded_to_thread(self, monkeypatch, tmp_path):
        import hermes_mobile.tools.desktop_tools as dt

        (tmp_path / "report_2026.txt").write_text("x")

        calls = []
        original_to_thread = asyncio.to_thread

        async def fake_to_thread(fn, *args, **kwargs):
            calls.append(fn)
            return await original_to_thread(fn, *args, **kwargs)

        monkeypatch.setattr(dt.asyncio, "to_thread", fake_to_thread)

        result = await dt.search_files_tool(
            "report_*", path=str(tmp_path), target="files", extra_dirs=[tmp_path], base_dir=tmp_path
        )
        assert result["count"] == 1
        assert calls == [dt._search_filenames]


# ═══════════════════════════════════════════════════════════════
# Provider write-path serialization
# ═══════════════════════════════════════════════════════════════


class TestProviderLock:
    def test_write_methods_are_locked(self, memory_provider):
        # Write paths carry the _locked wrapper; read paths stay unlocked.
        assert hasattr(memory_provider.save_conversation, "__wrapped__")
        assert hasattr(memory_provider.upsert_session_summary, "__wrapped__")
        assert hasattr(memory_provider.index_session_keywords, "__wrapped__")
        assert hasattr(memory_provider.cleanup_expired, "__wrapped__")
        assert not hasattr(memory_provider.get_conversation, "__wrapped__")
        assert not hasattr(memory_provider.search_sessions, "__wrapped__")

    def test_concurrent_writers_across_threads_do_not_corrupt(self, memory_provider):
        """Two threads hammering the shared provider must serialize cleanly."""
        errors: list[Exception] = []

        def writer(start: int):
            try:
                loop = asyncio.new_event_loop()
                try:
                    for i in range(20):
                        loop.run_until_complete(
                            memory_provider.store_memory(f"k{start}_{i}", f"v{start}_{i}")
                        )
                finally:
                    loop.close()
            except Exception as exc:  # pragma: no cover - failure path
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        # All 120 writes landed and are readable.
        for t in range(6):
            for i in range(20):
                assert loop_get(memory_provider, f"k{t}_{i}") == f"v{t}_{i}"


def loop_get(provider, key):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(provider.get_memory(key))
    finally:
        loop.close()
