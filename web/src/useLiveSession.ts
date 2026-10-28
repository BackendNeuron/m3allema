// The WebSocket to the agent: sends tasks and approvals, feeds server messages
// into the reducer.

import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { socketUrl } from "./api";
import { initialState, reducer } from "./state";
import type { PendingTool, ServerMessage } from "./types";

export type Connection = "connecting" | "open" | "closed";

export interface LiveSession {
  state: typeof initialState;
  connection: Connection;
  pendingTools: PendingTool[];
  notice: string | null;
  fatal: string | null;
  sendTask: (text: string) => boolean;
  decide: (id: string, allow: boolean) => void;
  compact: () => void;
  startNew: () => void;
  dismissNotice: () => void;
}

export function useLiveSession(onRunFinished: () => void): LiveSession {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [pendingTools, setPendingTools] = useState<PendingTool[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);
  const socket = useRef<WebSocket | null>(null);
  const finished = useRef(onRunFinished);
  finished.current = onRunFinished;

  useEffect(() => {
    const ws = new WebSocket(socketUrl());
    socket.current = ws;
    ws.onopen = () => setConnection("open");
    ws.onclose = () => setConnection("closed");
    ws.onmessage = (raw: MessageEvent<string>) => {
      const message = JSON.parse(raw.data) as ServerMessage;
      switch (message.type) {
        case "ready":
          dispatch({ type: "history", history: message.history });
          setPendingTools(message.pending_tools);
          break;
        case "event":
          dispatch({ type: "event", event: message });
          if (message.kind === "run_finished") finished.current();
          break;
        case "approval_request":
          dispatch({ type: "approval", request: message });
          break;
        case "receipt":
          dispatch({ type: "receipt", markdown: message.markdown });
          break;
        case "compacted":
          dispatch({ type: "history", history: [{ role: "user", text: "<conversation_summary>" }] });
          setNotice("Conversation compacted. Continuing from the summary.");
          break;
        case "error":
          dispatch({ type: "busy", busy: false });
          setNotice(message.message);
          break;
        case "fatal":
          setFatal(message.message);
          break;
      }
    };
    return () => ws.close();
  }, []);

  const send = useCallback((payload: object): boolean => {
    const ws = socket.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      setNotice("Not connected. Reload the page.");
      return false;
    }
    ws.send(JSON.stringify(payload));
    return true;
  }, []);

  return {
    state,
    connection,
    pendingTools,
    notice,
    fatal,
    sendTask: (text) => {
      const sent = send({ type: "task", text });
      if (sent) dispatch({ type: "busy", busy: true });
      return sent;
    },
    decide: (id, allow) => {
      if (send({ type: "approval", id, allow })) dispatch({ type: "decided", id, allow });
    },
    compact: () => {
      if (send({ type: "compact" })) {
        dispatch({ type: "busy", busy: true });
        setNotice("Summarising the conversation…");
      }
    },
    startNew: () => {
      send({ type: "new" });
    },
    dismissNotice: () => setNotice(null),
  };
}
