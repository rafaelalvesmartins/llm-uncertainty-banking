"use client";

import { useState } from "react";
import StateBadge from "@/components/StateBadge";
import { decisionLabel, humanizeIntent } from "@/components/console/types";

interface Comparison {
  threshold: number;
  decision: string;
  released: boolean;
  reason: string;
}
interface Result {
  query: string;
  intent: string;
  confidence: number;
  comparisons: Comparison[];
  n_distinct_decisions: number;
  note: string;
}

const DECISION_COLOR: Record<string, string> = {
  PASSTHROUGH: "var(--bc-pass-line)",
  FLAG: "var(--bc-flag-line)",
  REASK: "var(--bc-reask-line)",
  ESCALATE: "var(--bc-block-line)",
};

const EXAMPLES = [
  "I want to see my account balance",
  "my card was cloned",
  "I can't take it anymore",
];

export default function PlaygroundPanel() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function compare(q: string) {
    const text = q.trim();
    if (!text) return;
    setBusy(true);
    try {
      const r = await fetch("/api/playground/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: text }),
        cache: "no-store",
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setResult(await r.json());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card card--wide">
      <h2>
        Playground
        <StateBadge feature="playground" />
        <span className="card-subtitle">Compare the guard decision across multiple thresholds — side by side</span>
      </h2>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && compare(query)}
          placeholder="Type a query and see the threshold effect..."
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
          onClick={() => compare(query)}
          disabled={busy || !query.trim()}
          style={{
            background: "var(--bc-surface)",
            border: "1px solid var(--bc-border)",
            borderRadius: 6,
            padding: "7px 16px",
            color: "var(--bc-text)",
            cursor: busy || !query.trim() ? "default" : "pointer",
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          {busy ? "…" : "compare"}
        </button>
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            type="button"
            onClick={() => {
              setQuery(ex);
              compare(ex);
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
            {ex}
          </button>
        ))}
      </div>

      {error && <div className="empty error" role="alert">backend unreachable ({error})</div>}

      {result && (
        <>
          <div style={{ fontSize: 12, color: "#cbd5e1", marginBottom: 8 }}>
            intent <strong title={result.intent}>{humanizeIntent(result.intent)}</strong> · confidence {(result.confidence * 100).toFixed(0)}% ·{" "}
            {result.n_distinct_decisions} distinct decision(s) in sweep
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 8 }}>
            {result.comparisons.map((c) => (
              <div
                key={c.threshold}
                style={{
                  background: "var(--bc-bg)",
                  border: `1px solid ${DECISION_COLOR[c.decision] || "var(--bc-surface)"}`,
                  borderRadius: 6,
                  padding: "8px 10px",
                  textAlign: "center",
                }}
              >
                <div style={{ fontSize: 10, color: "var(--bc-text-dim)", textTransform: "uppercase", letterSpacing: 0.4 }}>
                  threshold {c.threshold.toFixed(2)}
                </div>
                <div style={{ fontSize: 14, fontWeight: 700, color: DECISION_COLOR[c.decision] || "var(--bc-text)", marginTop: 4 }}>
                  {decisionLabel(c.decision)}
                </div>
                <div style={{ fontSize: 10, color: c.released ? "var(--bc-pass-line)" : "var(--bc-text-dim)", marginTop: 2 }}>
                  {c.released ? "response released" : "response withheld"}
                </div>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 8 }}>{result.note}</div>
        </>
      )}
    </div>
  );
}
