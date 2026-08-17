"use client";

import { useEffect, useState, type ReactNode } from "react";
import { getJSON } from "@/components/console/api";
import { decisionTone, decisionLabel, humanizeIntent } from "@/components/console/types";
import AskInFlowLink from "@/components/console/AskInFlowLink";
import type { Integrations, Provider } from "@/components/console/types";
import StateBadge from "@/components/StateBadge";
import Disclosure from "@/components/console/Disclosure";
import DecisionLegend from "@/components/console/DecisionLegend";

// ── Local interfaces (tight) ─────────────────────────────────────────────────

interface MetricsPayload {
  queries_total: number;
  decisions: { PASSTHROUGH: number; FLAG: number; REASK: number; ESCALATE: number };
  resolution_rate: number; // 0..1
  escalation_rate: number; // 0..1
  avg_confidence?: number; // 0..1
  queries_by_intent?: Record<string, number>;
  avg_latency_ms?: number;
  p50_latency_ms?: number;
  p95_latency_ms?: number;
  p99_latency_ms?: number;
  target_resolution?: number;
}

interface HealthPayload {
  status?: string;
  backend?: string;
  backend_is_real?: boolean;
  audit_entries_current?: number;
}

interface AuditEntry {
  ts: number;
  intent: string;
  decision: string;
  channel: string;
  seq?: number;
}

interface AuditPayload {
  entries: AuditEntry[];
  total: number;
}

// /api/metrics BFF bundles all three in one response.
interface BundledResponse {
  metrics: MetricsPayload;
  health: HealthPayload;
  audit: AuditPayload;
}

interface StatsPayload {
  uptime_seconds?: number;
}

interface FamiliesPayload {
  families?: Record<string, number>;
}

