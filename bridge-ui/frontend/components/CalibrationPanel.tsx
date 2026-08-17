"use client";

import { useEffect, useState } from "react";
import StateBadge from "@/components/StateBadge";

interface Bin {
  lo: number;
  hi: number;
  mean_confidence: number;
  accuracy: number;
  accuracy_ci_low: number;
  accuracy_ci_high: number;
  count: number;
}
interface Miss {
  query: string;
  expected: string;
  predicted: string;
  confidence: number;
}
interface CalibData {
  title: string;
  source: string;
  method: string;
  honesty: string;
  n_bins: number;
  n: number;
  accuracy: number;
  ece: number;
  brier: number;
  sharpness: number;
  auroc: number;
  bins: Bin[];
  misses: Miss[];
}

// SVG plot geometry (confidence x-axis, accuracy y-axis).
const PAD_L = 36;
const PAD_T = 12;
const SIZE = 200;
const x = (c: number) => PAD_L + c * SIZE;
const y = (a: number) => PAD_T + (1 - a) * SIZE;

function binColor(b: Bin): string {
  const diff = b.accuracy - b.mean_confidence; // >0 underconfident, <0 overconfident
  if (Math.abs(diff) < 0.05) return "var(--bc-pass-line)"; // calibrado
  return diff < 0 ? "var(--bc-reask-line)" : "var(--bc-info-line)"; // super (laranja) vs sub (azul) confiante
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div
      style={{
        background: "var(--bc-bg)",
        border: "1px solid var(--bc-surface)",
        borderRadius: 6,
        padding: "6px 10px",
        minWidth: 78,
      }}
      title={hint}
    >
      <div style={{ fontSize: 16, fontWeight: 700, color: "var(--bc-text)" }}>{value}</div>
      <div style={{ fontSize: 10, color: "var(--bc-text-dim)", textTransform: "uppercase", letterSpacing: 0.4 }}>
        {label}
      </div>
    </div>
  );
}

