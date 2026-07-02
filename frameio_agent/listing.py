"""CLI commands: verify, projects, latest.

Reads through :mod:`api`, never touches HTTP directly. Output shapes are
the JSON contracts called out in the PRD and ``AGENTS.md``.
"""
from __future__ import annotations

import sys
from typing import Any, Callable, Optional

from . import api
from .auth import get_access_token
from .client import FrameioClient
from .config import load_config
from .errors import FrameioAgentError


def _frameio_url(account_id: str, project_id: str, file_id: str) -> str:
    """Best-effort URL to the file inside the Frame.io web app."""
    return f"https://next.frame.io/project/{project_id}/view/{file_id}"


def _expand_project_scopes(
    client: FrameioClient,
    account: Optional[str],
    workspace: Optional[str],
) -> list[dict[str, Any]]:
    """Walk accounts -> workspaces -> projects, optionally filtered."""
    out: list[dict[str, Any]] = []
    for acct in api.list_accounts(client):
        acct_id = acct.get("id") or acct.get("account_id")
        if not acct_id or (account and acct_id != account):
            continue
        acct_name = acct.get("name") or acct.get("display_name") or ""
        for ws in api.list_workspaces(client, acct_id):
            ws_id = ws.get("id") or ws.get("workspace_id")
            if not ws_id or (workspace and ws_id != workspace):
                continue
            ws_name = ws.get("name") or ""
            for proj in api.list_projects(client, acct_id, ws_id):
                proj_id = proj.get("id") or proj.get("project_id")
                if not proj_id:
                    continue
                out.append(
                    {
                        "account_id": acct_id,
                        "account_name": acct_name,
                        "workspace_id": ws_id,
                        "workspace_name": ws_name,
                        "project_id": proj_id,
                        "project_name": proj.get("name") or "",
                        "root_folder_id": proj.get("root_folder_id") or proj.get("root_asset_id"),
                        "updated_at": proj.get("updated_at"),
                    }
                )
    return out


def _normalize_file(account_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    file_id = raw.get("id") or raw.get("file_id") or ""
    project_id = raw.get("project_id") or ""
    out = {
        "file_id": file_id,
        "name": raw.get("name") or "",
        "project_id": project_id,
        "media_type": raw.get("media_type"),
        "file_size": raw.get("file_size") or raw.get("filesize"),
        "duration_seconds": raw.get("duration_seconds") or raw.get("duration"),
        # comments_count isn't returned by V4 listing endpoints; left null.
        # Use `comments <file_id>` to get the actual list.
        "comments_count": raw.get("comments_count") or raw.get("comment_count"),
        "created_at": raw.get("created_at"),
        "updated_at": raw.get("updated_at"),
        "frameio_url": raw.get("view_url") or (_frameio_url(account_id, project_id, file_id) if (project_id and file_id) else None),
    }
    # Preserve version_stack id if we unwrapped one — useful for share creation.
    if raw.get("version_stack_id"):
        out["version_stack_id"] = raw["version_stack_id"]
    return out


def _resolve_account_for_project(client: FrameioClient, project_id: str) -> str:
    """Find the account_id that owns a given project_id by scanning visible orgs."""
    cfg = load_config()
    if cfg.default_account_id:
        return cfg.default_account_id
    for entry in _expand_project_scopes(client, account=None, workspace=None):
        if entry["project_id"] == project_id:
            return entry["account_id"]
    raise FrameioAgentError(
        f"Could not find project {project_id} under any visible account.",
        remediation="Run: frameio-agent projects --json",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────────────────────────────────────

def cmd_verify(*, as_json: bool, emit: Callable[[Any, bool], None]) -> int:
    cfg = load_config()
    try:
        _, cache = get_access_token(cfg)
    except FrameioAgentError as e:
        print(f"Error: {e.render()}", file=sys.stderr)
        return 1

    try:
        with FrameioClient(cfg) as client:
            me = api.get_me(client)
            projects = _expand_project_scopes(client, account=None, workspace=None)
    except FrameioAgentError as e:
        print(f"Error: {e.render()}", file=sys.stderr)
        return 1

    payload = {
        "ok": True,
        "authenticated": True,
        "email": me.get("email") or cache.email,
        "accounts_visible": len({p["account_id"] for p in projects}),
        "projects_visible": len(projects),
    }
    if as_json:
        emit(payload, True)
    else:
        print(f"Connected as: {payload['email'] or '(email unavailable)'}")
        print(f"Accounts visible: {payload['accounts_visible']}")
        print(f"Projects visible: {payload['projects_visible']}")
        if projects:
            print()
            print("Sample projects:")
            for p in projects[:5]:
                print(f"  - {p['project_name']}  ({p['project_id']})")
    return 0


def cmd_projects(
    *,
    account: Optional[str],
    workspace: Optional[str],
    as_json: bool,
    emit: Callable[[Any, bool], None],
) -> int:
    cfg = load_config()
    try:
        with FrameioClient(cfg) as client:
            entries = _expand_project_scopes(client, account=account, workspace=workspace)
    except FrameioAgentError as e:
        print(f"Error: {e.render()}", file=sys.stderr)
        return 1

    if as_json:
        emit({"projects": entries}, True)
    else:
        if not entries:
            print("No projects visible.")
            print("  > Check that you've been added to a workspace.")
            return 0
        for p in entries:
            print(f"{p['project_name']}")
            print(f"  project_id: {p['project_id']}")
            print(f"  workspace:  {p['workspace_name']} ({p['workspace_id']})")
            print(f"  account:    {p['account_name']} ({p['account_id']})")
            print()
    return 0


def cmd_latest(
    *,
    project: str,
    limit: int,
    as_json: bool,
    emit: Callable[[Any, bool], None],
) -> int:
    cfg = load_config()
    try:
        with FrameioClient(cfg) as client:
            account_id = _resolve_account_for_project(client, project)
            raw = api.list_recent_files(client, account_id, project, limit=limit)
    except FrameioAgentError as e:
        print(f"Error: {e.render()}", file=sys.stderr)
        return 1

    items = [_normalize_file(account_id, r) for r in raw]
    payload = {
        "project_id": project,
        "account_id": account_id,
        "items": items,
    }
    if as_json:
        emit(payload, True)
    else:
        if not items:
            print(f"No video assets found in project {project}.")
            print("  > Try uploading content, or use `search` with a name.")
            return 0
        print(f"Latest in project {project}:")
        for i, item in enumerate(items, 1):
            updated = item.get("updated_at") or "?"
            count = item.get("comments_count")
            # V4 listing endpoints don't return comment counts; don't fake a 0.
            count_str = f"{count} comments" if count is not None else "comments: n/a"
            print(f"  {i}. {item['name']}  (updated {updated}, {count_str})")
            print(f"     file_id: {item['file_id']}")
        print()
        print("Tip: frameio-agent comments <file_id> --json")
    return 0
