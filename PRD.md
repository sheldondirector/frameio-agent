# Frame.io Agent Starter — PRD

**Status:** Draft v0.3
**Primary audience:** Newbie agent users who already use Frame.io and have a frontier coding agent (Claude Code, OpenAI Codex CLI, Cursor, Gemini CLI, or similar).
**Core thesis:** The lowest-barrier product is not "configure an MCP server." It is a tiny, self-contained repo that any coding agent can read, install, authenticate, verify, and use through a simple CLI with JSON output. MCP is optional after the CLI works.

**Scope guardrail (read this first):** This tool is **Frame.io and nothing else**. No video editing, no media processing, no cataloging, no external services. Read-only access to Frame.io projects, assets, and comments — **plus exactly one mutation: creating review shares** (a `share create` command, gated by an interactive confirmation by default). Upload, delete, rename, move, and permission changes remain hard-no. If a feature isn't "talk to Frame.io and return data, or create a single review share with explicit confirmation," it does not belong in this repo.

---

## What changed in v0.3 (deltas from v0.2)

1. **One mutation is now in scope: `share create`.** v0.2 forbade all mutation. v0.3 carves out exactly one — creating a Frame.io review share that bundles one or more assets — because "find the latest cut, then send the director a link" is the natural next step after the north-star. All other mutations (upload/delete/rename/move/permission/share-revoke/share-modify) remain hard-no. See §5 P2, §8, §11.8, §16, §23, §25.
2. **Safety stance preserved via three constraints on the new command** (§11.8): public-link visibility default, an interactive y/N confirmation that prints the full share config before any POST, and a `--yes` bypass that an agent MUST only use when the user has explicitly authorized the share.
3. AGENTS.md changes from a blanket mutation prohibition to a one-item allow-list — agents must not add other mutation commands even if asked.

## What changed in v0.2 (deltas from v0.1)

1. **Auth is now a designed, guided flow, not an open question.** §10 specifies an `auth login` wizard that walks a beginner through creating the Adobe Developer OAuth app *and* auto-captures the redirect via a local loopback (PKCE). This was the v0.1 make-or-break risk; it is now the centerpiece.
2. **"Find my latest cut" is a first-class command (`latest`), recency-first.** Naive full-folder traversal is demoted to a fallback for name search only (§11.5–11.6). Sort-by-recency is the default path so the headline moment is fast and reliable on big projects.
3. **A single north-star moment defines done (§7):** *"summarize my director's review comments with timecodes, without opening Frame.io."* Every command and the `comments` output shape are designed to make that one moment trivial.
4. **Open questions are resolved into decisions (§22).**
5. **Positioning sharpened + an unaffiliated disclaimer added (§6).**
6. **A concrete Session-1 build plan for a fresh agent (§24).**

---

## 1. One-line product

**Frame.io Agent Starter** lets any coding agent safely connect to a user's Frame.io account, list projects, find the latest cut, and summarize review comments — through simple local commands with JSON output.

---

## 2. Non-negotiable credential note

Any credentials/tokens used during development are **burner keys for testing**.

- Do **not** commit real access tokens, refresh tokens, client secrets, auth codes, or user token JSON to the repo.
- Do **not** print token values in terminal output, logs, test snapshots, README examples, screenshots, or demo videos.
- The repo may include `.env.example`, fake placeholder tokens, and fixtures with obviously fake values only.
- Any public release assumes users bring their own Frame.io / Adobe OAuth credentials (the `auth login` wizard makes this easy).
- If shared with an audience, say plainly: **"The included examples use placeholder values. Run `auth login` to connect your own Frame.io account."**

---

## 3. Problem

People with Frame.io accounts increasingly have strong coding agents, but the first mile is too hard:

