"""`frames pull` — extract a frame per clip to local disk, for agent vision.

This is the primitive that gives your agent eyes. It downloads one preview
frame (Frame.io's poster/thumbnail) per clip into a local directory and
writes a ``manifest.json`` mapping each local image back to its Frame.io
``file_id``.

The agent then Reads those images, judges them ("this shot is soft",
"there's a C-stand in the background", "this take is the good one"), and
drives the next command — ``share create`` with the keepers, or
``contact-sheet --from-manifest --exclude`` with the rejects.

Read-only: this command never mutates Frame.io. It only writes local files
to the directory you name with ``--out``. Pillow is NOT required (we save
raw bytes).

NOTE (honesty): Frame.io exposes one *poster* frame per clip, not arbitrary
timeline frames. That's enough to judge most "is this usable / is there a
C-stand" questions, but it is a single frame. True per-frame scrubbing needs
ffmpeg on the downloaded original — tracked as a follow-up, not built here.
"""
from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Optional

from . import media
from .client import FrameioClient
from .config import load_config
from .errors import FrameioAgentError


_SAFE = re.compile(r"[^A-Za-z0-9-]+")


def _safe_name(name: str, max_len: int = 40) -> str:
    """Sanitize an asset name into a filesystem-safe ASCII stem.

    Drops a trailing extension when it looks like one, then replaces every
    run of characters outside [A-Za-z0-9-] with a single underscore. This
    also neutralizes path separators and '..' sequences, so a hostile asset
    name can't escape the output directory.
    """
    base = (name or "").strip()
    if "." in base:
        stem, _, ext = base.rpartition(".")
        if stem and 1 <= len(ext) <= 5 and ext.isalnum():
            base = stem
    base = _SAFE.sub("_", base).strip("_")
    return (base or "frame")[:max_len]


def cmd_frames_pull(
    *,
    project: Optional[str],
    folder: Optional[str],
    out: str,
    max_files: int,
    parallel: int,
    as_json: bool,
    emit: Callable[[Any, bool], None],
) -> int:
    if not (project or folder):
        print("Error: --project or --folder is required.", file=sys.stderr)
        return 2

    out_dir = Path(out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_config()
    try:
        with FrameioClient(cfg) as client:
            account_id = media.resolve_account(
                client, project_id=project, configured_default=cfg.default_account_id,
            )
            print(f"Collecting files ({'project ' + project if project else 'folder ' + folder})...")
            files = media.collect_files(
                client, account_id,
                project_id=project, folder_id=folder, max_files=max_files,
            )
            if not files:
                print("No image/video files found.")
                return 0
            print(f"  Found {len(files)} file(s). Resolving frame URLs...")

            # Resolve thumbnail URLs in parallel, preserving collection
            # order — frame numbering must be deterministic across runs.
            slots: list[Optional[tuple[dict[str, Any], Optional[str]]]] = [None] * len(files)
            with ThreadPoolExecutor(max_workers=parallel) as pool:
                futs = {
                    pool.submit(media.fetch_thumb, client, account_id, f.get("id")): (i, f)
                    for i, f in enumerate(files) if f.get("id")
                }
                for fut in as_completed(futs):
                    i, f = futs[fut]
                    try:
                        _, name, url = fut.result()
                    except Exception:
                        name, url = None, None
                    slots[i] = (f, url)
            resolved = [pair for pair in slots if pair is not None]

            # Download frame bytes in parallel and write to disk.
            print(f"  Downloading frames to {out_dir}/ ...")
            frames_out: list[dict[str, Any]] = []
            missing: list[dict[str, Any]] = []

            def _do(idx_f_url: tuple[int, dict[str, Any], Optional[str]]) -> Optional[dict[str, Any]]:
                idx, f, url = idx_f_url
                fid = f.get("id")
                name = f.get("_display_name") or f.get("name") or f"frame_{idx}"
                if not url:
                    return None
                data = media.download_bytes(url)
                if not data:
                    return None
                fname = f"{idx:03d}_{_safe_name(name)}.jpg"
                (out_dir / fname).write_bytes(data)
                return {
                    "index": idx,
                    "file_id": fid,
                    "name": name,
                    "media_type": f.get("media_type"),
                    "local_path": str((out_dir / fname)),
                    "view_url": f.get("view_url"),
                }

            indexed = [(i, f, url) for i, (f, url) in enumerate(resolved)]
            with ThreadPoolExecutor(max_workers=parallel) as pool:
                results = list(pool.map(_do, indexed))

            for (i, f, url), res in zip(indexed, results):
                if res is None:
                    missing.append({"file_id": f.get("id"), "name": f.get("_display_name") or f.get("name")})
                else:
                    frames_out.append(res)

    except FrameioAgentError as e:
        print(f"Error: {e.render()}", file=sys.stderr)
        return 1

    manifest = {
        "source": {"account_id": account_id, "project_id": project, "folder_id": folder},
        "out_dir": str(out_dir),
        "count": len(frames_out),
        "frames": frames_out,
        "missing_thumbnail": missing,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if as_json:
        emit(manifest, True)
    else:
        print(f"\n  Saved {len(frames_out)} frame(s) to {out_dir}/")
        print(f"  Manifest: {manifest_path}")
        if missing:
            print(f"  {len(missing)} file(s) had no preview yet (still transcoding?).")
        print()
        print("  Next: have your agent Read the frames, then either")
        print(f"    frameio-agent share create <good file_ids> --name \"...\"")
        print(f"    frameio-agent contact-sheet --from-manifest {manifest_path} --exclude <bad file_ids> --out sheet.png")
    return 0
