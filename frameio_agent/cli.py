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
            "Run Frame.io from your coding agent. Read-only by default; mutations "
            "(share create, refs add) are confirmation-gated. "
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
        help="Guided Adobe IMS OAuth wizard (PKCE; captures the redirect from your clipboard automatically). Walks first-timers through Adobe Developer Console setup.",
    )
    auth_login.add_argument("--port", type=int, default=None, help="Loopback port (default: from FRAMEIO_REDIRECT_URI).")
    auth_login.add_argument("--no-browser", action="store_true", help="Print the authorize URL instead of opening a browser.")
    auth_login.add_argument(
        "--manual", action="store_true",
        help="Skip the loopback server; print the authorize URL and accept a pasted redirect URL or code. Use when Adobe redirects to a URI we can't capture (e.g. https://localhost).",
    )

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

    # search (account-wide, uses POST /search)
    search = sub.add_parser("search", help="Account-wide search across all your projects, folders, and files.")
    search.add_argument("query", help="Search query. Use --nlp for natural-language matching.")
    search.add_argument(
        "--engine",
        choices=("lexical", "nlp"),
        default="lexical",
        help="Search engine: 'lexical' (default, keyword match) or 'nlp' (natural language).",
    )
    search.add_argument("--nlp", dest="engine", action="store_const", const="nlp",
                        help="Shortcut for --engine nlp.")
    search.add_argument("--no-files", dest="files", action="store_false", default=True,
                        help="Exclude files and version-stacks.")
    search.add_argument("--no-folders", dest="folders", action="store_false", default=True,
                        help="Exclude folders.")
    search.add_argument("--no-projects", dest="projects", action="store_false", default=True,
                        help="Exclude projects.")
    search.add_argument("--account", help="Account ID. Defaults to FRAMEIO_ACCOUNT_ID or the first visible account.")
    search.add_argument("--limit", type=int, default=25, help="Max results (default: 25).")
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

    # frames (vision primitive: give the agent eyes)
    frames = sub.add_parser(
        "frames",
        help="Extract preview frames to local disk so a multimodal agent can look at them.",
    )
    frames_sub = frames.add_subparsers(dest="frames_command", metavar="<subcommand>")
    frames_pull = frames_sub.add_parser(
        "pull",
        help="Download one preview frame per clip + a manifest.json mapping images back to file_ids.",
    )
    frames_pull.add_argument("--project", help="Project ID. Either --project or --folder is required.")
    frames_pull.add_argument("--folder", help="Folder ID. Walks recursively.")
    frames_pull.add_argument("--out", required=True, help="Output directory for frames + manifest.json.")
    frames_pull.add_argument("--max-files", type=int, default=100, help="Cap on files to include (default: 100).")
    frames_pull.add_argument("--parallel", type=int, default=8, help="Concurrent downloads (default: 8).")
    _add_json_flag(frames_pull)

    # contact-sheet (founder-tier: PIL composite of thumbnails)
    contact = sub.add_parser(
        "contact-sheet",
        help="Composite thumbnails from a project or folder into a single PNG grid.",
    )
    contact.add_argument("--project", help="Project ID. One of --project / --folder / --from-manifest is required.")
    contact.add_argument("--folder", help="Folder ID. Walks recursively.")
    contact.add_argument(
        "--from-manifest",
        help="Build offline from a `frames pull` manifest.json (path to the file or its directory). No Frame.io calls.",
    )
    contact.add_argument("--only", help="Comma-separated file_ids to include (drop everything else).")
    contact.add_argument("--exclude", help="Comma-separated file_ids to leave out (e.g. rejected takes).")
    contact.add_argument("--out", required=True, help="Output PNG path.")
    contact.add_argument("--cols", type=int, default=6, help="Grid columns (default: 6).")
    contact.add_argument("--tile-size", type=int, default=240, help="Max tile width/height in px (default: 240).")
    contact.add_argument("--max-files", type=int, default=100, help="Cap on files to include (default: 100).")
    contact.add_argument("--no-labels", action="store_true", help="Omit filename labels under each tile.")
    contact.add_argument("--index", action="store_true", help="Number each tile + write a sidecar <out>.index.json.")
    contact.add_argument("--parallel", type=int, default=8, help="Concurrent downloads (default: 8).")
    _add_json_flag(contact)

    # refs (founder-tier: pull a reference into Frame.io)
    refs = sub.add_parser("refs", help="Pull a reference into a Frame.io folder (local file, direct URL, or YouTube/X).")
    refs_sub = refs.add_subparsers(dest="refs_command", metavar="<subcommand>")
    refs_add = refs_sub.add_parser("add", help="Add a reference to a folder. Auto-detects local / remote / yt-dlp.")
    refs_add.add_argument("source", help="Local path, direct URL, or YouTube/Vimeo/X/TikTok URL.")
    refs_add.add_argument("--folder", required=True, help="Target Frame.io folder ID.")
    refs_add.add_argument("--name", default=None, help="Override the file name shown in Frame.io.")
    refs_add.add_argument(
        "--via", choices=("local", "remote_upload", "yt_dlp"), default=None,
        help="Force a specific upload mode. Default: auto-detect.",
    )
    refs_add.add_argument("--yes", action="store_true", help="Skip the y/N confirmation.")
    _add_json_flag(refs_add)

    # share (confirmation-gated mutation; see PRD §11.8)
    share = sub.add_parser("share", help="Create a Frame.io review share (confirmation-gated).")
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
        "--reviewers", default=None,
        help="Comma-separated email addresses to notify (max 10). They get a Frame.io invite to view this share.",
    )
    share_create.add_argument(
        "--message", default=None,
        help="Optional message included in the reviewer notification email.",
    )
    share_create.add_argument(
        "--yes", action="store_true",
        help="Skip the y/N confirmation. Only use when the user has explicitly authorized this share.",
    )
    _add_json_flag(share_create)

    # mcp (optional layer)
    sub.add_parser("mcp", help="Run as an MCP server (optional; CLI works without it).")

    # Keep subparser references so main() can print group help WITHOUT the
    # SystemExit(0) that argparse's --help action raises (a bare
    # `frameio-agent frames` must exit 2, not 0).
    parser._group_parsers = {"auth": auth, "frames": frames, "refs": refs, "share": share}  # type: ignore[attr-defined]
    return parser