- Frame.io V4 requires **Adobe IMS OAuth**, not legacy `fio-u-*` tokens.
- Beginners don't know what credentials, scopes, callback URLs, or local files are needed — and **creating an Adobe Developer OAuth app is the single biggest wall**.
- MCP configuration is unfamiliar to beginners.
- Generic agents *can* run local commands, but they need a clean, documented repo with safe commands and explicit agent instructions.

The first useful experience should feel like:

> "I gave my coding agent a repo. It connected to Frame.io, found my latest cut, and summarized the director's 47 review notes with timecodes — and I never opened Frame.io."

---

## 4. Target users

**Primary:** a creative, editor, producer, marketer, or founder who uses Frame.io for review, has a retail coding agent, is comfortable cloning a repo (or asking an agent to), and does **not** want to learn OAuth, SDK quirks, or MCP first.

**Secondary:** an agent-builder / dev-rel audience who wants a clean example of making a SaaS media tool agent-readable — CLI-first with JSON output, MCP optional.

---

## 5. Product principles

1. **CLI first, MCP optional.** Every useful operation works through local commands before MCP exists.
2. **Read-only by default, with exactly one explicit mutation.** Read-only is the resting state. The single mutation — `share create` (§11.8) — is gated by a confirmation prompt and requires the user to opt into a `--yes` bypass. No upload, delete, move, rename, or permission change. No share modification or revocation. Period.
3. **Agent-readable by design.** Every command supports `--json` and clear exit codes.
4. **No secrets in output.** Tokens and auth codes redacted by default.
5. **Beginner-safe errors.** Every failure tells the user/agent exactly what to run next.
6. **One-command verification.** After setup, `verify` proves the connection.
7. **No personal/org-specific paths.** The public repo must never assume a specific home dir, account ID, or workspace.
8. **Self-contained.** Standard library + one HTTP client + the OAuth helper. No heavy framework, no external service.

---

## 6. Positioning

**Public name:** Frame.io Agent Starter
**Subtitle:** Give your coding agent safe, read-only access to your Frame.io projects.

**Plain-English promise:** Connect Frame.io to Claude Code, Cursor, Codex, Gemini CLI, or any agent that can run local commands. Your agent can list projects, find the latest cut, summarize review comments, and send a director a review link — and it can't touch your edit, delete files, or change permissions.

**The edge (what makes it worth using):** the *beginner onboarding* + *bounded safety* (read-only + one confirmation-gated mutation) + *agent-agnostic CLI*. It is **not** a new API, a Transfer replacement, or an automation platform. Its job is to make the first connection painless and the first two wins obvious: *see what the director said*, *send the next cut for review*.

**Disclaimer (must appear in README + repo footer):** *Unofficial community tool. Not affiliated with, endorsed by, or supported by Adobe or Frame.io. "Frame.io" is a trademark of Adobe.*

**Avoid this positioning:** "full automation platform," "production upload pipeline," "MCP-first protocol server," "replace Frame.io Transfer," "bulk media sync."

---

## 7. North-star moment (the bar for "done")

There is exactly one moment v1 must nail. Everything else serves it:

> **From a clean clone, a coding agent reaches: "summarize the review comments on my latest cut, with timecodes" — in under 10 minutes, read-only, with no Adobe/MCP knowledge required.**

Concretely, the agent should be able to run:
```
frameio-agent latest --project <id> --json      # find the newest cut + its comment count
frameio-agent comments <file_id> --json          # pull the notes (text + timecode + author)
```
…and hand the JSON to the model, which groups 47 raw notes into a few themed, timecoded fixes. If a beginner can reproduce that the same night they cloned the repo, v1 has succeeded.

---

## 8. MVP scope

### In scope for v1

