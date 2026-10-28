# Architecture

M3allema is a small set of layers with one rule: **dependencies point inward**. The domain
knows nothing about SDKs, MCP or databases; the agent loop knows only interfaces; concrete
adapters live at the edges and are wired together in one place.

```
src/m3allema/
  domain/        plain data: messages, events, tool specs        (no dependencies)
  config/        typed config.yaml schema + loader                (pydantic)
  workspace/     workspace folder, templates, system prompt, onboarding, memory, skills
  providers/     LLMProvider interface + Anthropic / OpenAI-compatible adapters
  agent/         the loop, the permission gate, the interfaces it needs
  tools/         ToolHub (MCP client) + built-in MCP servers
  storage/       EventStore: runs and the append-only event log   (SQLAlchemy)
  runtime.py     composition root: builds a ready Session
  cli/           Typer commands + Rich rendering
  server/        FastAPI dashboard: REST + one WebSocket per tab, WebApprover
  speech.py      Transcriber protocol: local faster-whisper or Groq
  telegram.py    Telegram bot (long polling) reusing WebApprover for approvals
web/             React + Vite source of the dashboard (built into server/static)
```

## Request flow

1. The CLI calls `runtime.open_session()`, which loads the workspace and config, builds the
   providers, connects the MCP servers and returns a `Session` with an `Agent`.
2. `Agent.run(task)` appends the task to the conversation and asks the main model for a turn.
3. The provider streams `TextDelta` events, then one `TurnCompleted` with the neutral
   `AssistantMessage`.
4. For each tool call, the agent validates it, asks the `PermissionGate`, runs it through the
   `ToolExecutor` with a timeout, and sends every result back in one `ToolResultMessage`.
5. Steps 2–4 repeat until the model answers without tools, refuses, runs out of tokens, or hits
   `max_steps`. The run always ends with exactly one `RunFinished` event.
6. Every event goes to the `EventSink` (the `EventStore`) as it happens.

## The dashboard server

`m3allema serve` runs the FastAPI app from `server/app.py`. Read-only endpoints (`/api/status`,
`/api/runs`, `/api/conversations`) open the stores directly. Each browser tab opens one
WebSocket (`/api/ws`), and `LiveSession` builds a normal `Session` for it through the same
`open_session` composition root as the CLI, so both interfaces share one code path.
Approvals use `WebApprover`, an `Approver` strategy that sends an `approval_request` and waits
for the browser's answer; unanswered requests (closed tab, 15 minute timeout) are declined.
The onboarding interview is plain REST (`/api/onboarding`) over
`workspace/onboarding.py`, which the `onboard` CLI command uses too.
Every request needs the token printed at start-up, and WebSocket connections must come from
this local server's own origin.

## Memory, skills, voice and Telegram

Memory (`MEMORY.md`) and skills (`skills/*.md`) are plain files, read into the system prompt
when a session opens: the whole memory file, and one line per skill (the full steps load on
demand through `skills__read_skill`, so many skills cost little context). They change only
through the `memory` and `skills` MCP servers, whose writes the template policy always sends
to the owner for approval.

Voice input goes through the `Transcriber` protocol (`speech.py`). The dashboard posts audio to
`/api/transcribe` and receives text only; the Telegram bot replies with the transcript and
Send/Edit buttons. In both, a transcript runs only after the owner sends it.

The Telegram bot is another interface over `open_session`, like the CLI and the dashboard. It
reuses `WebApprover` with a `send` function that renders approval requests as messages with
inline buttons, so all three interfaces share one approval mechanism.

## Design decisions

### A neutral message format
Providers disagree on message shapes (Claude puts tool results in user turns, OpenAI uses
`tool` messages). The domain defines its own `UserMessage`, `AssistantMessage` and
`ToolResultMessage`; each adapter translates both ways. Switching or mixing providers never
touches the loop.

### Exact replay for Claude
`AssistantMessage.raw` keeps the SDK's own content blocks, thinking blocks included. The
Anthropic adapter sends them back unchanged on the next turn. Rebuilding them would break
Claude's thinking signatures. Turns from other providers are rebuilt from neutral blocks.

### Native adapters instead of one OpenAI-compatible shim
Claude's native API keeps prompt caching, effort control and server-side refusal fallbacks.
Everything else speaks the OpenAI Chat Completions dialect, so one second adapter covers it.

### The permission gate lives in code
Risk comes from the tool (`ToolSpec.risk`), never from the model. Built-in MCP servers declare
risk through MCP annotations; external servers are untrusted and always `external` (ask).
Declined calls return an error result telling the model not to retry. Without an approver,
risky calls are declined, so unattended runs fail safe.

### Failure is data
Unknown tools, invalid JSON arguments, timeouts and tool exceptions become `is_error` tool
results, so the model can recover. Provider failures end the run with `status="failed"`.
Transient provider errors switch to the fallback model, but only before any text was shown.

### History stays valid
If a turn is cut off (`max_tokens`) or refused while it contains tool calls, the calls are
never run (their arguments may be partial), and the loop closes them with "not run" results.
That way the next request in the conversation is still valid for every provider.

### Conversations are saved message by message
`ConversationStore` writes each message as it is added, so `chat --resume` rebuilds the exact
history. Claude turns keep their raw blocks, which round-trip unchanged through JSON.
`/compact` never edits a conversation: it asks the model for a summary, then continues in a
new conversation that starts from it. Large tool output is cut *before* it enters the
history (`OutputArchive`), for the same reason.

### Policy, budgets and receipts
`PolicyGate` applies `policy.yaml` (auto / ask / deny per risk level or tool pattern). The
agent prices every turn with `PriceBook` and stops when a per-run or per-day budget is
reached. `ReceiptWriter`, another event sink, turns each finished run into a markdown
receipt. `FanOutSink` sends events to both the database and the receipt writer.

### Append-only event log
`EventStore` only inserts. `runs show` replays a run from it. Streaming text fragments are not
stored, because the completed turn holds the same text.

## Patterns used

| Pattern | Where |
|---|---|
| Adapter | `AnthropicProvider`, `OpenAICompatProvider` translate the neutral model |
| Strategy | `PermissionGate`, `Approver` (terminal now; web and Telegram later) |
| Factory / registry | `providers.factory.build_provider`, `tools.servers.BUILTIN_SERVERS` |
| Repository | `EventStore`, `ConversationStore` hide SQLAlchemy from callers |
| Observer | `EventSink` receives every agent event; `FanOutSink` broadcasts them || Composition root | `runtime.open_session` is the only place objects are wired |
| Dependency inversion | `Agent` depends on protocols in `agent/interfaces.py` |
