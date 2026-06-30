# Frame.io Agent

*by [VAXA Studio](https://vaxa.studio)*

> **Run Frame.io from your coding agent.**

Your agent can find your latest cut, summarize the director's notes with timecodes, pull a YouTube reference straight into a project folder, build a contact sheet from your last shoot, and send a curated review link to a client — all without opening Frame.io.

10-minute setup. Works with **Claude Code**, **Cursor**, **OpenAI Codex CLI**, **Gemini CLI**, or any agent that runs local commands. MCP optional. Read-only by default; every mutation (upload, share, comment) is confirmation-gated.

> *Unofficial community tool. Not affiliated with, endorsed by, or supported by Adobe or Frame.io. "Frame.io" is a trademark of Adobe.*

---

## Quick start (with an agent)

```bash
git clone https://github.com/sheldondirector/frameio-agent
cd frameio-agent
```

Then paste this to your coding agent:

```text
Connect this repo to my Frame.io account, read-only.
1. Read AGENTS.md.
2. Install deps.
3. Set up .env.
4. Run `frameio-agent auth login`.
5. Run `frameio-agent verify`.
6. List my projects.
7. Find my latest cut.
8. Summarize its review comments with timecodes.
Do not print secrets. Prefer --json when parsing.
```

## Quick start (manual)

```bash
python scripts/setup.py                          # install deps
cp .env.example .env                              # create config
python -m frameio_agent.cli auth login            # guided OAuth wizard
python -m frameio_agent.cli verify
python -m frameio_agent.cli projects --json
python -m frameio_agent.cli latest --project <id> --json
python -m frameio_agent.cli comments <file_id> --json
```

## What it does

**Read (no confirmation needed):**
- **`auth login`** — guided Adobe IMS OAuth wizard with clipboard auto-detect. First time only.
- **`auth status` / `verify`** — confirms the connection without printing tokens.
- **`projects --json`** — lists accounts / workspaces / projects.
- **`latest --project <id>`** — newest-updated video assets, recency-first.
- **`search "<query>"`** — account-wide search across all your projects and folders.
- **`comments <file_id> --json`** — normalized review notes (timecode + timestamp_seconds + author + thread).
- **`brief --project <id>`** — one-paragraph project status.

**Write (every one is confirmation-gated):**
- **`share create <file_id> [<file_id>...] --name "..."`** — bundle assets into a Frame.io review share. Multi-asset, optional `--reviewers email@a.com,email@b.com`. Default visibility public; `--restricted` for signed-in only. Prompts y/N before sending; `--yes` to skip.
- **`refs add <url-or-path> --folder <folder_id>`** — pull a YouTube/X URL via yt-dlp, or upload a local file, or trigger Frame.io's remote_upload for direct URLs Frame.io can fetch. One-stop reference ingestion.
- **`contact-sheet --project <id> --out sheet.png`** — composite thumbnails from a project or folder into a single image grid.

**Read-only by default.** Mutations only fire after explicit y/N confirmation (or `--yes` when the user has authorized the action in the current conversation).

## Security

- **Read-only by default; every mutation is opt-in and confirmation-gated.** Share creation, reference uploads, comment posts — all require y/N (or an explicit `--yes` the user authorized). No silent writes ever.
- **Delete / rename / move / permission-change are still NOT in scope.** Even the agent can't accidentally trash your project hierarchy. Those endpoints exist in V4; the CLI just doesn't call them.
- **Secrets stay local.** `.env` and `~/.frameio-agent/tokens.json` are git-ignored. The CLI redacts token-like values from any output. Share passwords are never echoed.
- **Bring your own credentials.** The wizard helps you create an Adobe Developer Console OAuth Web App; nothing is ever sent to the maintainers.

## Optional: MCP

If your agent supports MCP, run `frameio-agent mcp` to expose the same operations as MCP tools. The CLI is the spine — MCP is a thin wrapper.

## Troubleshooting

| If you see | Run |
|---|---|
| `Missing FRAMEIO_CLIENT_ID` | `frameio-agent auth login` |
| `Frame.io is not authenticated` | `frameio-agent auth login` |
| `Your Frame.io session expired` | `frameio-agent auth login` |
| `Found multiple accounts` | Re-run with `--account <id>` |
| `Traversal cap reached` | Use `latest` instead, or pass `--folder <id>` |

## License

MIT. See `LICENSE`.

---

Built by **[VAXA Studio](https://vaxa.studio)** — we make tools for creative teams using coding agents.

*Unofficial community tool. Not affiliated with, endorsed by, or supported by Adobe or Frame.io.*
