import { useGSAP } from "../useGsap";
import { money } from "../api";
import type { Item, Part } from "../state";
import type { ApprovalRequest } from "../types";

interface ThreadProps {
  items: Item[];
  onDecide: (id: string, allow: boolean) => void;
}

export function Thread({ items, onDecide }: ThreadProps) {
  const scope = useGSAP<HTMLDivElement>(
    (gsap, root) => {
      const last = root.lastElementChild;
      if (last) gsap.from(last, { opacity: 0, y: 8, duration: 0.4, ease: "power2.out" });
      root.scrollIntoView({ block: "end", behavior: "smooth" });
    },
    [items.length],
  );

  return (
    <div className="messages" ref={scope} aria-live="polite">
      {items.map((item) =>
        item.kind === "user" ? (
          <div className="row user" key={item.key}>
            <div className="avatar" aria-hidden="true">
              YOU
            </div>
            <div className="bubble">
              <div className="text">{item.text}</div>
            </div>
          </div>
        ) : (
          <div className="row agent" key={item.key}>
            <div className="avatar agent" aria-hidden="true" />
            <div className="bubble">
              {item.parts.map((part, index) => (
                <PartView key={index} part={part} onDecide={onDecide} />
              ))}
              {item.finish && (
                <div className="finish">
                  <span className={item.finish.status === "completed" ? "ok" : "warn"}>
                    {item.finish.status}
                  </span>
                  {` · ${item.finish.steps} steps · ${item.finish.tokens.toLocaleString()} tokens · ${money(item.finish.cost)}`}
                </div>
              )}
            </div>
          </div>
        ),
      )}
    </div>
  );
}

function PartView({ part, onDecide }: { part: Part; onDecide: ThreadProps["onDecide"] }) {
  switch (part.type) {
    case "text":
      return <div className="text">{part.text}</div>;
    case "note":
      return <div className="text muted">{part.text}</div>;
    case "tool": {
      const failed = part.outcome === "failed" || part.outcome === "not run";
      const suffix = part.outcome && part.outcome !== "done" ? ` · ${part.outcome}` : "";
      return <span className={`tool-chip ${failed ? "error" : ""}`}>{`${part.name}${suffix}`}</span>;
    }
    case "approval":
      return <ApprovalCard request={part.request} decision={part.decision} onDecide={onDecide} />;
  }
}

interface ApprovalCardProps {
  request: ApprovalRequest;
  decision?: boolean;
  onDecide: ThreadProps["onDecide"];
}

function ApprovalCard({ request, decision, onDecide }: ApprovalCardProps) {
  const card = useGSAP<HTMLElement>(
    (gsap, root) => {
      gsap.fromTo(
        root,
        { boxShadow: "0 0 0 0 rgba(194,51,74,0)" },
        { boxShadow: "0 0 0 4px rgba(194,51,74,0.16)", duration: 0.6, yoyo: true, repeat: 1 },
      );
    },
    [],
  );

  return (
    <section className="action" aria-label="Approval needed" ref={card}>
      <div className="action-head">
        <strong>{request.view?.title ?? request.tool}</strong>
        <span className={`risk ${request.risk}`}>{`${request.risk} · needs approval`}</span>
      </div>
      {request.view && (
        <dl className="action-fields">
          {request.view.fields.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
          <div>
            <dt>Tool</dt>
            <dd className="mono">{request.tool}</dd>
          </div>
        </dl>
      )}
      {request.view?.warnings.map((warning) => (
        <div className="action-warning" key={warning}>
          {warning}
        </div>
      ))}
      {request.view && request.view.mentions.length > 0 && (
        <div className="action-mentions">
          <span>Mentions</span>
          {request.view.mentions.map((mention) => (
            <code key={mention}>{mention}</code>
          ))}
        </div>
      )}
      <pre className="args">{request.full_text ?? JSON.stringify(request.arguments, null, 2)}</pre>
      <div className="action-foot">
        {decision === undefined ? (
          <>
            <span className="muted small">Nothing happens until you decide.</span>
            <div className="buttons">
              <button type="button" className="ghost" onClick={() => onDecide(request.id, false)}>
                Decline
              </button>
              <button type="button" className="primary" onClick={() => onDecide(request.id, true)}>
                Approve
              </button>
            </div>
          </>
        ) : decision ? (
          <span className="decided-ok">Approved by you</span>
        ) : (
          <span className="decided-no">Declined. Nothing was done.</span>
        )}
      </div>
    </section>
  );
}