interface TimeseriesResponse {
  points?: { PASSTHROUGH?: number; FLAG?: number; REASK?: number; ESCALATE?: number }[];
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtUptime(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

function fmtTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function pct(part: number, total: number): string {
  if (total === 0) return "0%";
  return `${Math.round((part / total) * 100)}%`;
}

/** Drill-down: switch the console view via the hash router in page.tsx. */
function go(view: string): void {
  if (typeof window !== "undefined") window.location.hash = view;
}

/** Deep-link to one audit entry: stash its seq for the Audit view to focus, then go. */
function viewInAudit(seq?: number): void {
  if (typeof window !== "undefined" && seq != null) {
    window.sessionStorage.setItem("bridge:auditFocusSeq", String(seq));
    // Clear any leftover filter (e.g. a prior Escalate tile click) so it can't
    // hide the row we're focusing — mirror of goToAuditFilter's symmetry.
    window.sessionStorage.removeItem("bridge:auditFilter");
  }
  go("audit");
}

/** Drill from a decision number (tile or funnel bucket) into the Audit trail, filtered
 *  to that decision. Empty string = all entries. Reuses the global-search filter channel
 *  + 'bridge:goto' so it lands even when already on Audit. */
function goToAuditFilter(filter: { decision?: string; intent?: string }): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem("bridge:auditFocusSeq");
  const clean: { decision?: string; intent?: string } = {};
  if (filter.decision) clean.decision = filter.decision;
  if (filter.intent) clean.intent = filter.intent;
  if (clean.decision || clean.intent) window.sessionStorage.setItem("bridge:auditFilter", JSON.stringify(clean));
  else window.sessionStorage.removeItem("bridge:auditFilter");
  window.location.hash = "audit";
  window.dispatchEvent(new CustomEvent("bridge:goto", { detail: { view: "audit" } }));
}

function goToAuditDecision(decision: string): void {
  goToAuditFilter({ decision });
}

function providerColor(status: string): string {
  if (status === "active") return "var(--bc-pass-line)";
  if (status === "available" || status === "reachable") return "var(--bc-info-line)";
  if (status === "unreachable") return "var(--bc-block-line)";
  return "var(--bc-text-mute)";
}

// ── Inspection-flow strip (illustrative pipeline shape; click → Flow) ─────────

const STAGES: { name: string; icon: ReactNode }[] = [
  { name: "Input", icon: <path d="M3 8h9M9 4l4 4-4 4" /> },
  { name: "Sanitize", icon: <path d="M3 4h10l-4 5v4l-2 1V9z" /> },
  { name: "Intent", icon: <><rect x="3" y="3" width="4.5" height="4.5" rx="1" /><rect x="9" y="3" width="4.5" height="4.5" rx="1" /><rect x="3" y="9" width="4.5" height="4.5" rx="1" /><rect x="9" y="9" width="4.5" height="4.5" rx="1" /></> },
  { name: "Guard", icon: <><circle cx="8" cy="8" r="5.5" /><path d="M8 8l3-2" /></> },
  { name: "Backend", icon: <><rect x="3" y="3" width="10" height="10" rx="1.5" /><path d="M6 6h4M6 9h4" /></> },
  { name: "Audit", icon: <><path d="M6 8a2.5 2.5 0 0 1 0-3.5l1-1a2.5 2.5 0 0 1 3.5 3.5l-.6.6" /><path d="M10 8a2.5 2.5 0 0 1 0 3.5l-1 1a2.5 2.5 0 0 1-3.5-3.5l.6-.6" /></> },
  { name: "Response", icon: <path d="M13 3L7 9M13 3l-4 10-2-4-4-2z" /> },
];

function FlowStrip() {
  return (
    <div
      className="bc-card"
      role="button"
      tabIndex={0}
      onClick={() => go("flow")}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go("flow"); } }}
      style={{ cursor: "pointer" }}
      title="Open the inspection flow"
    >
      <div className="bc-card-h">
        <h2 style={{ fontSize: 15 }}>Query inspection flow</h2>
        <span className="bc-chip" style={{ borderColor: "var(--bc-flag-line)", color: "var(--bc-flag-text)" }}>
          <span className="bc-dot flag" />
          click to inspect
        </span>
      </div>
      <div className="bc-flow">
        {STAGES.map((s, i) => {
          const active = s.name === "Guard";
          return (
            <div key={s.name} style={{ display: "contents" }}>
              <div className={`bc-stage${active ? " warn active" : ""}`}>
                <svg
                  width="16" height="16" viewBox="0 0 16 16" fill="none"
                  stroke={active ? "var(--bc-flag-line)" : "var(--bc-text-mute)"}
                  strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"
                  aria-hidden
                >
                  {s.icon}
                </svg>
                <div className="bc-stage-name">{s.name}</div>
              </div>
              {i < STAGES.length - 1 && <span className="bc-arrow" aria-hidden>›</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Connections mini-topology (click → Connections) ──────────────────────────

function MiniTopology({ data }: { data: Integrations | null }) {
  const providers: Provider[] = (data?.providers ?? []).slice(0, 4);
  const n = Math.max(1, providers.length);
  const rowH = 30;
  const h = Math.max(96, n * rowH + 24);
  const hubCY = h / 2;

  return (
    <div
      className="bc-card"
      role="button"
      tabIndex={0}
      onClick={() => go("connections")}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go("connections"); } }}
      style={{ cursor: "pointer" }}
      title="Open Connections"
    >
      <div className="bc-card-h">
        <h2 style={{ fontSize: 15 }}>Connections</h2>
        <span
          title="Manage connections"
          style={{
            fontSize: 11,
            color: "var(--bc-accent)",
            border: "1px solid var(--bc-accent)",
            borderRadius: 999,
            padding: "2px 8px",
            lineHeight: 1.4,
            whiteSpace: "nowrap",
          }}
        >
          ＋ New
        </span>
      </div>
      {!data ? (
        <div className="bc-loading">loading providers…</div>
      ) : (
        <svg viewBox={`0 0 260 ${h}`} className="bc-topo" aria-label="Backend topology">
          <rect x="14" y={hubCY - 16} width="64" height="32" rx="6" fill="var(--bc-accent-bg)" stroke="var(--bc-accent)" />
          <text x="46" y={hubCY + 4} textAnchor="middle" fontSize="11" fontWeight="600" style={{ fill: "var(--bc-accent)" }}>Bridge</text>
          {providers.map((p, i) => {
            const cy = 12 + (i + 0.5) * ((h - 24) / n);
            const color = providerColor(p.status);
            const isActive = p.id === data.active_backend;
            return (
              <g key={p.id}>
                <line x1="78" y1={hubCY} x2="150" y2={cy} stroke={color} strokeWidth={isActive ? 2 : 1.2} strokeDasharray={p.status === "not_configured" ? "4 3" : undefined} />
                <circle cx="156" cy={cy} r="4" fill={color} />
                <text x="166" y={cy + 4} fontSize="11" style={{ fill: "var(--bc-text-dim)" }}>{p.name}</text>
              </g>
            );
          })}
        </svg>
      )}
      {data && (
        <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 4, fontSize: 11 }}>
          <span style={{ color: "var(--bc-text-dim)" }}>
            active backend: {data.active_backend === "fake" ? "Demo (fixed answers)" : data.active_backend}
          </span>
          <span style={{ color: "var(--bc-text-mute)" }}>·</span>
          <span style={{ color: "var(--bc-text-mute)" }}>
            {data.n_available}/{data.n_providers} available
          </span>
        </div>
      )}
    </div>
  );
}

// ── Lightweight SVG charts (no chart lib — matches the inline-SVG topology) ────

interface Slice { label: string; value: number; color: string; audit?: { decision?: string; intent?: string } }

const INTENT_PALETTE = [
  "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899", "#84cc16",
];

