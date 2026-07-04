# Frame.io Agent

[![CI](https://github.com/sheldondirector/frameio-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/sheldondirector/frameio-agent/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

*by [VAXA Studio](https://vaxa.studio)*

> **Turn your coding agent into an assistant editor who actually knows Frame.io.**

Ask your agent, from anywhere:

- *"Dig through today's clips and cut me a reel of only the shots that don't suck."*
  → `frames pull` hands your agent a frame from every clip; it judges them and ships the keepers as a review link.
- *"Read every note the client left on v7 and tell me what they actually want."*
  → `comments --json` returns every note with timecodes; your agent does the diplomacy.
- *"Contact sheet of the shoot — minus every take with a C-stand in the background."*
  → your agent looks at the frames, spots the C-stands, rebuilds the sheet without them.

The CLI has **no LLM inside it** — it gives whatever agent you already run (Claude Code, Cursor, Codex, Gemini CLI, any OpenRouter harness) clean JSON, real pixels, and confirmation-gated write commands. Read-only by default; it can't delete, rename, move, or change permissions. Ever.

<!-- TODO: 5-second terminal GIF of the success moment (frames pull → agent judges → filtered contact sheet). Record after next live run. -->

> *Unofficial community tool. Not affiliated with, endorsed by, or supported by Adobe or Frame.io. "Frame.io" is a trademark of Adobe.*

---

## Prerequisites

- A **Frame.io V4** account (the `next.frame.io` platform — legacy v3 `fio-u-*` tokens won't work).
- An **Adobe ID** that can open the [Adobe Developer Console](https://developer.adobe.com/console/projects) and add the Frame.io API (free; one-time ~5-minute OAuth app setup — the wizard walks you through it).
- **Python 3.10+** and **git**.
- Optional: a **multimodal** agent for the vision workflows; `pip install "frameio-agent[images]"` for contact sheets; `[youtube]` for YouTube/X ingestion.

## Quick start (with an agent)

```bash
git clone https://github.com/sheldondirector/frameio-agent
cd frameio-agent
```

Then paste this to your coding agent:

```text
Connect this repo to my Frame.io account.
1. Read AGENTS.md — it has the rules and the agent-driven login flow.
2. Install deps: python scripts/setup.py
3. Set up .env from .env.example (ask me for my Adobe OAuth Client ID and Secret).
4. Authenticate with the two-step flow: run `frameio-agent auth start --json`,
   show me the sign-in URL, and when I paste the redirect URL back, run
   `frameio-agent auth complete "<that url>"`.
5. Run `frameio-agent verify`.
6. Then: find my latest cut and summarize its review comments with timecodes.
Never print secrets. Prefer --json when parsing.
Every write command shows a confirmation summary — ask me before using --yes.
```

## Quick start (manual, human at the terminal)

```bash
python scripts/setup.py                          # install deps
python -m frameio_agent.cli auth login            # guided OAuth wizard (interactive)
python -m frameio_agent.cli verify
python -m frameio_agent.cli projects --json
python -m frameio_agent.cli latest --project <id> --json
python -m frameio_agent.cli comments <file_id> --json
```

## What it does

**Read (no confirmation needed):**
- **`auth login`** — guided Adobe IMS OAuth wizard with clipboard auto-detect (for humans at a terminal). Agents use **`auth start`** / **`auth complete`** instead — non-interactive, documented in `AGENTS.md`.
- **`auth status` / `verify`** — confirms the connection without printing tokens.
- **`projects --json`** — lists accounts / workspaces / projects.
- **`latest --project <id>`** — newest-updated video assets, recency-first.
- **`search "<query>"`** — account-wide search. Add **`--nlp`** for natural-language matching (*"red car driving on highway"*), or keep the default lexical engine for exact names.
- **`comments <file_id> --json`** — normalized review notes (timecode + timestamp_seconds + author + thread).
- **`brief --project <id>`** — one-paragraph project status.

**Vision (give your agent eyes):**
- **`frames pull --project <id> --out ./frames`** — download one preview frame per clip + a `manifest.json` mapping each image back to its `file_id`. Read-only; writes only local files. Your multimodal agent then *looks* at the frames, judges them, and drives the next command — `share create` with the selects, or `contact-sheet --from-manifest --exclude` with the rejects. Works with any agent that can read an image.
- **`contact-sheet --project <id> --out sheet.png`** — thumbnail grid of a project or folder. Filter with `--only`/`--exclude` file_id lists, number tiles with `--index`, or build offline from a `frames pull` manifest with `--from-manifest`.

**Write (every one is confirmation-gated):**
- **`share create <file_id> [...] --name "..."`** — bundle assets into a Frame.io review share. Multi-asset; `--reviewers a@x.com,b@y.com` sends email invites (max 10); `--expires`, `--password`, `--no-download`. Default visibility is public-link; `--restricted` requires the `secure_sharing` feature on paid Frame.io plans (the CLI tells you plainly if yours lacks it).
- **`refs add <url-or-path> --folder <folder_id>`** — pull a YouTube/X/TikTok/Vimeo URL via yt-dlp, upload a local file, or point Frame.io at a direct URL it can fetch itself. One command, mode auto-detected.

**Read-only by default.** Mutations only fire after an explicit y/N confirmation (or `--yes` when the user has authorized that specific action).

## Security

- **Read-only by default; every mutation is opt-in and confirmation-gated.** Share creation and reference uploads require y/N (or an explicit, user-authorized `--yes`). No silent writes ever. Comment *posting* is not shipped; `comments` is read-only.
- **Delete / rename / move / permission-change are NOT in scope.** Those endpoints exist in Frame.io V4; the CLI just doesn't call them — and `AGENTS.md` instructs agents not to add them.
- **Secrets stay local.** `.env` and the token cache are git-ignored; the CLI redacts token-like values from all output; share passwords are never echoed.
- **Bring your own credentials.** Nothing is ever sent to the maintainers.

## Which agents work with this?

Any agent that can run local shell commands — the model is entirely your choice:

- **Claude Code / Cursor / OpenAI Codex CLI / Gemini CLI** — paste the quick-start prompt above and go.
- **OpenRouter-backed agents** (Aider, OpenHands, Cline, custom harnesses — any model): same thing. For the vision workflows, pick a multimodal model.
- **Agent-driven login:** agents use the non-interactive `auth start --json` → `auth complete "<redirect-url>"` pair; the interactive `auth login` is for humans at a terminal.

## Optional: MCP

If your agent supports MCP, run `frameio-agent mcp` to expose the core read operations (auth status, projects, latest, comments) as MCP tools. The CLI is the spine and carries the full command surface — MCP is a thin, read-only wrapper.

## Troubleshooting

| If you see | Do |
|---|---|
| `Missing FRAMEIO_CLIENT_ID` | Run `frameio-agent auth login` (or `auth start` if an agent is driving) |
| `Frame.io is not authenticated` / `session expired` | Re-run the login flow |
| `no pending login (or it expired)` | Run `frameio-agent auth start` again (15-min TTL) |
| `Could not resolve an account_id` | Set `FRAMEIO_ACCOUNT_ID` in `.env` (find it via `projects --json`) |
| `feature(s) not included in plan: secure_sharing` | Use the default `--public` share, or upgrade the Frame.io plan |
| `Warning: collection cap reached` | Re-run with a higher `--max-files` |
| `yt-dlp is not installed` | `pip install "frameio-agent[youtube]"` |
| `Pillow is required` | `pip install "frameio-agent[images]"` |

## Install without cloning

The CLI is published on PyPI as **`frameio-agent-starter`** — install it with pipx for a clean, per-user install, or with uvx for a one-shot run:

```bash
# pipx (persistent, adds `frameio-agent` to your PATH)
pipx install frameio-agent-starter
frameio-agent auth login

# uvx (no install needed — runs from cache)
uvx frameio-agent-starter --help
```

Both methods handle dependencies automatically. No `git clone`, no `pip install -e .`, no virtualenv.

## Roadmap

Open issues track what's next: HTTPS-loopback zero-paste auth, multi-frame extraction via ffmpeg. See [Issues](https://github.com/sheldondirector/frameio-agent/issues).

## License

MIT. See `LICENSE`.

## Credits

Built by **[VAXA Studio](https://vaxa.studio)** — we make tools for creative teams using coding agents.
Developed with [Claude Code](https://claude.com/claude-code) (Claude, by Anthropic) as pair programmer — architecture, implementation, tests, and this README were co-authored across human/agent sessions.

*Unofficial community tool. Not affiliated with, endorsed by, or supported by Adobe or Frame.io.*
