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

| Server | Tools | Risk |
|---|---|---|
| `files` | `list_files`, `read_file`, `search_files` | read |
| `files` | `write_file` (refuses to overwrite unless asked) | write |
| `web` | `fetch_url` (public http(s) only, private networks blocked) | read |

## `mcp_servers`

External MCP servers. Their tools appear as `<name>__<tool>` and are always treated as
`external` risk, so they ask before running.

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