| Capability | User value |
|---|---|
| `auth login` guided OAuth wizard | A beginner can connect Frame.io without understanding Adobe IMS. |
| `auth status` / `verify` | Removes "is this even connected?" confusion. |
| `projects` | Agent orients itself (accounts/workspaces/projects). |
| `latest` (recency-first) | Find the newest cut(s) in a project fast — the demo moment. |
| `search` (name/path, capped) | Find a named asset when recency isn't enough. |
| `comments` | Pull review notes (text, timecode, author, thread) for a file. |
| `brief` | One-paragraph "what's going on in this project." |
| **`share create` (the one mutation)** | **Bundle one or more assets into a review share with a URL the user can send to the director. Always gated by a confirmation prompt; `--yes` bypass for trusted agent flows.** |
| `--json` everywhere | Any agent can parse results. |
| `AGENTS.md` | Coding agents know the rules and the safe workflow. |
| `.env.example` | Humans understand config without secrets. |

### Out of scope for v1 (hard no)

Uploading · deleting · moving/renaming · permission changes · **modifying or revoking existing shares** · **listing existing shares** (deferred to v1.2) · bulk downloads · browser/GraphQL scraping fallbacks · any non-Frame.io service · any local media processing/editing/cataloging · required MCP · hosted SaaS or remote token storage. **Note: `share create` is the only mutation in v1 — adding any other mutation, even a sibling like `share revoke`, is out of scope and requires a PRD update first.**

---

## 9. First-run user experience

**Human:**
```bash
git clone https://github.com/<org>/frameio-agent-starter
cd frameio-agent-starter
```
Then tell the coding agent:
```text
Read AGENTS.md and set this repo up for my Frame.io account.
Start read-only. Do not print secrets or tokens.
After setup, verify auth, find my latest cut, and summarize its review comments.
```

**Agent expected flow:**
```bash
python scripts/setup.py            # install deps, create local config dir
python -m frameio_agent.cli auth login   # guided OAuth (see §10)
python -m frameio_agent.cli verify
python -m frameio_agent.cli projects --json
python -m frameio_agent.cli latest --project <id> --json
python -m frameio_agent.cli comments <file_id> --json
```

**Success moment (what the user sees):**
```text
Connected as: user@example.com

Latest in "Brand Campaign — Summer Cutdowns":
1. Rough Cut v4.mov — updated 2h ago — 47 comments
2. Color Pass v2.mov — updated yesterday — 3 comments

Tip: frameio-agent comments <file_id> --json   # then ask your agent to summarize
```

---

## 10. Auth — the guided OAuth flow (the make-or-break)

**Reality:** Frame.io V4 authenticates via **Adobe IMS OAuth**. A user needs an Adobe Developer Console project with a **Web App OAuth credential** (client ID, client secret, redirect URI) that has Frame.io API access. For a beginner this is the wall. `auth login` must make it feel like one guided step.

### `auth login` behavior (two phases)

**Phase A — ensure an OAuth app exists.**
- If `FRAMEIO_CLIENT_ID` / `FRAMEIO_CLIENT_SECRET` are missing from `.env`, print a **numbered, copy-paste walkthrough** (with the exact Adobe Developer Console URL) to create one:
  1. Open the Adobe Developer Console → Create new project.
  2. Add the **Frame.io API** to the project.
  3. Add an **OAuth Web App** credential.
  4. Set the **Redirect URI** to exactly `http://localhost:<PORT>/callback` (the wizard prints the port it will listen on).
  5. Copy the **Client ID** and **Client Secret** into `.env` (the wizard offers to write them for you when pasted at the prompt).
- Keep this walkthrough short, literal, and link-rich. Treat "can't get lost here" as the #1 acceptance criterion of the whole product.

**Phase B — run the login.**
- Start a **local loopback server** on `http://localhost:<PORT>/callback`.
- Open the browser to the Adobe IMS authorize URL with **PKCE** (code challenge), the configured scopes, and the loopback redirect.
- The user clicks **Allow**; the loopback **auto-captures the `code`** — no manual URL pasting.
- Exchange `code` → tokens; write the token cache (`FRAMEIO_TOKEN_FILE`) with private file permissions where the OS supports it.
- **Fallback:** if the browser/loopback can't be used (headless/SSH), print the authorize URL and accept a pasted redirect URL or code.

