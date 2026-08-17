"use client";

import { useEffect, useState } from "react";
import StateBadge from "@/components/StateBadge";
import { useConfirm } from "@/components/ConfirmProvider";
import { useAppContext } from "@/components/AppContextProvider";
import { apiErrorText } from "@/lib/apiError";
import { decisionLabel, humanizeIntent } from "@/components/console/types";

interface IntentDelta {
  intent: string;
  baseline_pct: number;
  current_pct: number;
  delta_pp: number;
}

interface DecisionDelta {
  decision: string;
  baseline_pct: number;
  current_pct: number;
  delta_pp: number;
}

interface DriftPayload {
  baseline_captured: boolean;
  current_queries: number;
  baseline_at?: number;
  remaining_until_auto_capture?: number;
  note?: string;
  baseline_captured_at?: number;
  baseline_source?: string;
  baseline_queries?: number;
  tv_distance?: number;
  drift_severity?: "low" | "moderate" | "high";
  intent_deltas?: IntentDelta[];
  top_movers?: IntentDelta[];
  decision_deltas?: DecisionDelta[];
}

interface Props {
  refreshKey: number;
}

const SEVERITY_COLOR: Record<string, string> = {
  low: "var(--bc-pass-line)",
  moderate: "var(--bc-flag-line)",
  high: "var(--bc-block-line)",
};

