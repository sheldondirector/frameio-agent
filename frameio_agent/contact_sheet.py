"""`contact-sheet` — composite thumbnails from a project (or folder) into a PNG grid.

Founder use case #4: *"make me a contact sheet of every shot from our recent shoot."*

Walks the folder tree (or starts from --folder if you want a subset),
fetches each file's thumbnail URL via Frame.io's media_links, downloads
them in parallel, and PIL-composites them into a labeled grid.

Pillow is an optional dependency. Install with: ``pip install '.[images]'``.
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

from . import api
from .client import FrameioClient
from .config import load_config
from .errors import FrameioAgentError
from .listing import _resolve_account_for_project


THUMBNAIL_FIELDS = ("thumb", "thumbnail", "poster", "small_thumbnail", "icon")


def _extract_thumbnail_url(file_meta: dict[str, Any]) -> Optional[str]:
    """Find a thumbnail URL in a File response. V4 nests these in media_links."""
    media_links = file_meta.get("media_links") or {}
    for field in THUMBNAIL_FIELDS:
        v = media_links.get(field)
        if isinstance(v, dict):
            url = v.get("download_url") or v.get("url") or v.get("href")
            if url:
                return url
        elif isinstance(v, str):
            return v
    # Some files put a flat field at the top level.
    for field in THUMBNAIL_FIELDS:
        v = file_meta.get(field)
        if isinstance(v, str):
            return v
    return None


def _collect_files(
    client: FrameioClient,
    account_id: str,
    *,
    project_id: Optional[str],
    folder_id: Optional[str],
    max_files: int,
) -> list[dict[str, Any]]:
    """BFS-walk to collect files (unwrapping version_stacks). Stops at max_files."""
    if folder_id:
        roots = [folder_id]
    else:
        if not project_id:
            raise FrameioAgentError(
                "Need --project or --folder.",
                remediation="Pass --project <id> or --folder <id>.",
            )
        project = api.get_project(client, account_id, project_id)
        root = project.get("root_folder_id") or project.get("root_asset_id")
        if not root:
            raise FrameioAgentError(
                f"Project {project_id} has no root folder.",
                remediation="Verify with `projects --json`.",
            )
        roots = [root]

    collected: list[dict[str, Any]] = []
    queue = list(roots)
    seen_folders = 0
    max_folders = 400  # safety
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
                    head["_display_name"] = child.get("name") or head.get("name")
                    collected.append(head)
                    if len(collected) >= max_files:
                        break
                continue
            # file
            mt = (child.get("media_type") or "").lower()
            if mt and not (mt.startswith("video/") or mt.startswith("image/")):
                continue  # skip audio/pdf/etc.
            collected.append(child)
            if len(collected) >= max_files:
                break
    return collected


def _fetch_thumb(
    client: FrameioClient,
    account_id: str,
    file_id: str,
) -> tuple[str, Optional[str], Optional[str]]:
    """Return (file_id, name, thumb_url). thumb_url None if unavailable."""
    try:
        meta = api.get_file(client, account_id, file_id)
    except FrameioAgentError:
        return file_id, None, None
    name = meta.get("name")
    url = _extract_thumbnail_url(meta)
    return file_id, name, url


def _download_image(url: str, timeout: float = 30.0) -> Optional["Image.Image"]:
    """Download URL and return a PIL Image, or None on failure."""
    from PIL import Image
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        if resp.status_code != 200:
            return None
        return Image.open(BytesIO(resp.content)).convert("RGB")
    except Exception:
        return None


def _composite_grid(
    tiles: list[tuple[str, "Image.Image"]],
    *,
    cols: int,
    tile_w: int,
    tile_h: int,
    padding: int,
    label: bool,
) -> "Image.Image":
    """Composite (name, image) tiles into a grid PNG."""
    from PIL import Image, ImageDraw, ImageFont
    n = len(tiles)
    rows = (n + cols - 1) // cols
    grid_w = cols * tile_w + (cols + 1) * padding
    label_h = 18 if label else 0
    grid_h = rows * (tile_h + label_h) + (rows + 1) * padding

    bg = Image.new("RGB", (grid_w, grid_h), color=(20, 20, 20))
    draw = ImageDraw.Draw(bg) if label else None
    try:
        font = ImageFont.truetype("arial.ttf", 12) if label else None
    except Exception:
        font = ImageFont.load_default() if label else None

    for i, (name, im) in enumerate(tiles):
        r, c = divmod(i, cols)
        # Fit image into tile while preserving aspect
        scaled = im.copy()
        scaled.thumbnail((tile_w, tile_h), Image.LANCZOS)
        x = padding + c * (tile_w + padding) + (tile_w - scaled.width) // 2
        y = padding + r * (tile_h + label_h + padding) + (tile_h - scaled.height) // 2
        bg.paste(scaled, (x, y))
        if label and draw and font:
            label_text = (name or "")[:30]
            draw.text(
                (padding + c * (tile_w + padding) + 4,
                 padding + r * (tile_h + label_h + padding) + tile_h + 2),
                label_text, fill=(220, 220, 220), font=font,
            )
    return bg


def cmd_contact_sheet(
    *,
    project: Optional[str],
    folder: Optional[str],
    out: str,
    cols: int,
    tile_size: int,
    max_files: int,
    no_labels: bool,
    parallel: int,
    as_json: bool,
    emit: Callable[[Any, bool], None],
) -> int:
    # Optional dep check
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print(
            "Error: Pillow is required for `contact-sheet`.",
            file=sys.stderr,
        )
        print("  > Install with: pip install '.[images]'", file=sys.stderr)
        return 2

    if not (project or folder):
        print("Error: --project or --folder is required.", file=sys.stderr)
        return 2

    out_path = Path(out).expanduser()
    if out_path.is_dir():
        out_path = out_path / "contact-sheet.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cfg = load_config()
    try:
        with FrameioClient(cfg) as client:
            if project:
                account_id = _resolve_account_for_project(client, project)
            else:
                account_id = cfg.default_account_id
                if not account_id:
                    accounts = api.list_accounts(client)
                    if accounts:
                        account_id = accounts[0].get("id") or accounts[0].get("account_id")

            if not account_id:
                raise FrameioAgentError(
                    "Could not resolve an account_id.",
                    remediation="Set FRAMEIO_ACCOUNT_ID in .env.",
                )

            print(f"Collecting files ({'project ' + project if project else 'folder ' + folder})...")
            files = _collect_files(
                client, account_id,
                project_id=project, folder_id=folder, max_files=max_files,
            )
            if not files:
                print("No image/video files found.")
                return 0
            print(f"  Found {len(files)} file(s). Fetching thumbnails...")

            # Resolve thumbnail URLs in parallel
            urls: list[tuple[str, str]] = []  # (display_name, url)
            with ThreadPoolExecutor(max_workers=parallel) as pool:
                futures = {
                    pool.submit(_fetch_thumb, client, account_id, (f.get("id") or "")): f
                    for f in files if f.get("id")
                }
                for fut in as_completed(futures):
                    f = futures[fut]
                    try:
                        _, name, url = fut.result()
                    except Exception:
                        name, url = None, None
                    if url:
                        display = f.get("_display_name") or name or f.get("name") or "(unnamed)"
                        urls.append((display, url))

    except FrameioAgentError as e:
        print(f"Error: {e.render()}", file=sys.stderr)
        return 1

    if not urls:
        print("No thumbnails available yet — Frame.io may still be transcoding.")
        print("  > Try again in a few minutes.")
        return 0

    print(f"  Downloading {len(urls)} thumbnail(s)...")
    tiles: list[tuple[str, Any]] = []
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = {pool.submit(_download_image, u): (name, u) for (name, u) in urls}
        for fut in as_completed(futures):
            name, _ = futures[fut]
            im = fut.result()
            if im is not None:
                tiles.append((name, im))

    if not tiles:
        print("Could not download any thumbnails.")
        return 1

    print(f"  Compositing {len(tiles)} tiles into {cols}-column grid...")
    grid = _composite_grid(
        tiles, cols=cols, tile_w=tile_size, tile_h=tile_size,
        padding=8, label=not no_labels,
    )
    grid.save(out_path, "PNG", optimize=True)

    payload = {
        "out": str(out_path),
        "tile_count": len(tiles),
        "cols": cols,
        "tile_size": tile_size,
    }
    if as_json:
        emit(payload, True)
    else:
        print(f"\n  Saved: {out_path}  ({len(tiles)} tiles, {grid.width}x{grid.height} px)")
    return 0