**Acceptance:**
- Never prints access/refresh tokens.
- On success prints only:
```text
Authenticated as user@example.com
Token cache saved: ~/.frameio-agent/tokens.json
```
- Refresh is automatic on later commands; expired/revoked refresh → actionable "run auth login" message.

**Trial path (resolves v0.1 Open Q1):** the canonical path is **bring-your-own Adobe app via the wizard**. An optional `--demo` mode (against a maintainer sandbox app + sandbox project) MAY exist for trying the UX, clearly labeled *"demo only — run `auth login` to use your own account."* Ship the wizard first; add demo mode only if a sandbox can be maintained.

---

## 11. Core commands

Single executable `frameio-agent <command>`; module fallback `python -m frameio_agent.cli <command>`. Every command takes `--json`.

### 11.1 `auth login` / `auth status` — see §10.
`auth status --json` →
```json
{ "ok": true, "authenticated": true, "email": "user@example.com",
  "token_file_exists": true, "has_refresh_token": true, "expires_at": "2026-07-01T12:34:56Z" }
```
No token values.

### 11.2 `verify`
Imports config, refreshes token if needed, calls the "current user" endpoint, lists a few projects. Exit `0` on success; nonzero + actionable message on failure. This is the "is it connected?" command.

### 11.3 `projects --json`
Lists accounts → workspaces → projects visible to the user.
```json
{ "projects": [ { "account_id": "...", "workspace_id": "...", "project_id": "...",
  "project_name": "Client A — Campaign", "root_folder_id": "...", "updated_at": "..." } ] }
```

### 11.4 `latest` (recency-first — the demo command)
```bash
frameio-agent latest --project <project_id> --limit 5 --json
```
Returns the most-recently-updated **video** assets in the project, newest first, each with a comment count. This is the path the "find my latest cut" moment uses — it must NOT depend on full traversal.
- Prefer the Frame.io V4 list/query endpoints with **sort by `updated_at` desc** and a media-type filter.
- Output shares the asset shape in §11.5.

### 11.5 `search` (name/path — capped fallback)
```bash
frameio-agent search "rough cut" --project <id> --limit 20 --max-folders 200 --max-assets 1000 --json
```
For finding a *named* asset when recency isn't enough. Capped recursive traversal + local name/path filtering; caps prevent runaway projects. Output:
```json
{ "query": "rough cut", "results": [ {
  "file_id": "...", "name": "Rough Cut v4.mov", "project_id": "...", "project_name": "...",
  "folder_path": "Editorial/Rough Cuts", "media_type": "video", "file_size": 123456789,
  "created_at": "...", "updated_at": "...", "comments_count": 12,
  "frameio_url": "https://next.frame.io/..." } ] }
```

### 11.6 `comments` (the payload that powers the north-star)
```bash
frameio-agent comments <file_id> --json [--by-timecode]
```
Returns normalized review notes in a shape that is trivial to group/summarize:
```json
{ "file_id": "...", "file_name": "Rough Cut v4.mov", "duration_seconds": 154.2,
  "comments": [ { "comment_id": "...", "text": "Tighten this section.",
    "timecode": "00:00:12:10", "timestamp_seconds": 12.34,
    "author_name": "Reviewer", "created_at": "...", "parent_id": null, "is_reply": false } ] }
```
- Include both human `timecode` and numeric `timestamp_seconds` (the model groups by time).
- `--by-timecode` sorts ascending by `timestamp_seconds`.
- Replies carry `parent_id` so threads can be collapsed.

### 11.7 `brief`
```bash
frameio-agent brief --project <id>          # human text; --json for structured
```
A concise newbie-friendly project status: recent assets (with comment counts) + 2–3 "likely next actions." Built only from data the read-only calls already return.

### 11.8 `share create` (the one mutation — gated by confirmation)

```bash
frameio-agent share create <file_id> [<file_id> ...] --name "Director review — v4" [flags]
```