export default function DriftPanel({ refreshKey }: Props) {
  const confirm = useConfirm();
  const { operator } = useAppContext();
  const [data, setData] = useState<DriftPayload | null>(null);
  const [capturing, setCapturing] = useState(false);
  const [captureErr, setCaptureErr] = useState<string | null>(null);
  // Distinguish "still loading" from "tried, backend unreachable".
  const [polled, setPolled] = useState(false);
  const [backendDown, setBackendDown] = useState(false);

  async function tick() {
    try {
      const r = await fetch("/api/drift", { cache: "no-store" });
      if (r.ok) setData(await r.json());
      setPolled(true);
      setBackendDown(!r.ok);
    } catch {
      setPolled(true);
      setBackendDown(true);
    }
  }

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      await tick();
      if (cancelled) return;
    };
    run();
    const id = setInterval(() => { if (!document.hidden) run(); }, 15000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [refreshKey]);

  async function captureBaseline() {
    if (!(await confirm("Capture the current distribution as the new drift baseline? This resets the comparison window."))) return;
    setCapturing(true);
    setCaptureErr(null);
    try {
      const r = await fetch(`/api/drift?operator=${encodeURIComponent(operator)}`, { method: "POST" });
      if (r.ok) {
        await tick();
      } else {
        // A failed rebaseline must be VISIBLE — otherwise the spinner completes and
        // the operator assumes the baseline was captured when nothing changed.
        const j = await r.json().catch(() => null);
        setCaptureErr(apiErrorText(j, r.status));
      }
    } catch (e) {
      setCaptureErr(e instanceof Error ? e.message : String(e));
    } finally {
      setCapturing(false);
    }
  }

  if (!data) {
    return (
      <div className="card">
        <h2>Drift Detection</h2>
        <div className="empty">{!polled ? "loading drift snapshot..." : backendDown ? "Backend unreachable — retrying every 15s." : "No drift snapshot yet."}</div>
      </div>
    );
  }

  if (!data.baseline_captured) {
    return (
      <div className="card">
        <h2>
          Drift Detection
          <button
            type="button"
            className="link-btn"
            onClick={captureBaseline}
            disabled={capturing || data.current_queries === 0 || (data.remaining_until_auto_capture ?? 1) <= 0}
            style={{ marginLeft: 8 }}
          >
            {capturing ? "capturing…" : "capture baseline now"}
          </button>
          {captureErr && <span style={{ color: "var(--bc-block-line)", fontSize: 11, marginLeft: 8 }}>⚠ {captureErr}</span>}
        </h2>
        <div className="empty">
          Baseline is captured automatically at query #{data.baseline_at} (current{" "}
          {data.current_queries}, remaining {data.remaining_until_auto_capture}).
          <div style={{ fontSize: 11, marginTop: 6, color: "var(--bc-text-dim)" }}>
            {data.note}
          </div>
        </div>
      </div>
    );
  }

  const severity = data.drift_severity || "low";
  const tv = data.tv_distance ?? 0;
  return (
    <div className="card">
      <h2>
        Drift Detection
        <StateBadge feature="drift-detection" />
        <span
          className="muted"
          style={{ fontWeight: 400, fontSize: 11, marginLeft: 8, textTransform: "none", letterSpacing: 0 }}
        >
          baseline {data.baseline_source} · {data.baseline_queries} queries
        </span>
        <button
          type="button"
          className="link-btn"
          onClick={captureBaseline}
          disabled={capturing}
          style={{ marginLeft: 8 }}
          title="Capture the current distribution as the new comparison baseline"
        >
          {capturing ? "capturing…" : "rebaseline"}
        </button>
        {captureErr && <span style={{ color: "var(--bc-block-line)", fontSize: 11, marginLeft: 8 }}>⚠ {captureErr}</span>}
      </h2>
      <div
        style={{
          marginBottom: 10,
          padding: "8px 10px",
          background: "var(--bc-bg)",
          border: `1px solid ${SEVERITY_COLOR[severity]}`,
          borderRadius: 4,
          fontSize: 12,
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}
      >
        <span
          style={{
            padding: "2px 8px",
            borderRadius: 3,
            background: SEVERITY_COLOR[severity],
            color: "var(--bc-bg)",
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: 0.5,
            fontSize: 10,
          }}
        >
          {severity}
        </span>
        <span>
          <strong>TV Distance:</strong> {tv.toFixed(3)}
          <span className="muted" style={{ fontSize: 11, marginLeft: 6, fontWeight: 400 }}>
            (how different today&apos;s question mix is from your normal pattern — 0 = identical, 1 = completely different)
          </span>
        </span>
        <span className="muted" style={{ fontSize: 11 }}>
          {tv > 0.20
            ? "Significant shift — investigate the source channel"
            : tv > 0.10
            ? "Moderate shift — monitor"
            : "Stable distribution"}
        </span>
      </div>

      {severity === "high" && (
        <div
          style={{
            marginBottom: 12,
            padding: "8px 10px",
            background: "var(--bc-bg)",
            border: `1px solid ${SEVERITY_COLOR.high}`,
            borderRadius: 4,
            fontSize: 12,
            lineHeight: 1.5,
          }}
        >
          <strong>What to do:</strong> review the new questions below. If this shift is
          expected (for example a new product or seasonal change), set today&apos;s pattern
          as the new &ldquo;normal&rdquo; by clicking <strong>rebaseline</strong> above.
        </div>
      )}

      {data.top_movers && data.top_movers.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div
            className="muted"
            style={{ fontSize: 10, marginBottom: 4, textTransform: "uppercase", letterSpacing: 0.5 }}
          >
            top movers
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            {data.top_movers.map((m) => (
              <div
                key={m.intent}
                style={{
                  fontSize: 12,
                  padding: "4px 8px",
                  background: "var(--bc-bg)",
                  borderRadius: 3,
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                }}
              >
                <span>
                  <strong title={m.intent}>{humanizeIntent(m.intent)}</strong>{" "}
                  <span className="muted">
                    {m.baseline_pct.toFixed(1)}% → {m.current_pct.toFixed(1)}%
                  </span>
                </span>
                <span
                  style={{
                    color: m.delta_pp > 0 ? "var(--bc-flag-line)" : "var(--bc-info-line)",
                    fontFamily: "monospace",
                  }}
                >
                  {m.delta_pp > 0 ? "+" : ""}
                  {m.delta_pp.toFixed(1)}pp
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {data.decision_deltas && data.decision_deltas.length > 0 && (
        <div>
          <div
            className="muted"
            style={{ fontSize: 10, marginBottom: 4, textTransform: "uppercase", letterSpacing: 0.5 }}
          >
            decision mix shift
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {data.decision_deltas.map((d) => (
              <div
                key={d.decision}
                style={{
                  fontSize: 11,
                  padding: "3px 8px",
                  background: "var(--bc-bg)",
                  borderRadius: 3,
                }}
              >
                <span className="muted">{decisionLabel(d.decision)}</span>{" "}
                <span style={{ color: d.delta_pp > 0 ? "var(--bc-flag-line)" : d.delta_pp < 0 ? "var(--bc-info-line)" : "var(--bc-text-dim)" }}>
                  {d.delta_pp > 0 ? "+" : ""}
                  {d.delta_pp.toFixed(1)}pp
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
