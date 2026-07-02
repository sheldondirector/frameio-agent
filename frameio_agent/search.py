"""Account-wide search via Frame.io V4's POST /accounts/{id}/search.

Replaces the v0.3 folder-traversal implementation. The V4 search endpoint
hits all of your projects, folders, and files/version-stacks in one call
and supports two engines:

  * ``lexical`` — keyword match (default; fast, predictable)
  * ``nlp``     — natural-language query (e.g. "red car driving on highway")

Output shape per :data:`AGENTS.md`:
    {
      "query": "...",
      "engine": "lexical",
      "total_count": 42,
      "results": [
        {
          "type": "file" | "version_stack" | "folder" | "project",
          "id": "...",
          "name": "...",
          "project_id": "...",
          "view_url": "https://next.frame.io/...",
          "created_at": "...",
          "updated_at": "...",
          "matches": [...]   # match-term highlight info from V4
        }
      ]
    }
"""
from __future__ import annotations

import sys
from typing import Any, Callable, Optional

from . import api
from .client import FrameioClient
from .config import load_config
from .errors import FrameioAgentError


def _normalize_search_result(raw: dict[str, Any]) -> dict[str, Any]:
    """Flatten the V4 search result envelope ({result:{...}, matches:[...]}) ."""
    inner = raw.get("result") or {}
    return {
        "type": inner.get("type"),
        "id": inner.get("id"),
        "name": inner.get("name"),
        "project_id": inner.get("project_id"),
        "parent_id": inner.get("parent_id"),
        "created_at": inner.get("created_at"),
        "updated_at": inner.get("updated_at"),
        "view_url": inner.get("view_url"),
        "matches": raw.get("matches") or [],
    }


def cmd_search(
    *,
    query: str,
    engine: str,
    files: bool,
    folders: bool,
    projects: bool,
    limit: int,
    account: Optional[str],
    as_json: bool,
    emit: Callable[[Any, bool], None],
) -> int:
    if not query.strip():
        print("Error: query is required.", file=sys.stderr)
        return 2
    if engine not in ("lexical", "nlp"):
        print("Error: --engine must be 'lexical' or 'nlp'.", file=sys.stderr)
        return 2
    if not (files or folders or projects):
        print("Error: at least one of files/folders/projects must be enabled.", file=sys.stderr)
        return 2

    cfg = load_config()
    try:
        with FrameioClient(cfg) as client:
            account_id = account or cfg.default_account_id
            if not account_id:
                accounts = api.list_accounts(client)
                if not accounts:
                    raise FrameioAgentError(
                        "No Frame.io accounts visible.",
                        remediation="Run: frameio-agent verify",
                    )
                account_id = accounts[0].get("id") or accounts[0].get("account_id")
            raw_results = api.search_account(
                client, account_id,
                query=query, engine=engine,
                files=files, folders=folders, projects=projects,
                limit=limit,
            )
    except FrameioAgentError as e:
        print(f"Error: {e.render()}", file=sys.stderr)
        return 1

    results = [_normalize_search_result(r) for r in raw_results]
    payload = {
        "query": query,
        "engine": engine,
        "result_count": len(results),
        "results": results,
    }
    if as_json:
        emit(payload, True)
    else:
        if not results:
            print(f"No matches for '{query}' (engine={engine}).")
            print("  > Try a different engine (--nlp or --engine lexical), or broaden the query.")
            return 0
        print(f"Matches for '{query}' (engine={engine}, {len(results)} shown):")
        for r in results:
            kind = r.get("type") or "?"
            name = r.get("name") or "(no name)"
            print(f"  [{kind:<14}] {name}")
            if r.get("id"):
                print(f"                  id: {r['id']}")
            if r.get("view_url"):
                print(f"                  url: {r['view_url']}")
    return 0
