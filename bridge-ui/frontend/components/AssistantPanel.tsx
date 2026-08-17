"use client";

import { useState, useRef } from "react";
import StateBadge from "@/components/StateBadge";

interface Answer {
  answer: string;
  model: string;
  engine: string;
  live: boolean;
}

const SUGGESTIONS = [
  "What does the Governance tab do?",
  "Why does a query get flagged?",
  "What is the effective challenge under SR 11-7?",
];

export default function AssistantPanel() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const cancelledRef = useRef(false);

  const TIMEOUT_MS = 90_000;

  async function ask(q: string) {
    const text = q.trim();
    if (!text) return;
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    cancelledRef.current = false;
    const to = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
    setBusy(true);
    setAnswer(null);
    setError(null);
    setElapsed(0);
    timerRef.current = setInterval(() => setElapsed((s) => s + 1), 1000);
    try {
      const r = await fetch("/api/assistant/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text }),
        cache: "no-store",
        signal: ctrl.signal,
      });
      if (!r.ok) throw new Error(`assistant call failed (HTTP ${r.status})`);
      setAnswer(await r.json());
      setError(null);
    } catch (e) {
      if (cancelledRef.current) {
        setError(null); // user cancelled — not an error
      } else if (ctrl.signal.aborted) {
        setError(`The assistant (Ollama) didn't respond within ${TIMEOUT_MS / 1000}s — it may be loading a model. Try again.`);
      } else {
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      clearTimeout(to);
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
      abortRef.current = null;
      setBusy(false);
    }
  }

  function cancel() {
    cancelledRef.current = true;
    abortRef.current?.abort();
  }

  return (
    <div className="card card--wide">
      <h2>
        Ask AI
        <StateBadge feature="assistant" />
        <span className="card-subtitle">Dashboard copilot — real LLM (Ollama), opt-in</span>
      </h2>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask(question)}
          placeholder="Ask about the panels and decisions..."
          style={{
            flex: 1,
            minWidth: 220,
            background: "var(--bc-bg)",
            border: "1px solid var(--bc-border)",
            borderRadius: 6,
            padding: "7px 10px",
            color: "var(--bc-text)",
            fontSize: 13,
          }}
        />
        <button
          type="button"
          onClick={() => ask(question)}
          disabled={busy || !question.trim()}
          style={{
            background: "var(--bc-surface)",
            border: "1px solid var(--bc-border)",
            borderRadius: 6,
            padding: "7px 16px",
            color: "var(--bc-text)",
            cursor: busy || !question.trim() ? "default" : "pointer",
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          {busy ? "thinking…" : "ask"}
        </button>
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => {
              setQuestion(s);
              ask(s);
            }}
            style={{
              background: "transparent",
              border: "1px solid var(--bc-surface)",
              borderRadius: 12,
              padding: "2px 10px",
              color: "var(--bc-text-dim)",
              cursor: "pointer",
              fontSize: 11,
            }}
          >
            {s}
          </button>
        ))}
      </div>

      {busy && (
        <div className="muted" style={{ fontSize: 12, display: "flex", gap: 10, alignItems: "center" }}>
          querying the real LLM (Ollama) — {elapsed}s…
          <button type="button" className="link-btn" onClick={cancel}>Cancel</button>
        </div>
      )}
      {error && <div className="empty error" role="alert">{error}</div>}

      {answer && !busy && (
        <div
          style={{
            background: "var(--bc-bg)",
            border: "1px solid var(--bc-surface)",
            borderRadius: 6,
            padding: "10px 12px",
            fontSize: 13,
            color: "var(--bc-text)",
            lineHeight: 1.5,
          }}
        >
          {answer.answer}
          <div style={{ fontSize: 10, color: "var(--bc-text-mute)", marginTop: 8 }}>
            {answer.live ? `via ${answer.engine}:${answer.model} (real LLM)` : "Ollama unavailable — honest degradation, no fabricated answer"}
          </div>
        </div>
      )}
    </div>
  );
}
