# Configuration reference

`config.yaml` lives at the root of a workspace. It is validated on load: unknown keys and
broken references fail with a clear message.

**Secrets never go in this file.** Write `env:NAME` and put the value in `.env` next to it (or
in the environment).

## `providers`

Named connections to LLM providers.

```yaml
providers:
  claude:
    type: anthropic
    api_key: env:ANTHROPIC_API_KEY
    options:
      effort: medium            # low | medium | high | xhigh | max
      refusal_fallback: true    # server retries refused requests on a suitable model
  groq:
    type: openai_compat
    base_url: https://api.groq.com/openai/v1
    api_key: env:GROQ_API_KEY
  local:
    type: openai_compat
    base_url: http://localhost:11434/v1   # Ollama: no key needed
```

| Key | Meaning |
|---|---|
| `type` | `anthropic` (native Claude API) or `openai_compat` (any Chat Completions server) |
| `api_key` | Usually `env:NAME`. Omit for local servers |
| `base_url` | Endpoint override; needed for most `openai_compat` servers |
| `options` | Adapter options. For `anthropic`: `effort`, `refusal_fallback` |

## `models`

Roles mapped to `provider/model`:

```yaml
models:
  main: claude/claude-opus-5-5      # required: plans and uses tools
  fast: groq/llama-3.3-70b-versatile # optional: cheap bulk steps (used from milestone 2)
  fallback: local/qwen3:8b           # optional: used when main is temporarily unavailable
```

## `agent`

| Key | Default | Meaning |
|---|---|---|
| `max_steps` | 25 | Model turns per run before stopping |
| `max_tokens` | 16000 | Output tokens per turn |
| `tool_timeout_s` | 60 | Seconds before a tool call is abandoned |

## `builtin_tools`

Built-in MCP servers to enable: `files`, `web`. Default: both.

Default: `[files, excel, docs, web]`. Add `shell` to enable the Docker sandbox, and
`gmail`, `calendar`, `sheets` after [connecting Google](google-setup.md).

| Server | Tools | Risk |
|---|---|---|
| `files` | `list_files`, `read_file` (paged with `start_line`), `search_files` | read |
| `files` | `write_file` (refuses to overwrite unless asked) | write |
| `excel` | `list_sheets`, `read_sheet` (paged with `start_row`) | read |
| `excel` | `write_sheet`, `append_rows` | write |
| `docs` | `read_document` (.docx, .pdf paged by page) | read |
| `docs` | `write_docx` (headings, bullets, paragraphs) | write |
| `web` | `fetch_url` (public http(s) only, private networks blocked) | read |
| `shell` | `run_command` in a container: no network, 512 MB, 1 CPU, non-root, sees only `files/` | external |
| `gmail` | `search_emails`, `read_email` | read |
| `gmail` | `create_draft`, `archive_email` | write |
| `gmail` | `send_email` | external |
| `calendar` | `list_events` | read |
| `calendar` | `create_event` (sends invitations) | external |
| `sheets` | `read_range` | read |
| `sheets` | `append_rows` | write |
| `sheets` | `update_range` (overwrites cells) | external |

Tool output longer than 8,000 characters is saved under `files/_tool_outputs/`; the model
gets the beginning and reads the rest a page at a time.

## `pricing`

Prices for models M3allema doesn't know, in USD per million tokens. Current Claude models
are built in. Without a price, a run's cost shows as unknown and budgets can't limit it.

```yaml
pricing:
  llama-3.3-70b-versatile: {input: 0.59, output: 0.79}
  qwen3:8b: {input: 0, output: 0}          # local model, free
```

# `policy.yaml` reference

Enforced in code by the permission gate. A missing file means the safe defaults shown here.

```yaml
defaults:          # by risk level
  read: auto       # runs on its own
  write: ask       # waits for approval
  external: ask
tools:             # per-tool overrides; shell-style patterns, first match wins
  "files__write_file": auto
  "shell__*": deny
budget:
  per_run_usd: 1.00
  per_day_usd: 10.00
```

| Mode | Meaning |
|---|---|
| `auto` | Runs without asking |
| `ask` | Waits for the owner. With nobody to ask (unattended run), it is declined |
| `deny` | Never runs, and the owner is not asked |

When a budget is reached the run stops with status `budget`. The day is counted in UTC.

## `mcp_servers`

External MCP servers. Their tools appear as `<name>__<tool>` and are always treated as
`external` risk, so they ask before running. Each tool's name, description and input schema
are fingerprinted: a tool that is new or has changed stays hidden until you approve it with
`m3allema mcp trust <name>` (review first with `m3allema mcp list`).

```yaml
mcp_servers:
  postgres:
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-postgres", "postgresql://localhost/shop"]
    enabled_tools: [query]          # optional allowlist
  notion:
    transport: http
    url: https://mcp.notion.com/mcp
```

## `storage`

```yaml
storage:
  url: postgresql+psycopg://user:pass@localhost/m3allema   # default: SQLite in .m3allema/
```

The database holds runs, the event log and every conversation message (which is what
`chat --resume` reads). Database migrations are not set up yet: after upgrading during early
development, delete `.m3allema/m3allema.db` if the CLI reports a missing column.

# Environment variables

| Variable | Used for |
|---|---|
| `ANTHROPIC_API_KEY` and any `env:NAME` in `config.yaml` | Provider keys, read from `.env` |
| `M3ALLEMA_SECRET_KEY` | Encrypts the Google sign-in token; created by `m3allema google connect` |
| `M3ALLEMA_DASHBOARD_TOKEN` | Fixed access token for `m3allema serve`. Without it, a new random token is made at each start and printed in the dashboard link. Set it only for development. |

# The onboarding interview

`m3allema onboard` and the dashboard's Setup page ask the same questions (defined in
`m3allema/workspace/onboarding.py`). The answers are validated, then:

- `IDENTITY.md`, `BUSINESS.md`, `OWNER.md` and `RULES.md` are rewritten.
- In `config.yaml`, the `builtin_tools:` line is set.
- In `policy.yaml`, `write:`, `external:`, `per_run_usd:` and `per_day_usd:` are set.

Other lines and comments are kept. A setting whose line cannot be found (because you
restructured the file) is listed as "set by hand" instead of guessed. Previous versions go to
`.m3allema/backups/<timestamp>/`.
