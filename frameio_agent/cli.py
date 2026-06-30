"""Frame.io Agent Starter — CLI entry point.

Routing only. Each subcommand delegates to a module in the package. Every
command supports ``--json``; human output is the default for terminals.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import __version__


def _emit(payload: Any, as_json: bool) -> None:
    """Print payload as JSON (machine) or text (human)."""
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=False))
    else:
        if isinstance(payload, str):
            print(payload)
        else:
            print(json.dumps(payload, indent=2, sort_keys=False))


def _add_json_flag(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="Emit JSON instead of human text.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="frameio-agent",
        description=(
            "Give your coding agent safe, read-only access to your Frame.io projects. "
            "Run `frameio-agent auth login` first."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # auth
    auth = sub.add_parser("auth", help="Authentication subcommands.")
    auth_sub = auth.add_subparsers(dest="auth_command", metavar="<subcommand>")

    auth_login = auth_sub.add_parser(
        "login",
        help="Guided Adobe IMS OAuth wizard (PKCE + loopback). Walks first-timers through Adobe Developer Console setup.",
    )
    auth_login.add_argument("--port", type=int, default=None, help="Loopback port (default: from FRAMEIO_REDIRECT_URI).")
    auth_login.add_argument("--no-browser", action="store_true", help="Print the authorize URL instead of opening a browser.")

    auth_status = auth_sub.add_parser("status", help="Show whether auth tokens are present and valid (no secrets printed).")
    _add_json_flag(auth_status)

    # verify
    verify = sub.add_parser("verify", help="Confirm Frame.io connectivity. Exits 0 on success.")
    _add_json_flag(verify)

    # projects
    projects = sub.add_parser("projects", help="List accounts / workspaces / projects visible to you.")
    projects.add_argument("--account", help="Filter by account_id.")
    projects.add_argument("--workspace", help="Filter by workspace_id.")
    _add_json_flag(projects)

    # latest
    latest = sub.add_parser("latest", help="Most-recently-updated video assets in a project (the demo command).")
    latest.add_argument("--project", required=True, help="Project ID.")
    latest.add_argument("--limit", type=int, default=5, help="Max results (default: 5).")
    _add_json_flag(latest)

    # search
    search = sub.add_parser("search", help="Capped name/path search across a project.")
    search.add_argument("query", help="Substring to match against asset names.")
    search.add_argument("--project", required=True, help="Project ID.")
    search.add_argument("--limit", type=int, default=20, help="Max results (default: 20).")
    search.add_argument("--max-folders", type=int, default=200, help="Folder traversal cap (default: 200).")
    search.add_argument("--max-assets", type=int, default=1000, help="Asset traversal cap (default: 1000).")
    _add_json_flag(search)

    # comments
    comments = sub.add_parser("comments", help="Fetch normalized review comments for a file (text + timecode + author).")
    comments.add_argument("file_id", help="File ID to fetch comments for.")
    comments.add_argument("--by-timecode", action="store_true", help="Sort comments ascending by timestamp_seconds.")
    _add_json_flag(comments)

    # brief
    brief = sub.add_parser("brief", help="One-paragraph project status (recent assets + likely next actions).")
    brief.add_argument("--project", required=True, help="Project ID.")
    _add_json_flag(brief)

    # share (the one mutation — gated by confirmation; see PRD §11.8)
    share = sub.add_parser("share", help="Create a Frame.io review share (the only mutation in v1).")
    share_sub = share.add_subparsers(dest="share_command", metavar="<subcommand>")
    share_create = share_sub.add_parser(
        "create",
        help="Bundle one or more assets into a review share and return the URL.",
    )
    share_create.add_argument("file_ids", nargs="+", help="One or more file IDs to include in the share.")
    share_create.add_argument("--name", required=True, help="Human label for the share (shown in Frame.io).")
    share_create.add_argument(
        "--allow-comments", dest="allow_comments", action="store_true", default=True,
        help="Allow recipients to leave comments (default).",
    )
    share_create.add_argument(
        "--no-comments", dest="allow_comments", action="store_false",
        help="Disallow comments from recipients.",
    )
    share_create.add_argument(
        "--allow-download", dest="allow_download", action="store_true", default=False,
        help="Allow recipients to download originals.",
    )
    share_create.add_argument(
        "--no-download", dest="allow_download", action="store_false",
        help="Disallow downloads (default).",
    )
    share_create.add_argument("--expires", dest="expires_at", default=None, help="Optional ISO date for expiration.")
    share_create.add_argument("--password", default=None, help="Optional password protection (never echoed).")
    share_create.add_argument(
        "--public", dest="public", action="store_true", default=True,
        help="Anyone with the URL can view (default).",
    )
    share_create.add_argument(
        "--restricted", dest="public", action="store_false",
        help="Only signed-in Frame.io users can view.",
    )
    share_create.add_argument(
        "--yes", action="store_true",
        help="Skip the y/N confirmation. Only use when the user has explicitly authorized this share.",
    )
    _add_json_flag(share_create)

    # mcp (optional layer)
    sub.add_parser("mcp", help="Run as an MCP server (optional; CLI works without it).")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    # Lazy imports so --help is fast and runs without httpx etc.
    try:
        if args.command == "auth":
            if args.auth_command == "login":
                from .auth import cmd_login
                return cmd_login(port=args.port, no_browser=args.no_browser)
            if args.auth_command == "status":
                from .auth import cmd_status
                return cmd_status(as_json=args.json, emit=_emit)
            parser.parse_args(["auth", "--help"])
            return 2

        if args.command == "verify":
            from .listing import cmd_verify
            return cmd_verify(as_json=args.json, emit=_emit)

        if args.command == "projects":
            from .listing import cmd_projects
            return cmd_projects(account=args.account, workspace=args.workspace, as_json=args.json, emit=_emit)

        if args.command == "latest":
            from .listing import cmd_latest
            return cmd_latest(project=args.project, limit=args.limit, as_json=args.json, emit=_emit)

        if args.command == "search":
            from .search import cmd_search
            return cmd_search(
                query=args.query,
                project=args.project,
                limit=args.limit,
                max_folders=args.max_folders,
                max_assets=args.max_assets,
                as_json=args.json,
                emit=_emit,
            )

        if args.command == "comments":
            from .comments import cmd_comments
            return cmd_comments(file_id=args.file_id, by_timecode=args.by_timecode, as_json=args.json, emit=_emit)

        if args.command == "brief":
            from .brief import cmd_brief
            return cmd_brief(project=args.project, as_json=args.json, emit=_emit)

        if args.command == "share":
            if args.share_command == "create":
                from .shares import cmd_share_create
                return cmd_share_create(
                    file_ids=args.file_ids,
                    name=args.name,
                    allow_comments=args.allow_comments,
                    allow_download=args.allow_download,
                    expires_at=args.expires_at,
                    password=args.password,
                    public=args.public,
                    yes=args.yes,
                    as_json=args.json,
                    emit=_emit,
                )
            parser.parse_args(["share", "--help"])
            return 2

        if args.command == "mcp":
            try:
                from .optional.mcp_server import run as mcp_run
            except ModuleNotFoundError:
                print(
                    "MCP server module not installed. Run: pip install '.[mcp]'",
                    file=sys.stderr,
                )
                return 2
            return mcp_run()

    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        return 130

    parser.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
