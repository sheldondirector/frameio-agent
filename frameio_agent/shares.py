"""The single mutation command: ``share create`` (PRD §11.8).

Behavior:
  * Build the share payload from CLI flags.
  * Print a confirmation summary (passwords masked).
  * Prompt y/N unless ``--yes`` is passed.
  * Refuse on non-TTY without ``--yes``.
  * POST to Frame.io and return the normalized share record.

Never echoes share passwords. The only mutation surface in the whole CLI.
"""
from __future__ import annotations

import sys
from typing import Any, Callable, Optional

from . import api
from .client import FrameioClient
from .comments import _resolve_account_for_file  # account-resolution helper
from .config import load_config
from .errors import AuthError, FrameioAgentError


def build_payload(
    *,
    name: str,
    asset_ids: list[str],
    allow_comments: bool,
    allow_download: bool,
    expires_at: Optional[str],
    password: Optional[str],
    public: bool,
) -> dict[str, Any]:
    """Translate CLI flags into the share-creation request body.

    Field names follow Frame.io V4 conventions; if a field is rejected by the
    live API we fix it in this one function. Nothing else should mint share
    payloads.
    """
    body: dict[str, Any] = {
        "name": name,
        "asset_ids": list(asset_ids),
        "allow_comments": allow_comments,
        "allow_download": allow_download,
        "access": "public" if public else "restricted",
    }
    if expires_at:
        body["expires_at"] = expires_at
    if password:
        body["password"] = password
    return body


def _render_confirmation(payload: dict[str, Any]) -> str:
    lines = [
        "About to create a Frame.io share:",
        f"  Name:         {payload['name']}",
        f"  Visibility:   {'public link (anyone with URL)' if payload['access'] == 'public' else 'restricted (signed-in Frame.io users only)'}",
        f"  Assets:       {len(payload['asset_ids'])} file(s)",
    ]
    for aid in payload["asset_ids"]:
        lines.append(f"                  - {aid}")
    lines.append(f"  Comments:     {'allowed' if payload['allow_comments'] else 'not allowed'}")
    lines.append(f"  Download:     {'allowed' if payload['allow_download'] else 'not allowed'}")
    lines.append(f"  Expires:      {payload.get('expires_at') or 'never'}")
    lines.append(f"  Password:     {'set' if payload.get('password') else 'none'}")
    return "\n".join(lines)


def _prompt_confirm() -> bool:
    """Read y/N from stdin. Empty input or anything not starting with y/Y is No."""
    try:
        answer = input("\nCreate this share? [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def _normalize_share_response(raw: dict[str, Any], request_body: dict[str, Any]) -> dict[str, Any]:
    """Coerce Frame.io's response into the JSON contract documented in AGENTS.md."""
    return {
        "share_id": raw.get("id") or raw.get("share_id"),
        "name": raw.get("name") or request_body["name"],
        "url": raw.get("url") or raw.get("short_url") or raw.get("share_url"),
        "visibility": raw.get("access") or request_body["access"],
        "allow_comments": raw.get("allow_comments", request_body["allow_comments"]),
        "allow_download": raw.get("allow_download", request_body["allow_download"]),
        "expires_at": raw.get("expires_at"),
        "password_protected": bool(raw.get("password") or request_body.get("password")),
        "asset_count": len(request_body["asset_ids"]),
        "asset_ids": request_body["asset_ids"],
        "created_at": raw.get("created_at"),
    }


def cmd_share_create(
    *,
    file_ids: list[str],
    name: str,
    allow_comments: bool,
    allow_download: bool,
    expires_at: Optional[str],
    password: Optional[str],
    public: bool,
    yes: bool,
    as_json: bool,
    emit: Callable[[Any, bool], None],
    stdin: Any = None,
) -> int:
    if not file_ids:
        print("Error: at least one file_id is required.", file=sys.stderr)
        return 2
    if not name.strip():
        print("Error: --name is required.", file=sys.stderr)
        return 2

    payload = build_payload(
        name=name,
        asset_ids=file_ids,
        allow_comments=allow_comments,
        allow_download=allow_download,
        expires_at=expires_at,
        password=password,
        public=public,
    )

    print(_render_confirmation(payload))

    if not yes:
        in_stream = stdin if stdin is not None else sys.stdin
        if not in_stream.isatty():
            print(
                "\nError: Share creation requires interactive confirmation; stdin is not a TTY.",
                file=sys.stderr,
            )
            print(
                "  > Re-run with --yes if the user has explicitly authorized creating this share.",
                file=sys.stderr,
            )
            return 2
        if not _prompt_confirm():
            print("Aborted. No share was created.", file=sys.stderr)
            return 1

    cfg = load_config()
    try:
        with FrameioClient(cfg) as client:
            account_id = _resolve_account_for_file(client, file_ids[0])
            raw = api.create_share(client, account_id, payload)
    except AuthError as e:
        # Hint at scope issues, which are the most likely failure mode for write.
        rendered = e.render()
        if "scope" in rendered.lower() or "insufficient" in rendered.lower():
            print(
                "Error: Frame.io rejected the share request (insufficient OAuth scope).",
                file=sys.stderr,
            )
            print("  > Run: frameio-agent auth login", file=sys.stderr)
            return 1
        print(f"Error: {rendered}", file=sys.stderr)
        return 1
    except FrameioAgentError as e:
        print(f"Error: {e.render()}", file=sys.stderr)
        return 1

    normalized = _normalize_share_response(raw, payload)
    if as_json:
        emit(normalized, True)
    else:
        print()
        print("Share created.")
        print(f"  URL:    {normalized['url']}")
        print(f"  ID:     {normalized['share_id']}")
        print(f"  Assets: {normalized['asset_count']}")
    return 0
