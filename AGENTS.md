# Frame.io Agent — Agent Instructions

You are helping the user run Frame.io from this local repo.

## Allowed operations

**Read (no confirmation needed):**
- `auth login`, `auth status`, `verify`
- `projects` — list accounts / workspaces / projects
- `latest` — newest assets in a project (recency-first)
- `search "<query>"` — account-wide search (lexical or `--nlp` for natural language)
- `comments <file_id>` — normalized review notes (text + timecode + author + thread)
- `brief --project <id>` — one-paragraph project status

**Vision (read-only; local file writes only):**
- `frames pull --project|--folder <id> --out <dir>` — download one preview frame per clip + `manifest.json` mapping images to file_ids. Then YOU (the agent) Read the images, judge them, and drive the next command. The CLI never judges images.
- `contact-sheet --project|--folder <id> --out X.png` — PIL composite of thumbnails. `--from-manifest <dir>` builds offline from a frames-pull output; `--only`/`--exclude` filter by file_id; `--index` numbers tiles + writes `<out>.index.json`.

**Write (every one is confirmation-gated):**
- `share create [file_ids...] --name "..."` — bundle assets into a review share. Optional `--reviewers a@x.com,b@y.com` adds email recipients.
- `refs add <source> --folder <id>` — upload a local file, trigger a remote_upload from a direct URL, or yt-dlp from a streaming platform.

For every mutation:
- **Always show the confirmation summary the CLI prints, then wait for the user's y/N before sending.**
- Only pass `--yes` when the user has *explicitly* authorized the specific action in the current conversation. Authorization to "send the director a link" once is not standing authorization for future shares or uploads.
- Pre-fill flags from what the user said; never invent recipients, expirations, passwords, target folders, or source URLs.
- Echo the visibility / mode plainly in your readout: "public link, anyone with the URL will be able to view" / "yt-dlp will download to a temp file before uploading" / "no downloads allowed."

## Forbidden — do not add, even if asked

- **Delete, rename, move, copy, or change permissions on any asset.** Those endpoints exist in V4; the CLI doesn't call them. Don't shell out to add them.
- **Modify or revoke existing shares.** Only `share create` is in scope.
- **Browser/GraphQL scraping** to work around missing API surface — if a V4 endpoint isn't available, surface the gap to the user.
- **Store tokens anywhere other than `FRAMEIO_TOKEN_FILE`.**

If the user asks for one of the above, explain it's out of scope (see PRD §scope guardrail) and suggest a separate repo if they need it.

## Rules

- **Never print** access tokens, refresh tokens, client secrets, auth codes, or token JSON. The CLI already redacts; do not work around it.
- **Never echo** a share password or reviewer message back in output unless the user is *editing* it.
- **Do not commit** `.env`, token files, or anything under `.frameio-agent/`. `.gitignore` already excludes them.
- **Use Frame.io V4 via Adobe IMS OAuth.** Do not use legacy `fio-u-*` tokens.
- **Run setup and verify before anything else.** Prefer `--json` when parsing output.
- **If auth fails**, run `frameio-agent auth login` and ask the user for the redirect URL if needed.
- **If a write fails with a scope/plan error** (`secure_sharing`, etc.), explain plainly and suggest the public/free alternative.

## Suggested first task (the north-star path)

1. `python scripts/setup.py`
2. `frameio-agent auth login`
3. `frameio-agent verify`
4. `frameio-agent projects --json`
5. `frameio-agent latest --project <id> --json`
6. `frameio-agent comments <file_id> --json` — then summarize the notes for the user, grouped by `timestamp_seconds` with `timecode` labels.

## Founder workflows you can compose

