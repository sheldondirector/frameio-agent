"""One-paragraph project status from the data ``latest`` already gives us.

Built only from read-only calls already implemented in :mod:`listing` and
:mod:`api`. Useful for "catch me up on this project" prompts.
"""
from __future__ import annotations

import sys
from typing import Any, Callable

from . import api
from .client import FrameioClient
from .config import load_config
from .errors import FrameioAgentError
from .listing import _normalize_file, _resolve_account_for_project


def cmd_brief(*, project: str, as_json: bool, emit: Callable[[Any, bool], None]) -> int:
    cfg = load_config()
    try:
        with FrameioClient(cfg) as client:
            account_id = _resolve_account_for_project(client, project)
            project_meta = api.get_project(client, account_id, project)
            recent_raw = api.list_recent_files(client, account_id, project, limit=5)
    except FrameioAgentError as e:
        print(f"Error: {e.render()}", file=sys.stderr)
        return 1

    recent = [_normalize_file(account_id, r) for r in recent_raw]
    needs_review = [r for r in recent if (r.get("comments_count") or 0) > 0]

    next_actions: list[str] = []
    if needs_review:
        top = needs_review[0]
        next_actions.append(
            f"Summarize the {top['comments_count']} comments on '{top['name']}' "
            f"(`comments {top['file_id']} --json`)."
        )
    if len(recent) > 1:
        next_actions.append("Compare the two most recent cuts to see what changed.")
    if not recent:
        next_actions.append("Upload a first cut to begin review.")

    payload: dict[str, Any] = {
        "project_id": project,
        "project_name": project_meta.get("name"),
        "recent": recent,
        "next_actions": next_actions,
    }

    if as_json:
        emit(payload, True)
    else:
        print(f"Project: {payload['project_name'] or project}")
        print()
        if recent:
            print("Recent assets:")
            for r in recent:
                upd = r.get("updated_at") or "?"
                count = r.get("comments_count") or 0
                print(f"  - {r['name']}  ({upd}, {count} comments)")
        else:
            print("(no recent assets)")
        if next_actions:
            print()
            print("Likely next actions:")
            for a in next_actions:
                print(f"  - {a}")
    return 0