function decisionSlices(m: MetricsPayload): Slice[] {
  return [
    { label: "Pass", value: m.decisions?.PASSTHROUGH ?? 0, color: "var(--bc-pass-line)", audit: { decision: "PASSTHROUGH" } },
    { label: "Flag", value: m.decisions?.FLAG ?? 0, color: "var(--bc-flag-line)", audit: { decision: "FLAG" } },
    { label: "Re-ask", value: m.decisions?.REASK ?? 0, color: "var(--bc-reask-line)", audit: { decision: "REASK" } },
    { label: "Escalate", value: m.decisions?.ESCALATE ?? 0, color: "var(--bc-block-line)", audit: { decision: "ESCALATE" } },
  ];
}

/** Donut (pie) chart — proportions of `slices`, total in the centre. */
function Donut({ slices, size = 132, thickness = 22, center, onSlice }: { slices: Slice[]; size?: number; thickness?: number; center?: string; onSlice?: (s: Slice) => void }) {
  const total = slices.reduce((s, x) => s + x.value, 0);
  const r = (size - thickness) / 2;
  const c = size / 2;
  const circ = 2 * Math.PI * r;
  let off = 0;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label="donut chart" style={{ flexShrink: 0 }}>
      <circle cx={c} cy={c} r={r} fill="none" stroke="var(--bc-surface-2)" strokeWidth={thickness} />
      {total > 0 && slices.filter((s) => s.value > 0).map((s) => {
        const dash = (s.value / total) * circ;
        const clickable = !!onSlice && !!s.audit;
        const node = (
          <circle
            key={s.label} cx={c} cy={c} r={r} fill="none" stroke={s.color}
            strokeWidth={thickness} strokeDasharray={`${dash} ${circ - dash}`}
            strokeDashoffset={-off} transform={`rotate(-90 ${c} ${c})`}
            onClick={clickable ? () => onSlice!(s) : undefined}
            style={clickable ? { cursor: "pointer" } : undefined}
          >
            <title>{`${s.label}: ${s.value} (${Math.round((s.value / total) * 100)}%)${clickable ? " — click to open in audit" : ""}`}</title>
          </circle>
        );
        off += dash;
        return node;
      })}
      <text x={c} y={c - 1} textAnchor="middle" fontSize="22" fontWeight="700" style={{ fill: "var(--bc-text)" }}>{total}</text>
      {center && <text x={c} y={c + 16} textAnchor="middle" fontSize="10" style={{ fill: "var(--bc-text-mute)" }}>{center}</text>}
    </svg>
  );
}

function Legend({ slices, onSlice }: { slices: Slice[]; onSlice?: (s: Slice) => void }) {
  const total = slices.reduce((s, x) => s + x.value, 0);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0, flex: 1 }}>
      {slices.map((s) => {
        const clickable = !!onSlice && !!s.audit;
        return (
          <div
            key={s.label}
            role={clickable ? "button" : undefined}
            tabIndex={clickable ? 0 : undefined}
            onClick={clickable ? () => onSlice!(s) : undefined}
            onKeyDown={clickable ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSlice!(s); } } : undefined}
            title={clickable ? "Open these in the audit trail" : undefined}
            style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, cursor: clickable ? "pointer" : "default" }}
          >
            <span style={{ width: 10, height: 10, borderRadius: 2, background: s.color, flexShrink: 0 }} />
            <span style={{ color: "var(--bc-text-dim)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.label}</span>
            <span style={{ color: "var(--bc-text-mute)" }}>{s.value} · {total > 0 ? Math.round((s.value / total) * 100) : 0}%</span>
          </div>
        );
      })}
    </div>
  );
}

/** Horizontal latency bars (p50/p95/p99). */
function LatencyBars({ m }: { m: MetricsPayload }) {
  const rows: [string, number, string][] = [
    ["p50", m.p50_latency_ms ?? 0, "var(--bc-pass-line)"],
    ["p95", m.p95_latency_ms ?? 0, "var(--bc-flag-line)"],
    ["p99", m.p99_latency_ms ?? 0, "var(--bc-block-line)"],
  ];
  const max = Math.max(...rows.map((r) => r[1]), 1);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {rows.map(([label, val, color]) => (
        <div key={label} style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ minWidth: 32, fontSize: 12, color: "var(--bc-text-mute)" }}>{label}</span>
          <div style={{ flex: 1, height: 8, background: "var(--bc-surface-2)", borderRadius: 4, overflow: "hidden" }}>
            <div style={{ width: `${(val / max) * 100}%`, height: "100%", background: color, borderRadius: 4, transition: "width 0.4s ease" }} />
          </div>
          <span style={{ minWidth: 64, textAlign: "right", fontSize: 12, color: "var(--bc-text-dim)" }}>{Math.round(val)}ms</span>
        </div>
      ))}
      {m.avg_latency_ms != null && (
        <div style={{ fontSize: 11, color: "var(--bc-text-mute)", textAlign: "right" }}>avg {Math.round(m.avg_latency_ms)}ms</div>
      )}
    </div>
  );
}

