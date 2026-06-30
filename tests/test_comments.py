"""Tests for comment normalization and timecode math."""
from __future__ import annotations

import pytest

from frameio_agent.comments import _detect_fps, _normalize_comment, seconds_to_timecode


class TestSecondsToTimecode:
    @pytest.mark.parametrize(
        "seconds,fps,expected",
        [
            (0, 30, "00:00:00:00"),
            (1, 30, "00:00:01:00"),
            (12.34, 30, "00:00:12:10"),  # 12.34 * 30 = 370.2 -> 370 frames = 12s 10f
            (60, 30, "00:01:00:00"),
            (3600, 30, "01:00:00:00"),
            (1.0, 24, "00:00:01:00"),
            (None, 30, "00:00:00:00"),
            (-5, 30, "00:00:00:00"),
        ],
    )
    def test_known_values(self, seconds, fps, expected) -> None:
        assert seconds_to_timecode(seconds, fps) == expected


class TestNormalizeComment:
    def test_basic_shape(self) -> None:
        raw = {
            "id": "c123",
            "text": "Tighten this section.",
            "timestamp": 12.34,
            "owner": {"name": "Reviewer"},
            "created_at": "2026-06-30T12:00:00Z",
            "parent_id": None,
        }
        out = _normalize_comment(raw, fps=30.0)
        assert out["comment_id"] == "c123"
        assert out["text"] == "Tighten this section."
        assert out["timestamp_seconds"] == 12.34
        assert out["timecode"] == "00:00:12:10"
        assert out["author_name"] == "Reviewer"
        assert out["is_reply"] is False

    def test_reply_detected(self) -> None:
        raw = {"id": "c2", "text": "Reply", "timestamp": 5.0, "parent_id": "c1"}
        out = _normalize_comment(raw, fps=30.0)
        assert out["is_reply"] is True
        assert out["parent_id"] == "c1"

    def test_missing_timestamp_safe(self) -> None:
        raw = {"id": "c3", "text": "General note", "timestamp": None}
        out = _normalize_comment(raw, fps=30.0)
        assert out["timestamp_seconds"] is None
        assert out["timecode"] is None

    def test_string_owner(self) -> None:
        raw = {"id": "c4", "text": "x", "timestamp": 0, "owner": "Bare Name"}
        out = _normalize_comment(raw, fps=30.0)
        assert out["author_name"] == "Bare Name"

    def test_falls_back_to_email(self) -> None:
        raw = {"id": "c5", "text": "x", "timestamp": 0, "owner": {"email": "rev@ex.com"}}
        out = _normalize_comment(raw, fps=30.0)
        assert out["author_name"] == "rev@ex.com"


class TestDetectFps:
    @pytest.mark.parametrize(
        "meta,expected",
        [
            ({"fps": 24}, 24.0),
            ({"frame_rate": "29.97"}, 29.97),
            ({"framerate": 60}, 60.0),
            ({}, 30.0),
            ({"fps": None}, 30.0),
        ],
    )
    def test_fps_detection(self, meta, expected) -> None:
        assert _detect_fps(meta) == expected
