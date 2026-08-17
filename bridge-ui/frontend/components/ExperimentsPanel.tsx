"use client";

import { useEffect, useState } from "react";
import StateBadge from "@/components/StateBadge";

interface Failure {
  id: string;
  input: string;
  expected: string;
  predicted: string;
}
interface Run {
  dataset: string;
  dataset_version: string;
  generated_at: string;
  n_cases: number;
  n_pass: number;
  accuracy: number;
  by_intent: Record<string, { total: number; pass: number }>;
  failures: Failure[];
  content_sha256: string;
  note: string;
}

const TH: React.CSSProperties = {
  textAlign: "left",
  fontSize: 10,
  textTransform: "uppercase",
  letterSpacing: 0.4,
  color: "var(--bc-text-dim)",
  padding: "4px 8px",
  borderBottom: "1px solid var(--bc-surface)",
  whiteSpace: "nowrap",
};
const TD: React.CSSProperties = { fontSize: 12, color: "var(--bc-text)", padding: "5px 8px", borderBottom: "1px solid var(--bc-border)" };

export default function ExperimentsPanel() {
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // poll until first success, then stop (self-heal under dashboard load)
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | undefined;
    const attempt = () => {
      fetch("/api/experiments/run", { cache: "no-store" })
        .then(async (r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then((j) => {
          if (cancelled) return;
          setRun(j);
          setError(null);
          if (timer) clearInterval(timer);
        })
        .catch((e: unknown) => {
          if (!cancelled) setError(e instanceof Error ? e.message : String(e));
        });
    };
    attempt();
    timer = setInterval(() => { if (!document.hidden) attempt(); }, 15000);
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, []);

  async function rerun() {
    setBusy(true);
    try {
      const r = await fetch("/api/experiments/run?refresh=1", { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setRun(await r.json());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (error && !run) {
    return (
      <div className="card card--wide">
        <h2>Experiments</h2>
        <div className="empty error" role="alert">backend unreachable ({error})</div>
      </div>
    );
  }
  if (!run) {
    return (
      <div className="card card--wide">
        <h2>Experiments</h2>
        <div className="empty">loading…</div>
      </div>
    );
  }

  const acc = run.accuracy * 100;
  const accColor = acc >= 90 ? "var(--bc-pass-line)" : acc >= 80 ? "var(--bc-flag-line)" : "var(--bc-block-line)";

  return (
    <div className="card card--wide">
      <h2>
        Experiments
        <StateBadge feature="experiments" />
        <span className="card-subtitle">Labeled dataset → real classifier (SR 11-7 effective challenge)</span>
      </h2>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", marginBottom: 10 }}>
        <span style={{ fontSize: 20, fontWeight: 700, color: accColor }}>{acc.toFixed(1)}% accuracy</span>
        <span className="muted" style={{ fontSize: 12 }}>
          {run.n_pass}/{run.n_cases} cases · dataset <code style={{ fontSize: 11 }}>{run.dataset}</code> v
          <code style={{ fontSize: 11 }}>{run.dataset_version}</code>
        </span>
        <button
          type="button"
          onClick={rerun}
          disabled={busy}
          style={{
            background: "var(--bc-surface)",
            border: "1px solid var(--bc-border)",
            borderRadius: 6,
            padding: "5px 12px",
            color: "var(--bc-text)",
            cursor: busy ? "default" : "pointer",
            fontSize: 12,
            marginLeft: "auto",
          }}
        >
          {busy ? "…" : "▶ run experiment"}
        </button>
      </div>

      {run.failures.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <div style={{ fontSize: 11, color: "var(--bc-text-dim)", margin: "4px 2px" }}>
            {run.failures.length} case(s) misclassified:
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={TH}>Input</th>
                <th style={TH}>Expected</th>
                <th style={TH}>Predicted</th>
              </tr>
            </thead>
            <tbody>
              {run.failures.map((f) => (
                <tr key={f.id}>
                  <td style={{ ...TD, color: "var(--bc-text)" }}>{f.input}</td>
                  <td style={{ ...TD, color: "var(--bc-pass-line)" }}>{f.expected}</td>
                  <td style={{ ...TD, color: "var(--bc-block-line)" }}>{f.predicted}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 8, marginTop: 10 }}>
        <div style={{ background: "var(--bc-bg)", border: "1px solid var(--bc-surface)", borderRadius: 6, padding: "6px 10px" }}>
          <div style={{ fontSize: 10, color: "var(--bc-text-dim)", textTransform: "uppercase", letterSpacing: 0.4 }}>Generated at</div>
          <div style={{ fontSize: 13, color: "var(--bc-text)", marginTop: 2 }}>{run.generated_at}</div>
        </div>
        <div style={{ background: "var(--bc-bg)", border: "1px solid var(--bc-surface)", borderRadius: 6, padding: "6px 10px" }}>
          <div style={{ fontSize: 10, color: "var(--bc-text-dim)", textTransform: "uppercase", letterSpacing: 0.4 }}>Hash (sha256)</div>
          <div style={{ fontSize: 13, color: "var(--bc-text)", marginTop: 2, wordBreak: "break-all" }}>
            <code style={{ fontSize: 11 }}>{run.content_sha256.slice(0, 32)}…</code>
          </div>
        </div>
      </div>

      <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 8 }}>{run.note}</div>
    </div>
  );
}