def _group_help(parser: argparse.ArgumentParser, command: str) -> int:
    """Print a command group's help and exit nonzero (missing subcommand)."""
    group = getattr(parser, "_group_parsers", {}).get(command)
    if group is not None:
        group.print_help(sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    # Windows consoles fall back to legacy codepages (cp1252/cp437) when
    # output is piped or redirected; API-derived text (comments, file names,
    # author names) is arbitrary Unicode. Degrade unencodable characters
    # instead of crashing with UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except (ValueError, OSError):  # pragma: no cover - closed/odd streams
                pass

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
                return cmd_login(port=args.port, no_browser=args.no_browser, manual=args.manual)
            if args.auth_command == "status":
                from .auth import cmd_status
                return cmd_status(as_json=args.json, emit=_emit)
            return _group_help(parser, "auth")

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
                engine=args.engine,
                files=args.files,
                folders=args.folders,
                projects=args.projects,
                account=args.account,
                limit=args.limit,
                as_json=args.json,
                emit=_emit,
            )

        if args.command == "comments":
            from .comments import cmd_comments
            return cmd_comments(file_id=args.file_id, by_timecode=args.by_timecode, as_json=args.json, emit=_emit)

        if args.command == "brief":
            from .brief import cmd_brief
            return cmd_brief(project=args.project, as_json=args.json, emit=_emit)

        if args.command == "frames":
            if args.frames_command == "pull":
                from .frames import cmd_frames_pull
                return cmd_frames_pull(
                    project=args.project,
                    folder=args.folder,
                    out=args.out,
                    max_files=args.max_files,
                    parallel=args.parallel,
                    as_json=args.json,
                    emit=_emit,
                )
            return _group_help(parser, "frames")

        if args.command == "contact-sheet":
            from .contact_sheet import cmd_contact_sheet
            return cmd_contact_sheet(
                project=args.project,
                folder=args.folder,
                from_manifest=args.from_manifest,
                only=args.only,
                exclude=args.exclude,
                out=args.out,
                cols=args.cols,
                tile_size=args.tile_size,
                max_files=args.max_files,
                no_labels=args.no_labels,
                index=args.index,
                parallel=args.parallel,
                as_json=args.json,
                emit=_emit,
            )

        if args.command == "refs":
            if args.refs_command == "add":
                from .refs import cmd_refs_add
                return cmd_refs_add(
                    source=args.source,
                    folder=args.folder,
                    name=args.name,
                    via=args.via,
                    yes=args.yes,
                    as_json=args.json,
                    emit=_emit,
                )
            return _group_help(parser, "refs")

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
                    reviewers=args.reviewers,
                    message=args.message,
                )
            return _group_help(parser, "share")

        if args.command == "mcp":
            try:
                from .optional.mcp_server import run as mcp_run
            except ModuleNotFoundError:
                print(
                    'MCP server module not installed. Run: pip install "frameio-agent[mcp]"',
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
