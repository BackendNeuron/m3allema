import { type FormEvent, type KeyboardEvent, useCallback, useEffect, useState } from "react";

import { getJson, token } from "./api";
import { Inspector } from "./components/Inspector";
import { Intro } from "./components/Intro";
import { Onboarding } from "./components/Onboarding";
import { RunsView } from "./components/RunsView";
import { Thread } from "./components/Thread";
import type { Onboarding as OnboardingData, Status } from "./types";
import { useLiveSession } from "./useLiveSession";

type View = "thread" | "runs" | "setup";

const VIEW_NAMES: Record<View, string> = { thread: "Thread", runs: "Runs", setup: "Setup" };

export function App() {
  const [view, setView] = useState<View>("thread");
  const [status, setStatus] = useState<Status | null>(null);
  const [draft, setDraft] = useState("");

  const refreshStatus = useCallback(() => {
    getJson<Status>("/api/status").then(setStatus, () => setStatus(null));
  }, []);
  useEffect(refreshStatus, [refreshStatus]);

  const [onboarding, setOnboarding] = useState<OnboardingData | null>(null);
  useEffect(() => {
    getJson<OnboardingData>("/api/onboarding").then((data) => {
      setOnboarding(data);
      if (data.needed) setView("setup");
    }, () => setOnboarding(null));
  }, []);

  const live = useLiveSession(refreshStatus);
  const { state } = live;

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    const text = draft.trim();
    if (!text || state.busy) return;
    if (live.sendTask(text)) setDraft("");
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  const perDay = status?.budget.per_day_usd;
  const spendWidth = perDay ? `${Math.min(100, ((status?.spent_today_usd ?? 0) / perDay) * 100)}%` : "0";
  const statusLabel =
    live.connection === "closed" ? "Disconnected" : live.connection === "connecting" ? "Connecting" : state.busy ? "Working" : "Ready";
  const statusClass = live.connection !== "open" ? "" : state.busy ? "busy" : "ok";

  const banners = [
    !token && "Open the dashboard with the link printed by 'm3allema serve' (it contains your access token).",
    status && !status.ready && `Setup needed: ${status.problem}`,
    live.fatal,
    live.pendingTools.length > 0 &&
      `${live.pendingTools.length} external tool(s) are hidden until you approve them: run 'm3allema mcp trust ${live.pendingTools[0].server}'.`,
  ].filter(Boolean) as string[];

  return (
    <>
      <Intro />
      <div className="shell">
        <nav className="rail" aria-label="Primary">
          <div className="brand">
            <div className="mark" aria-hidden="true">
              <span>3</span>
            </div>
            <div className="brand-text">
              <strong>M3allema</strong>
              <span>{status?.workspace ?? "Workspace"}</span>
            </div>
          </div>
          <div className="nav-group">
            <span className="nav-label">Workspace</span>
            {(["thread", "runs", "setup"] as const).map((name) => (
              <button
                key={name}
                type="button"
                className={`nav ${view === name ? "active" : ""}`}
                onClick={() => setView(name)}
              >
                {VIEW_NAMES[name]}
                {name === "setup" && onboarding?.needed && <span className="nav-dot" aria-label="needed" />}
              </button>
            ))}
          </div>
          <div className="nav-group">
            <span className="nav-label">Conversation</span>
            <button type="button" className="nav" onClick={live.startNew} disabled={state.busy}>
              New conversation
            </button>
            <button type="button" className="nav" onClick={live.compact} disabled={state.busy}>
              Compact
            </button>
          </div>
          <div className="budget" aria-label="Spend today">
            <div className="budget-row">
              <span>Today</span>
              <span className="mono">${(status?.spent_today_usd ?? 0).toFixed(2)}</span>
            </div>
            <div className="bar">
              <div className="bar-fill" style={{ width: spendWidth }} />
            </div>
            <div className="budget-row muted">
              <span>{status?.google_connected ? "Google: connected" : "Google: not connected"}</span>
            </div>
          </div>
        </nav>

        <div className="workspace">
          <header className="topbar">
            <div className="crumbs">
              <span className="muted">M3allema</span>
              <span className="sep">/</span>
              <span>{VIEW_NAMES[view]}</span>
              <span className={`status ${statusClass}`}>
                <span className="dot" />
                {statusLabel}
              </span>
            </div>
            <div className="chips">
              <span className="chip mono">{status?.model ?? "model"}</span>
              {status && (
                <span className="chip">{`Policy · write ${status.policy.write} · external ${status.policy.external}`}</span>
              )}
            </div>
          </header>

          <div className="panes">
            {view === "setup" && onboarding ? (
              // A fresh page load opens a new session, so the agent picks up the new files.
              <Onboarding questions={onboarding.questions} onDone={() => window.location.reload()} />
            ) : view === "runs" ? (
              <RunsView />
            ) : (
              <main className="thread">
                {banners.map((text) => (
                  <div className="banner" key={text}>
                    {text}
                  </div>
                ))}
                <Thread items={state.items} onDecide={live.decide} />
                <form className="composer" onSubmit={submit}>
                  <label htmlFor="input" className="sr-only">
                    Message M3allema
                  </label>
                  <textarea
                    id="input"
                    rows={2}
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    onKeyDown={onKeyDown}
                    placeholder="Ask in Arabic, Franco or English…"
                  />
                  <div className="composer-bar">
                    <span className="muted small">Enter to send · Shift+Enter for a new line</span>
                    <button type="submit" className="primary" disabled={state.busy || live.connection !== "open"}>
                      Send
                    </button>
                  </div>
                </form>
              </main>
            )}
            <Inspector
              turns={state.turns}
              tokens={state.tokens}
              cost={state.cost}
              steps={state.steps}
              receipt={state.receipt}
            />
          </div>
        </div>
      </div>
      {live.notice && (
        <div className="toast" role="status" onClick={live.dismissNotice}>
          {live.notice}
        </div>
      )}
    </>
  );
}