The only command in v1 that writes to Frame.io. Bundles one or more asset IDs into a single share and returns the public URL. Designed for the "send the director the next cut" moment that naturally follows the north-star.

**Flags:**

| Flag | Default | Meaning |
|---|---|---|
| `--name "..."` | *required* | Human label for the share (shown in Frame.io UI and in confirmation output). |
| `--allow-comments` / `--no-comments` | allow | Whether recipients can leave comments. |
| `--allow-download` / `--no-download` | **no** | Whether recipients can download originals. Safer default. |
| `--expires <ISO-date>` | none | Optional expiration (e.g. `2026-07-15`). |
| `--password "..."` | none | Optional password gate. Never echoed back; redacted in any log line. |
| `--public` / `--restricted` | **public** | `public` = anyone with the URL can view; `restricted` = signed-in Frame.io users only. |
| `--yes` | off | Skip the interactive y/N confirmation prompt. **Agents must only set this when the user has explicitly authorized creating the share in this conversation.** |
| `--json` | off | Emit the response as JSON. |

**Confirmation flow (default):**

```text
About to create a Frame.io share:
  Name:         Director review — v4
  Visibility:   public link (anyone with URL)
  Assets:       2 files
                  - Rough Cut v4.mov   (file_xxx1)
                  - Color Pass v2.mov  (file_xxx2)
  Comments:     allowed
  Download:     not allowed
  Expires:      never
  Password:     none

Create this share? [y/N]:
```

If stdin isn't a TTY and `--yes` is absent, the command refuses with a clear remediation. Passwords are never echoed in the confirmation summary; only "set" / "none" is shown.

**Output (`--json`):**

```json
{
  "share_id": "...",
  "name": "Director review — v4",
  "url": "https://f.io/p/xxxxxx",
  "visibility": "public",
  "allow_comments": true,
  "allow_download": false,
  "expires_at": null,
  "password_protected": false,
  "asset_count": 2,
  "asset_ids": ["...", "..."],
  "created_at": "2026-06-30T13:00:00Z"
}
```

**What `share create` does NOT do (and the CLI must reject):**

- It does not list, modify, or revoke any existing share. Those endpoints exist in Frame.io V4 — the CLI just doesn't call them.
- It does not upload anything. The assets must already exist in Frame.io.
- It does not auto-`--yes` itself, even on retry; the agent must surface the prompt to the user.

---

## 12. Optional MCP layer

Not the first-run path. An optional adapter over the same internal functions — no duplicate logic.
```bash
frameio-agent mcp
```
Tools: `frameio_auth_status`, `frameio_list_projects`, `frameio_latest`, `frameio_search_assets`, `frameio_get_comments`, `frameio_brief_project`, `frameio_create_share` (must require an explicit `confirm: true` argument from the calling agent — the MCP layer enforces the same gate the CLI does).
README: *"If your agent supports MCP, run this as an MCP server. If not, your agent can call the CLI directly."*

---

## 13. `AGENTS.md` (required at repo root)

```md
# Frame.io Agent Starter — Agent Instructions

You are helping the user connect this local repo to their Frame.io account, read-only.

Rules:
- Start read-only. Never upload, delete, move, rename, or create shares.
- Never print access tokens, refresh tokens, client secrets, auth codes, or token JSON.
- Do not commit .env, token files, or local config.
- Use Frame.io V4 via Adobe IMS OAuth. Do not use legacy fio-u-* tokens.
- Run setup and verify before anything else. Prefer --json when parsing.
- If auth fails, run `frameio-agent auth login` and ask the user for the redirect/code if needed.

Suggested first task:
1. Install dependencies (scripts/setup.py).
2. Create local .env from .env.example.
3. Help the user authenticate (auth login).
4. verify.
5. projects --json.
6. latest --project <id> --json, then comments <file_id> --json, then summarize the notes.
```

---

## 14. Configuration

