# Changelog

All notable changes are listed here. The project follows [Semantic Versioning](https://semver.org);
until 1.0, minor versions may change configuration formats (with notes here).

## [0.1.0] - unreleased

The first public release: the open-source core of M3allema.

### Agent and models

- Tool-use agent loop with step, token and cost budgets, and a fallback model.
- Native Claude provider and an OpenAI-compatible provider (OpenAI, Groq, Gemini, Ollama,
  OpenRouter, vLLM), with prices per run.
- Resumable conversations (`chat --resume`) and `/compact`; large tool output paged from
  files instead of flooding the context.

### Trust layer

- `policy.yaml` with auto / ask / deny per risk level and per tool, enforced in code.
- Daily and per-run budgets, a receipt for every run, and a replayable event log.
- External MCP tools are pinned and hidden until approved (`m3allema mcp trust`).

### Tools

- Files, Excel, Word/PDF, web fetch (private networks blocked), Docker-sandboxed shell.
- Gmail, Google Calendar and Google Sheets with encrypted sign-in.
- Memory (`MEMORY.md`) and skills (`skills/`) that always need approval to change, and five
  starter skills.

### Interfaces

- CLI, local web dashboard (live timeline, approvals, runs, onboarding interview, voice input)
  and a Telegram bot with approval buttons and voice notes.
- Voice input with local faster-whisper or Groq; transcripts are never sent on their own.

### Evals and setup

- Public eval suite (`m3allema eval`, 15 cases) with pass rate per category: 14/15 with
  `openai/gpt-oss-120b` on Groq. Runs that hit a provider quota stop and are marked incomplete.
- Prompt-injection defence: tool output is marked as data, and the agent refuses and reports
  instructions planted in files, emails or web pages.
- Retry policy: rejected tool calls are explained to the model and retried; transient
  provider errors retry once without a fallback model; empty replies are nudged once.
- Docker image and `compose.yaml` for a one-command setup.
