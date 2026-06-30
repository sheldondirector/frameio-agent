"""Capped name/path search across a project's folder tree.

Recency-first ``latest`` is the headline command. This is the fallback for
finding a *named* asset when the user knows what they're looking for. Caps
prevent runaway traversal on big projects.
"""
from __future__ import annotations

import sys
from typing import Any, Callable, Optional

from . import api
from .client import FrameioClient
from .config import load_config
from .errors import FrameioAgentError, TraversalCapError
from .listing import _normalize_file, _resolve_account_for_project


def _walk(
    client: FrameioClient,
    account_id: str,
    root_folder: str,
    *,
    max_folders: int,
    max_assets: int,
) -> list[tuple[str, dict[str, Any]]]:
    """Yield (folder_path, asset) tuples up to the caps."""
    out: list[tuple[str, dict[str, Any]]] = []
    queue: list[tuple[str, str]] = [("", root_folder)]
    seen_folders = 0
    seen_assets = 0
    while queue:
        path, folder_id = queue.pop(0)
        seen_folders += 1
        if seen_folders > max_folders:
            raise TraversalCapError(
                "Traversal cap reached.",
                remediation="Try `latest` instead, or narrow with --max-folders / --folder.",
            )
        for child in api.list_folder_children(client, account_id, folder_id):
            seen_assets += 1
            if seen_assets > max_assets:
                raise TraversalCapError(
                    "Traversal cap reached.",
                    remediation="Try `latest` instead, or narrow with --max-assets / --folder.",
                )
            kind = child.get("type") or child.get("kind") or ""
            name = child.get("name") or ""
            if kind == "folder":
                child_id = child.get("id") or child.get("folder_id")
                if child_id:
                    queue.append((f"{path}/{name}" if path else name, child_id))
                continue
            out.append((path, child))
    return out


def cmd_search(
    *,
    query: str,
    project: str,
    limit: int,
    max_folders: int,
    max_assets: int,
    as_json: bool,
    emit: Callable[[Any, bool], None],
) -> int:
    cfg = load_config()
    q = query.lower()
    try:
        with FrameioClient(cfg) as client:
            account_id = _resolve_account_for_project(client, project)
            project_meta = api.get_project(client, account_id, project)
            root = project_meta.get("root_folder_id") or project_meta.get("root_asset_id")
            if not root:
                raise FrameioAgentError(
                    f"Project {project} has no root folder.",
                    remediation="Verify the project ID with `projects --json`.",
                )
            walked = _walk(
                client, account_id, root,
                max_folders=max_folders, max_assets=max_assets,
            )
    except FrameioAgentError as e:
        print(f"Error: {e.render()}", file=sys.stderr)
        return 1

    matched: list[dict[str, Any]] = []
    for folder_path, child in walked:
        name = (child.get("name") or "").lower()
        if q in name or q in folder_path.lower():
            normalized = _normalize_file(account_id, child)
            normalized["folder_path"] = folder_path
            normalized["project_name"] = project_meta.get("name") or ""
            matched.append(normalized)
            if len(matched) >= limit:
                break

    payload = {"query": query, "project_id": project, "results": matched}
    if as_json:
        emit(payload, True)
    else:
        if not matched:
            print(f"No matches for '{query}' in project {project}.")
            print("  > Try `latest` or list projects first.")
            return 0
        print(f"Matches for '{query}' in project {project}:")
        for r in matched:
            print(f"  - {r['name']}  ({r['folder_path']})")
            print(f"    file_id: {r['file_id']}  comments: {r['comments_count']}")
    return 0
