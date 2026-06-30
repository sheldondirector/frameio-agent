# Frame.io Agent Starter

*by [VAXA Studio](https://vaxa.studio)*

> **47 director notes, summarized with timecodes, before you open Frame.io.**

Your coding agent can read every comment, find your latest cut, and send the next one for review — and it can't touch your edit, delete a file, or change a permission.

10-minute setup. Works with **Claude Code**, **Cursor**, **OpenAI Codex CLI**, **Gemini CLI**, or any agent that runs local commands. MCP optional.

> *Unofficial community tool. Not affiliated with, endorsed by, or supported by Adobe or Frame.io. "Frame.io" is a trademark of Adobe.*

---

## Quick start (with an agent)

```bash
git clone https://github.com/sheldondirector/frameio-agent-starter
cd frameio-agent-starter
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

- **`auth login`** — guided Adobe IMS OAuth wizard. If you don't have credentials yet, it prints a numbered walkthrough for the Adobe Developer Console. Captures the OAuth `code` automatically via a local loopback server (PKCE). You never paste anything.
- **`auth status` / `verify`** — confirms the connection without printing tokens.
- **`projects --json`** — lists accounts → workspaces → projects you can see.
- **`latest --project <id>`** — newest-updated video assets in a project, with comment counts. Recency-first; no full traversal.
- **`search "<query>" --project <id>`** — capped name search for when you need a specific asset.
- **`comments <file_id> --json`** — review notes normalized with both human `timecode` and numeric `timestamp_seconds`, plus author and thread info.
- **`brief --project <id>`** — one-paragraph "what's going on in this project."
- **`share create <file_id> [<file_id>...] --name "..."`** — the one mutation in v1. Bundles assets into a Frame.io review share and returns the URL. Prints a confirmation summary and waits for `y/N` before sending; pass `--yes` to skip. Default visibility is `--public` (anyone with the URL); use `--restricted` for signed-in users only. Passwords are never echoed.

## Security

- **Read by default, one explicit mutation.** v1 cannot upload, delete, rename, move, or change permissions. The only write operation is `share create`, which prints a confirmation summary and requires `y/N` (or an explicit `--yes`) before sending. See [PRD §5, §8, §11.8](PRD.md) for the full scope.
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
