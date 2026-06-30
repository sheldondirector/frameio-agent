"""Frame.io V4 REST endpoint wrappers.

Single source of truth for URL shapes and query parameters. The rest of the
package calls these helpers; nothing else should hardcode V4 paths.

If a path or parameter name proves wrong against the current V4 docs, fix
it here and downstream callers stay untouched. The logical surface is:

  * me (current user)
  * accounts -> workspaces -> projects
  * folder children (for traversal)
  * file detail
  * comments per file
"""
from __future__ import annotations

from typing import Any, Iterator, Optional

from .client import FrameioClient


# ──────────────────────────────────────────────────────────────────────────────
# User / orgs
# ──────────────────────────────────────────────────────────────────────────────

def get_me(client: FrameioClient) -> dict[str, Any]:
    """Return the current authenticated user."""
    return client.get("/me")


def list_accounts(client: FrameioClient) -> list[dict[str, Any]]:
    payload = client.get("/accounts")
    return payload.get("data") or payload.get("accounts") or []


def list_workspaces(client: FrameioClient, account_id: str) -> list[dict[str, Any]]:
    payload = client.get(f"/accounts/{account_id}/workspaces")
    return payload.get("data") or payload.get("workspaces") or []


def list_projects(client: FrameioClient, account_id: str, workspace_id: str) -> list[dict[str, Any]]:
    payload = client.get(f"/accounts/{account_id}/workspaces/{workspace_id}/projects")
    return payload.get("data") or payload.get("projects") or []


def get_project(client: FrameioClient, account_id: str, project_id: str) -> dict[str, Any]:
    payload = client.get(f"/accounts/{account_id}/projects/{project_id}")
    return payload.get("data") or payload


# ──────────────────────────────────────────────────────────────────────────────
# Folder traversal + file detail
# ──────────────────────────────────────────────────────────────────────────────

def list_folder_children(
    client: FrameioClient,
    account_id: str,
    folder_id: str,
) -> Iterator[dict[str, Any]]:
    """Yield every direct child (folder or file) of a folder.

    Verified against the live V4 API: this endpoint returns ``{"data": [...]}``
    and rejects pagination query params (HTTP 422). If the response includes
    a ``meta.next_cursor`` we follow it; otherwise one call returns everything.
    """
    yield from client.paginate(f"/accounts/{account_id}/folders/{folder_id}/children")


def get_file(client: FrameioClient, account_id: str, file_id: str) -> dict[str, Any]:
    payload = client.get(f"/accounts/{account_id}/files/{file_id}")
    return payload.get("data") or payload


def get_version_stack(client: FrameioClient, account_id: str, stack_id: str) -> dict[str, Any]:
    """Fetch a version_stack's detail. Use head_version.id for comments/file calls."""
    payload = client.get(f"/accounts/{account_id}/version_stacks/{stack_id}")
    return payload.get("data") or payload


def list_recent_files(
    client: FrameioClient,
    account_id: str,
    project_id: str,
    *,
    media_type: Optional[str] = "video",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return the most recently updated files in a project.

    Frame.io V4 has no project-wide list/search endpoint — verified against
    live API: /accounts/{id}/projects/{id}/search, /files, /assets all 404.
    The only path is folder traversal from the project's root folder.
    """
    return _recent_via_traversal(client, account_id, project_id, media_type=media_type, limit=limit)


def _recent_via_traversal(
    client: FrameioClient,
    account_id: str,
    project_id: str,
    *,
    media_type: Optional[str],
    limit: int,
    max_folders: int = 200,
    max_assets: int = 2000,
) -> list[dict[str, Any]]:
    """Walk the project's folder tree, collect file assets, sort by recency.

    Frame.io V4 returns children mixed: folders + files + version_stacks.
    We:
      * enqueue folders for recursion,
      * accept files as-is,
      * unwrap version_stacks to their head_version (one extra call each)
        so downstream `comments` / `share create` always get a real file_id.

    Caps prevent runaway traversal on very large projects.
    """
    project = get_project(client, account_id, project_id)
    root = project.get("root_folder_id") or project.get("root_asset_id")
    if not root:
        return []

    seen_folders = 0
    seen_assets = 0
    files: list[dict[str, Any]] = []
    queue: list[str] = [root]
    while queue and seen_folders < max_folders and seen_assets < max_assets:
        folder_id = queue.pop(0)
        seen_folders += 1
        for child in list_folder_children(client, account_id, folder_id):
            seen_assets += 1
            if seen_assets > max_assets:
                break
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
                    stack = get_version_stack(client, account_id, stack_id)
                except Exception:
                    continue
                head = stack.get("head_version") or {}
                if not head.get("id"):
                    continue
                # Take head_version's id/file_size/media_type, keep
                # version_stack's name (usually identical) + updated_at.
                merged = {
                    **head,
                    "name": child.get("name") or head.get("name"),
                    "updated_at": child.get("updated_at") or head.get("updated_at"),
                    "version_stack_id": stack_id,
                }
                if _passes_media_filter(merged, media_type):
                    files.append(merged)
                continue
            # kind == "file"
            if _passes_media_filter(child, media_type):
                files.append(child)

    files.sort(key=lambda f: f.get("updated_at") or "", reverse=True)
    return files[:limit]


def _passes_media_filter(child: dict[str, Any], media_type: Optional[str]) -> bool:
    """Apply media_type filter permissively. V4 uses MIME types like 'video/mp4'."""
    if not media_type:
        return True
    actual = child.get("media_type") or ""
    if not actual:
        return True  # be permissive when the field is missing
    # "video" matches "video/mp4", "video/quicktime", etc.
    return actual.startswith(f"{media_type}/") or actual == media_type


# ──────────────────────────────────────────────────────────────────────────────
# Comments
# ──────────────────────────────────────────────────────────────────────────────

def list_comments(
    client: FrameioClient,
    account_id: str,
    file_id: str,
) -> list[dict[str, Any]]:
    return list(client.paginate(f"/accounts/{account_id}/files/{file_id}/comments"))


# ──────────────────────────────────────────────────────────────────────────────
# Share creation — the ONE mutation in v1 (see PRD §11.8)
# ──────────────────────────────────────────────────────────────────────────────

def create_share(
    client: FrameioClient,
    account_id: str,
    project_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    """POST a new review share. Endpoint is project-scoped per V4 OpenAPI spec.

    Body must wrap fields in ``{"data": {"type": "asset", ...}}`` — the
    discriminator field ``type`` is required and currently has the single
    value ``"asset"``. ``access`` is ``"public"`` or ``"secure"``.
    """
    payload = client.request(
        "POST",
        f"/accounts/{account_id}/projects/{project_id}/shares",
        json_body=body,
        accept_status=(200, 201),
    )
    return payload.get("data") or payload
