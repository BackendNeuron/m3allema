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

> **Status: early development (Phase 1, milestone 2).** The agent loop, providers, file,
> Excel, Word/PDF, web and sandboxed shell tools, `policy.yaml`, budgets, receipts and
> resumable conversations work from the CLI. Gmail, the web dashboard and more are on the
> [roadmap](#roadmap).

## Quick start

Not on PyPI yet. Until the first release, install from source:

```bash
uv tool install git+https://github.com/BackendNeuron/m3allema
m3allema init my-business     # creates the workspace files
cd my-business
cp .env.example .env          # then put your ANTHROPIC_API_KEY in .env
m3allema chat
```

Try: *"Read the invoices in files/ and build an Excel summary"*. Reading runs on its own;
writing the workbook asks you first. When the run ends, a receipt in `receipts/` lists what
she did, what it cost and what still needs you.

## How it works

```
 CLI (today) · Web UI · Telegram (later)
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
| `config.yaml` | Providers, models, tools, prices ([reference](docs/configuration.md)) |
| `policy.yaml` | **Enforced** permissions (auto / ask / deny) and budgets |
| `.env` | API keys, never committed |
| `files/` | The only folder the built-in tools can touch |
| `receipts/` | One plain-language receipt per run |

## Commands

| Command | What it does |
|---|---|
| `m3allema init [PATH]` | Create a workspace |
| `m3allema chat` | Talk to M3allema |
| `m3allema chat --resume` | Continue the last conversation (`-c ID` for a specific one) |
| `m3allema run "TASK"` | Run one task and exit |
| `m3allema conversations` | Saved conversations you can resume |
| `m3allema runs list` | Recent runs with status, tokens, cost and today's spend |
| `m3allema runs show ID` | Replay every step of a run |

Inside `chat`: `/compact` summarises the conversation and continues from the summary (the
original stays saved), `/new` starts fresh, `/help` lists commands. `mek` is a short alias
for `m3allema`.

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

## Development

```bash
uv sync
uv run pytest            # tests
uv run ruff check .      # lint
uv run mypy              # strict type checking
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Roadmap

| Milestone | Scope |
|---|---|
| ✅ 1. Foundation | Agent loop, Claude + OpenAI-compatible providers, files and web tools (MCP), permission gate, event log, CLI |
| ✅ 2. Trust layer + documents | `policy.yaml`, budgets, cost per run, receipts, resumable conversations and `/compact`, Excel and Word/PDF tools, sandboxed shell, large-output paging |
| 3. Google + MCP | Gmail, Calendar, Sheets, external MCP hardening |
| 4. Web dashboard | Live run timeline, approve buttons, cost per run, onboarding interview |
| 5. Memory, skills, Telegram | Learned skills with approval, voice notes (local Whisper), Telegram approvals |
| 6. Evals + launch | Public eval suite and pass rate, Docker one-command setup |

## License

[Apache-2.0](LICENSE). "M3allema" is a trademark of its author; the license does not grant
rights to the name.
