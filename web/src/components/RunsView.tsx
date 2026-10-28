import { useEffect, useState } from "react";

import { getJson, money } from "../api";
import type { RunEvent, RunRow } from "../types";

function summary(payload: Record<string, unknown>): string {
  const call = payload.call as { name: string; arguments: unknown } | undefined;
  if (call) return `${call.name} ${JSON.stringify(call.arguments).slice(0, 120)}`;
  for (const key of ["answer", "task"]) {
    if (typeof payload[key] === "string") return (payload[key] as string).slice(0, 120);
  }
  return "";
}

export function RunsView() {
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [selected, setSelected] = useState<RunRow | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getJson<RunRow[]>("/api/runs").then(setRuns, (e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!selected) return;
    getJson<RunEvent[]>(`/api/runs/${encodeURIComponent(selected.id)}/events`).then(
      setEvents,
      (e: Error) => setError(e.message),
    );
  }, [selected]);

  return (
    <main className="runs-view">
      <h2>Runs</h2>
      {error && <div className="banner">{error}</div>}
      <div className="table-wrap">
        <table className="runs-table">
          <thead>
            <tr>
              <th>Started</th>
              <th>Task</th>
              <th>Status</th>
              <th className="num">Steps</th>
              <th className="num">Tokens</th>
              <th className="num">Cost</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.id} onClick={() => setSelected(run)}>
                <td>{new Date(run.started_at).toLocaleString()}</td>
                <td>{run.task.slice(0, 80)}</td>
                <td>{run.status}</td>
                <td className="num">{run.steps}</td>
                <td className="num">{(run.input_tokens + run.output_tokens).toLocaleString()}</td>
                <td className="num">{money(run.cost_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selected && (
        <div className="run-detail">
          <strong>{selected.task}</strong>
          {events.map((event) => (
            <div key={event.seq}>{`${String(event.seq).padStart(3, " ")}  ${event.kind}  ${summary(event.payload)}`}</div>
          ))}
        </div>
      )}
    </main>
  );
}
