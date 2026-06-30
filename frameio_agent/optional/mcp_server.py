"""Optional MCP wrapper over the same internal functions used by the CLI.

Install with the ``mcp`` extra:

    pip install '.[mcp]'

Then run:

    frameio-agent mcp

The wrapper does not duplicate logic; it calls the same functions the CLI uses.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from .. import api
from ..auth import load_tokens
from ..client import FrameioClient
from ..comments import _detect_fps, _normalize_comment
from ..config import load_config
from ..listing import (
    _expand_project_scopes,
    _normalize_file,
    _resolve_account_for_project,
)


def _tool_auth_status() -> dict[str, Any]:
    cfg = load_config()
    cache = load_tokens(cfg)
    if cache is None:
        return {"authenticated": False, "remediation": "Run: frameio-agent auth login"}
    return {
        "authenticated": True,
        "email": cache.email,
        "expires_at_unix": cache.expires_at,
        "expired": cache.is_expired(0),
        "has_refresh_token": bool(cache.refresh_token),
    }


def _tool_list_projects() -> dict[str, Any]:
    cfg = load_config()
    with FrameioClient(cfg) as client:
        return {"projects": _expand_project_scopes(client, account=None, workspace=None)}


def _tool_latest(project_id: str, limit: int = 5) -> dict[str, Any]:
    cfg = load_config()
    with FrameioClient(cfg) as client:
        account_id = _resolve_account_for_project(client, project_id)
        raw = api.list_recent_files(client, account_id, project_id, limit=limit)
        return {
            "project_id": project_id,
            "account_id": account_id,
            "items": [_normalize_file(account_id, r) for r in raw],
        }


def _tool_get_comments(file_id: str, by_timecode: bool = False) -> dict[str, Any]:
    cfg = load_config()
    with FrameioClient(cfg) as client:
        accounts = api.list_accounts(client)
        account_id = cfg.default_account_id or (accounts[0].get("id") if accounts else None)
        if not account_id:
            return {"error": "No account_id available."}
        file_meta = api.get_file(client, account_id, file_id)
        raw_comments = api.list_comments(client, account_id, file_id)
    fps = _detect_fps(file_meta)
    items = [_normalize_comment(c, fps) for c in raw_comments]
    if by_timecode:
        items.sort(key=lambda c: c["timestamp_seconds"] or 0.0)
    return {
        "file_id": file_id,
        "file_name": file_meta.get("name"),
        "duration_seconds": file_meta.get("duration_seconds") or file_meta.get("duration"),
        "fps": fps,
        "comments_count": len(items),
        "comments": items,
    }


def run() -> int:
    """Launch the MCP server over stdio. Requires the ``mcp`` package."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print(
            "The optional 'mcp' dependency is not installed.\n"
            "Install with:  pip install '.[mcp]'",
            file=sys.stderr,
        )
        return 2

    server = FastMCP("frameio-agent")

    @server.tool()
    def frameio_auth_status() -> str:
        """Return whether Frame.io auth is configured and valid (no secrets)."""
        return json.dumps(_tool_auth_status())

    @server.tool()
    def frameio_list_projects() -> str:
        """List accounts/workspaces/projects visible to the authenticated user."""
        return json.dumps(_tool_list_projects())

    @server.tool()
    def frameio_latest(project_id: str, limit: int = 5) -> str:
        """Most-recently-updated video files in a project, with comment counts."""
        return json.dumps(_tool_latest(project_id, limit))

    @server.tool()
    def frameio_get_comments(file_id: str, by_timecode: bool = False) -> str:
        """Normalized review comments for a file (text + timecode + author + thread)."""
        return json.dumps(_tool_get_comments(file_id, by_timecode))

    server.run()
    return 0
