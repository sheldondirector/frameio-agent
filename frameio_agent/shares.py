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
    allow_download: bool,
    expires_at: Optional[str],
    password: Optional[str],
    public: bool,
) -> dict[str, Any]:
    """Translate CLI flags into the V4 ``CreateShareParams`` body.

    Spec: ``POST /v4/accounts/{acct}/projects/{proj}/shares`` with::

        {"data": {
            "type": "asset",           # required discriminator
            "name": "...",
            "asset_ids": ["..."],
            "access": "public" | "secure",
            "downloading_enabled": bool,
            "expiration": "ISO timestamp",
            "passphrase": "..."
        }}

    NOTE: ``commenting_enabled`` is read-only on the Share response and is
    NOT a valid CreateShareParams field — comments behavior is set by the
    project, not the share. The CLI's --allow-comments / --no-comments
    flags are accepted for forward-compat and currently no-op.
    """
    inner: dict[str, Any] = {
        "type": "asset",
        "name": name,
        "asset_ids": list(asset_ids),
        "access": "public" if public else "secure",
        "downloading_enabled": allow_download,
    }
    if expires_at:
        inner["expiration"] = expires_at
    if password:
        inner["passphrase"] = password
    return {"data": inner}


def _render_confirmation(payload: dict[str, Any]) -> str:
    d = payload["data"]
    lines = [
        "About to create a Frame.io share:",
        f"  Name:         {d['name']}",
        f"  Visibility:   {'public link (anyone with URL)' if d['access'] == 'public' else 'secure (passphrase or signed-in Frame.io users)'}",
        f"  Assets:       {len(d['asset_ids'])} file(s)",
    ]
    for aid in d["asset_ids"]:
        lines.append(f"                  - {aid}")
    lines.append(f"  Download:     {'allowed' if d['downloading_enabled'] else 'not allowed'}")
    lines.append(f"  Expires:      {d.get('expiration') or 'never'}")
    lines.append(f"  Password:     {'set' if d.get('passphrase') else 'none'}")
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
    d = request_body["data"]
    return {
        "share_id": raw.get("id") or raw.get("share_id"),
        "name": raw.get("name") or d["name"],
        "url": raw.get("short_url") or raw.get("url"),
        "visibility": raw.get("access") or d["access"],
        "allow_comments": raw.get("commenting_enabled"),
        "allow_download": raw.get("downloading_enabled", d["downloading_enabled"]),
        "expires_at": raw.get("expiration"),
        "password_protected": bool(raw.get("passphrase") or d.get("passphrase")),
        "asset_count": len(d["asset_ids"]),
        "asset_ids": d["asset_ids"],
        "created_at": raw.get("created_at"),
    }


def cmd_share_create(
    *,
    file_ids: list[str],
    name: str,
    allow_comments: bool,  # accepted for forward-compat; V4 doesn't expose at create
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
            # V4 shares are project-scoped — resolve project_id from the first file.
            file_meta = api.get_file(client, account_id, file_ids[0])
            project_id = file_meta.get("project_id")
            if not project_id:
                raise FrameioAgentError(
                    f"Could not resolve project_id for file {file_ids[0]}.",
                    remediation="Verify the file_id with `latest` or `search`.",
                )
            raw = api.create_share(client, account_id, project_id, payload)
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
        rendered = e.render()
        if "feature(s) not included in plan" in rendered:
            # Surface Frame.io plan limitations clearly. The plan-gated feature
            # name is in the error (e.g. "secure_sharing").
            print(
                f"Error: This Frame.io plan does not include the feature required for "
                f"the requested share options.\n  > {rendered.split(' on POST')[0]}",
                file=sys.stderr,
            )
            print(
                "  > Try `--public` instead of `--restricted`, or upgrade your Frame.io plan.",
                file=sys.stderr,
            )
            return 1
        print(f"Error: {rendered}", file=sys.stderr)
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
