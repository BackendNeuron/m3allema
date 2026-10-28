import { type FormEvent, useMemo, useState } from "react";

import { postJson } from "../api";
import type { Answer, OnboardingResult, Question } from "../types";
import { useGSAP } from "../useGsap";

interface Props {
  questions: Question[];
  onDone: (result: OnboardingResult) => void;
}

const asLines = (value: Answer): string => (Array.isArray(value) ? value.join("\n") : String(value ?? ""));

/** Turn the form's text values into the shapes the server validates. */
function toPayload(questions: Question[], values: Record<string, Answer>): Record<string, Answer> {
  const payload: Record<string, Answer> = {};
  for (const q of questions) {
    const value = values[q.id];
    if (q.kind === "list") payload[q.id] = asLines(value).split("\n").map((s) => s.trim()).filter(Boolean);
    else if (q.kind === "money") payload[q.id] = Number(value);
    else payload[q.id] = value;
  }
  return payload;
}

/** The onboarding interview: one section per step, written into the workspace files at the end. */
export function Onboarding({ questions, onDone }: Props) {
  const sections = useMemo(() => [...new Set(questions.map((q) => q.section))], [questions]);
  const [step, setStep] = useState(0);
  const [values, setValues] = useState<Record<string, Answer>>(() =>
    Object.fromEntries(questions.map((q) => [q.id, q.kind === "list" ? asLines(q.default) : q.default])),
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const current = questions.filter((q) => q.section === sections[step]);
  const last = step === sections.length - 1;

  const scope = useGSAP<HTMLFormElement>(
    (gsap) => {
      gsap.from(".question", { opacity: 0, y: 10, duration: 0.45, stagger: 0.06, ease: "power3.out" });
    },
    [step],
  );

  const set = (id: string, value: Answer) => setValues((prev) => ({ ...prev, [id]: value }));
  const toggle = (id: string, option: string) => {
    const chosen = (values[id] as string[]) ?? [];
    set(id, chosen.includes(option) ? chosen.filter((o) => o !== option) : [...chosen, option]);
  };

  const missing = current.filter((q) => q.required && !asLines(values[q.id]).trim());

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (missing.length > 0) {
      setError(`Please answer: ${missing.map((q) => q.prompt).join(" ")}`);
      return;
    }
    setError(null);
    if (!last) {
      setStep(step + 1);
      return;
    }
    setSaving(true);
    try {
      onDone(await postJson<OnboardingResult>("/api/onboarding", toPayload(questions, values)));
    } catch (e) {
      setError((e as Error).message);
      setSaving(false);
    }
  };

  return (
    <main className="onboarding">
      <header className="onboarding-head">
        <span className="eyebrow">Setup · step {step + 1} of {sections.length}</span>
        <h2>{sections[step]}</h2>
        <div className="progress" aria-hidden="true">
          {sections.map((name, i) => (
            <span key={name} className={i <= step ? "on" : ""} />
          ))}
        </div>
      </header>
      <form ref={scope} onSubmit={submit} className="questions">
        {current.map((q) => (
          <div className="question" key={q.id}>
            <label htmlFor={`q-${q.id}`}>
              {q.prompt}
              {q.required && <span className="gold"> *</span>}
            </label>
            {q.help && <span className="muted small">{q.help}</span>}
            <Field question={q} value={values[q.id]} onChange={(v) => set(q.id, v)} onToggle={(o) => toggle(q.id, o)} />
          </div>
        ))}
        {error && <div className="banner">{error}</div>}
        <div className="onboarding-foot">
          <button type="button" className="ghost" disabled={step === 0 || saving} onClick={() => setStep(step - 1)}>
            Back
          </button>
          <button type="submit" className="primary" disabled={saving}>
            {last ? (saving ? "Saving…" : "Save and start") : "Continue"}
          </button>
        </div>
      </form>
    </main>
  );
}

interface FieldProps {
  question: Question;
  value: Answer;
  onChange: (value: Answer) => void;
  onToggle: (option: string) => void;
}

function Field({ question: q, value, onChange, onToggle }: FieldProps) {
  const id = `q-${q.id}`;
  switch (q.kind) {
    case "choice":
      return (
        <div className="options" role="radiogroup" id={id}>
          {q.options.map((option) => (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={value === option}
              className={`option ${value === option ? "on" : ""}`}
              onClick={() => onChange(option)}
            >
              {option}
            </button>
          ))}
        </div>
      );
    case "multi":
      return (
        <div className="options" id={id}>
          {q.options.map((option) => {
            const on = (value as string[]).includes(option);
            return (
              <button
                key={option}
                type="button"
                aria-pressed={on}
                className={`option ${on ? "on" : ""}`}
                onClick={() => onToggle(option)}
              >
                {option}
              </button>
            );
          })}
        </div>
      );
    case "long_text":
    case "list":
      return <textarea id={id} rows={3} value={asLines(value)} onChange={(e) => onChange(e.target.value)} />;
    case "money":
      return (
        <input
          id={id}
          type="number"
          min="0.01"
          step="0.01"
          value={String(value)}
          onChange={(e) => onChange(e.target.value)}
        />
      );
    default:
      return <input id={id} type="text" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />;
  }
}
