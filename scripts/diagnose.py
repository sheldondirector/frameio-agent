"""Diagnostic script: hits Frame.io V4 endpoints with the cached token and
dumps raw responses. Run when an `api.py` endpoint guess is wrong.

Usage:
  python scripts/diagnose.py <project_id>
"""
from __future__ import annotations

import json
import sys

import httpx

from frameio_agent.auth import get_access_token
from frameio_agent.config import load_config


def dump(label: str, resp: httpx.Response) -> None:
    print(f"\n=== {label} ===")
    print(f"GET {resp.request.url}")
    print(f"HTTP {resp.status_code}")
    try:
        body = resp.json()
        print(json.dumps(body, indent=2)[:2000])
    except ValueError:
        print((resp.text or "")[:2000])


def main(project_id: str) -> int:
    cfg = load_config()
    token, cache = get_access_token(cfg)
    headers = {
        "Authorization": f"Bearer {token}",
        "x-api-key": cfg.client_id or "",
        "Accept": "application/json",
    }
    base = cfg.api_base

    with httpx.Client(timeout=30.0, headers=headers) as client:
        # 1. Get the account
        accts = client.get(f"{base}/accounts").json()
        acct = (accts.get("data") or accts.get("accounts") or [{}])[0]
        account_id = acct.get("id") or acct.get("account_id")
        print(f"Using account_id: {account_id}")

        # 2. Project detail (need root_folder_id)
        proj_resp = client.get(f"{base}/accounts/{account_id}/projects/{project_id}")
        dump("project detail", proj_resp)
        proj = proj_resp.json().get("data") or proj_resp.json()
        root = proj.get("root_folder_id") or proj.get("root_asset_id")
        print(f"\nroot folder: {root}")

        if not root:
            print("No root folder found — stopping.")
            return 1

        # 3. Try the children endpoint a few different ways
        candidates = [
            ("children (no params)",  f"/accounts/{account_id}/folders/{root}/children", {}),
            ("children (page_size)",  f"/accounts/{account_id}/folders/{root}/children", {"page_size": 10}),
            ("children (limit)",      f"/accounts/{account_id}/folders/{root}/children", {"limit": 10}),
            ("children (page[size])", f"/accounts/{account_id}/folders/{root}/children", {"page[size]": 10}),
            ("items (alt path)",      f"/accounts/{account_id}/folders/{root}/items",    {}),
        ]
        for label, path, params in candidates:
            try:
                r = client.get(f"{base}{path}", params=params)
                dump(label, r)
                if r.status_code == 200:
                    print(f"\n*** {label} WORKED — use this shape ***")
                    break
            except Exception as e:
                print(f"\n=== {label} === EXCEPTION: {type(e).__name__}: {e}")

        # 4. Try the search endpoint
        search_paths = [
            f"/accounts/{account_id}/projects/{project_id}/search",
            f"/accounts/{account_id}/projects/{project_id}/files",
            f"/accounts/{account_id}/projects/{project_id}/assets",
        ]
        for path in search_paths:
            try:
                r = client.get(f"{base}{path}", params={"sort": "-updated_at"})
                dump(f"search variant: {path}", r)
                if r.status_code == 200:
                    print(f"\n*** {path} WORKED ***")
            except Exception as e:
                print(f"=== {path} === EXCEPTION: {type(e).__name__}: {e}")

    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/diagnose.py <project_id>")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