export default function CalibrationPanel() {
  const [data, setData] = useState<CalibData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showMisses, setShowMisses] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | undefined;
    const attempt = () => {
      fetch("/api/calibration", { cache: "no-store" })
        .then(async (r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          const json = await r.json();
          if (cancelled) return;
          setData(json);
          setError(null);
          if (timer) clearInterval(timer); // healed — stop polling
        })
        .catch((err: unknown) => {
          if (!cancelled) setError(err instanceof Error ? err.message : String(err));
        });
    };
    attempt();
    timer = setInterval(() => { if (!document.hidden) attempt(); }, 15000);
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, []);

  if (error) {
    return (
      <div className="card card--wide">
        <h2>Calibration</h2>
        <div className="empty error" role="alert">backend unreachable ({error})</div>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="card card--wide">
        <h2>Calibration</h2>
        <div className="empty">loading…</div>
      </div>
    );
  }

  const pts = [...data.bins].sort((a, b) => a.mean_confidence - b.mean_confidence);
  const polyline = pts.map((b) => `${x(b.mean_confidence)},${y(b.accuracy)}`).join(" ");

  return (
    <div className="card card--wide">
      <h2>
        Calibration
        <StateBadge feature="calibration" />
        <span className="card-subtitle" title={data.method}>
          Classifier reliability diagram (real metrics via lub · SR 11-7)
        </span>
      </h2>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 16, alignItems: "flex-start" }}>
        {/* Reliability diagram */}
        <svg
          width={x(1) + 12}
          height={y(0) + 26}
          viewBox={`0 0 ${x(1) + 12} ${y(0) + 26}`}
          role="img"
          aria-label="Reliability diagram: predicted confidence vs observed accuracy"
          style={{ background: "var(--bc-bg)", border: "1px solid var(--bc-surface)", borderRadius: 6 }}
        >
          {/* plot frame */}
          <rect x={PAD_L} y={PAD_T} width={SIZE} height={SIZE} fill="none" stroke="var(--bc-surface)" />
          {/* gridlines + ticks at 0, .5, 1 */}
          {[0, 0.5, 1].map((t) => (
            <g key={t}>
              <line x1={x(t)} y1={PAD_T} x2={x(t)} y2={PAD_T + SIZE} stroke="var(--bc-border)" />
              <line x1={PAD_L} y1={y(t)} x2={PAD_L + SIZE} y2={y(t)} stroke="var(--bc-border)" />
              <text x={x(t)} y={y(0) + 14} fontSize="9" fill="var(--bc-text-mute)" textAnchor="middle">
                {t}
              </text>
              <text x={PAD_L - 5} y={y(t) + 3} fontSize="9" fill="var(--bc-text-mute)" textAnchor="end">
                {t}
              </text>
            </g>
          ))}
          {/* perfect-calibration diagonal */}
          <line
            x1={x(0)}
            y1={y(0)}
            x2={x(1)}
            y2={y(1)}
            stroke="var(--bc-text-mute)"
            strokeDasharray="4 3"
          />
          {/* calibration curve */}
          {pts.length > 1 && (
            <polyline points={polyline} fill="none" stroke="var(--bc-text-dim)" strokeWidth={1.5} />
          )}
          {/* per-bin: 95% CI error bar + point + sample count */}
          {pts.map((b, i) => {
            const cx = x(b.mean_confidence);
            const cap = 3;
            return (
              <g key={i}>
                <line x1={cx} y1={y(b.accuracy_ci_low)} x2={cx} y2={y(b.accuracy_ci_high)} stroke={binColor(b)} strokeWidth={1} opacity={0.55} />
                <line x1={cx - cap} y1={y(b.accuracy_ci_high)} x2={cx + cap} y2={y(b.accuracy_ci_high)} stroke={binColor(b)} strokeWidth={1} opacity={0.55} />
                <line x1={cx - cap} y1={y(b.accuracy_ci_low)} x2={cx + cap} y2={y(b.accuracy_ci_low)} stroke={binColor(b)} strokeWidth={1} opacity={0.55} />
                <circle cx={cx} cy={y(b.accuracy)} r={3 + Math.sqrt(b.count) * 1.6} fill={binColor(b)} fillOpacity={0.85} stroke="var(--bc-bg)">
                  <title>{`conf ${(b.mean_confidence * 100).toFixed(0)}% · accuracy ${(b.accuracy * 100).toFixed(0)}% (CI95 ${(b.accuracy_ci_low * 100).toFixed(0)}–${(b.accuracy_ci_high * 100).toFixed(0)}%) · n=${b.count}`}</title>
                </circle>
                <text x={cx} y={y(b.accuracy_ci_high) - 4} fontSize="8" fill="var(--bc-text-dim)" textAnchor="middle">
                  n={b.count}
                </text>
              </g>
            );
          })}
          {/* axis labels */}
          <text x={PAD_L + SIZE / 2} y={y(0) + 24} fontSize="10" fill="var(--bc-text-dim)" textAnchor="middle">
            predicted confidence
          </text>
          <text
            x={12}
            y={PAD_T + SIZE / 2}
            fontSize="10"
            fill="var(--bc-text-dim)"
            textAnchor="middle"
            transform={`rotate(-90 12 ${PAD_T + SIZE / 2})`}
          >
            observed accuracy
          </text>
        </svg>

        {/* Metrics + reading */}
        <div style={{ flex: "1 1 240px", minWidth: 240 }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            <Metric label="ECE" value={data.ece.toFixed(3)} hint="Expected Calibration Error (Guo 2017) — lower is better" />
            <Metric label="Brier" value={data.brier.toFixed(3)} hint="Mean squared error confidence×correctness — lower is better" />
            <Metric label="AUROC" value={data.auroc.toFixed(2)} hint="Does confidence separate correct from incorrect? 0.5 = random, 1.0 = perfect" />
            <Metric label="Accuracy" value={`${(data.accuracy * 100).toFixed(0)}%`} hint={`${data.n} labeled queries`} />
            <Metric label="Sharpness" value={data.sharpness.toFixed(3)} hint="Confidence standard deviation (decisive vs hedging)" />
          </div>
          <div style={{ fontSize: 12, color: "var(--bc-text)", marginTop: 10, lineHeight: 1.5 }}>
            Points <span style={{ color: "var(--bc-info-line)" }}>blue</span> = underconfident (accuracy above
            confidence), <span style={{ color: "var(--bc-reask-line)" }}>orange</span> = overconfident,{" "}
            <span style={{ color: "var(--bc-pass-line)" }}>green</span> = calibrated. The dashed line is
            perfect calibration; point size ∝ number of samples in the bin. Vertical bars
            are the 95% CI (Wilson) of bin accuracy — wide because of few samples per bin
            (n shown at each point).
          </div>
          <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 8 }}>{data.honesty}</div>

          {data.misses.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <button
                type="button"
                className="link-btn"
                onClick={() => setShowMisses((v) => !v)}
              >
                {showMisses ? "▾" : "▸"} {data.misses.length} classifier misses
              </button>
              {showMisses && (
                <div style={{ marginTop: 6 }}>
                  {data.misses.map((m, i) => (
                    <div
                      key={i}
                      style={{
                        fontSize: 11,
                        color: "var(--bc-text)",
                        padding: "3px 0",
                        borderTop: "1px solid var(--bc-border)",
                      }}
                    >
                      <code style={{ fontSize: 10 }}>“{m.query}”</code>
                      <div className="muted">
                        expected <strong style={{ color: "var(--bc-pass-line)" }}>{m.expected}</strong> · predicted{" "}
                        <strong style={{ color: "var(--bc-reask-line)" }}>{m.predicted}</strong> ({(m.confidence * 100).toFixed(0)}%)
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
