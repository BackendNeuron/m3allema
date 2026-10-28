import { useEffect, useRef } from "react";

import { gsap } from "../useGsap";
import type { Step } from "../state";

interface InspectorProps {
  turns: number;
  tokens: number;
  cost: number;
  steps: Step[];
  receipt: string | null;
}

/** Animates a number from its previous value to `value`. */
function CountUp({ value, format }: { value: number; format: (v: number) => string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const previous = useRef(0);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const tween = { v: previous.current };
    previous.current = value;
    const animation = gsap.to(tween, {
      v: value,
      duration: 0.6,
      ease: "power2.out",
      onUpdate: () => {
        node.textContent = format(tween.v);
      },
    });
    return () => {
      animation.kill();
    };
  }, [value, format]);
  return (
    <span className="mono" ref={ref}>
      {format(value)}
    </span>
  );
}

const integer = (v: number) => Math.round(v).toLocaleString();
const dollars = (v: number) => `$${v.toFixed(4)}`;

export function Inspector({ turns, tokens, cost, steps, receipt }: InspectorProps) {
  return (
    <aside className="inspector" aria-label="Run inspector">
      <div className="stats">
        <div>
          <span className="label">Turns</span>
          <CountUp value={turns} format={integer} />
        </div>
        <div>
          <span className="label">Tokens</span>
          <CountUp value={tokens} format={integer} />
        </div>
        <div>
          <span className="label">Cost</span>
          <span className="gold">
            <CountUp value={cost} format={dollars} />
          </span>
        </div>
      </div>
      <section>
        <h3>Steps</h3>
        <ol className="steps">
          {steps.map((step) => (
            <li key={step.callId} className={`step ${step.state}`}>
              <span className="step-name">{step.name}</span>
              <span className="step-meta">{step.meta}</span>
            </li>
          ))}
        </ol>
      </section>
      <section>
        <h3>Receipt</h3>
        <div className="receipt-box small">
          {receipt ? receipt.replaceAll("**", "") : <span className="muted">Appears when a run finishes.</span>}
        </div>
      </section>
    </aside>
  );
}
