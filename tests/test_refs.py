"""Tests for `refs add` — mode detection, name derivation, confirmation guards."""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from frameio_agent import refs


class _FakeTTY(io.StringIO):
    def __init__(self, text: str = "", tty: bool = True) -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


class TestDetectMode:
    @pytest.mark.parametrize("url", [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://vimeo.com/123",
        "https://x.com/foo/status/1",
        "https://twitter.com/foo/status/1",
        "https://www.tiktok.com/@user/video/1",
        "https://www.instagram.com/p/abc/",
    ])
    def test_streaming_urls_use_yt_dlp(self, url: str) -> None:
        assert refs._detect_mode(url, None) == "yt_dlp"

    @pytest.mark.parametrize("url", [
        "https://example.com/clip.mp4",
        "https://cdn.example.com/path/to/file.mov",
        "https://my-bucket.s3.amazonaws.com/asset.mp4",
    ])
    def test_direct_urls_use_remote_upload(self, url: str) -> None:
        assert refs._detect_mode(url, None) == "remote_upload"

    def test_local_path(self) -> None:
        assert refs._detect_mode("/tmp/file.mp4", None) == "local"
        assert refs._detect_mode("./file.mp4", None) == "local"
        assert refs._detect_mode("C:\\Users\\me\\file.mp4", None) == "local"

    def test_via_override(self) -> None:
        assert refs._detect_mode("https://youtube.com/watch?v=x", "remote_upload") == "remote_upload"
        assert refs._detect_mode("/tmp/file.mp4", "yt_dlp") == "yt_dlp"


class TestDefaultNameFromSource:
    def test_local_filename(self) -> None:
        assert refs._default_name_from_source("/path/to/file.mp4", "local") == "file.mp4"

    def test_url_last_segment(self) -> None:
        assert refs._default_name_from_source("https://example.com/x/clip.mov", "remote_upload") == "clip.mov"

    def test_url_no_path_falls_back_to_host(self) -> None:
        assert refs._default_name_from_source("https://example.com/", "remote_upload") == "example.com"

    def test_empty_falls_back(self) -> None:
        assert refs._default_name_from_source("https://", "remote_upload") == "reference"


class TestHumanBytes:
    @pytest.mark.parametrize("n,expected_unit", [
        (500, "B"),
        (2048, "KB"),
        (5 * 1024 * 1024, "MB"),
        (2 * 1024**3, "GB"),
    ])
    def test_units(self, n: int, expected_unit: str) -> None:
        assert expected_unit in refs._human_bytes(n)


class TestCmdRefsAddGuards:
    def _emit(self, captured: list[Any]):
        def emit(p: Any, j: bool) -> None: captured.append((p, j))
        return emit

    def test_empty_source_refused(self) -> None:
        rc = refs.cmd_refs_add(
            source="", folder="fld1", name=None, via=None, yes=True,
            as_json=False, emit=self._emit([]),
        )
        assert rc == 2

    def test_empty_folder_refused(self) -> None:
        rc = refs.cmd_refs_add(
            source="https://example.com/x.mp4", folder="  ", name=None, via=None, yes=True,
            as_json=False, emit=self._emit([]),
        )
        assert rc == 2

    def test_missing_local_file_refused(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.mp4"
        rc = refs.cmd_refs_add(
            source=str(missing), folder="fld1", name=None, via=None, yes=True,
            as_json=False, emit=self._emit([]),
        )
        assert rc == 2

    def test_non_tty_without_yes_refused(self, tmp_path: Path) -> None:
        local = tmp_path / "f.mp4"
        local.write_bytes(b"x" * 100)
        rc = refs.cmd_refs_add(
            source=str(local), folder="fld1", name=None, via=None, yes=False,
            as_json=False, emit=self._emit([]),
            stdin=_FakeTTY(tty=False),
        )
        assert rc == 2

    def test_tty_with_n_aborts(self, tmp_path: Path) -> None:
        local = tmp_path / "f.mp4"
        local.write_bytes(b"x" * 100)
        with patch("builtins.input", return_value="n"):
            rc = refs.cmd_refs_add(
                source=str(local), folder="fld1", name=None, via=None, yes=False,
                as_json=False, emit=self._emit([]),
                stdin=_FakeTTY(tty=True),
            )
        assert rc == 1


class TestRenderConfirmation:
    def test_local_shape(self) -> None:
        text = refs._render_confirmation(
            source="/tmp/f.mp4", mode="local", name="f.mp4", folder_id="fld1", file_size=1024 * 1024,
        )
        assert "/tmp/f.mp4" in text
        assert "local upload" in text
        assert "fld1" in text
        assert "MB" in text

    def test_yt_dlp_shape(self) -> None:
        text = refs._render_confirmation(
            source="https://youtube.com/watch?v=x", mode="yt_dlp", name="clip.mp4", folder_id="fld1", file_size=None,
        )
        assert "yt-dlp" in text
        assert "Size:" not in text  # unknown size for yt-dlp pre-download