`.env.example`:
```dotenv
# Frame.io / Adobe IMS OAuth Web App credentials (create via `auth login` walkthrough)
FRAMEIO_CLIENT_ID=your_client_id_here
FRAMEIO_CLIENT_SECRET=your_client_secret_here
FRAMEIO_REDIRECT_URI=http://localhost:8722/callback

# Local token cache — never commit the real file
FRAMEIO_TOKEN_FILE=.frameio-agent/tokens.json

# Optional defaults
FRAMEIO_ACCOUNT_ID=
FRAMEIO_WORKSPACE_ID=
```

`.gitignore` must include:
```gitignore
.env
.env.local
.frameio-agent/
*tokens*.json
*.token.json
.DS_Store
__pycache__/
.pytest_cache/
```

---

## 15. Architecture

```text
frameio-agent-starter/
  README.md   AGENTS.md   .env.example   .gitignore   pyproject.toml
  frameio_agent/
    __init__.py
    cli.py          # routing + JSON/text formatting
    config.py       # load .env, resolve config path, validate keys
    auth.py         # IMS OAuth: walkthrough, PKCE, loopback capture, token cache + refresh
    client.py       # thin authenticated Frame.io V4 REST client (retry, paging, redaction)
    api.py          # endpoint wrappers: me, accounts, workspaces, projects, folders, files, comments
    listing.py      # projects + recency-first `latest`
    search.py       # capped traversal name/path search
    comments.py     # fetch + normalize comments (timecode + seconds)
    brief.py        # project summary from listing + comments
    redact.py       # redact secrets in strings/errors/logs
    errors.py       # friendly exceptions w/ remediation
  optional/
    mcp_server.py   # optional MCP wrapper over the same functions
  scripts/
    setup.py        verify.py
  tests/
    test_redaction.py  test_config.py  test_url_parsing.py  test_cli_json_shapes.py
    fixtures/  fake_projects.json  fake_comments.json
```

**API note for the implementer:** Frame.io V4 is a **REST API authenticated via Adobe IMS OAuth**. Build a thin REST client (one HTTP library); do not rely on the legacy `fio-u-*` token SDK. Confirm exact endpoint paths, paging, and the sort/query parameters against the **current Frame.io V4 API docs** — the logical surface is: current user, accounts, workspaces, projects, folders, files (with `updated_at` + `media_type`), and per-file comments (with timecode). Keep all calls in `api.py` so a future API change is a one-file fix.

---

## 16. Safety & privacy

**Secret handling.** Never print raw env values for keys containing `TOKEN`, `SECRET`, `KEY`, `CODE`, `AUTH`. Redact URL query params named `code`, `access_token`, `refresh_token`, `client_secret`, `Signature`, `X-Amz-Signature`. Token file gets private perms where the OS supports it.

**Bounded-write default.** v1 must not mutate Frame.io state except: (a) OAuth token refresh, (b) local token cache writes, and (c) **the single `share create` POST** described in §11.8, which is guarded by an interactive prompt and the `--yes` bypass policy. Allowed read calls: user/account/workspace/project/folder/file list+show, comments list, share-creation POST. Disallowed in v1: upload, delete, move, rename, permission changes, share modification, share revocation, share listing.

---

## 17. Error messages (a feature)

| Situation | Message |
|---|---|
| Missing config | `Missing FRAMEIO_CLIENT_ID. Run: frameio-agent auth login` |
| Missing token | `Frame.io is not authenticated. Run: frameio-agent auth login` |
| Expired/revoked refresh | `Your Frame.io session expired. Run: frameio-agent auth login` |
| Multiple accounts | `Found multiple accounts. Re-run with --account <id>.` |
| Traversal cap hit | `Traversal cap reached. Try `latest` instead, or narrow with --folder <id>.` |
| No results | `No matching assets. Try `latest`, or list projects first.` |
| Share create on non-TTY without --yes | `Share creation requires interactive confirmation; stdin is not a TTY. Re-run with --yes if the user has explicitly authorized creating this share.` |
| Share create scope missing | `Frame.io rejected the share request (insufficient scope). Run: frameio-agent auth login` |

