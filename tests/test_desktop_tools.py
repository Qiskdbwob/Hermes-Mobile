"""Tests for desktop-parity tools (search size caps, code execution)."""

from __future__ import annotations

import pytest

from hermes_mobile.tools.desktop_tools import MAX_FILE_BYTES, search_files_tool


@pytest.mark.asyncio
async def test_search_content_skips_files_over_size_cap(tmp_path, monkeypatch):
    # The sandbox only allows paths under get_allowed_directories(); let the
    # search work on the temp directory for this test.
    monkeypatch.setattr(
        "hermes_mobile.tools.path_security.get_allowed_directories",
        lambda: [tmp_path],
    )

    small = tmp_path / "small.txt"
    small.write_text("needle found here")
    big = tmp_path / "big.txt"
    big.write_text("needle in big file\n" + "x" * (MAX_FILE_BYTES + 10))

    result = await search_files_tool(pattern="needle", path=str(tmp_path))

    assert "error" not in result
    paths = [m["path"] for m in result["matches"]]
    assert str(small) in paths
    assert str(big) not in paths
