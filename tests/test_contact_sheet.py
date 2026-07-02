"""Tests for contact-sheet — filters, manifest loading, CLI guards."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from frameio_agent import contact_sheet as cs
from frameio_agent.errors import FrameioAgentError


class TestParseIdList:
    def test_none_and_empty(self) -> None:
        assert cs.parse_id_list(None) == set()
        assert cs.parse_id_list("") == set()

    def test_single(self) -> None:
        assert cs.parse_id_list("abc") == {"abc"}

    def test_multi_with_whitespace_and_blanks(self) -> None:
        assert cs.parse_id_list("a, b ,,c,") == {"a", "b", "c"}


class TestApplyFilters:
    ENTRIES = [
        {"file_id": "a", "name": "A"},
        {"file_id": "b", "name": "B"},
        {"file_id": "c", "name": "C"},
    ]

    def test_no_filters_passthrough(self) -> None:
        out = cs.apply_filters(self.ENTRIES, only=set(), exclude=set())
        assert len(out) == 3

    def test_only(self) -> None:
        out = cs.apply_filters(self.ENTRIES, only={"a", "c"}, exclude=set())
        assert [e["file_id"] for e in out] == ["a", "c"]

    def test_exclude(self) -> None:
        out = cs.apply_filters(self.ENTRIES, only=set(), exclude={"b"})
        assert [e["file_id"] for e in out] == ["a", "c"]

    def test_only_and_exclude_compose(self) -> None:
        out = cs.apply_filters(self.ENTRIES, only={"a", "b"}, exclude={"b"})
        assert [e["file_id"] for e in out] == ["a"]

    def test_id_key_fallback(self) -> None:
        entries = [{"id": "x", "name": "X"}]
        out = cs.apply_filters(entries, only={"x"}, exclude=set())
        assert len(out) == 1


class TestLoadManifest:
    def _write(self, tmp_path: Path, payload: dict) -> Path:
        p = tmp_path / "manifest.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    def test_loads_frames_list(self, tmp_path: Path) -> None:
        p = self._write(tmp_path, {"frames": [{"file_id": "a", "local_path": "x.jpg"}]})
        out = cs.load_manifest(str(p))
        assert out[0]["file_id"] == "a"

    def test_accepts_directory(self, tmp_path: Path) -> None:
        self._write(tmp_path, {"frames": []})
        assert cs.load_manifest(str(tmp_path)) == []

    def test_missing_raises_with_remediation(self, tmp_path: Path) -> None:
        with pytest.raises(FrameioAgentError) as ei:
            cs.load_manifest(str(tmp_path / "nope"))
        assert "frames pull" in ei.value.remediation

    def test_malformed_json_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "manifest.json"
        p.write_text("{not json", encoding="utf-8")
        with pytest.raises(FrameioAgentError):
            cs.load_manifest(str(p))

    def test_missing_frames_key_raises(self, tmp_path: Path) -> None:
        p = self._write(tmp_path, {"something_else": []})
        with pytest.raises(FrameioAgentError):
            cs.load_manifest(str(p))


class TestCmdContactSheetGuards:
    def _emit(self, captured: list[Any]):
        def emit(p: Any, j: bool) -> None: captured.append((p, j))
        return emit

    def _call(self, tmp_path: Path, **overrides: Any) -> int:
        kwargs: dict[str, Any] = dict(
            project=None, folder=None, from_manifest=None, only=None, exclude=None,
            out=str(tmp_path / "out.png"), cols=4, tile_size=120, max_files=50,
            no_labels=False, index=False, parallel=4,
            as_json=False, emit=self._emit([]),
        )
        kwargs.update(overrides)
        return cs.cmd_contact_sheet(**kwargs)

    def test_no_source_refused(self, tmp_path: Path) -> None:
        assert self._call(tmp_path) == 2

    def test_manifest_missing_errors_cleanly(self, tmp_path: Path) -> None:
        rc = self._call(tmp_path, from_manifest=str(tmp_path / "missing"))
        assert rc == 1

    def test_manifest_all_filtered_out_is_ok(self, tmp_path: Path) -> None:
        p = tmp_path / "manifest.json"
        p.write_text(json.dumps({"frames": [{"file_id": "a", "local_path": "gone.jpg", "name": "A"}]}), encoding="utf-8")
        rc = self._call(tmp_path, from_manifest=str(p), exclude="a")
        assert rc == 0  # "no files matched" is a clean exit


class TestOfflineSheetFromManifest:
    """End-to-end offline path with real (tiny) PNGs — no Frame.io calls."""

    def _make_png(self, path: Path, color: tuple[int, int, int]) -> None:
        from PIL import Image
        Image.new("RGB", (32, 32), color=color).save(path, "PNG")

    def test_builds_sheet_and_index(self, tmp_path: Path) -> None:
        pytest.importorskip("PIL")
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        entries = []
        for i, color in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255)]):
            img = frames_dir / f"{i:03d}_clip{i}.jpg"
            self._make_png(img, color)
            entries.append({"index": i, "file_id": f"id{i}", "name": f"clip{i}", "local_path": str(img)})
        manifest = frames_dir / "manifest.json"
        manifest.write_text(json.dumps({"frames": entries}), encoding="utf-8")

        out_png = tmp_path / "sheet.png"
        captured: list[Any] = []

        def emit(p: Any, j: bool) -> None: captured.append(p)

        rc = cs.cmd_contact_sheet(
            project=None, folder=None, from_manifest=str(manifest),
            only=None, exclude="id1",
            out=str(out_png), cols=2, tile_size=64, max_files=50,
            no_labels=False, index=True, parallel=2,
            as_json=True, emit=emit,
        )
        assert rc == 0
        assert out_png.exists()
        payload = captured[0]
        assert payload["tile_count"] == 2  # id1 excluded
        tile_ids = {t["file_id"] for t in payload["tiles"]}
        assert tile_ids == {"id0", "id2"}
        index_file = Path(payload["index_file"])
        assert index_file.exists()
        sidecar = json.loads(index_file.read_text(encoding="utf-8"))
        assert len(sidecar["tiles"]) == 2