interface TrendPoint { pass: number; flag: number; reask: number; escalate: number }

/** Live stacked-area line: cumulative volume partitioned by decision, sampled per poll. */
function StackedTrend({ points, height = 130 }: { points: TrendPoint[]; height?: number }) {
  if (points.length < 2) {
    return <div className="bc-empty" style={{ minHeight: height, display: "flex", alignItems: "center", justifyContent: "center" }}>collecting trend… (updates every 15s)</div>;
  }
  const W = 100;
  const series: [keyof TrendPoint, string][] = [
    ["pass", "var(--bc-pass-line)"],
    ["flag", "var(--bc-flag-line)"],
    ["reask", "var(--bc-reask-line)"],
    ["escalate", "var(--bc-block-line)"],
  ];
  const maxTotal = Math.max(...points.map((p) => p.pass + p.flag + p.reask + p.escalate), 1);
  const n = points.length;
  const x = (i: number) => (i / (n - 1)) * W;
  const y = (v: number) => height - (v / maxTotal) * height;
  const cum = points.map(() => 0);
  const areas = series.map(([key, color]) => {
    const top: string[] = [];
    const bottomRev: string[] = [];
    points.forEach((p, i) => {
      const base = cum[i];
      const next = base + (p[key] as number);
      top.push(`${x(i).toFixed(2)},${y(next).toFixed(2)}`);
      bottomRev.unshift(`${x(i).toFixed(2)},${y(base).toFixed(2)}`);
      cum[i] = next;
    });
    return <polygon key={String(key)} points={`${top.join(" ")} ${bottomRev.join(" ")}`} fill={color} fillOpacity={0.85} />;
  });
  return (
    <svg viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" width="100%" height={height} role="img" aria-label="decision volume trend over time">
      {areas}
    </svg>
  );
}

const FAMILY_COLORS: Record<string, string> = {
  banking: "var(--bc-pass-line)",
  fraud: "var(--bc-flag-line)",
  safety: "var(--bc-block-line)",
};

/** Circular (radial) gauge — value vs target, using the validated dasharray ring. */
function RadialGauge({ value, target, label, lowerIsBetter = false, size = 124, onClick }: { value: number; target: number; label: string; lowerIsBetter?: boolean; size?: number; onClick?: () => void }) {
  const thickness = 12;
  const r = (size - thickness) / 2;
  const c = size / 2;
  const circ = 2 * Math.PI * r;
  const dash = Math.max(0, Math.min(1, value)) * circ;
  const ok = lowerIsBetter ? value <= target : value >= target;
  const color = ok ? "var(--bc-pass-line)" : "var(--bc-flag-line)";
  const tAng = (-90 + Math.max(0, Math.min(1, target)) * 360) * (Math.PI / 180);
  const tx = c + r * Math.cos(tAng);
  const ty = c + r * Math.sin(tAng);
  return (
    <div
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onClick={onClick}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(); } } : undefined}
      title={onClick ? "Open these in the audit trail" : undefined}
      style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4, cursor: onClick ? "pointer" : "default" }}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label}>
        <circle cx={c} cy={c} r={r} fill="none" stroke="var(--bc-surface-2)" strokeWidth={thickness} />
        <circle
          cx={c} cy={c} r={r} fill="none" stroke={color} strokeWidth={thickness}
          strokeDasharray={`${dash} ${circ - dash}`} transform={`rotate(-90 ${c} ${c})`} strokeLinecap="round"
        />
        <circle cx={tx} cy={ty} r={3.5} fill="var(--bc-text)"><title>{`target ${Math.round(target * 100)}%`}</title></circle>
        <text x={c} y={c - 1} textAnchor="middle" fontSize="24" fontWeight="700" style={{ fill: "var(--bc-text)" }}>{Math.round(value * 100)}%</text>
        <text x={c} y={c + 16} textAnchor="middle" fontSize="9" style={{ fill: "var(--bc-text-mute)" }}>{label}</text>
      </svg>
      <div style={{ fontSize: 11, color: ok ? "var(--bc-pass-text)" : "var(--bc-flag-text)" }}>
        {ok ? "on target" : lowerIsBetter ? "above target" : "below target"} · target {Math.round(target * 100)}%
      </div>
    </div>
  );
}

/** Customer-flow funnel — the journey narrowing from every message received down to
 *  the ones the AI handled with no human, with the rest (re-ask / escalate) called out.
 *  A plain-language "where did the questions go" view. */
