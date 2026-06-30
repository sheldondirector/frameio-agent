"""`refs add` — pull a reference into a Frame.io folder.

Three input modes, auto-detected:

  * **Local path** -> ``POST /folders/{id}/files/local_upload`` then chunked
    PUT to Frame.io's pre-signed URLs.
  * **Direct URL Frame.io can fetch** (regular HTTP file URLs) ->
    ``POST .../remote_upload``; Frame.io fetches asynchronously.
  * **YouTube / Vimeo / X / TikTok / Instagram URL** -> shell out to
    ``yt-dlp`` to download to a temp file, then local_upload.

Auto-detection can be overridden with ``--via``. Every upload is
confirmation-gated unless ``--yes`` is passed (and `--yes` should only be
set when the user has explicitly authorized that specific upload).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

from . import api
from .client import FrameioClient
from .config import load_config
from .errors import FrameioAgentError


# Hosts where Frame.io's remote_upload almost certainly won't work
# (auth-gated streaming services). For these, default to yt-dlp.
YT_DLP_HOSTS: tuple[str, ...] = (
    "youtube.com", "youtu.be", "m.youtube.com",
    "vimeo.com",
    "x.com", "twitter.com", "t.co",
    "tiktok.com", "vm.tiktok.com",
    "instagram.com",
    "facebook.com", "fb.watch",
    "reddit.com",
    "twitch.tv",
)


def _looks_like_url(source: str) -> bool:
    return source.startswith(("http://", "https://"))


def _needs_yt_dlp(url: str) -> bool:
    """True if the URL host is a known streaming service that needs yt-dlp."""
    host = (urlsplit(url).hostname or "").lower().lstrip("www.")
    if host.startswith("www."):
        host = host[4:]
    return any(host == h or host.endswith("." + h) for h in YT_DLP_HOSTS)


def _detect_mode(source: str, via: Optional[str]) -> str:
    """Resolve to one of: 'local', 'remote_upload', 'yt_dlp'."""
    if via:
        return via
    if not _looks_like_url(source):
        return "local"
    return "yt_dlp" if _needs_yt_dlp(source) else "remote_upload"


def _default_name_from_source(source: str, mode: str) -> str:
    if mode == "local":
        return Path(source).name
    # URL — use last path segment or fall back to host
    parts = urlsplit(source)
    last = (parts.path.rsplit("/", 1)[-1] or parts.hostname or "reference").strip()
    return last or "reference"


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _render_confirmation(
    *,
    source: str,
    mode: str,
    name: str,
    folder_id: str,
    file_size: Optional[int],
) -> str:
    mode_label = {
        "local": "local upload (chunked PUT to Frame.io)",
        "remote_upload": "remote upload (Frame.io fetches the URL itself)",
        "yt_dlp": "yt-dlp download -> local upload",
    }.get(mode, mode)
    lines = [
        "About to add a reference to Frame.io:",
        f"  Source:   {source}",
        f"  Mode:     {mode_label}",
        f"  Name:     {name}",
        f"  Folder:   {folder_id}",
    ]
    if file_size is not None:
        lines.append(f"  Size:     {_human_bytes(file_size)}")
    return "\n".join(lines)


def _prompt_confirm() -> bool:
    try:
        answer = input("\nProceed? [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def _run_yt_dlp(source: str, dest_dir: Path) -> Path:
    """Download `source` via yt-dlp into dest_dir. Returns the downloaded file path."""
    if shutil.which("yt-dlp") is None:
        raise FrameioAgentError(
            "yt-dlp is not on PATH.",
            remediation="Install with: pip install '.[youtube]'  (or: pip install yt-dlp)",
        )

    # Ask yt-dlp to print the final filepath after the download succeeds.
    # %(filepath)s is yt-dlp's post-processing placeholder for the local file.
    cmd = [
        "yt-dlp",
        "--no-progress",
        "--no-warnings",
        "--restrict-filenames",
        "-f", "mp4/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
        "-o", str(dest_dir / "%(title)s.%(ext)s"),
        "--print", "after_move:filepath",
        source,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise FrameioAgentError(
            f"yt-dlp failed (exit {proc.returncode}): {proc.stderr.strip()[:300]}",
            remediation="Check the URL or try a different one. Some sites may require auth/cookies.",
        )
    out = proc.stdout.strip().splitlines()
    if not out:
        raise FrameioAgentError(
            "yt-dlp produced no output path.",
            remediation="Re-run with --via local after downloading manually.",
        )
    final = Path(out[-1].strip())
    if not final.exists():
        # Fallback: pick the largest file in dest_dir.
        candidates = sorted(dest_dir.iterdir(), key=lambda p: p.stat().st_size, reverse=True)
        if not candidates:
            raise FrameioAgentError("yt-dlp finished but no file was found.", remediation="")
        final = candidates[0]
    return final


def _do_local_upload(
    client: FrameioClient,
    *,
    account_id: str,
    folder_id: str,
    file_path: Path,
    name: str,
) -> dict[str, Any]:
    file_size = file_path.stat().st_size
    created = api.create_file_local_upload(
        client, account_id, folder_id, name=name, file_size=file_size,
    )
    upload_urls = created.get("upload_urls") or []
    if not upload_urls:
        raise FrameioAgentError(
            "Frame.io did not return upload URLs.",
            remediation="Re-run; this is a Frame.io API anomaly.",
        )
    total = len(upload_urls)

    def _progress(idx: int, total: int, sent: int, total_bytes: int) -> None:
        pct = (sent / total_bytes * 100) if total_bytes else 0
        print(f"  Uploaded chunk {idx}/{total}  ({_human_bytes(sent)} / {_human_bytes(total_bytes)}, {pct:.0f}%)")

    api.put_chunks_to_signed_urls(file_path, upload_urls, progress_cb=_progress)
    return created


def _do_remote_upload(
    client: FrameioClient,
    *,
    account_id: str,
    folder_id: str,
    source_url: str,
    name: str,
) -> dict[str, Any]:
    return api.create_file_remote_upload(
        client, account_id, folder_id, name=name, source_url=source_url,
    )


def _resolve_account_for_folder(client: FrameioClient, folder_id: str) -> str:
    """Best-effort account_id resolver — prefer configured default, else first."""
    cfg = load_config()
    if cfg.default_account_id:
        return cfg.default_account_id
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


def cmd_refs_add(
    *,
    source: str,
    folder: str,
    name: Optional[str],
    via: Optional[str],
    yes: bool,
    as_json: bool,
    emit: Callable[[Any, bool], None],
    stdin: Any = None,
) -> int:
    if not source.strip():
        print("Error: source is required (URL or local path).", file=sys.stderr)
        return 2
    if not folder.strip():
        print("Error: --folder is required.", file=sys.stderr)
        return 2

    mode = _detect_mode(source, via)
    display_name = name or _default_name_from_source(source, mode)

    # Pre-compute file size if local; for URL modes we won't know until later.
    file_size: Optional[int] = None
    if mode == "local":
        local_path = Path(source).expanduser()
        if not local_path.exists() or not local_path.is_file():
            print(f"Error: local file not found: {local_path}", file=sys.stderr)
            return 2
        file_size = local_path.stat().st_size

    print(_render_confirmation(
        source=source, mode=mode, name=display_name, folder_id=folder, file_size=file_size,
    ))

    if not yes:
        in_stream = stdin if stdin is not None else sys.stdin
        if not in_stream.isatty():
            print(
                "\nError: Upload requires interactive confirmation; stdin is not a TTY.",
                file=sys.stderr,
            )
            print("  > Re-run with --yes if you've explicitly authorized this upload.", file=sys.stderr)
            return 2
        if not _prompt_confirm():
            print("Aborted. No upload happened.", file=sys.stderr)
            return 1

    cfg = load_config()
    try:
        with FrameioClient(cfg) as client:
            account_id = _resolve_account_for_folder(client, folder)

            if mode == "local":
                print(f"\nUploading {_human_bytes(file_size or 0)} to Frame.io...")
                created = _do_local_upload(
                    client, account_id=account_id, folder_id=folder,
                    file_path=Path(source).expanduser(), name=display_name,
                )

            elif mode == "remote_upload":
                print(f"\nTelling Frame.io to fetch {source}...")
                created = _do_remote_upload(
                    client, account_id=account_id, folder_id=folder,
                    source_url=source, name=display_name,
                )

            elif mode == "yt_dlp":
                print(f"\nDownloading via yt-dlp...")
                with tempfile.TemporaryDirectory(prefix="frameio-agent-") as tmpdir:
                    local_file = _run_yt_dlp(source, Path(tmpdir))
                    actual_size = local_file.stat().st_size
                    print(f"  yt-dlp wrote {local_file.name}  ({_human_bytes(actual_size)})")
                    if name is None:
                        display_name = local_file.name
                    print(f"\nUploading to Frame.io...")
                    created = _do_local_upload(
                        client, account_id=account_id, folder_id=folder,
                        file_path=local_file, name=display_name,
                    )
            else:
                print(f"Error: unknown --via mode: {mode}", file=sys.stderr)
                return 2

    except FrameioAgentError as e:
        print(f"Error: {e.render()}", file=sys.stderr)
        return 1

    out = {
        "file_id": created.get("id"),
        "name": created.get("name") or display_name,
        "project_id": created.get("project_id"),
        "parent_folder_id": created.get("parent_id") or folder,
        "status": created.get("status"),
        "view_url": created.get("view_url"),
        "mode": mode,
        "source": source,
    }
    if as_json:
        emit(out, True)
    else:
        print(f"\n  Added.")
        print(f"  file_id: {out['file_id']}")
        if out["view_url"]:
            print(f"  URL:     {out['view_url']}")
        print(f"  Status:  {out['status']} (Frame.io will transcode in the background)")
    return 0
