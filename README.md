# M3allema

**The open-source AI back office for small businesses.**
She drafts, asks, then acts, with a receipt for everything.

[![CI](https://github.com/BackendNeuron/m3allema/actions/workflows/ci.yml/badge.svg)](https://github.com/BackendNeuron/m3allema/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)

M3allema (معلّمة, Egyptian for "the boss lady who runs the show") is an AI agent that handles
office work: documents, spreadsheets, email and the web. Unlike general-purpose agents, she is
built for business owners, and **trust is the product**:

- **Approve-first.** Every tool has a risk level (`read`, `write`, `external`). Risky actions
  wait for the owner's approval. The rule is enforced in code, so no prompt or email can talk
  her past it.
- **Everything is logged.** Every step of every run goes into an append-only event log you
  can replay.
- **Any model.** Claude through its native API, plus anything OpenAI-compatible (OpenAI, Groq,
  Gemini, Ollama, OpenRouter, vLLM), with automatic fallback.
- **Built on MCP.** Her tools are MCP servers, and any MCP server plugs in.
- **Speaks your language.** English, Arabic, Egyptian and Gulf dialect, and Franco-Arabic.

> **Status: early development (Phase 1, milestone 5 done).** The agent loop, providers,
> file, Excel, Word/PDF, web, shell, Gmail, Calendar and Sheets tools, `policy.yaml`,
> budgets, receipts, resumable conversations, the web dashboard, onboarding, memory, skills,
> voice input and the Telegram bot all work. Evals and Docker are next on the
> [roadmap](#roadmap).

## Quick start

Not on PyPI yet. Until the first release, install from source:

```bash
uv tool install git+https://github.com/BackendNeuron/m3allema
m3allema init my-business     # creates the workspace files
cd my-business
m3allema onboard              # a short interview that fills them in for your business
cp .env.example .env          # then put your ANTHROPIC_API_KEY in .env
m3allema chat
```

Or with Docker (no Python needed):

```bash
git clone https://github.com/BackendNeuron/m3allema && cd m3allema
docker compose run --rm init          # creates ./workspace
# put your ANTHROPIC_API_KEY in workspace/.env
docker compose up -d dashboard        # the dashboard link is in: docker compose logs dashboard
```

The dashboard is published on `127.0.0.1` only, and everything stays in `./workspace`.

Try: *"Read the invoices in files/ and build an Excel summary"*. Reading runs on its own;
writing the workbook asks you first. When the run ends, a receipt in `receipts/` lists what
she did, what it cost and what still needs you.

## How it works

```
 CLI · Web dashboard · Telegram
            │
            ▼
   runtime.open_session()            composition root: wires everything below
            │
   ┌────────▼─────────┐
   │      Agent       │  plan → tool call → permission gate → act → observe → repeat
   └──┬─────┬─────┬───┘
      │     │     └── EventStore      append-only log of every step (SQLite / Postgres)
      │     └──────── ToolHub         built-in + external MCP servers
      └────────────── ModelRouter     main / fast / fallback models
                         ├─ AnthropicProvider    (native Claude API)
                         └─ OpenAICompatProvider (OpenAI, Groq, Gemini, Ollama...)
```

The agent loop only depends on small interfaces (`LLMProvider`, `ToolExecutor`,
`PermissionGate`, `EventSink`). Concrete classes are injected at start-up, which keeps every
part replaceable and easy to test. See [docs/architecture.md](docs/architecture.md).

## The workspace

`m3allema init` creates a folder the owner can read and edit:

| File | Purpose |
|---|---|
| `IDENTITY.md` | Her tone and languages |
| `BUSINESS.md` | Facts about the business |
| `OWNER.md` | The owner's preferences |
| `RULES.md` | Soft guidance for the model |
| `MEMORY.md` | Facts she learned, one dated line each; edit or delete freely |
| `skills/` | Procedures for recurring jobs, one Markdown file each |
| `config.yaml` | Providers, models, tools, prices ([reference](docs/configuration.md)) |
| `policy.yaml` | **Enforced** permissions (auto / ask / deny) and budgets |
| `.env` | API keys, never committed |
| `files/` | The only folder the built-in tools can touch |
| `receipts/` | One plain-language receipt per run |

## Commands

| Command | What it does |
|---|---|
| `m3allema init [PATH]` | Create a workspace |
| `m3allema onboard` | Answer the setup interview (also in the dashboard) |
| `m3allema chat` | Talk to M3allema |
| `m3allema chat --resume` | Continue the last conversation (`-c ID` for a specific one) |
| `m3allema run "TASK"` | Run one task and exit |
| `m3allema serve` | Open the web dashboard on `127.0.0.1` |
| `m3allema telegram` | Run the Telegram bot ([setup guide](docs/telegram.md)) |
| `m3allema eval` | Run the public eval suite with your models ([details](docs/evals.md)) |
| `m3allema conversations` | Saved conversations you can resume |
| `m3allema runs list` | Recent runs with status, tokens, cost and today's spend |
| `m3allema runs show ID` | Replay every step of a run |
| `m3allema google connect` | Sign in to Google once ([setup guide](docs/google-setup.md)) |
| `m3allema mcp list` / `mcp trust NAME` | Review and approve external MCP servers' tools |

Inside `chat`: `/compact` summarises the conversation and continues from the summary (the
original stays saved), `/new` starts fresh, `/help` lists commands. `mek` is a short alias
for `m3allema`.

### The dashboard

`m3allema serve` starts a local dashboard and opens it in your browser: a live timeline of
each run, approve and decline buttons for risky actions, receipts, cost per run and the run
history. It listens only on `127.0.0.1`, and the link it prints carries a one-time token that
every request must present; connections from other websites are refused. The interface is
built from `web/` (React, TypeScript, GSAP, Vite) and ships inside the Python package, so
users do not need Node.js.

On a new workspace the dashboard opens on **Setup**: a short interview about the business,
the owner, M3allema's tone and languages, and which tools and limits to use. The answers
rewrite `IDENTITY.md`, `BUSINESS.md`, `OWNER.md` and `RULES.md`, and set the matching lines
in `config.yaml` and `policy.yaml` without touching your comments or other settings. Every
file is backed up to `.m3allema/backups/` first. Run it again any time from Setup or with
`m3allema onboard`.

The microphone button records a voice message, transcribes it (locally with faster-whisper
`small` by default) and puts the text in the message box for you to edit. It is never sent on
its own. Local transcription needs `pip install "m3allema[voice]"`; set `speech.engine: groq`
to use Groq's hosted Whisper instead.

### Memory and skills

**Memory** is `MEMORY.md`. When you tell her something that will matter later ("Cairo Hotel
pays net 30"), she offers to remember it, and with your approval adds one dated line. The file
is part of every conversation, so she knows it next time. Delete a line and she forgets it.

**Skills** are written procedures in `skills/`, one Markdown file each with a one-line
description. She sees the list of skills and reads a skill's full steps when a task matches.
New workspaces start with five: invoice summary, inbox triage, meeting scheduler, weekly
report and client follow-up. You can write your own, and after a job goes well she can
propose saving it as a new skill.

Memory and skills outlive a conversation, so saving them always needs your approval (the
template `policy.yaml` sets `memory__*` and `skills__save_skill` to `ask` even when `write`
is `auto`). That stops an email or web page from planting lasting instructions.

### Telegram

`m3allema telegram` lets you send tasks and voice notes from your phone and approve actions
with a tap. Only the Telegram ids you list are served. Voice notes come back as a transcript
with Send and Edit buttons, so nothing runs until you confirm. See
[docs/telegram.md](docs/telegram.md).

## Built-in tools

| Server | Tools | Default policy |
|---|---|---|
| `files` | list, read (paged), search | auto |
| `files` | write (never overwrites unless asked) | ask |
| `excel` | list sheets, read sheet (paged) | auto |
| `excel` | write sheet, append rows | ask |
| `docs` | read Word or PDF | auto |
| `docs` | write Word | ask |
| `web` | fetch a public page (private networks blocked) | auto |
| `shell` | run a command in a Docker sandbox with no network (opt-in) | ask |
| `gmail` | search, read | auto |
| `gmail` | draft, archive | ask |
| `gmail` | **send** | ask (external) |
| `calendar` | list events | auto |
| `calendar` | **create event with invitations** | ask (external) |
| `sheets` | read range | auto |
| `sheets` | append rows / **overwrite range** | ask |
| `memory` | remember a fact / forget facts | ask (always) |
| `skills` | list, read | auto |
| `skills` | save a new skill | ask (always) |

Google tools need a one-time sign-in: see [docs/google-setup.md](docs/google-setup.md).

External MCP servers are untrusted: their tools always ask before running, and a tool that is
new or whose description changed stays hidden until you approve it with `m3allema mcp trust`.
This blocks "tool poisoning", where a server slips instructions into a tool description.

## Evals

`m3allema eval` runs 15 real tasks across spreadsheets, documents, permissions, safety
(prompt injection in files and emails), Arabic and Franco-Arabic, memory and skills, each in a
throwaway workspace with your own models, and reports the pass rate per category. See
[docs/evals.md](docs/evals.md).

Latest full run: **14/15 (93%)** with `openai/gpt-oss-120b` on Groq (M3allema 0.1.0).

| Category | Passed |
|---|---|
| Spreadsheets | 2/2 |
| Documents | 3/3 |
| Permissions | 2/2 |
| Safety (prompt injection, warning the owner) | 4/4 |
| Arabic and Franco-Arabic | 2/2 |
| Memory and skills | 1/2 |

The one failure was the starter invoice skill telling her to ask for the period instead of
using a sensible default; the skill was fixed and the case then passed 2 of 2 targeted runs.
The first run scored 10/14. The problems it found (crashes on rejected tool calls, empty
replies, skipped skills, a planted instruction that the model acted on, files written to the
wrong folder) were fixed in the agent, not by loosening the tests. Model runs vary, so rerun
the suite with your own model before relying on a number.

## Development

```bash
uv sync
uv run pytest            # tests
uv run ruff check .      # lint
uv run mypy              # strict type checking

cd web; npm ci; npm run build   # rebuild the dashboard into src/m3allema/server/static
```

During dashboard work, run `m3allema serve` and `npm run dev` in `web/` (Vite proxies `/api`
to port 8765). Commit the rebuilt static files; CI fails if they are out of date.

See [CONTRIBUTING.md](CONTRIBUTING.md). Security reports: [SECURITY.md](SECURITY.md).
Releases: [CHANGELOG.md](CHANGELOG.md); pushing a `v*` tag builds, checks and publishes to PyPI.

## Roadmap

| Milestone | Scope |
|---|---|
| ✅ 1. Foundation | Agent loop, Claude + OpenAI-compatible providers, files and web tools (MCP), permission gate, event log, CLI |
| ✅ 2. Trust layer + documents | `policy.yaml`, budgets, cost per run, receipts, resumable conversations and `/compact`, Excel and Word/PDF tools, sandboxed shell, large-output paging |
| ✅ 3. Google + MCP | Gmail, Calendar, Sheets with encrypted sign-in; external MCP tools pinned and approved before use |
| ✅ 4. Web dashboard | Live run timeline, approve buttons, cost per run, onboarding interview |
| ✅ 5. Memory, skills, Telegram | Memory and learned skills with approval, five starter skills, voice input (local Whisper or Groq), Telegram tasks and approvals |
| 6. Evals + launch | ✅ Public eval suite, Docker one-command setup, release pipeline · next: first published pass rate and PyPI release |

## License

[Apache-2.0](LICENSE). "M3allema" is a trademark of its author; the license does not grant
rights to the name.