function DecisionFunnel({ m }: { m: MetricsPayload }) {
  const total = m.queries_total ?? 0;
  const pass = m.decisions?.PASSTHROUGH ?? 0;
  const flag = m.decisions?.FLAG ?? 0;
  const reask = m.decisions?.REASK ?? 0;
  const esc = m.decisions?.ESCALATE ?? 0;
  const pctOf = (n: number) => (total > 0 ? Math.round((n / total) * 100) : 0);
  if (total === 0) return <AskInFlowLink prefix="No queries processed yet." />;
  const stages: { label: string; desc: string; count: number; color: string; decision?: string }[] = [
    { label: "Received", desc: "every customer message", count: total, color: "var(--bc-accent)", decision: "" },
    { label: "Answered by the AI", desc: "released to the customer (allowed + flagged)", count: pass + flag, color: "var(--bc-pass-line)" },
    { label: "Self-served — no human", desc: "passed straight through", count: pass, color: "var(--bc-pass-line)", decision: "PASSTHROUGH" },
  ];
  return (
    <div style={{ display: "flex", gap: 24, flexWrap: "wrap", alignItems: "flex-start" }}>
      <div style={{ flex: 1, minWidth: 260, display: "flex", flexDirection: "column", gap: 4 }}>
        {stages.map((s, i) => {
          const w = Math.max(14, (s.count / total) * 100);
          return (
            <div key={s.label} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
              <div
                role={s.decision !== undefined ? "button" : undefined}
                tabIndex={s.decision !== undefined ? 0 : undefined}
                onClick={s.decision !== undefined ? () => goToAuditDecision(s.decision as string) : undefined}
                onKeyDown={s.decision !== undefined ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); goToAuditDecision(s.decision as string); } } : undefined}
                title={s.decision !== undefined ? "Open these in the audit trail" : undefined}
                style={{
                  width: `${w}%`, minWidth: 150, background: s.color, color: "#0b1220",
                  borderRadius: 8, padding: "8px 12px", textAlign: "center", transition: "width 0.4s ease",
                  cursor: s.decision !== undefined ? "pointer" : "default",
                }}
              >
                <div style={{ fontWeight: 700, fontSize: 19 }}>
                  {s.count.toLocaleString("en-US")} <span style={{ fontWeight: 500, fontSize: 12 }}>· {pctOf(s.count)}%</span>
                </div>
                <div style={{ fontSize: 11, fontWeight: 600 }}>{s.label}</div>
              </div>
              <div style={{ fontSize: 10, color: "var(--bc-text-mute)" }}>{s.desc}</div>
              {i < stages.length - 1 && <span aria-hidden style={{ color: "var(--bc-text-mute)", fontSize: 13, lineHeight: 1 }}>▼</span>}
            </div>
          );
        })}
      </div>
      <div style={{ minWidth: 190, display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5, color: "var(--bc-text-mute)" }}>Other outcomes</div>
        <div
          role="button" tabIndex={0}
          onClick={() => goToAuditDecision("FLAG")}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); goToAuditDecision("FLAG"); } }}
          title="Open these in the audit trail"
          style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}
        >
          <span className="bc-badge flag" style={{ minWidth: 84, textAlign: "center" }}>{decisionLabel("FLAG")}</span>
          <strong style={{ fontSize: 17 }}>{flag}</strong>
          <span style={{ color: "var(--bc-text-mute)", fontSize: 12 }}>({pctOf(flag)}%) answered + reviewed</span>
        </div>
        <div
          role="button" tabIndex={0}
          onClick={() => goToAuditDecision("REASK")}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); goToAuditDecision("REASK"); } }}
          title="Open these in the audit trail"
          style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}
        >
          <span className="bc-badge reask" style={{ minWidth: 84, textAlign: "center" }}>{decisionLabel("REASK")}</span>
          <strong style={{ fontSize: 17 }}>{reask}</strong>
          <span style={{ color: "var(--bc-text-mute)", fontSize: 12 }}>({pctOf(reask)}%) asked to clarify</span>
        </div>
        <div
          role="button" tabIndex={0}
          onClick={() => goToAuditDecision("ESCALATE")}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); goToAuditDecision("ESCALATE"); } }}
          title="Open these in the audit trail"
          style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}
        >
          <span className="bc-badge block" style={{ minWidth: 84, textAlign: "center" }}>{decisionLabel("ESCALATE")}</span>
          <strong style={{ fontSize: 17 }}>{esc}</strong>
          <span style={{ color: "var(--bc-text-mute)", fontSize: 12 }}>({pctOf(esc)}%) escalated</span>
        </div>
        <div style={{ fontSize: 11.5, color: "var(--bc-text-dim)", marginTop: 4, lineHeight: 1.5 }}>
          <strong style={{ color: "var(--bc-pass-text)" }}>{pctOf(pass)}%</strong> handled with no human at all ·{" "}
          <strong style={{ color: "var(--bc-block-text)" }}>{pctOf(esc)}%</strong> routed to a specialist for safety.
        </div>
      </div>
    </div>
  );
}

// ── Component ────────────────────────────────────────────────────────────────

