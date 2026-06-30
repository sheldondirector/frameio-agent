"""Unit tests for the account-wide search command."""
from __future__ import annotations

from typing import Any

import pytest

from frameio_agent import search as search_mod


class TestNormalizeSearchResult:
    def test_file_result(self) -> None:
        raw = {
            "type": "file_result",
            "result": {
                "id": "f1",
                "name": "rough_cut_v4.mov",
                "type": "file",
                "project_id": "p1",
                "parent_id": "fld1",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-02-01T00:00:00Z",
                "view_url": "https://next.frame.io/project/p1/view/f1",
            },
            "matches": [{"name": "rough_cut_v4.mov", "terms": ["rough"], "type": "name_match"}],
        }
        out = search_mod._normalize_search_result(raw)
        assert out["id"] == "f1"
        assert out["name"] == "rough_cut_v4.mov"
        assert out["type"] == "file"
        assert out["project_id"] == "p1"
        assert out["view_url"].startswith("https://next.frame.io/")
        assert len(out["matches"]) == 1

    def test_version_stack_result(self) -> None:
        raw = {
            "result": {"id": "v1", "name": "Cut", "type": "version_stack", "project_id": "p1"},
            "matches": [],
        }
        out = search_mod._normalize_search_result(raw)
        assert out["type"] == "version_stack"
        assert out["matches"] == []

    def test_missing_result_block_safe(self) -> None:
        raw = {"matches": []}  # malformed
        out = search_mod._normalize_search_result(raw)
        assert out["id"] is None
        assert out["matches"] == []


class TestCmdSearchGuards:
    def _emit(self, captured: list[Any]):
        def emit(p: Any, j: bool) -> None: captured.append((p, j))
        return emit

    def test_empty_query_refused(self) -> None:
        rc = search_mod.cmd_search(
            query="  ", engine="lexical", files=True, folders=True, projects=True,
            limit=10, account=None, as_json=False, emit=self._emit([]),
        )
        assert rc == 2

    def test_bad_engine_refused(self) -> None:
        rc = search_mod.cmd_search(
            query="x", engine="fuzzy", files=True, folders=True, projects=True,
            limit=10, account=None, as_json=False, emit=self._emit([]),
        )
        assert rc == 2

    def test_no_filters_refused(self) -> None:
        rc = search_mod.cmd_search(
            query="x", engine="lexical", files=False, folders=False, projects=False,
            limit=10, account=None, as_json=False, emit=self._emit([]),
        )
        assert rc == 2
