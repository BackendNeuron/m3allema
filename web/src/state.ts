// Pure state for the live session: server events in, thread + inspector out.
// Keeping this a reducer (no I/O) makes the UI predictable and easy to test.

import type { AgentEvent, ApprovalRequest, StoredMessage } from "./types";

export type Part =
  | { type: "text"; text: string }
  | { type: "tool"; callId: string; name: string; outcome?: "done" | "failed" | "not run" }
  | { type: "approval"; request: ApprovalRequest; decision?: boolean }
  | { type: "note"; text: string };

export interface Finish {
  status: string;
  steps: number;
  tokens: number;
  cost: number | null;
}

export type Item =
  | { kind: "user"; key: string; text: string }
  | { kind: "agent"; key: string; parts: Part[]; finish?: Finish };

export interface Step {
  callId: string;
  name: string;
  state: "running" | "done" | "error";
  meta: string;
}

export interface SessionState {
  items: Item[];
  steps: Step[];
  turns: number;
  tokens: number;
  cost: number;
  receipt: string | null;
  busy: boolean;
}

export const initialState: SessionState = {
  items: [],
  steps: [],
  turns: 0,
  tokens: 0,
  cost: 0,
  receipt: null,
  busy: false,
};

export type Action =
  | { type: "history"; history: StoredMessage[] }
  | { type: "event"; event: AgentEvent }
  | { type: "approval"; request: ApprovalRequest }
  | { type: "decided"; id: string; allow: boolean }
  | { type: "receipt"; markdown: string }
  | { type: "busy"; busy: boolean };

let counter = 0;
const nextKey = () => `k${++counter}`;

/** Apply a change to the last agent item (the one the current run is writing into). */
function updateAgent(state: SessionState, change: (parts: Part[]) => Part[], finish?: Finish): Item[] {
  const items = [...state.items];
  const index = items.findLastIndex((item) => item.kind === "agent");
  if (index < 0) return items;
  const agent = items[index] as Extract<Item, { kind: "agent" }>;
  items[index] = { ...agent, parts: change(agent.parts), finish: finish ?? agent.finish };
  return items;
}

function fromHistory(history: StoredMessage[]): Item[] {
  const items: Item[] = [];
  for (const message of history) {
    if (message.role === "user") {
      const summary = message.text.startsWith("<conversation_summary>");
      items.push({ kind: "user", key: nextKey(), text: summary ? "(continued from a summary)" : message.text });
    } else if (message.role === "assistant") {
      const parts: Part[] = [];
      for (const block of message.blocks) {
        if (block.type === "text" && block.text) parts.push({ type: "text", text: block.text });
        if (block.type === "tool_call") parts.push({ type: "tool", callId: block.id, name: block.name, outcome: "done" });
      }
      if (parts.length) items.push({ kind: "agent", key: nextKey(), parts });
    }
  }
  return items;
}

function applyEvent(state: SessionState, event: AgentEvent): SessionState {
  switch (event.kind) {
    case "run_started":
      return {
        ...state,
        busy: true,
        steps: [],
        turns: 0,
        tokens: 0,
        cost: 0,
        receipt: null,
        items: [
          ...state.items,
          { kind: "user", key: nextKey(), text: event.payload.task },
          { kind: "agent", key: nextKey(), parts: [] },
        ],
      };
    case "text_delta":
      return {
        ...state,
        items: updateAgent(state, (parts) => {
          const last = parts[parts.length - 1];
          if (last?.type === "text") return [...parts.slice(0, -1), { ...last, text: last.text + event.payload.text }];
          return [...parts, { type: "text", text: event.payload.text }];
        }),
      };
    case "turn_completed": {
      const usage = event.payload.usage;
      return {
        ...state,
        turns: state.turns + 1,
        tokens: state.tokens + usage.input_tokens + usage.output_tokens,
        cost: state.cost + (event.payload.cost_usd ?? 0),
      };
    }
    case "tool_call_started": {
      const { call } = event.payload;
      return {
        ...state,
        steps: [...state.steps, { callId: call.id, name: call.name, state: "running", meta: "running…" }],
        items: updateAgent(state, (parts) => [...parts, { type: "tool", callId: call.id, name: call.name }]),
      };
    }
    case "tool_call_finished": {
      const { call, result, duration_ms, risk } = event.payload;
      const notRun = result.is_error && result.content.startsWith("Not run:");
      const outcome = notRun ? "not run" : result.is_error ? "failed" : "done";
      return {
        ...state,
        steps: state.steps.map((step) =>
          step.callId === call.id
            ? { ...step, state: result.is_error ? "error" : "done", meta: `${risk || "?"} · ${outcome === "done" ? `${duration_ms} ms` : outcome}` }
            : step,
        ),
        items: updateAgent(state, (parts) =>
          parts.map((part) => (part.type === "tool" && part.callId === call.id ? { ...part, outcome } : part)),
        ),
      };
    }
    case "run_finished": {
      const p = event.payload;
      const finish = { status: p.status, steps: p.steps, tokens: p.usage.input_tokens + p.usage.output_tokens, cost: p.cost_usd };
      const note: Part[] = p.status !== "completed" && p.answer ? [{ type: "note", text: p.answer }] : [];
      return { ...state, busy: false, items: updateAgent(state, (parts) => [...parts, ...note], finish) };
    }
  }
}

export function reducer(state: SessionState, action: Action): SessionState {
  switch (action.type) {
    case "history":
      return { ...initialState, items: fromHistory(action.history) };
    case "event":
      return applyEvent(state, action.event);
    case "approval":
      return { ...state, items: updateAgent(state, (parts) => [...parts, { type: "approval", request: action.request }]) };
    case "decided":
      return {
        ...state,
        items: state.items.map((item) =>
          item.kind !== "agent"
            ? item
            : {
                ...item,
                parts: item.parts.map((part) =>
                  part.type === "approval" && part.request.id === action.id ? { ...part, decision: action.allow } : part,
                ),
              },
        ),
      };
    case "receipt":
      return { ...state, receipt: action.markdown };
    case "busy":
      return { ...state, busy: action.busy };
  }
}
