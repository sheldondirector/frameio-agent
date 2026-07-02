"""`contact-sheet` — composite thumbnails from a project/folder into a PNG grid.

Founder use case #4: *"make me a contact sheet of every shot from our recent
shoot"* — and, with the vision loop, *"...minus every take with a C-stand
photobombing the background."*

Two modes:

* **Online** (``--project`` / ``--folder``): walk Frame.io, fetch each file's
  thumbnail, composite.
* **Offline** (``--from-manifest``): build from a ``frames pull`` output
  directory — no Frame.io calls. This is the second half of the vision loop:
  the agent Reads the pulled frames, decides which file_ids to drop, then
  rebuilds the sheet with ``--exclude``.

Filtering (both modes): ``--only id1,id2`` / ``--exclude id1,id2``.
``--index`` numbers each tile and writes a sidecar ``<out>.index.json`` so an
agent (or human) can refer to tiles by number.

Pillow is an optional dependency: ``pip install '.[images]'``.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Optional

from . import media
from .client import FrameioClient
from .config import load_config
from .errors import FrameioAgentError


def parse_id_list(raw: Optional[str]) -> set[str]:
    """Comma-separated id list -> cleaned set. Empty/None -> empty set."""
    if not raw:
        return set()
    return {piece.strip() for piece in raw.split(",") if piece.strip()}


def load_manifest(path: str) -> list[dict[str, Any]]:
    """Read a `frames pull` manifest.json and return its frame entries.

    Accepts either the manifest file itself or the directory containing it.
    Raises FrameioAgentError with remediation on any shape problem.
    """
    p = Path(path).expanduser()
    if p.is_dir():
        p = p / "manifest.json"
    if not p.exists():
        raise FrameioAgentError(
            f"Manifest not found: {p}",
            remediation="Run `frameio-agent frames pull ... --out <dir>` first.",
        )
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise FrameioAgentError(
            f"Could not read manifest {p}: {type(e).__name__}",
            remediation="Re-run `frames pull` to regenerate it.",
        )
    frames = data.get("frames")
    if not isinstance(frames, list):
        raise FrameioAgentError(
            f"Manifest {p} has no 'frames' list.",
            remediation="Re-run `frames pull` to regenerate it.",
        )
    return frames


def apply_filters(
    entries: list[dict[str, Any]],
    *,
    only: set[str],
    exclude: set[str],
) -> list[dict[str, Any]]:
    """Filter (name, file_id) entries by --only / --exclude id sets."""
    out = []
    for e in entries:
        fid = e.get("file_id") or e.get("id") or ""
        if only and fid not in only:
            continue
        if fid in exclude:
            continue
        out.append(e)
    return out


def _open_image(data: bytes) -> Optional["Image.Image"]:
    from PIL import Image
    try:
        return Image.open(BytesIO(data)).convert("RGB")
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
    numbered: bool,
) -> "Image.Image":
    """Composite (label_text, image) tiles into a grid."""
    from PIL import Image, ImageDraw, ImageFont
    n = len(tiles)
    cols = max(1, min(cols, n))
    rows = (n + cols - 1) // cols
    grid_w = cols * tile_w + (cols + 1) * padding
    label_h = 18 if label else 0
    grid_h = rows * (tile_h + label_h) + (rows + 1) * padding

    bg = Image.new("RGB", (grid_w, grid_h), color=(20, 20, 20))
    draw = ImageDraw.Draw(bg)
    font = None
    if label:
        try:
            font = ImageFont.truetype("arial.ttf", 12)
        except Exception:
            font = ImageFont.load_default()

    for i, (name, im) in enumerate(tiles):
        r, c = divmod(i, cols)
        scaled = im.copy()
        scaled.thumbnail((tile_w, tile_h), Image.LANCZOS)
        x = padding + c * (tile_w + padding) + (tile_w - scaled.width) // 2
        y = padding + r * (tile_h + label_h + padding) + (tile_h - scaled.height) // 2
        bg.paste(scaled, (x, y))
        if label and font:
            prefix = f"{i:03d}  " if numbered else ""
            label_text = (prefix + (name or ""))[:34]
            draw.text(
                (padding + c * (tile_w + padding) + 4,
                 padding + r * (tile_h + label_h + padding) + tile_h + 2),
                label_text, fill=(220, 220, 220), font=font,
            )
    return bg


def _collect_online(
    *,
    project: Optional[str],
    folder: Optional[str],
    max_files: int,
    parallel: int,
) -> list[dict[str, Any]]:
    """Walk Frame.io and return [{file_id, name, url}] entries with thumb URLs."""
    cfg = load_config()
    with FrameioClient(cfg) as client:
        account_id = media.resolve_account(
            client, project_id=project, configured_default=cfg.default_account_id,
        )
        print(f"Collecting files ({'project ' + project if project else 'folder ' + str(folder)})...")
        files = media.collect_files(
            client, account_id,
            project_id=project, folder_id=folder, max_files=max_files,
        )
        if not files:
            return []
        print(f"  Found {len(files)} file(s). Fetching thumbnail URLs...")
        entries: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            futs = {
                pool.submit(media.fetch_thumb, client, account_id, f.get("id")): f
                for f in files if f.get("id")
            }
            for fut in as_completed(futs):
                f = futs[fut]
                try:
                    fid, name, url = fut.result()
                except Exception:
                    continue
                if url:
                    entries.append({
                        "file_id": fid,
                        "name": f.get("_display_name") or name or f.get("name") or "(unnamed)",
                        "url": url,
                    })
        return entries


def cmd_contact_sheet(
    *,
    project: Optional[str],
    folder: Optional[str],
    from_manifest: Optional[str],
    only: Optional[str],
    exclude: Optional[str],
    out: str,
    cols: int,
    tile_size: int,
    max_files: int,
    no_labels: bool,
    index: bool,
    parallel: int,
    as_json: bool,
    emit: Callable[[Any, bool], None],
) -> int:
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("Error: Pillow is required for `contact-sheet`.", file=sys.stderr)
        print("  > Install with: pip install '.[images]'", file=sys.stderr)
        return 2

    if not (project or folder or from_manifest):
        print("Error: --project, --folder, or --from-manifest is required.", file=sys.stderr)
        return 2

    only_ids = parse_id_list(only)
    exclude_ids = parse_id_list(exclude)

    out_path = Path(out).expanduser()
    if out_path.is_dir():
        out_path = out_path / "contact-sheet.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Gather entries ────────────────────────────────────────────────────
    try:
        if from_manifest:
            entries = load_manifest(from_manifest)
        else:
            entries = _collect_online(
                project=project, folder=folder, max_files=max_files, parallel=parallel,
            )
    except FrameioAgentError as e:
        print(f"Error: {e.render()}", file=sys.stderr)
        return 1

    entries = apply_filters(entries, only=only_ids, exclude=exclude_ids)
    if not entries:
        print("No files matched (after --only/--exclude filters).")
        return 0

    # ── Load images ───────────────────────────────────────────────────────
    tiles: list[tuple[str, dict[str, Any], Any]] = []  # (name, entry, image)
    if from_manifest:
        print(f"  Loading {len(entries)} frame(s) from disk...")
        for e in entries:
            lp = e.get("local_path")
            if not lp or not Path(lp).exists():
                continue
            try:
                data = Path(lp).read_bytes()
            except OSError:
                continue
            im = _open_image(data)
            if im is not None:
                tiles.append((e.get("name") or "(unnamed)", e, im))
    else:
        print(f"  Downloading {len(entries)} thumbnail(s)...")
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            futs = {pool.submit(media.download_bytes, e["url"]): e for e in entries}
            for fut in as_completed(futs):
                e = futs[fut]
                data = fut.result()
                if not data:
                    continue
                im = _open_image(data)
                if im is not None:
                    tiles.append((e.get("name") or "(unnamed)", e, im))

    if not tiles:
        print("No usable images (thumbnails may still be transcoding).")
        return 1

    # Keep a deterministic order: manifest/collection order, so index numbers
    # in the sidecar match the tile numbering on the sheet.
    order = {id(e): i for i, e in enumerate(entries)}
    tiles.sort(key=lambda t: order.get(id(t[1]), 0))

    print(f"  Compositing {len(tiles)} tile(s) into a {cols}-column grid...")
    grid = _composite_grid(
        [(name, im) for (name, _e, im) in tiles],
        cols=cols, tile_w=tile_size, tile_h=tile_size,
        padding=8, label=not no_labels, numbered=index,
    )
    grid.save(out_path, "PNG", optimize=True)

    index_entries = [
        {"index": i, "file_id": e.get("file_id") or e.get("id"), "name": name}
        for i, (name, e, _im) in enumerate(tiles)
    ]
    index_path: Optional[Path] = None
    if index:
        index_path = out_path.with_suffix(out_path.suffix + ".index.json")
        index_path.write_text(json.dumps({"tiles": index_entries}, indent=2), encoding="utf-8")

    payload: dict[str, Any] = {
        "out": str(out_path),
        "tile_count": len(tiles),
        "cols": cols,
        "tile_size": tile_size,
        "excluded": sorted(exclude_ids),
        "tiles": index_entries,
    }
    if index_path:
        payload["index_file"] = str(index_path)

    if as_json:
        emit(payload, True)
    else:
        print(f"\n  Saved: {out_path}  ({len(tiles)} tiles, {grid.width}x{grid.height} px)")
        if index_path:
            print(f"  Index: {index_path}")
    return 0
