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
from .comments import find_file  # locates a file across visible accounts
from .config import load_config
from .errors import FrameioAgentError


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


def _render_confirmation(payload: dict[str, Any], *, reviewers: Optional[list[str]] = None, message: Optional[str] = None) -> str:
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
    if reviewers:
        lines.append(f"  Reviewers:    {len(reviewers)} email recipient(s)")
        for email in reviewers:
            lines.append(f"                  - {email}")
        if message:
            short_msg = (message[:60] + "...") if len(message) > 60 else message
            lines.append(f"  Message:      {short_msg!r}")
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


def _parse_reviewer_list(raw: Optional[str]) -> list[str]:
    """Comma-separated email addresses → cleaned list."""
    if not raw:
        return []
    out: list[str] = []
    for piece in raw.split(","):
        email = piece.strip()
        if email:
            out.append(email)
    return out


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
    reviewers: Optional[str] = None,
    message: Optional[str] = None,
) -> int:
    if not file_ids:
        print("Error: at least one file_id is required.", file=sys.stderr)
        return 2
    if not name.strip():
        print("Error: --name is required.", file=sys.stderr)
        return 2

    reviewer_emails = _parse_reviewer_list(reviewers)
    if len(reviewer_emails) > 10:
        print("Error: max 10 reviewer emails per share (V4 limit).", file=sys.stderr)
        return 2

    payload = build_payload(
        name=name,
        asset_ids=file_ids,
        allow_download=allow_download,
        expires_at=expires_at,
        password=password,
        public=public,
    )

    print(_render_confirmation(payload, reviewers=reviewer_emails or None, message=message))

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
            # V4 shares are project-scoped — locate the first file (probing
            # all visible accounts) and take its project_id.
            account_id, file_meta = find_file(client, cfg, file_ids[0])
            project_id = file_meta.get("project_id")
            if not project_id:
                raise FrameioAgentError(
                    f"Could not resolve project_id for file {file_ids[0]}.",
                    remediation="Verify the file_id with `latest` or `search`.",
                )
            raw = api.create_share(client, account_id, project_id, payload)
    except FrameioAgentError as e:
        rendered = e.render()
        lowered = rendered.lower()
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
        if "scope" in lowered or "insufficient" in lowered:
            # API-side scope rejections arrive as ApiError (a FrameioAgentError).
            print(
                "Error: Frame.io rejected the share request (insufficient OAuth scope).",
                file=sys.stderr,
            )
            print("  > Run: frameio-agent auth login", file=sys.stderr)
            return 1
        print(f"Error: {rendered}", file=sys.stderr)
        return 1

    normalized = _normalize_share_response(raw, payload)

    # Optionally add email reviewers — second mutation, separately surfaced.
    reviewer_status: Optional[str] = None
    if reviewer_emails and normalized.get("share_id"):
        try:
            with FrameioClient(cfg) as client:
                # account_id was resolved during share creation above.
                api.add_reviewers_to_share(
                    client, account_id, normalized["share_id"],
                    emails=reviewer_emails, message=message,
                )
            reviewer_status = "added"
        except FrameioAgentError as e:
            reviewer_status = f"failed: {e.render()}"

    normalized["reviewers_added"] = reviewer_emails if reviewer_status == "added" else []
    normalized["reviewer_status"] = reviewer_status

    if as_json:
        emit(normalized, True)
    else:
        print()
        print("Share created.")
        print(f"  URL:    {normalized['url']}")
        print(f"  ID:     {normalized['share_id']}")
        print(f"  Assets: {normalized['asset_count']}")
        if reviewer_status == "added":
            print(f"  Reviewers: notified {len(reviewer_emails)} email(s)")
        elif reviewer_status and reviewer_status.startswith("failed"):
            print(f"  Reviewers: {reviewer_status}", file=sys.stderr)
    return 0
