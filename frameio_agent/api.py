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
    *,
    page_size: int = 50,
) -> Iterator[dict[str, Any]]:
    """Yield every direct child (folder or file) of a folder, paginated."""
    yield from client.paginate(
        f"/accounts/{account_id}/folders/{folder_id}/children",
        page_size=page_size,
    )


def get_file(client: FrameioClient, account_id: str, file_id: str) -> dict[str, Any]:
    payload = client.get(f"/accounts/{account_id}/files/{file_id}")
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

    Uses the project search endpoint with sort=-updated_at. If your V4
    deployment doesn't expose this exact shape, this is the single place
    to change it.
    """
    params: dict[str, Any] = {
        "sort": "-updated_at",
        "page_size": limit,
        "type": "file",
    }
    if media_type:
        params["media_type"] = media_type
    payload = client.get(
        f"/accounts/{account_id}/projects/{project_id}/search",
        params=params,
        accept_status=(200, 404),  # 404 is the "endpoint missing" signal
    )
    items = payload.get("data") or payload.get("results") or []
    if items:
        return items[:limit]
    # Fallback: walk from the project root recursively (capped).
    return _recent_via_traversal(client, account_id, project_id, media_type=media_type, limit=limit)


def _recent_via_traversal(
    client: FrameioClient,
    account_id: str,
    project_id: str,
    *,
    media_type: Optional[str],
    limit: int,
    max_folders: int = 60,
    max_assets: int = 600,
) -> list[dict[str, Any]]:
    """Conservative fallback when the search endpoint isn't available.

    Walks the project's folder tree, collects file assets, sorts by
    updated_at desc, and returns the top ``limit``. Caps prevent runaway
    traversals on big projects — `latest` should not need this on production
    V4, but the fallback keeps the demo path usable.
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
            if media_type and child.get("media_type") not in (media_type, None):
                continue
            files.append(child)

    files.sort(key=lambda f: f.get("updated_at") or "", reverse=True)
    return files[:limit]


# ──────────────────────────────────────────────────────────────────────────────
# Comments
# ──────────────────────────────────────────────────────────────────────────────

def list_comments(
    client: FrameioClient,
    account_id: str,
    file_id: str,
    *,
    page_size: int = 50,
) -> list[dict[str, Any]]:
    return list(
        client.paginate(
            f"/accounts/{account_id}/files/{file_id}/comments",
            page_size=page_size,
        )
    )


# ──────────────────────────────────────────────────────────────────────────────
# Share creation — the ONE mutation in v1 (see PRD §11.8)
# ──────────────────────────────────────────────────────────────────────────────

def create_share(
    client: FrameioClient,
    account_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    """POST a new review share. Body shape comes from shares.build_payload()."""
    payload = client.request(
        "POST",
        f"/accounts/{account_id}/shares",
        json_body=body,
        accept_status=(200, 201),
    )
    return payload.get("data") or payload
