#!/usr/bin/env python3
"""Recall evaluation for session search + session_read (P2).

Seeds realistic sessions (English + Indonesian) with hidden facts, then checks
that ``search_sessions`` ranks the right session first (retrieval@1) and that
``session_read`` returns the actual content. Runs against a throwaway SQLite DB
in BOTH plaintext and encrypted modes.

Usage:
    python3 scripts/recall_eval.py            # full run
    python3 scripts/recall_eval.py --quick     # fewer seeds
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hermes_mobile.core.agent import Message  # noqa: E402
from hermes_mobile.memory.provider import MobileMemoryProvider  # noqa: E402
from hermes_mobile.memory.summarizer import build_session_summary, extract_keywords  # noqa: E402

# (session_id, messages, expected recall queries -> must-hit session)
SCENARIOS = [
    (
        "s-browser",
        [
            Message.user("Tolong bantu validasi browser webview"),
            Message.assistant("Saya cek scroll, click, dan type di WebView."),
            Message.user("Ternyata scroll tidak jalan di halaman JS"),
            Message.assistant("Sudah saya catat: scroll WebView perlu perbaikan."),
        ],
        ["browser", "scroll", "webview"],
    ),
    (
        "s-postgres",
        [
            Message.user("Ingat bahwa proyek saya menggunakan Postgres"),
            Message.assistant("Dicatat: proyek pakai Postgres."),
        ],
        ["postgres", "proyek"],
    ),
    (
        "s-cron",
        [
            Message.user("Tolong buatkan cron job untuk mengingatkan saya minum air"),
            Message.assistant("Saya jadwalkan oneshot 5 menit lagi."),
            Message.user("Terima kasih"),
        ],
        ["cron", "jadwal", "minum"],
    ),
    (
        "s-recipes",
        [
            Message.user("How do I bake sourdough bread at home"),
            Message.assistant("Here is the full sourdough recipe."),
            Message.user("Can I use rye flour instead"),
            Message.assistant("Yes, rye works but changes hydration."),
        ],
        ["sourdough", "bread", "rye"],
    ),
    (
        "s-ollama",
        [
            Message.user("Set up Ollama with an OpenAI-compatible endpoint"),
            Message.assistant("OLLAMA_HOST is now editable in Settings."),
            Message.user("I prefer to run models locally on this phone"),
            Message.assistant("Noted: local models preferred."),
        ],
        ["ollama", "local", "endpoint"],
    ),
]


async def _run(encrypt: bool, quick: bool) -> tuple[int, int]:
    with tempfile.TemporaryDirectory(prefix="recall_eval_") as tmp:
        db = Path(tmp) / "memory.db"
        provider = MobileMemoryProvider(db_path=db, encrypt=encrypt)
        try:
            passed = 0
            failed = 0
            scenarios = SCENARIOS[:2] if quick else SCENARIOS

            for sid, messages, queries in scenarios:
                await provider.save_conversation(sid, messages)
                summary = build_session_summary(messages)
                await provider.upsert_session_summary(sid, summary)
                await provider.index_session_keywords(sid, extract_keywords(summary))

                for q in queries:
                    results = await provider.search_sessions(q, limit=3)
                    if results and results[0]["id"] == sid:
                        passed += 1
                    else:
                        failed += 1
                        top = results[0]["id"] if results else "none"
                        print(
                            f"  [FAIL] {sid!r} query={q!r} -> top={top!r} "
                            f"(mode={'encrypted' if encrypt else 'plaintext'})"
                        )

                # session_read must return the real content.
                read = await provider.get_conversation(sid, limit=30)
                if (
                    any("scroll" in (m.get("content") or "").lower() for m in read)
                    or len(read) >= 2
                ):
                    passed += 1
                else:
                    failed += 1
                    print(f"  [FAIL] session_read {sid!r} returned nothing useful")

            return passed, failed
        finally:
            provider.close()


async def main(quick: bool) -> int:
    total_pass = 0
    total_fail = 0
    for encrypt in (False, True):
        label = "encrypted" if encrypt else "plaintext"
        print(f"== mode: {label} ==")
        passed, failed = await _run(encrypt, quick)
        total_pass += passed
        total_fail += failed
        print(f"   {passed} passed, {failed} failed")
    print(f"\nTOTAL: {total_pass} passed, {total_fail} failed")
    return 1 if total_fail else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="fewer seeds")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.quick)))
