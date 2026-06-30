# Frame.io Agent Starter — Agent Instructions

You are helping the user connect this local repo to their Frame.io account, **read-only**.

## Rules

- **Start read-only.** Never upload, delete, move, rename, or create shares. v1 has no mutation commands; do not add any.
- **Never print** access tokens, refresh tokens, client secrets, auth codes, or token JSON. The CLI already redacts; do not work around it.
- **Do not commit** `.env`, token files, or anything under `.frameio-agent/`. The `.gitignore` already excludes them.
- **Use Frame.io V4 via Adobe IMS OAuth.** Do not use legacy `fio-u-*` tokens.
- **Run setup and verify before anything else.** Prefer `--json` when parsing output.
- **If auth fails**, run `frameio-agent auth login` and ask the user for the redirect/code if needed.

## Suggested first task (the north-star path)

1. Install dependencies (`python scripts/setup.py`).
2. Create local `.env` from `.env.example`.
3. Help the user authenticate: `frameio-agent auth login` (this prints a step-by-step Adobe Developer Console walkthrough if credentials are missing).
4. `frameio-agent verify`
5. `frameio-agent projects --json`
6. `frameio-agent latest --project <id> --json`
7. `frameio-agent comments <file_id> --json` — then summarize the notes for the user, grouped by `timestamp_seconds` with `timecode` labels.

## JSON contracts (stable)

- `projects --json` → `{ "projects": [ { "account_id", "workspace_id", "project_id", "project_name", "root_folder_id", "updated_at" } ] }`
- `latest --project <id> --json` → `{ "project_id", "items": [ { "file_id", "name", "updated_at", "comments_count", "duration_seconds", "frameio_url" } ] }`
- `comments <file_id> --json` → `{ "file_id", "file_name", "duration_seconds", "comments": [ { "comment_id", "text", "timecode", "timestamp_seconds", "author_name", "created_at", "parent_id", "is_reply" } ] }`

## Things you must NOT do

- Do not add upload, delete, rename, move, share-create, or permission-change commands.
- Do not scrape the Frame.io web UI or use GraphQL.
- Do not store tokens anywhere other than the file at `FRAMEIO_TOKEN_FILE`.
- Do not paste secrets into Git commits, screenshots, PR descriptions, or examples.
- Do not require MCP. MCP is an optional thin wrapper; the CLI is the spine.

If a feature isn't *"talk to Frame.io and return data,"* it does not belong in this repo.
