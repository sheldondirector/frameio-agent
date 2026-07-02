"""Tests for `frames pull` — filename sanitization + CLI guards."""
from __future__ import annotations

from typing import Any

import pytest

from frameio_agent import frames


class TestSafeName:
    def test_plain(self) -> None:
        assert frames._safe_name("clip") == "clip"

    def test_spaces_and_specials(self) -> None:
        assert frames._safe_name("0506 CLIP 4_Reliable!.mp4") == "0506_CLIP_4_Reliable"

    def test_extension_dropped(self) -> None:
        assert "." not in frames._safe_name("shot.v2.final.mov").replace("_", "")

    def test_path_separators_neutralized(self) -> None:
        out = frames._safe_name("../../etc/passwd")
        assert "/" not in out and "\\" not in out and ".." not in out

    def test_empty_falls_back(self) -> None:
        assert frames._safe_name("") == "frame"
        assert frames._safe_name("...") == "frame"

    def test_truncated_to_max(self) -> None:
        assert len(frames._safe_name("x" * 200)) <= 40

    def test_unicode_stripped(self) -> None:
        out = frames._safe_name("镜头_04 final")
        assert out  # non-empty, ASCII-safe
        assert all(ord(c) < 128 for c in out)


class TestCmdFramesPullGuards:
    def _emit(self, captured: list[Any]):
        def emit(p: Any, j: bool) -> None: captured.append((p, j))
        return emit

    def test_neither_project_nor_folder_refused(self, tmp_path) -> None:
        rc = frames.cmd_frames_pull(
            project=None, folder=None, out=str(tmp_path / "frames"),
            max_files=50, parallel=4, as_json=False, emit=self._emit([]),
        )
        assert rc == 2
