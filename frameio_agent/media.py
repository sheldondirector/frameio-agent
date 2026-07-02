"""Shared media layer: collect files + fetch their frames/thumbnails.

This is the foundation of the *vision* features. The design principle
(matching the PRD's "the tool is dumb, the agent is smart"):

    The CLI does NOT judge images. It extracts Frame.io's pixels to local
    files + a manifest, and hands them to whatever multimodal agent the
    user runs. The agent sees; the agent decides; the agent drives the
    next command (share create, contact-sheet --exclude, etc.).

That keeps vision model-agnostic (Claude, GPT-4o, Gemini — any agent that
can read an image), free (no embedded vision API / key), and safe (the
CLI still only reads Frame.io + writes local files).

Both :mod:`frames` and :mod:`contact_sheet` build on this module. It is
PIL-free on purpose — downloading raw bytes needs no image library, so
`frames pull` works without the optional ``[images]`` extra.
"""
from __future__ import annotations

from typing import Any, Optional

import httpx

from . import api
from .client import FrameioClient
from .errors import FrameioAgentError


# Frame.io nests preview imagery under media_links; field names vary by asset.
THUMBNAIL_FIELDS: tuple[str, ...] = (
    "thumb", "thumbnail", "poster", "small_thumbnail", "efficient", "icon",
)

VISUAL_MEDIA_PREFIXES = ("video/", "image/")


def extract_thumbnail_url(file_meta: dict[str, Any]) -> Optional[str]:
    """Find a preview-image URL in a File response.

    V4 usually nests these under ``media_links`` as either a dict with a
    ``download_url``/``url``/``href`` or a bare string. A few payloads put
    a flat field at the top level. We try, in order of preference.
    """
    media_links = file_meta.get("media_links") or {}
    for field in THUMBNAIL_FIELDS:
        v = media_links.get(field)
        if isinstance(v, dict):
            url = v.get("download_url") or v.get("url") or v.get("href")
            if url:
                return url
        elif isinstance(v, str) and v:
            return v
    for field in THUMBNAIL_FIELDS:
        v = file_meta.get(field)
        if isinstance(v, str) and v:
            return v
    return None


def collect_files(
    client: FrameioClient,
    account_id: str,
    *,
    project_id: Optional[str],
    folder_id: Optional[str],
    max_files: int,
    visual_only: bool = True,
) -> list[dict[str, Any]]:
    """BFS-walk a project or folder, returning file assets.

    Version stacks are unwrapped to their head_version so downstream code
    always gets a real file_id. When ``visual_only`` is set, audio / PDF /
    other non-image, non-video media is skipped. Caps at ``max_files``.
    """
    if folder_id:
        roots = [folder_id]
    elif project_id:
        project = api.get_project(client, account_id, project_id)
        root = project.get("root_folder_id") or project.get("root_asset_id")
        if not root:
            raise FrameioAgentError(
                f"Project {project_id} has no root folder.",
                remediation="Verify the project ID with `projects --json`.",
            )
        roots = [root]
    else:
        raise FrameioAgentError(
            "Need --project or --folder.",
            remediation="Pass --project <id> or --folder <id>.",
        )

    collected: list[dict[str, Any]] = []
    queue = list(roots)
    seen_folders = 0
    max_folders = 400  # safety valve on deep trees

    while queue and len(collected) < max_files and seen_folders < max_folders:
        fid = queue.pop(0)
        seen_folders += 1
        for child in api.list_folder_children(client, account_id, fid):
            kind = child.get("type") or child.get("kind") or ""
            if kind == "folder":
                child_id = child.get("id") or child.get("folder_id")
                if child_id:
                    queue.append(child_id)
                continue
            if kind == "version_stack":
                stack_id = child.get("id")
                if not stack_id:
                    continue
                try:
                    stack = api.get_version_stack(client, account_id, stack_id)
                except Exception:
                    continue
                head = stack.get("head_version") or {}
                if head.get("id"):
                    head = dict(head)
                    head["_display_name"] = child.get("name") or head.get("name")
                    if _is_visual(head, visual_only):
                        collected.append(head)
                        if len(collected) >= max_files:
                            break
                continue
            # kind == "file"
            if _is_visual(child, visual_only):
                collected.append(child)
                if len(collected) >= max_files:
                    break
    return collected


def _is_visual(child: dict[str, Any], visual_only: bool) -> bool:
    if not visual_only:
        return True
    mt = (child.get("media_type") or "").lower()
    if not mt:
        return True  # unknown at list level — be permissive
    return mt.startswith(VISUAL_MEDIA_PREFIXES)


def fetch_thumb(
    client: FrameioClient,
    account_id: str,
    file_id: str,
) -> tuple[str, Optional[str], Optional[str]]:
    """Return (file_id, name, thumbnail_url). URL is None if unavailable."""
    try:
        meta = api.get_file(client, account_id, file_id)
    except FrameioAgentError:
        return file_id, None, None
    return file_id, meta.get("name"), extract_thumbnail_url(meta)


def download_bytes(url: str, *, timeout: float = 30.0) -> Optional[bytes]:
    """Download a URL and return raw bytes, or None on failure. PIL-free."""
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        if resp.status_code != 200 or not resp.content:
            return None
        return resp.content
    except httpx.HTTPError:
        return None


def resolve_account(
    client: FrameioClient,
    *,
    project_id: Optional[str] = None,
    configured_default: Optional[str] = None,
) -> str:
    """Resolve an account_id: configured default -> project owner -> first visible."""
    if configured_default:
        return configured_default
    if project_id:
        # Scan visible projects to find the owner account.
        for acct in api.list_accounts(client):
            acct_id = acct.get("id") or acct.get("account_id")
            if not acct_id:
                continue
            for ws in api.list_workspaces(client, acct_id):
                ws_id = ws.get("id") or ws.get("workspace_id")
                if not ws_id:
                    continue
                for proj in api.list_projects(client, acct_id, ws_id):
                    if (proj.get("id") or proj.get("project_id")) == project_id:
                        return acct_id
    accounts = api.list_accounts(client)
    if not accounts:
        raise FrameioAgentError(
            "No Frame.io accounts visible.",
            remediation="Run: frameio-agent verify",
        )
    acct_id = accounts[0].get("id") or accounts[0].get("account_id")
    if not acct_id:
        raise FrameioAgentError(
            "Could not resolve an account_id.",
            remediation="Set FRAMEIO_ACCOUNT_ID in .env.",
        )
    return acct_id
