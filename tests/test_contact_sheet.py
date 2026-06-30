"""Tests for contact-sheet — thumbnail extraction + CLI guards."""
from __future__ import annotations

from typing import Any

import pytest

from frameio_agent import contact_sheet as cs


class TestExtractThumbnailUrl:
    def test_media_links_nested_dict(self) -> None:
        meta = {"media_links": {"thumbnail": {"download_url": "https://x/y.jpg"}}}
        assert cs._extract_thumbnail_url(meta) == "https://x/y.jpg"

    def test_media_links_alt_key(self) -> None:
        meta = {"media_links": {"poster": {"url": "https://x/p.jpg"}}}
        assert cs._extract_thumbnail_url(meta) == "https://x/p.jpg"

    def test_media_links_string(self) -> None:
        meta = {"media_links": {"thumb": "https://x/t.jpg"}}
        assert cs._extract_thumbnail_url(meta) == "https://x/t.jpg"

    def test_top_level_thumbnail(self) -> None:
        meta = {"thumbnail": "https://x/t.jpg"}
        assert cs._extract_thumbnail_url(meta) == "https://x/t.jpg"

    def test_missing_returns_none(self) -> None:
        meta = {"id": "f1", "name": "x.mp4"}
        assert cs._extract_thumbnail_url(meta) is None


class TestCmdContactSheetGuards:
    def _emit(self, captured: list[Any]):
        def emit(p: Any, j: bool) -> None: captured.append((p, j))
        return emit

    def test_neither_project_nor_folder_refused(self, tmp_path) -> None:
        rc = cs.cmd_contact_sheet(
            project=None, folder=None, out=str(tmp_path / "out.png"),
            cols=4, tile_size=120, max_files=50, no_labels=False, parallel=4,
            as_json=False, emit=self._emit([]),
        )
        assert rc == 2
