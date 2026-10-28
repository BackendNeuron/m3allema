// Shapes of the data the Python server sends. They mirror the dataclasses in
// m3allema.domain and the JSON built in m3allema.server.app.

export type Risk = "read" | "write" | "external";

export interface Usage {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
}

export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

export interface ToolResult {
  call_id: string;
  content: string;
  is_error: boolean;
}

export type AgentEvent =
  | { kind: "run_started"; payload: { run_id: string; task: string; model: string } }
  | { kind: "text_delta"; payload: { text: string } }
  | { kind: "turn_completed"; payload: { usage: Usage; model: string; cost_usd: number | null } }
  | { kind: "tool_call_started"; payload: { call: ToolCall } }
  | {
      kind: "tool_call_finished";
      payload: { call: ToolCall; result: ToolResult; duration_ms: number; risk: string };
    }
  | {
      kind: "run_finished";
      payload: {
        status: string;
        answer: string;
        usage: Usage;
        steps: number;
        cost_usd: number | null;
      };
    };

export interface ApprovalRequest {
  id: string;
  tool: string;
  risk: Risk;
  description: string;
  arguments: Record<string, unknown>;
}

export type StoredMessage =
  | { role: "user"; text: string }
  | {
      role: "assistant";
      blocks: ({ type: "text"; text: string } | { type: "tool_call"; id: string; name: string })[];
    }
  | { role: "tool"; results: ToolResult[] };

export interface PendingTool {
  server: string;
  name: string;
  status: "new" | "changed";
}

export type ServerMessage =
  | {
      type: "ready";
      conversation_id: string;
      history: StoredMessage[];
      pending_tools: PendingTool[];
    }
  | ({ type: "event" } & AgentEvent)
  | ({ type: "approval_request" } & ApprovalRequest)
  | { type: "receipt"; path: string; markdown: string }
  | { type: "compacted"; summary: string; conversation_id: string }
  | { type: "error"; message: string }
  | { type: "fatal"; message: string };

export interface Status {
  version: string;
  workspace: string;
  model: string | null;
  tools: string[];
  ready: boolean;
  problem?: string;
  spent_today_usd: number;
  budget: { per_run_usd: number | null; per_day_usd: number | null };
  policy: Record<Risk, string>;
  google_connected: boolean;
}

export interface RunRow {
  id: string;
  task: string;
  status: string;
  started_at: string;
  steps: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
}

export interface RunEvent {
  seq: number;
  kind: string;
  payload: Record<string, unknown>;
  at: string;
}