---

## 18. Documentation

**README sections:** what it is · who it's for · **animated GIF of the success moment up top** · quick start (copy-paste agent prompt) · manual quick start · commands · JSON examples · security/secrets · optional MCP · troubleshooting · disclaimer · roadmap.

The README **opens with a GIF of the terminal success moment** (connect → latest → comments summarized). A repo like this lives or dies on the first screen.

**Required copy-paste agent prompt:**
```md
Connect this repo to my Frame.io account, read-only.
1. Read AGENTS.md. 2. Install deps. 3. Set up .env. 4. Run auth login. 5. verify.
6. List my projects. 7. Find my latest cut. 8. Summarize its review comments with timecodes.
Do not print secrets. Prefer --json when parsing.
```

---

## 19. Acceptance criteria for v1

**Functional**
- [ ] New user clones, runs setup, and `auth login` completes (incl. first-time Adobe app creation) in **under 10 minutes**.
- [ ] A coding agent can complete the whole flow from `AGENTS.md` + `README.md` alone, without asking the human to learn MCP or Adobe internals.
- [ ] `verify` confirms access without printing secrets.
- [ ] `projects --json`, `latest --json`, `search --json` return parseable JSON (or a clear no-results message).
- [ ] `comments <file_id> --json` returns normalized comments with `timecode` + `timestamp_seconds`.
- [ ] **North-star:** an agent reaches "summarize my latest cut's review notes with timecodes" end-to-end.

**Safety**
- [ ] `.env` + token files git-ignored; redaction tests pass for token-like strings and signed URLs.
- [ ] No command prints raw token contents.
- [ ] No mutation calls anywhere in v1.

**Agent usability**
- [ ] Every command supports `--json`; JSON shapes documented + stable.
- [ ] Nonzero exits include the exact next command.
- [ ] README has the copy-paste agent prompt + success GIF.

---

## 20. Testing

**Unit** (no network): env loading without printing values; token path resolution; redaction of tokens/codes/signed URLs; CLI JSON shapes; no secret leakage in exception formatting.

**Integration smoke** (burner creds): `verify` exits 0; `projects --json` returns valid JSON; no token values in stdout/stderr.

**Agent simulation:** a fresh coding agent, given only README + AGENTS.md, completes setup → auth status → projects → latest → comments. **Pass only if it never asks the human to understand MCP or Adobe internals first.**

---

## 21. Metrics

- Clone → `verify` success: **< 10 min** for a first-timer (including Adobe app creation).
- Clone → first `latest` result: **< 12 min**.
- Users who can run without MCP: **100%**.
- Token leaks in logs/examples/tests: **0**.
- ≥ 1 frontier agent completes setup from the provided prompt with no extra context.
- **Demo metric:** within 5 minutes after auth, an agent answers: *"Find my latest video with review comments and summarize what people want changed."*

---

## 22. Open questions → resolved

1. **BYO Adobe app vs hosted demo?** → **BYO via the `auth login` wizard is canonical.** Optional `--demo` sandbox mode only if a sandbox is maintainable; never the default.
2. **Token storage: local JSON vs keychain?** → **Local JSON** (transparent + agent-inspectable for `auth status`) with private file perms. OS keychain is a later opt-in flag.
3. **Demo content?** → Use a **sandbox or the user's own project**, anonymized; never ship real third-party media in examples.
4. **Summarize in CLI or agent?** → **CLI returns comments; the agent summarizes.** (Keeps the tool dumb, safe, and model-agnostic.)
5. **Test matrix?** → **Claude Code, OpenAI Codex CLI, Cursor** (and Gemini CLI if time). Public matrix only — no internal/proprietary agents.
6. **Default share visibility (v0.3)?** → **Public link.** Matches the most common "send the director a review URL" workflow. Recipients don't need a Frame.io account. The agent must show the user what `public` means in the confirmation summary before creating.
7. **Share create confirmation policy (v0.3)?** → **Always interactive y/N by default; `--yes` bypasses.** Agents must only set `--yes` when the user has explicitly authorized that specific share in the current conversation. On non-TTY stdin without `--yes`, the command refuses.

