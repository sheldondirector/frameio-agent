# Frame.io Agent Starter — Agent Instructions

You are helping the user connect this local repo to their Frame.io account.

## Allowed operations (everything else is forbidden)

**Read** (no confirmation needed):
- `auth login`, `auth status`, `verify`
- `projects` (accounts / workspaces / projects)
- `latest` (recency-first list of newest assets)
- `search` (capped name/path search)
- `comments` (normalized review notes — text + timecode + author + thread)
- `brief` (one-paragraph project status)

**Write — exactly ONE operation is allowed:**
- `share create` (bundle one or more assets into a single review share, return a URL)
  - **Always show the confirmation summary the CLI prints, then wait for the user's y/N before sending it.**
  - Only pass `--yes` when the user has *explicitly* authorized creating this specific share in the current conversation. Authorization to "send the director a link" once is not standing authorization for future shares.
  - Pre-fill flags from what the user said; never invent recipients, expirations, or passwords.
  - When `--public` (the default) is used, say so plainly in your readout: "anyone with the URL will be able to view."

## Forbidden — do not add, even if asked

- Upload, delete, rename, move, copy, or set permissions on any asset.
- Modify, revoke, or list existing shares (only `share create` exists in v1; do not add siblings).
- Any non-Frame.io service: YouTube/Vimeo download, media transcoding, S3 access, link scraping, etc.
- Browser/GraphQL scraping fallbacks for missing API surface — if a V4 endpoint is not available, surface the gap to the user; do not work around it.
- Storing tokens anywhere other than the file at `FRAMEIO_TOKEN_FILE`.

If the user asks for one of the above, decline and explain it is out of scope for v1 (see the PRD §8). Suggest they file an issue or start a sibling repo.

## Rules

- **Never print** access tokens, refresh tokens, client secrets, auth codes, or token JSON. The CLI already redacts; do not work around it.
- **Never echo** a share password back in any output — passwords are write-only.
- **Do not commit** `.env`, token files, or anything under `.frameio-agent/`. The `.gitignore` already excludes them.
- **Use Frame.io V4 via Adobe IMS OAuth.** Do not use legacy `fio-u-*` tokens.
- **Run setup and verify before anything else.** Prefer `--json` when parsing output.
- **If auth fails**, run `frameio-agent auth login` and ask the user for the redirect/code if needed.
- **If a share write fails with a scope error**, the user may need to re-run `auth login` after the OAuth app has been granted write scopes.

## Suggested first task (the north-star path)

1. Install dependencies (`python scripts/setup.py`).
2. Create local `.env` from `.env.example`.
3. Help the user authenticate: `frameio-agent auth login`.
4. `frameio-agent verify`
5. `frameio-agent projects --json`
6. `frameio-agent latest --project <id> --json`
7. `frameio-agent comments <file_id> --json` — then summarize the notes for the user, grouped by `timestamp_seconds` with `timecode` labels.

## Suggested second-win task (the one mutation)

If the user wants to send the director a link to one or more cuts:

1. Confirm with the user *which* assets to share, *what to call* the share, and *whether downloads are allowed* (default no).
2. Show the user the exact command you're about to run.
3. Run it WITHOUT `--yes` first so the user sees the confirmation summary and types y/N themselves.
4. If the user later asks you to "do that again with v5" or similar, treat each new share as a fresh authorization — re-confirm.

## JSON contracts (stable)

- `projects --json` → `{ "projects": [ { "account_id", "workspace_id", "project_id", "project_name", "root_folder_id", "updated_at" } ] }`
- `latest --project <id> --json` → `{ "project_id", "items": [ { "file_id", "name", "updated_at", "comments_count", "duration_seconds", "frameio_url" } ] }`
- `comments <file_id> --json` → `{ "file_id", "file_name", "duration_seconds", "comments": [ { "comment_id", "text", "timecode", "timestamp_seconds", "author_name", "created_at", "parent_id", "is_reply" } ] }`
- `share create ... --json` → `{ "share_id", "name", "url", "visibility", "allow_comments", "allow_download", "expires_at", "password_protected", "asset_count", "asset_ids", "created_at" }`

If a feature isn't *"talk to Frame.io and return data, or create a single review share with explicit confirmation,"* it does not belong in this repo.
