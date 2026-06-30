"""Normalize Frame.io comments into the agent-friendly shape (the north-star).

Output contract per PRD §11.6:

    {
      "file_id": "...",
      "file_name": "Rough Cut v4.mov",
      "duration_seconds": 154.2,
      "comments": [
        {
          "comment_id": "...",
          "text": "Tighten this section.",
          "timecode": "00:00:12:10",
          "timestamp_seconds": 12.34,
          "author_name": "Reviewer",
          "created_at": "...",
          "parent_id": null,
          "is_reply": false
        }
      ]
    }

The model groups by ``timestamp_seconds`` and labels with ``timecode``. Both
fields are always present (timecode is generated when Frame.io only ships
seconds).
"""
from __future__ import annotations

import sys
from typing import Any, Callable, Optional

from . import api
from .client import FrameioClient
from .config import load_config
from .errors import FrameioAgentError
from .listing import _resolve_account_for_project  # internal helper, fine to share


DEFAULT_FPS = 30.0


def seconds_to_timecode(seconds: float, fps: float = DEFAULT_FPS) -> str:
    """Convert seconds to HH:MM:SS:FF timecode."""
    if seconds is None or seconds < 0:
        return "00:00:00:00"
    total_frames = int(round(seconds * fps))
    frames_per_hour = int(round(fps)) * 3600
    frames_per_minute = int(round(fps)) * 60
    frames_per_second = int(round(fps))

    h = total_frames // frames_per_hour
    rem = total_frames % frames_per_hour
    m = rem // frames_per_minute
    rem = rem % frames_per_minute
    s = rem // frames_per_second
    f = rem % frames_per_second
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def _normalize_comment(raw: dict[str, Any], fps: float) -> dict[str, Any]:
    ts = raw.get("timestamp")
    if ts is None:
        ts = raw.get("timestamp_seconds")
    try:
        ts_seconds: Optional[float] = float(ts) if ts is not None else None
    except (TypeError, ValueError):
        ts_seconds = None

    owner = raw.get("owner") or raw.get("author") or {}
    if isinstance(owner, dict):
        author_name = owner.get("name") or owner.get("display_name") or owner.get("email") or ""
    else:
        author_name = str(owner)

    parent_id = raw.get("parent_id")
    return {
        "comment_id": raw.get("id") or raw.get("comment_id"),
        "text": raw.get("text") or raw.get("body") or "",
        "timecode": seconds_to_timecode(ts_seconds or 0.0, fps) if ts_seconds is not None else None,
        "timestamp_seconds": ts_seconds,
        "author_name": author_name,
        "created_at": raw.get("created_at"),
        "parent_id": parent_id,
        "is_reply": bool(parent_id),
    }


def _detect_fps(file_meta: dict[str, Any]) -> float:
    for key in ("fps", "frame_rate", "framerate"):
        v = file_meta.get(key)
        if v:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return DEFAULT_FPS


def cmd_comments(
    *,
    file_id: str,
    by_timecode: bool,
    as_json: bool,
    emit: Callable[[Any, bool], None],
) -> int:
    cfg = load_config()
    try:
        with FrameioClient(cfg) as client:
            # File detail needs an account_id; resolve from default or by scanning.
            account_id = _resolve_account_for_file(client, file_id)
            file_meta = api.get_file(client, account_id, file_id)
            raw_comments = api.list_comments(client, account_id, file_id)
    except FrameioAgentError as e:
        print(f"Error: {e.render()}", file=sys.stderr)
        return 1

    fps = _detect_fps(file_meta)
    normalized = [_normalize_comment(c, fps) for c in raw_comments]
    if by_timecode:
        normalized.sort(key=lambda c: c["timestamp_seconds"] if c["timestamp_seconds"] is not None else 0.0)

    payload = {
        "file_id": file_id,
        "file_name": file_meta.get("name"),
        "duration_seconds": file_meta.get("duration_seconds") or file_meta.get("duration"),
        "fps": fps,
        "comments_count": len(normalized),
        "comments": normalized,
    }
    if as_json:
        emit(payload, True)
    else:
        print(f"{payload['file_name'] or file_id} — {len(normalized)} comments")
        if payload["duration_seconds"]:
            print(f"  duration: {payload['duration_seconds']:.1f}s  fps: {fps:g}")
        print()
        for c in normalized[:50]:
            tag = "    > " if c["is_reply"] else "  - "
            tc = c["timecode"] or "  -    "
            who = c["author_name"] or "(unknown)"
            print(f"{tag}{tc}  {who}: {c['text']}")
        if len(normalized) > 50:
            print(f"  ... ({len(normalized) - 50} more, use --json to see all)")
    return 0


def _resolve_account_for_file(client: FrameioClient, file_id: str) -> str:
    """Find the account_id for a file, preferring the configured default."""
    cfg = load_config()
    if cfg.default_account_id:
        return cfg.default_account_id
    # Fall back to first visible account — most users have just one.
    accounts = api.list_accounts(client)
    if not accounts:
        raise FrameioAgentError(
            "No Frame.io accounts visible.",
            remediation="Run: frameio-agent verify",
        )
    acct_id = accounts[0].get("id") or accounts[0].get("account_id")
    if not acct_id:
        raise FrameioAgentError(
            "Could not resolve an account_id for this request.",
            remediation="Set FRAMEIO_ACCOUNT_ID in .env.",
        )
    return acct_id