---

## 23. Roadmap

- **v0.1** — skeleton: structure, `AGENTS.md`, `.env.example`, `auth status` with mocked client, redaction tests.
- **v0.2** — real read-only: `auth login` (wizard + PKCE loopback), `verify`, `projects`, `latest`, `search`, `comments`, `brief`; JSON contracts frozen.
- **v0.3** — adds `share create` (the one mutation), with public-link default + interactive confirmation + `--yes` bypass; OAuth scope updated to allow the write call; AGENTS.md changed from blanket prohibition to one-item allow-list.
- **v0.4** — optional MCP wrapper mirroring the CLI (including `frameio_create_share` with `confirm:true` gate); example configs for Claude Code / Cursor.
- **v0.5** — polished README + success GIF (both moments: see-comments AND send-share); tested against ≥ 2 agents; `pipx` / `uvx` packaging.
- **v1.0** — public beginner release: read + the single share-create mutation, unaffiliated disclaimer.
- **Later (separate, opt-in, explicit confirmation each):** v1.2 may add `share list` + `share revoke` (still mutations on shares only, never on assets). *Upload, delete, rename, move, permission changes, and any non-Frame.io ingestion (YouTube, etc.) remain out of this product's identity and should be a different repo if ever built.*

---

## 24. Session-1 build plan (for a fresh agent)

Execute in order; verify each before moving on.

**Task 1 — Skeleton.** Create `README.md`, `AGENTS.md`, `.env.example`, `.gitignore`, `pyproject.toml`, `frameio_agent/__init__.py`, `frameio_agent/cli.py`.
→ verify: `python -m frameio_agent.cli --help`

**Task 2 — Config + redaction.** `config.py`, `redact.py`, `tests/test_config.py`, `tests/test_redaction.py`.
→ verify: `pytest tests/test_config.py tests/test_redaction.py -v`

**Task 3 — Auth (the hard one — do it carefully, §10).** `auth.py` (walkthrough + PKCE + loopback capture + token cache/refresh), `client.py`, wire `auth login` / `auth status` / `verify`.
→ verify with a real Adobe Web App OAuth credential: `frameio-agent verify` exits 0; no token printed.

**Task 4 — Listing.** `api.py`, `listing.py`, `projects` + `latest`, `tests/test_cli_json_shapes.py`.
→ verify: `frameio-agent projects --json` and `frameio-agent latest --project <id> --json` parse.

**Task 5 — Comments + search + brief.** `comments.py`, `search.py`, `brief.py`.
→ verify the **north-star**: `comments <file_id> --json` returns timecoded notes; hand to the model → grouped, timecoded summary.

**Task 6 — Docs + GIF + optional MCP.** README with success GIF + copy-paste prompt; `optional/mcp_server.py`.
→ verify: a fresh agent completes the §20 simulation from README + AGENTS.md alone.

---

## 25. Final product rule

If a first-time user or coding agent has to understand MCP, Adobe SDK internals, GraphQL share auth, S3 upload headers, or Frame.io Transfer to get value, **v1 has failed.**

The two wins v1 must nail (and only these two):

1. **See the notes:**
   ```text
   connect → verify → find latest cut → summarize its review comments
   ```
2. **Send the next cut:**
   ```text
   find the assets → share create --name "..." [files...] → review URL
   ```

Everything in this repo serves those two sentences. Anything else — uploads, deletes, permission edits, YouTube ingestion, share management, automation orchestration — is out of scope and belongs in a different repo.