- **Curated reel + custom link:** `search "reel"` → pick files → `share create ... --reviewers client@x.com`
- **Director-notes summary:** `latest --project <id>` → `comments <file_id>` → group by theme/timecode
- **Reference pack from YouTube:** `refs add https://www.youtube.com/watch?v=... --folder <id>` (multiple times) — agent uses yt-dlp + local upload
- **Contact sheet for the wall:** `contact-sheet --project <id> --out ~/Desktop/sheet.png`
- **Visual select ("cut me a reel of shots that don't suck"):** `frames pull --project <id> --out ./frames` → Read each image in the manifest → judge → `share create <keeper file_ids> --name "Selects"`
- **Filtered sheet ("minus every take with a C-stand"):** `frames pull` → Read images, note the file_ids with the problem → `contact-sheet --from-manifest ./frames --exclude <bad ids> --out sheet.png`
- Caveat to keep in mind when judging: `frames pull` gives ONE poster frame per clip, not the whole timeline. Say so if the user's ask needs per-frame scrubbing (that's an open follow-up using ffmpeg on downloaded originals).

## JSON contracts (stable)

- `projects --json` → `{ "projects": [ { "account_id", "workspace_id", "project_id", "project_name", "root_folder_id", "updated_at" } ] }`
- `latest --project <id> --json` → `{ "project_id", "account_id", "items": [ { "file_id", "name", "media_type", "updated_at", "frameio_url" } ] }`
- `search "<q>" --json` → `{ "query", "engine", "result_count", "results": [ { "type", "id", "name", "project_id", "view_url", "matches" } ] }`
- `comments <file_id> --json` → `{ "file_id", "file_name", "duration_seconds", "fps", "comments_count", "comments": [ { "comment_id", "text", "timecode", "timestamp_seconds", "author_name", "created_at", "parent_id", "is_reply" } ] }`
- `share create ... --json` → `{ "share_id", "name", "url", "visibility", "allow_download", "expires_at", "password_protected", "asset_count", "asset_ids", "created_at", "reviewers_added", "reviewer_status" }`
- `refs add ... --json` → `{ "file_id", "name", "project_id", "parent_folder_id", "status", "view_url", "mode", "source" }`
- `frames pull ... --json` → `{ "source", "out_dir", "count", "frames": [ { "index", "file_id", "name", "media_type", "local_path", "view_url" } ], "missing_thumbnail" }`
- `contact-sheet --json` → `{ "out", "tile_count", "cols", "tile_size", "excluded", "tiles": [ { "index", "file_id", "name" } ], "index_file"? }`

---

## How to add a new command (for future contributors / agents)

The CLI is organized as one module per command family. To add a new feature:

1. **Wrap the V4 endpoint** in `frameio_agent/api.py`. One function per endpoint, with a docstring naming the URL and discriminator quirks. Pull the request/response schema from `https://api.frame.io/v4/openapi.json` — don't guess.

2. **Create the command module** at `frameio_agent/<feature>.py`. Convention:
   - `cmd_<verb>(*, ...kwargs, as_json, emit) -> int` — returns the exit code.
   - Mutations take `yes: bool` + `stdin: Any = None`, call `_prompt_confirm()` unless `yes`, and refuse on non-TTY without `yes`.
   - Use `FrameioClient` from `client.py`; never construct HTTP calls directly.
   - Raise `FrameioAgentError` from `errors.py` for user-actionable failures; the CLI prints `e.render()` with the remediation message.

3. **Wire it into `cli.py`**:
   - Add an `argparse` subparser in `build_parser()`. Use `--json` via `_add_json_flag(parser)`.
   - Add a routing branch in `main()` that imports the command lazily and forwards args.

4. **Write tests** at `tests/test_<feature>.py`. Cover at minimum:
   - Input validation guards (empty args, bad enum values, missing files).
   - Confirmation flow for mutations (non-TTY refuses, n/empty aborts, --yes bypasses).
   - Payload/response normalization edge cases.

5. **Update this file** (`AGENTS.md`):
   - Add to "Allowed operations" with the safety notes.
   - Add to "JSON contracts" if you exposed a new output shape.
   - If it's a new founder workflow, add a line to "Founder workflows you can compose."

6. **Update the README's "What it does" section** with one line for the new command.

7. **Bump version** in `pyproject.toml` and `frameio_agent/__init__.py` (semver: new feature = minor bump).

Do NOT auto-generate dozens of commands from the OpenAPI spec. Each command should have a real user use case behind it. If you can't name the founder/producer moment it serves, it doesn't belong.