export default function Painel() {
  const [bundled, setBundled] = useState<BundledResponse | null>(null);
  const [uptime, setUptime] = useState<number | null>(null);
  const [integrations, setIntegrations] = useState<Integrations | null>(null);
  const [families, setFamilies] = useState<Record<string, number> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [history, setHistory] = useState<TrendPoint[]>([]);

  useEffect(() => {
    let cancelled = false;

    async function tick() {
      try {
        const b = await getJSON<BundledResponse>("/api/metrics");
        if (!cancelled) {
          setBundled(b);
          setError(null);
          setLoading(false);
        }
        // Supplementary, non-blocking calls — swallow failures.
        try {
          const s = await getJSON<StatsPayload>("/api/stats");
          if (!cancelled && typeof s.uptime_seconds === "number") setUptime(s.uptime_seconds);
        } catch { /* uptime is optional */ }
        try {
          const ig = await getJSON<Integrations>("/api/integrations");
          if (!cancelled) setIntegrations(ig);
        } catch { /* topology is optional */ }
        try {
          // Real backend-held time series — survives a frontend refresh.
          const ts = await getJSON<TimeseriesResponse>("/api/metrics/timeseries?max_points=60");
          if (!cancelled && Array.isArray(ts.points)) {
            setHistory(ts.points.map((p) => ({
              pass: p.PASSTHROUGH ?? 0, flag: p.FLAG ?? 0, reask: p.REASK ?? 0, escalate: p.ESCALATE ?? 0,
            })));
          }
        } catch { /* trend is optional */ }
        try {
          const fam = await getJSON<FamiliesPayload>("/api/intents");
          if (!cancelled && fam.families) setFamilies(fam.families);
        } catch { /* families optional */ }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Unknown error");
          setLoading(false);
        }
      }
    }

    tick();
    const id = setInterval(() => { if (!document.hidden) tick(); }, 15000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (loading) {
    return (
      <div className="bc-card">
        <div className="bc-card-h"><h2>Operations dashboard <StateBadge feature="bridge-metrics" /></h2></div>
        <div className="bc-loading">Loading data…</div>
      </div>
    );
  }

  if (error || !bundled) {
    return (
      <div className="bc-card">
        <div className="bc-card-h"><h2>Operations dashboard <StateBadge feature="bridge-metrics" /></h2></div>
        <div className="bc-error">
          Service temporarily unavailable. Please try again in a moment.
        </div>
      </div>
    );
  }

  const m = bundled.metrics;
  const h = bundled.health;
  const auditEntries = (bundled.audit?.entries ?? []).slice(0, 6);

  const total = m.queries_total ?? 0;
  const passCount = m.decisions?.PASSTHROUGH ?? 0;
  const flagCount = m.decisions?.FLAG ?? 0;
  const reaskCount = m.decisions?.REASK ?? 0;
  const blockCount = m.decisions?.ESCALATE ?? 0;
  const intentSlices: Slice[] = Object.entries(m.queries_by_intent ?? {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 8)
    .map(([name, val], i) => ({ label: humanizeIntent(name), value: val, color: INTENT_PALETTE[i % INTENT_PALETTE.length], audit: { intent: name } }));
  const familySlices: Slice[] = Object.entries(families ?? {})
    .filter(([, v]) => v > 0)
    .map(([name, val]) => ({ label: name, value: val, color: FAMILY_COLORS[name] ?? "var(--bc-text-mute)" }));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <p style={{ fontSize: 12.5, color: "var(--bc-text-mute)", margin: 0, lineHeight: 1.55 }}>
        <strong style={{ color: "var(--bc-text)" }}>What this does:</strong>{" "}
        {"A live overview of every customer question the AI has handled since the service started — how many it answered on its own, flagged for review, asked to clarify, or sent to a person. Click a tile to drill into the records."}
      </p>

      {/* Row 1: four metric tiles (decision tiles drill into Audit) */}
      <div className="bc-card">
        <div className="bc-card-h">
          <h2>Operations dashboard <StateBadge feature="bridge-metrics" /></h2>
        </div>
        <div className="bc-grid-4">
          <div className="bc-metric">
            <div className="bc-metric-label">Queries</div>
            <div className="bc-metric-value">{total.toLocaleString("en-US")}</div>
            <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 2 }}>since service start</div>
          </div>
          <div className="bc-metric" role="button" tabIndex={0} onClick={() => goToAuditDecision("PASSTHROUGH")} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); goToAuditDecision("PASSTHROUGH"); } }} style={{ cursor: "pointer" }} title="See the allowed ones in the audit trail">
            <div className="bc-metric-label">{decisionLabel("PASSTHROUGH")}</div>
            <div className="bc-metric-value pass">{pct(passCount, total)}</div>
            <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 2 }}>{passCount} of {total}</div>
          </div>
          <div className="bc-metric" role="button" tabIndex={0} onClick={() => goToAuditDecision("FLAG")} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); goToAuditDecision("FLAG"); } }} style={{ cursor: "pointer" }} title="See the flagged ones in the audit trail">
            <div className="bc-metric-label">{decisionLabel("FLAG")}</div>
            <div className="bc-metric-value flag">{pct(flagCount, total)}</div>
            <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 2 }}>{flagCount} of {total}</div>
          </div>
          <div className="bc-metric" role="button" tabIndex={0} onClick={() => goToAuditDecision("REASK")} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); goToAuditDecision("REASK"); } }} style={{ cursor: "pointer" }} title="See the re-asked ones in the audit trail">
            <div className="bc-metric-label">{decisionLabel("REASK")}</div>
            <div className="bc-metric-value reask">{pct(reaskCount, total)}</div>
            <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 2 }}>{reaskCount} of {total}</div>
          </div>
          <div className="bc-metric" role="button" tabIndex={0} onClick={() => goToAuditDecision("ESCALATE")} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); goToAuditDecision("ESCALATE"); } }} style={{ cursor: "pointer" }} title="See the escalated ones in the audit trail">
            <div className="bc-metric-label">{decisionLabel("ESCALATE")}</div>
            <div className="bc-metric-value block">{pct(blockCount, total)}</div>
            <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 2 }}>{blockCount} of {total}</div>
          </div>
          <div className="bc-metric">
            <div className="bc-metric-label">Avg confidence</div>
            <div className="bc-metric-value">{m.avg_confidence != null ? `${Math.round(m.avg_confidence * 100)}%` : "—"}</div>
            <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 2 }}>how sure, on average</div>
          </div>
          <div className="bc-metric">
            <div className="bc-metric-label">Avg latency</div>
            <div className="bc-metric-value">{m.avg_latency_ms != null ? `${Math.round(m.avg_latency_ms)}ms` : "—"}</div>
            <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 2 }}>per question</div>
          </div>
          <div className="bc-metric">
            <div className="bc-metric-label">Latency p95</div>
            <div className="bc-metric-value">{m.p95_latency_ms != null ? `${Math.round(m.p95_latency_ms)}ms` : "—"}</div>
            <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 2 }}>slowest 5%</div>
          </div>
        </div>
        <p style={{ fontSize: 11.5, color: "var(--bc-text-mute)", margin: "10px 2px 0", lineHeight: 1.55 }}>
          In plain terms: <strong style={{ color: "var(--bc-text-dim)" }}>resolution rate</strong> = % answered without a human ·{" "}
          <strong style={{ color: "var(--bc-text-dim)" }}>escalation rate</strong> = % handed to a person (lower is better) ·{" "}
          <strong style={{ color: "var(--bc-text-dim)" }}>intent families</strong> = groups of question types.
        </p>
        <DecisionLegend title="What the four decisions mean" />
      </div>

      {/* Customer flow funnel — plain-language "where did the questions go" */}
      <div className="bc-card">
        <div className="bc-card-h"><h2 style={{ fontSize: 15 }}>Customer flow</h2></div>
        <DecisionFunnel m={m} />
      </div>

      {/* Process analytics — pie + line charts, grouped under a collapsible so the
          default Dashboard stays lean (tiles + health). Expand to read the flow. */}
      <Disclosure title="Process analytics" hint="pie · trend · latency · families · targets" defaultOpen={true}>
      <div className="bc-grid-2">
        <div className="bc-card">
          <div className="bc-card-h"><h2 style={{ fontSize: 15 }}>Decision mix</h2></div>
          {total === 0 ? (
            <div className="bc-empty">No queries processed yet.</div>
          ) : (
            <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
              <Donut slices={decisionSlices(m)} center="decisions" onSlice={(s) => { if (s.audit) goToAuditFilter(s.audit); }} />
              <Legend slices={decisionSlices(m)} onSlice={(s) => { if (s.audit) goToAuditFilter(s.audit); }} />
            </div>
          )}
        </div>
        <div className="bc-card">
          <div className="bc-card-h"><h2 style={{ fontSize: 15 }}>What customers asked</h2></div>
          {intentSlices.length === 0 ? (
            <div className="bc-empty">No intent data yet.</div>
          ) : (
            <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
              <Donut slices={intentSlices} center="intents" onSlice={(s) => { if (s.audit) goToAuditFilter(s.audit); }} />
              <Legend slices={intentSlices} onSlice={(s) => { if (s.audit) goToAuditFilter(s.audit); }} />
            </div>
          )}
        </div>
      </div>

      <div className="bc-grid-2">
        <div className="bc-card">
          <div className="bc-card-h"><h2 style={{ fontSize: 15 }}>Decision trend (live)</h2></div>
          <StackedTrend points={history} />
          <div style={{ marginTop: 6, fontSize: 11, color: "var(--bc-text-mute)" }}>
            Decisions over time — updates every 15s.
          </div>
        </div>
        <div className="bc-card">
          <div className="bc-card-h"><h2 style={{ fontSize: 15 }}>Latency profile</h2></div>
          {total === 0 ? (
            <div className="bc-empty">No queries processed yet.</div>
          ) : (
            <LatencyBars m={m} />
          )}
        </div>
      </div>

      <div className="bc-grid-2">
        <div className="bc-card">
          <div className="bc-card-h"><h2 style={{ fontSize: 15 }}>Intent families</h2></div>
          {familySlices.length === 0 ? (
            <div className="bc-empty">No family data yet.</div>
          ) : (
            <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
              <Donut slices={familySlices} center="families" />
              <Legend slices={familySlices} />
            </div>
          )}
        </div>
        <div className="bc-card">
          <div className="bc-card-h"><h2 style={{ fontSize: 15 }}>Targets</h2></div>
          {total === 0 ? (
            <div className="bc-empty">No queries processed yet.</div>
          ) : (
            <div style={{ display: "flex", gap: 24, justifyContent: "space-around", flexWrap: "wrap" }}>
              <RadialGauge value={m.resolution_rate} target={m.target_resolution ?? 0.83} label="self-resolved" onClick={() => goToAuditDecision("PASSTHROUGH")} />
              <RadialGauge value={m.escalation_rate} target={0.2} label="escalated to human" lowerIsBetter onClick={() => goToAuditDecision("ESCALATE")} />
            </div>
          )}
        </div>
      </div>
      </Disclosure>

      {/* Row 2: the inspection-flow strip (hero, click → Flow) */}
      <FlowStrip />

      {/* Row 3: connections mini-topology + recent events */}
      <div className="bc-grid-2">
        <MiniTopology data={integrations} />

        <div className="bc-card">
          <div className="bc-card-h">
            <h2 style={{ fontSize: 15 }}>Recent events</h2>
            <span
              role="button" tabIndex={0}
              onClick={() => go("audit")}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go("audit"); } }}
              title="Open the full audit trail"
              style={{ fontSize: 11.5, color: "var(--bc-accent)", cursor: "pointer", whiteSpace: "nowrap" }}
            >
              view all in Audit →
            </span>
          </div>
          {auditEntries.length === 0 ? (
            <div className="bc-empty">No audit events available.</div>
          ) : (
            <table className="bc-table" style={{ width: "100%" }}>
              <thead>
                <tr><th>Time</th><th>Intent</th><th>Decision</th></tr>
              </thead>
              <tbody>
                {auditEntries.map((e, i) => {
                  const tone = decisionTone(e.decision);
                  return (
                    <tr key={e.seq ?? i} tabIndex={0} onClick={() => viewInAudit(e.seq)} onKeyDown={(ev) => { if (ev.key === "Enter") viewInAudit(e.seq); }} style={{ cursor: "pointer" }} title="View this event in Audit">
                      <td style={{ color: "var(--bc-text-dim)", whiteSpace: "nowrap" }}>{fmtTime(e.ts)}</td>
                      <td style={{ color: "var(--bc-text)" }} title={e.intent}>{humanizeIntent(e.intent)}</td>
                      <td><span className={`bc-badge ${tone}`}>{decisionLabel(e.decision)}</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Row 4: backend health */}
      <div className="bc-grid-2">
        <div className="bc-card">
          <div className="bc-card-h"><h2 style={{ fontSize: 15 }}>System status</h2></div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className={`bc-dot ${h.status === "ok" ? "pass" : "block"}`} title={h.status ?? "unknown"} />
              <span style={{ color: "var(--bc-text)", fontWeight: 600 }}>{h.backend === "fake" ? "Demo (fixed answers)" : h.backend ?? "—"}</span>
              <span className="bc-chip" style={{ marginLeft: "auto" }} title="Real AI model vs. pre-scripted demo answers">
                {h.backend_is_real ? "real model" : "demo answers"}
              </span>
            </div>
            {uptime !== null && (
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                <span style={{ color: "var(--bc-text-mute)" }}>Uptime</span>
                <span style={{ color: "var(--bc-text-dim)" }}>{fmtUptime(uptime)}</span>
              </div>
            )}
            {typeof h.audit_entries_current === "number" && (
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                <span style={{ color: "var(--bc-text-mute)" }}>Audit entries</span>
                <span style={{ color: "var(--bc-text-dim)" }}>{h.audit_entries_current}</span>
              </div>
            )}
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
              <span style={{ color: "var(--bc-text-mute)" }}>Auto-resolution</span>
              <span style={{ color: m.resolution_rate >= 0.83 ? "var(--bc-pass-text)" : "var(--bc-flag-text)" }}>
                {Math.round(m.resolution_rate * 100)}%
              </span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
              <span style={{ color: "var(--bc-text-mute)" }}>Escalation rate</span>
              <span style={{ color: m.escalation_rate < 0.2 ? "var(--bc-pass-text)" : "var(--bc-block-text)" }}>
                {Math.round(m.escalation_rate * 100)}%
              </span>
            </div>
          </div>
        </div>
      </div>

    </div>
  );
}
