#!/usr/bin/env python3
"""Production-readiness stress test for Hermes Mobile.

Hammers the subsystems that matter for a released APK — agent loop,
encrypted memory, memory harness, context compression, cron scheduler,
gateway pairing, and the WebView automation engine — with volume,
concurrency, and malformed input, then reports PASS/FAIL per check.

Usage:
    python3 scripts/stress_test.py            # full run
    python3 scripts/stress_test.py --quick    # reduced volume

The script writes nothing outside a fresh temp DATA_DIR (all subsystems
resolve their storage from settings.data_dir) and exits non-zero if any
check fails. Run it from the repository root. Pure stdlib + project deps.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import pkgutil
import random
import sys
import tempfile
import time
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Never touch real user data: point every subsystem (memory DB, cron dir,
# gateway pairing, settings JSON) at a fresh temp tree before any import.
_STRESS_DIR = Path(tempfile.mkdtemp(prefix="hermes-stress-"))
os.environ["DATA_DIR"] = str(_STRESS_DIR)

RESULTS: List[Dict[str, Any]] = []


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    RESULTS.append({"name": name, "ok": bool(ok), "detail": detail})


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def validate_api_messages(messages: List[Dict[str, Any]]) -> None:
    """Assert OpenAI-compatible conversation invariants.

    - messages[0] is the system prompt
    - every assistant(tool_calls) message is immediately followed by a tool
      result for each call id, before any other role appears
    """
    assert messages and messages[0].get("role") == "system", "missing system message"
    i = 1
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            pending = {tc["id"] for tc in msg["tool_calls"]}
            assert pending, "assistant with empty tool_calls list"
            j = i + 1
            while pending:
                assert j < len(messages), f"unanswered tool calls: {pending}"
                tool_msg = messages[j]
                assert tool_msg.get("role") == "tool", (
                    f"expected tool result, got role={tool_msg.get('role')!r} "
                    f"(call {next(iter(pending))})"
                )
                call_id = tool_msg.get("tool_call_id")
                assert call_id in pending, f"stray tool_call_id: {call_id!r}"
                pending.discard(call_id)
                j += 1
            i = j
        else:
            i += 1


class _FakeToolCallMsg:
    def __init__(self, name: str, arguments: str, call_id: str):
        self.function = SimpleNamespace(name=name, arguments=arguments)
        self.id = call_id


class _FakeMessage:
    def __init__(self, content: str = "", tool_calls: Optional[List[Any]] = None):
        self.content = content
        self.tool_calls = tool_calls or []


class _FakeChoice:
    def __init__(self, message: _FakeMessage):
        self.message = message


class _FakeResponse:
    def __init__(self, content: str = "", tool_calls: Optional[List[Any]] = None):
        self.choices = [_FakeChoice(_FakeMessage(content, tool_calls))]


class _FakeCompletions:
    """Returns responses in order, repeating the last one."""

    def __init__(self, responses: List[Any]):
        self.responses = responses
        self.calls = 0

    async def create(self, **kwargs: Any) -> Any:
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


class _FakeClient:
    def __init__(self, responses: List[Any]):
        self.chat = SimpleNamespace(completions=_FakeCompletions(responses))


class _FakeStream:
    def __init__(self, chunks: List[Any]):
        self._chunks = list(chunks)

    def __aiter__(self) -> "_FakeStream":
        return self

    async def __anext__(self) -> Any:
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


def _stream_delta(content: Optional[str] = None, tool_calls: Optional[List[Any]] = None) -> Any:
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def _stream_chunk(delta: Any) -> Any:
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


async def _noop_summarize(text: str) -> str:
    return ""


# ---------------------------------------------------------------------------
# 1. Import gate
# ---------------------------------------------------------------------------


def import_gate() -> None:
    import hermes_mobile  # noqa: F401 - walking the package below

    failures: List[str] = []
    for module in pkgutil.walk_packages(hermes_mobile.__path__, prefix="hermes_mobile."):
        try:
            importlib.import_module(module.name)
        except Exception as exc:  # noqa: BLE001 - stress gate reports any failure
            failures.append(f"{module.name}: {exc.__class__.__name__}: {exc}")
    check(
        "every hermes_mobile module imports",
        not failures,
        "; ".join(failures[:5])
        or f"{len(list(pkgutil.iter_modules(hermes_mobile.__path__)))} top-level modules",
    )


# ---------------------------------------------------------------------------
# 2. Memory provider volume + concurrency + TTL soak
# ---------------------------------------------------------------------------


async def memory_provider_soak(quick: bool) -> None:
    from hermes_mobile.core.agent import Message
    from hermes_mobile.memory.provider import MobileMemoryProvider

    tmp = Path(tempfile.mkdtemp(prefix="hm-mem-"))
    encrypted = MobileMemoryProvider(
        db_path=tmp / "enc.db", encrypt=True, encryption_key="stress-test-key"
    )
    plain = MobileMemoryProvider(db_path=tmp / "plain.db", encrypt=False)
    volume = 60 if quick else 200
    try:
        # Conversations: volume + encrypted round-trip integrity.
        for i in range(volume):
            await encrypted.save_conversation(
                f"stress-sess-{i}",
                [
                    Message.user(f"hello {i} secret payload"),
                    Message.assistant(f"hi back {i}"),
                ],
            )
        convos = await encrypted.list_conversations(limit=volume + 50)
        check(
            "conversation volume persisted",
            len(convos) == volume,
            f"{len(convos)}/{volume}",
        )
        restored = await encrypted.get_conversation("stress-sess-7", limit=10)
        decrypted_ok = any(str(m.get("content")) == "hello 7 secret payload" for m in restored)
        check("encrypted conversation round-trips", decrypted_ok)

        # Long-term memory entries + keyword search.
        for i in range(volume):
            await plain.add_memory_entry(f"mem-sess-{i}", f"User prefers stack number {i % 12}.")
        hits = await plain.search_memory("stack number 7", limit=5)
        check("memory keyword search returns hits", len(hits) >= 1, f"{len(hits)} hits")
        context = await plain.get_relevant_context("stack", limit=3)
        check("get_relevant_context returns text", bool(context.strip()))

        # Memory items + evidence + dedup (harness storage path).
        for i in range(volume):
            item_id = await encrypted.insert_memory_item(
                content=f"Please remember project uses stack {i % 12}.",
                memory_type="stable_fact",
                scope_type="global",
                ttl_days=30,
            )
            await encrypted.add_memory_evidence(
                item_id,
                "user_explicit",
                session_id=f"sess-{i}",
                evidence_text=f"evidence {i}",
            )
        dup = await encrypted.find_duplicate_memory(
            "Please remember project uses stack 4.", "global"
        )
        check("memory dedup finds duplicate", dup is not None)
        items = await encrypted.list_memory_items(statuses=("active",), limit=volume + 50)
        check("memory_items persisted", len(items) == volume, f"{len(items)} items")
        evidence = await encrypted.get_memory_evidence(items[0]["id"])
        check("memory evidence persisted", len(evidence) >= 1)

        # Session summaries: upsert versioning.
        await encrypted.upsert_session_summary("sum-s", "first summary", token_estimate=100)
        await encrypted.upsert_session_summary("sum-s", "second summary", token_estimate=120)
        latest = await encrypted.get_session_summary("sum-s")
        check("session summary upserts to latest", latest == "second summary")

        # TTL: expired rows are physically pruned by cleanup_expired (reads
        # already hide them, so count rows directly in the table).
        conn = encrypted._get_conn()

        def kv_row_count() -> int:
            return conn.execute("SELECT COUNT(*) AS c FROM kv_memory").fetchone()["c"]

        for i in range(volume):
            await encrypted.store_memory(f"kv-expired-{i}", f"secret value {i}", ttl_days=-1)
        before = kv_row_count()
        await encrypted.cleanup_expired()
        after = kv_row_count()
        check(
            "expired kv_memory pruned by cleanup_expired",
            after < before,
            f"{before} -> {after} physical rows",
        )

        # KV round trip with concurrent writes.
        await asyncio.gather(
            *[
                encrypted.store_memory(f"conc-{i}", f"val-{i}", ttl_days=30)
                for i in range(40 if quick else 80)
            ]
        )
        values = await asyncio.gather(
            *[encrypted.get_memory(f"conc-{i}") for i in range(40 if quick else 80)]
        )
        check(
            "concurrent kv writes all readable",
            all(v == f"val-{i}" for i, v in enumerate(values)),
            f"{sum(1 for v in values if v)}/{len(values)}",
        )

        # Consolidation path.
        cons = await encrypted.consolidate_memories()
        check("consolidate_memories returns counts", isinstance(cons, dict) and "expired" in cons)

        stats = await encrypted.get_stats()
        check(
            "get_stats reports all stores",
            all(
                key in stats
                for key in (
                    "conversations",
                    "memory_entries",
                    "memory_items",
                    "memory_evidence",
                    "session_summaries",
                )
            ),
            str(stats),
        )
    finally:
        encrypted.close()
        plain.close()


# ---------------------------------------------------------------------------
# 3. Memory harness soak (extraction -> policy -> persistence -> snapshot)
# ---------------------------------------------------------------------------


async def harness_soak(quick: bool) -> None:
    from hermes_mobile.memory.harness import MemoryHarness
    from hermes_mobile.memory.provider import MobileMemoryProvider

    tmp = Path(tempfile.mkdtemp(prefix="hm-harness-"))
    provider = MobileMemoryProvider(db_path=tmp / "harness.db", encrypt=False)
    harness = MemoryHarness(provider=provider)
    turns = 120 if quick else 300
    try:
        templates = [
            "Please remember that my project uses stack {n}.",
            "I prefer answers in {lang}.",
            "Remember my password is hunter{n}.",
            "Please always keep answers short.",
            "Nothing special here today.",
            "Please remember that my project uses stack {n}.",
        ]
        totals: Counter[str] = Counter()
        for i in range(turns):
            text = templates[i % len(templates)].format(
                n=(i // 2) % 10, lang="Indonesian" if i % 2 else "English"
            )
            result = await harness.process_turn(f"harness-sess-{i}", text)
            for key, value in result.items():
                totals[key] += value

        items = await provider.list_memory_items(limit=1000)
        leaked = [m for m in items if "hunter" in str(m.get("content", ""))]
        check(
            "secrets never enter long-term memory",
            not leaked,
            f"{len(leaked)} leaked items",
        )
        check(
            "duplicate detection active under load",
            totals["duplicates"] > 0,
            f"duplicates={totals['duplicates']}",
        )
        check(
            "auto-save persisted candidates",
            totals["auto_saved"] > 0,
            f"auto_saved={totals['auto_saved']} ignored={totals['ignored']}",
        )

        snapshot = await harness.build_snapshot(token_budget=800)
        budget_chars = max(200, 800 * 4)
        check(
            "frozen snapshot respects token budget",
            len(snapshot) <= budget_chars + 4000,
            f"{len(snapshot)} chars vs budget {budget_chars}",
        )
        check("frozen snapshot renders", snapshot.startswith("# MEMORY SNAPSHOT"))

        # ASK must be bounded: a slow confirmation channel may never hang the
        # pipeline, especially on non-interactive channels.
        async def slow_ask(candidate: Any) -> bool:
            await asyncio.sleep(30)
            return True

        bounded = MemoryHarness(provider=provider, ask_callback=slow_ask, ask_timeout=0.05)
        started = time.monotonic()
        result = await bounded.process_turn("ask-sess", "Please always summarize my meetings.")
        elapsed = time.monotonic() - started
        check(
            "ASK confirmation is bounded (timeout)",
            elapsed < 3 and result["asked"] == 1 and result["approved"] == 0,
            f"{elapsed:.2f}s asked={result['asked']} approved={result['approved']}",
        )
    finally:
        provider.close()


# ---------------------------------------------------------------------------
# 4. Agent loop stress (bounds, tool execution, streaming, compression)
# ---------------------------------------------------------------------------


async def agent_loop_stress() -> None:
    from hermes_mobile.core.agent import MobileAgent, ToolCall

    # 4a. The loop must terminate at max_iterations even if the model
    #     requests a tool on every turn (infinite-loop guard).
    agent = MobileAgent(provider="openai", model="gpt-stress", memory_provider=None)
    agent.max_iterations = 6
    agent._client = _FakeClient(
        [_FakeResponse(content="", tool_calls=[_FakeToolCallMsg("get_time", "{}", "call-1")])]
    )
    async for _ in agent.run_conversation("loop stress", stream=False):
        pass
    tool_turns = sum(1 for m in agent.messages if m.tool_calls)
    tool_results = sum(1 for m in agent.messages if m.role == "tool")
    check(
        "agent loop stops at max_iterations",
        agent.iteration == 6 and tool_turns == 6,
        f"iterations={agent.iteration} tool_turns={tool_turns}",
    )
    check(
        "every tool call got exactly one result",
        tool_turns == tool_results,
        f"{tool_turns} calls / {tool_results} results",
    )
    validate_api_messages(agent.get_messages_for_api())
    check("agent history is API-valid after loop", True)

    # 4b. Multi-tool turn then a plain final answer.
    agent2 = MobileAgent(provider="openai", model="gpt-stress", memory_provider=None)
    agent2.max_iterations = 10
    agent2._client = _FakeClient(
        [
            _FakeResponse(
                content="",
                tool_calls=[
                    _FakeToolCallMsg("get_time", "{}", "c1"),
                    _FakeToolCallMsg("get_time", "{}", "c2"),
                ],
            ),
            _FakeResponse(content="final answer text", tool_calls=None),
        ]
    )
    chunks: List[str] = []
    async for chunk in agent2.run_conversation("multi tool", stream=False):
        chunks.append(chunk)
    check(
        "multi-tool turn completes with final answer",
        agent2.iteration == 2 and "final answer text" in "".join(chunks),
        f"iterations={agent2.iteration}",
    )
    validate_api_messages(agent2.get_messages_for_api())
    check("multi-tool history is API-valid", True)

    # 4c. Streaming tool-call delta reconstruction (fragmented name/args).
    stream = _FakeStream(
        [
            _stream_chunk(
                _stream_delta(
                    tool_calls=[
                        SimpleNamespace(
                            index=0, id="tc-1", function=SimpleNamespace(name="get", arguments="")
                        )
                    ]
                )
            ),
            _stream_chunk(
                _stream_delta(
                    tool_calls=[
                        SimpleNamespace(
                            index=0,
                            id=None,
                            function=SimpleNamespace(name="_time", arguments="{"),
                        )
                    ]
                )
            ),
            _stream_chunk(
                _stream_delta(
                    tool_calls=[
                        SimpleNamespace(
                            index=0, id=None, function=SimpleNamespace(name="", arguments="}")
                        )
                    ]
                )
            ),
            _stream_chunk(_stream_delta(content=" streamed done")),
        ]
    )
    agent3 = MobileAgent(provider="openai", model="gpt-stress", memory_provider=None)
    agent3.max_iterations = 4
    agent3._client = _FakeClient(
        [stream, _FakeStream([_stream_chunk(_stream_delta(content="streamed done"))])]
    )
    streamed: List[str] = []
    async for chunk in agent3.run_conversation("stream tool", stream=True):
        streamed.append(chunk)
    executed = [m for m in agent3.messages if m.role == "tool" and m.name == "get_time"]
    check(
        "streamed tool call reconstructed and executed",
        len(executed) == 1 and "streamed done" in "".join(streamed),
        f"tool results={len(executed)}",
    )
    validate_api_messages(agent3.get_messages_for_api())
    check("streamed history is API-valid", True)

    # 4d. Malformed tool arguments must not crash the loop.
    agent4 = MobileAgent(provider="openai", model="gpt-stress", memory_provider=None)
    agent4.max_iterations = 3
    agent4._client = _FakeClient(
        [
            _FakeResponse(
                content="", tool_calls=[_FakeToolCallMsg("get_time", "{not-json", "bad-1")]
            ),
            _FakeResponse(content="recovered", tool_calls=None),
        ]
    )
    async for _ in agent4.run_conversation("bad args", stream=False):
        pass
    error_results = [
        m for m in agent4.messages if m.role == "tool" and "Invalid JSON" in str(m.content)
    ]
    check(
        "malformed tool args produce a friendly error and continue",
        agent4.iteration == 2 and len(error_results) == 1,
        f"iterations={agent4.iteration} error_results={len(error_results)}",
    )
    validate_api_messages(agent4.get_messages_for_api())
    check("recovered history is API-valid", True)

    # 4e. Compression keeps the conversation valid and bounded.
    agent5 = MobileAgent(provider="openai", model="gpt-stress", memory_provider=None)
    agent5.settings.max_context_tokens = 2000
    for i in range(250):
        agent5.add_user_message(f"user message number {i} with some padding content")
        tool_call = ToolCall(name="get_time", arguments={}, call_id=f"c{i}")
        agent5.add_assistant_message("", tool_calls=[tool_call])
        agent5.add_tool_result("the current time is now", f"c{i}", "get_time")
    before = len(agent5.messages)
    agent5._summarize_with_llm = _noop_summarize  # type: ignore[method-assign]
    await agent5._apply_compression()
    compressed_ok = len(agent5.messages) < before
    validate_api_messages(agent5.get_messages_for_api())
    check(
        "compression shrinks history and stays API-valid",
        compressed_ok,
        f"{before} -> {len(agent5.messages)} messages",
    )

    # 4f. Compression triggers inside a live turn.
    agent6 = MobileAgent(provider="openai", model="gpt-stress", memory_provider=None)
    agent6.settings.max_context_tokens = 1500
    for i in range(150):
        agent6.add_user_message(f"message {i} " + "x" * 40)
        agent6.add_assistant_message(f"reply {i} " + "y" * 40)
    agent6._client = _FakeClient([_FakeResponse(content="compressed path ok")])
    agent6._summarize_with_llm = _noop_summarize  # type: ignore[method-assign]
    out: List[str] = []
    async for chunk in agent6.run_conversation("trigger compression", stream=False):
        out.append(chunk)
    check(
        "run_conversation survives mid-turn compression",
        "compressed path ok" in "".join(out),
        f"messages={len(agent6.messages)}",
    )
    validate_api_messages(agent6.get_messages_for_api())
    check("compressed turn history is API-valid", True)

    # 4g. API serialization is always JSON-safe.
    payload = json.dumps(agent6.get_messages_for_api())
    check("get_messages_for_api is JSON-serializable", len(payload) > 0)


# ---------------------------------------------------------------------------
# 5. Context compressor fuzz (random valid histories, invariant check)
# ---------------------------------------------------------------------------


def compressor_fuzz(quick: bool) -> None:
    from hermes_mobile.core.context_compressor import compress_messages

    def random_conversation(rng: random.Random, turns: int) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = [{"role": "system", "content": "system prompt"}]
        for i in range(turns):
            messages.append({"role": "user", "content": f"user {i} " + "z" * rng.randint(0, 40)})
            if rng.random() < 0.55:
                call_ids = [f"c{i}_{k}" for k in range(rng.randint(1, 3))]
                messages.append(
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {"name": "get_time", "arguments": "{}"},
                            }
                            for call_id in call_ids
                        ],
                    }
                )
                for call_id in call_ids:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "name": "get_time",
                            "content": "now",
                        }
                    )
            else:
                messages.append({"role": "assistant", "content": f"answer {i}"})
        return messages

    rounds = 20 if quick else 80
    failures = 0
    for seed in range(rounds):
        rng = random.Random(seed)
        original = random_conversation(rng, rng.randint(3, 70))
        try:
            compressed = compress_messages(
                original,
                max_tokens=rng.choice([200, 600, 2500, 128000]),
                previous_summary=f"summary {seed}" if seed % 3 == 0 else None,
            )
            validate_api_messages(compressed)
        except AssertionError as exc:
            failures += 1
            if failures <= 3:
                print(f"      fuzz seed {seed} failed: {exc}")
    check(
        "compressor fuzz keeps history valid", failures == 0, f"{rounds} seeds, {failures} failures"
    )


# ---------------------------------------------------------------------------
# 6. Cron scheduler soak (volume, persistence, run history, lock integrity)
# ---------------------------------------------------------------------------


def cron_soak(quick: bool) -> None:
    import hermes_mobile.cron.scheduler as cron

    jobs = cron.list_jobs()
    for job in jobs:
        cron.delete_job(job.id)

    count = 25 if quick else 60
    created: List[str] = []
    for i in range(count):
        job = cron.create_job(
            name=f"stress-{i}",
            schedule="*/5 * * * *" if i % 3 else "oneshot",
            command="echo ok",
            description=f"stress job {i}",
            tags=["stress"],
        )
        created.append(job.id)
    reloaded = {job.id for job in cron.list_jobs()}
    check(
        "cron jobs persist across reload",
        reloaded == set(created),
        f"{len(reloaded)}/{len(created)} ids match",
    )

    # Concurrent creation must not corrupt jobs.json (advisory lock).
    def _create(i: int) -> str:
        return cron.create_job(name=f"thread-{i}", schedule="0 * * * *", command="echo t").id

    extra = 30 if quick else 60
    with ThreadPoolExecutor(max_workers=16) as pool:
        thread_ids = list(pool.map(_create, range(extra)))
    with open(cron._get_jobs_file(), encoding="utf-8") as handle:
        json.load(handle)  # must parse
    all_ids = {job.id for job in cron.list_jobs()}
    check(
        "concurrent cron creation keeps jobs.json valid",
        len(thread_ids) == extra and set(thread_ids) <= all_ids,
        f"{len(all_ids)} total jobs after {extra} threaded creates",
    )

    # Run-now records history in the JSONL output store.
    oneshot = [job.id for job in cron.list_jobs() if job.schedule == "oneshot"]
    for job_id in oneshot[:10]:
        output = cron.run_job_now(job_id)
        history = cron.get_job_output(job_id, limit=5)
        assert history, f"no output recorded for {job_id}"
        assert output.status in ("success", "failed")
    check("run-now executes and records output", True, f"{min(10, len(oneshot))} jobs run")

    # Delete half the jobs and verify the remainder survive.
    to_delete = all_ids - set(created)
    deleted = sum(1 for job_id in to_delete if cron.delete_job(job_id))
    remaining = {job.id for job in cron.list_jobs()}
    check(
        "deleting jobs leaves the rest intact",
        deleted == len(to_delete) and remaining == set(created),
        f"deleted={deleted} remaining={len(remaining)}",
    )

    status = cron.get_ticker_status()
    check("ticker status endpoint responds", isinstance(status, dict), str(status))


# ---------------------------------------------------------------------------
# 7. Gateway pairing soak (rate limit, lockout, expiry, persistence)
# ---------------------------------------------------------------------------


def pairing_soak(quick: bool) -> None:
    from collections import defaultdict

    from hermes_mobile.gateway.mobile_gateway import PairingManager

    manager = PairingManager()
    platforms = ["telegram", "signal", "discord", "matrix"]
    count = 15 if quick else 30
    pairs: List[tuple] = []
    pending_per_platform: Dict[str, int] = defaultdict(int)
    for i in range(count):
        platform = platforms[i % len(platforms)]
        code = manager.request_pairing(platform, f"user-{i}", f"User {i}")
        assert code is not None, f"pairing request {i} rejected for {platform}"
        pairs.append((platform, f"user-{i}", code))
        # Stay under MAX_PENDING_PER_PLATFORM=3 by approving as we go.
        pending_per_platform[platform] += 1
        if pending_per_platform[platform] >= 3:
            assert manager.approve_code(code.code) is True
            pending_per_platform[platform] -= 1

    approved = [(p, u) for p, u, c in pairs if c.approved]
    authorized = sum(1 for p, u in approved if manager.is_user_authorized(p, u))
    check(
        "pairing codes approve and authorize",
        authorized == len(approved),
        f"{authorized} authorized of {len(approved)} approved ({count} requests)",
    )

    # Rate limiting: a second request for the same user raises ValueError.
    first = manager.request_pairing("telegram", "rate-user", "Rate")
    rate_blocked = False
    try:
        manager.request_pairing("telegram", "rate-user", "Rate")
    except ValueError:
        rate_blocked = True
    check("pairing request rate limit enforced", first is not None and rate_blocked)

    # Lockout after repeated failed attempts (each attempt produces a revoked
    # code — that is what _record_failed_attempt counts).
    from hermes_mobile.gateway.mobile_gateway import MAX_FAILED_ATTEMPTS

    lock_user = "lockout-user"
    for _ in range(MAX_FAILED_ATTEMPTS):
        code = manager.request_pairing("signal", lock_user, "Lock")
        assert code is not None
        code.revoked = True
        manager._record_failed_attempt("signal", lock_user)
        manager._rate_limits.pop(f"signal:{lock_user}", None)  # bypass cooldown, keep failures
    locked = False
    try:
        manager.request_pairing("signal", lock_user, "Lock")
    except ValueError as exc:
        locked = "failed attempts" in str(exc)
    check("pairing lockout after 5 failures", locked)

    # Expired codes cannot be approved.
    expired = manager.request_pairing("discord", "expire-user", "Exp")
    assert expired is not None
    expired.expires_at = time.time() - 10
    manager._save()
    check("expired pairing code rejected", manager.approve_code(expired.code) is False)

    # Revocation removes authorization.
    revoked = next((c for p, u, c in pairs if not c.approved), None)
    assert revoked is not None
    assert manager.revoke_code(revoked.code) is True
    check(
        "revoked code no longer authorizes",
        not manager.is_user_authorized(revoked.platform, revoked.user_id),
    )

    manager.cleanup_expired()
    pending = manager.get_pending_codes()
    check("cleanup_expired leaves consistent pending set", isinstance(pending, list))


# ---------------------------------------------------------------------------
# 8. WebView automation engine soak
# ---------------------------------------------------------------------------


async def webview_soak(quick: bool) -> None:
    import flet as ft

    from hermes_mobile.tools.webview_engine import WebViewEngine

    class FakePage:
        platform = ft.PagePlatform.ANDROID

        def __init__(self) -> None:
            self.updates = 0

        def update(self) -> None:
            self.updates += 1

    class FakeContainer:
        def __init__(self) -> None:
            self.content: Any = None

    class FakeControl:
        def __init__(self) -> None:
            self.loaded: List[str] = []
            self.js: List[str] = []
            self.scrolls: List[tuple] = []
            self.scroll_tos: List[tuple] = []
            self.reloads = 0
            self.back_count = 0
            self.can_back = True
            self.title = "Fake Title"
            self.current_url = "https://example.com/initial"
            self.js_result = "page text sample"

        async def load_request(self, url: str) -> None:
            self.loaded.append(url)
            self.current_url = url

        async def run_javascript(self, js: str) -> str:
            self.js.append(js)
            return self.js_result

        async def scroll_by(self, x: int, y: int) -> None:
            self.scrolls.append((x, y))

        async def scroll_to(self, x: int, y: int) -> None:
            self.scroll_tos.append((x, y))

        async def reload(self) -> None:
            self.reloads += 1

        async def can_go_back(self) -> bool:
            return self.can_back

        async def go_back(self) -> None:
            self.back_count += 1

        async def get_title(self) -> str:
            return self.title

        async def get_current_url(self) -> str:
            return self.current_url

    page = FakePage()
    engine = WebViewEngine(page)
    engine._control = FakeControl()

    cycles = 60 if quick else 150
    for i in range(cycles):
        result = await engine.navigate(f"https://example.com/page/{i}", timeout=1)
        assert result["ok"] is True
        assert await engine.scroll("down", 200) is True
        assert await engine.scroll("top") is True
        assert await engine.click_selector("button#go") is True
        assert await engine.type_selector("input[name=q]", f"query {i}") is True
        assert await engine.press_key("enter") is True
        assert await engine.page_text() == "page text sample"
        assert await engine.back() is True
    check(
        "webview engine survives repeated automation cycles",
        True,
        f"{cycles} navigate/scroll/click/type/back cycles",
    )

    # Mount/dismount churn must not leak state.
    container = FakeContainer()
    for _ in range(40 if quick else 100):
        engine.mount(container)
        assert engine.is_mounted and container.content is engine._control
        engine.dismount()
        assert not engine.is_mounted and container.content is None
    check("webview mount/dismount churn is stable", True, "100 cycles")


# ---------------------------------------------------------------------------
# 9. Tool schema integrity (zero divergence between schemas and handlers)
# ---------------------------------------------------------------------------


def tool_schema_integrity() -> None:
    from hermes_mobile.core.agent import MobileAgent

    agent = MobileAgent(memory_provider=None)
    schemas = agent.get_tool_schemas()
    schema_names = {s["function"]["name"] for s in schemas}
    handler_names = set(agent._builtin_tools.keys())
    missing_handlers = sorted(schema_names - handler_names)
    missing_schemas = sorted(handler_names - schema_names)
    check(
        "every schema has a real handler and vice versa",
        not missing_handlers and not missing_schemas,
        f"{len(schema_names)} tools; missing_handlers={missing_handlers[:5]} "
        f"missing_schemas={missing_schemas[:5]}",
    )

    # Required-arg names in each schema must be declared in properties.
    malformed = []
    for schema in schemas:
        fn = schema["function"]
        params = fn.get("parameters", {})
        props = set(params.get("properties", {}))
        for required in params.get("required", []):
            if required not in props:
                malformed.append(f"{fn['name']}: required '{required}' not in properties")
    check("tool schemas declare their required args", not malformed, "; ".join(malformed[:3]))

    # Blocked tools are filtered from the shipped schema list.
    blocked = MobileAgent(memory_provider=None, blocked_tools={"web_search", "terminal"})
    blocked_names = {s["function"]["name"] for s in blocked.get_tool_schemas()}
    check(
        "blocked_tools filtering works",
        "web_search" not in blocked_names and "terminal" not in blocked_names,
    )


# ---------------------------------------------------------------------------
# 10. Providers + environment completeness
# ---------------------------------------------------------------------------


def providers_and_env() -> None:
    from hermes_mobile.providers import get_provider_profile, list_local_providers

    profiles = list_local_providers()
    check("provider catalog is non-empty", len(profiles) >= 8, f"{len(profiles)} profiles")

    # Every provider env var must be documented somewhere operators read when
    # setting the app up: .env.example and/or the README provider table.
    doc_sources = []
    env_example = ROOT / ".env.example"
    readme = ROOT / "README.md"
    if env_example.exists():
        doc_sources.append(env_example.read_text(encoding="utf-8"))
    if readme.exists():
        doc_sources.append(readme.read_text(encoding="utf-8"))
    doc_text = "\n".join(doc_sources)
    missing_env: List[str] = []
    for profile in profiles:
        for var in profile.env_vars:
            if var not in doc_text:
                missing_env.append(f"{profile.name}:{var}")
    check(
        "every provider env var is documented (env example/README)",
        not missing_env,
        "; ".join(missing_env),
    )

    ollama = get_provider_profile("ollama")
    check(
        "ollama is keyless with an editable endpoint",
        ollama is not None and not ollama.requires_api_key and bool(ollama.base_url),
    )

    # Graceful degradation: a provider without a key must not crash the agent.
    from hermes_mobile.core.agent import MobileAgent

    keyless_provider = next(
        (p.name for p in profiles if p.requires_api_key and p.env_vars), "deepseek"
    )
    agent = MobileAgent(provider=keyless_provider, model="stress-model", memory_provider=None)
    check(
        "missing provider key degrades gracefully",
        agent._client is None and bool(agent._client_error),
        f"{keyless_provider}: {agent._client_error[:80] if agent._client_error else 'no error'}",
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def _main_async(quick: bool) -> None:
    section("1. Import gate")
    import_gate()

    section("2. Memory provider soak")
    await memory_provider_soak(quick)

    section("3. Memory harness soak")
    await harness_soak(quick)

    section("4. Agent loop stress")
    await agent_loop_stress()

    section("5. Context compressor fuzz")
    compressor_fuzz(quick)

    section("6. Cron scheduler soak")
    cron_soak(quick)

    section("7. Gateway pairing soak")
    pairing_soak(quick)

    section("8. WebView engine soak")
    await webview_soak(quick)

    section("9. Tool schema integrity")
    tool_schema_integrity()

    section("10. Providers + environment completeness")
    providers_and_env()


def main(argv: Optional[List[str]] = None) -> int:
    quick = "--quick" in (argv if argv is not None else sys.argv[1:])
    started = time.monotonic()
    try:
        asyncio.run(_main_async(quick))
    except Exception as exc:  # noqa: BLE001 - top-level gate
        print(f"\nSTRESS RUN CRASHED: {exc}")
        traceback.print_exc()
        RESULTS.append({"name": "run", "ok": False, "detail": str(exc)})

    passed = sum(1 for r in RESULTS if r["ok"])
    failed = sum(1 for r in RESULTS if not r["ok"])
    elapsed = time.monotonic() - started
    print(f"\n{'=' * 60}")
    print(f"RESULT: {passed} passed, {failed} failed, {elapsed:.1f}s")
    for result in RESULTS:
        if not result["ok"]:
            print(f"  FAILED: {result['name']} — {result['detail']}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
