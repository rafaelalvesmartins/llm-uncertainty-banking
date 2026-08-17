"use client";

import { useEffect, useState } from "react";
import StateBadge from "@/components/StateBadge";
import { apiErrorText } from "@/lib/apiError";
import { useAppContext } from "@/components/AppContextProvider";

interface WindowStat {
  requests: number;
  errors: number;
  qps: number;
  error_rate: number;
}

interface StatsPayload {
  uptime_seconds: number;
  process_start_ts: number;
  requests_total: number;
  errors_total: number;
  windows: { "1m": WindowStat; "5m": WindowStat; "10m": WindowStat };
  last_error: {
    ts: number;
    path: string;
    method: string;
    error_type: string;
    error_message: string;
  } | null;
}

interface StageBudget {
  name: string;
  count: number;
  avg_ms: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  max_ms: number | null;
  budget_ms: number | null;
  breach: boolean;
}

interface BudgetsPayload {
  stages: StageBudget[];
  window: number;
  total_breaches: number;
}

interface Props {
  refreshKey: number;
}

function fmtUptime(s: number): string {
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
}

export default function OpsPanel({ refreshKey }: Props) {
  const { operator } = useAppContext();
  const [stats, setStats] = useState<StatsPayload | null>(null);
  const [budgets, setBudgets] = useState<BudgetsPayload | null>(null);
  const [rebaselineN, setRebaselineN] = useState<number | "">(200);
  const [rebaselineMsg, setRebaselineMsg] = useState<string | null>(null);
  const [rebaselining, setRebaselining] = useState(false);
  // Two flags so a down backend reads as "unreachable", not an eternal "loading…".
  const [polled, setPolled] = useState(false);
  const [backendDown, setBackendDown] = useState(false);
  const [exportErr, setExportErr] = useState<string | null>(null);

  // Fetch→blob download instead of navigating: a failed export (502 JSON, auth)
  // must NOT replace the whole dashboard with a raw error page mid-demo.
  async function downloadAudit(format: "json" | "csv", source: "memory" | "disk") {
    setExportErr(null);
    try {
      const r = await fetch(`/api/audit/export?format=${format}&source=${source}`, { cache: "no-store" });
      if (!r.ok) { setExportErr(`export failed (HTTP ${r.status})`); return; }
      const blob = await r.blob();
      const cd = r.headers.get("Content-Disposition") || "";
      const m = cd.match(/filename="?([^"]+)"?/);
      const name = m ? m[1] : `audit-${source}.${format}`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setExportErr(`export failed (${e instanceof Error ? e.message : String(e)})`);
    }
  }

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const [s, b] = await Promise.all([
          fetch("/api/stats", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)),
          fetch("/api/stages/budgets", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)),
        ]);
        if (cancelled) return;
        // Keep the last-good snapshot on a transient non-OK (s/b are null then) —
        // otherwise one 502 blip resets the whole panel to "loading…".
        if (s !== null) setStats(s);
        if (b !== null) setBudgets(b);
        setPolled(true);
        setBackendDown(s === null && b === null);
      } catch {
        if (!cancelled) { setPolled(true); setBackendDown(true); }
      }
    };
    tick();
    const id = setInterval(() => { if (!document.hidden) tick(); }, 15000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [refreshKey]);

  async function applyAutoRebaseline() {
    if (rebaselining) return; // guard against double-submit firing duplicate POSTs
    setRebaselining(true);
    setRebaselineMsg(null);
    // An empty field reads as 0 (disabled) before hitting the int endpoint.
    const every = rebaselineN === "" ? 0 : rebaselineN;
    try {
      const r = await fetch(`/api/drift/auto-rebaseline?every=${every}&operator=${encodeURIComponent(operator)}`, { method: "POST" });
      const j = await r.json().catch(() => null);
      if (r.ok) {
        // Fall back to the value we posted if the body can't be parsed, so a
        // positive cadence isn't mislabeled "disabled".
        const n = typeof j?.auto_rebaseline_every === "number" ? j.auto_rebaseline_every : every;
        setRebaselineMsg(`auto-rebaseline ${n > 0 ? `every ${n} queries` : "disabled"}`);
      } else {
        setRebaselineMsg(`error: ${apiErrorText(j, r.status)}`);
      }
    } catch (e) {
      // A transport failure (proxy/network down) must surface, not vanish silently.
      setRebaselineMsg(`error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setRebaselining(false);
    }
  }

  return (
    <div className="card">
      <h2>Operations Panel<StateBadge feature="ops-dashboard" /></h2>

      {/* Health watchdog */}
      <div style={{ marginBottom: 14 }}>
        <div
          className="muted"
          style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}
        >
          health monitor
        </div>
        {!stats ? (
          <div className="empty">{!polled ? "loading…" : backendDown ? "Backend unreachable — retrying every 15s." : "No data yet."}</div>
        ) : (
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", fontSize: 12 }}>
            <div>
              <span className="muted">uptime</span>{" "}
              <strong>{fmtUptime(stats.uptime_seconds)}</strong>
            </div>
            <div>
              <span className="muted">requests</span>{" "}
              <strong>{stats.requests_total}</strong>{" "}
              <span className="muted">({stats.errors_total} errors)</span>
            </div>
            {(["1m", "5m", "10m"] as const).map((k) => {
              const w = stats.windows[k];
              const errPct = (w.error_rate * 100).toFixed(1);
              return (
                <div key={k}>
                  <span className="muted">{k}</span>{" "}
                  <strong>{w.qps} req/s</strong>{" "}
                  <span style={{ color: w.error_rate > 0.05 ? "var(--bc-block-line)" : "var(--bc-text-dim)" }}>
                    · error {errPct}%
                  </span>
                </div>
              );
            })}
          </div>
        )}
        {stats?.last_error && (
          <div
            style={{
              marginTop: 6,
              padding: "4px 8px",
              background: "var(--bc-block)",
              border: "1px solid var(--bc-block)",
              borderRadius: 3,
              fontSize: 11,
              color: "var(--bc-block-text)",
            }}
          >
            <strong>last error:</strong>{" "}
            {new Date(stats.last_error.ts * 1000).toLocaleTimeString()} ·{" "}
            {stats.last_error.method} {stats.last_error.path} ·{" "}
            {stats.last_error.error_type}: {stats.last_error.error_message}
          </div>
        )}
      </div>

      {/* Per-stage latency budgets */}
      <div style={{ marginBottom: 14 }}>
        <div
          className="muted"
          style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}
        >
          <span title="How long each step takes vs. the time limit it's promised to stay under. SLA = the agreed speed target for that step.">
            step speed vs target (SLA)
          </span>{" "}
          {budgets && budgets.total_breaches > 0 && (
            <span style={{ color: "var(--bc-block-line)", marginLeft: 8 }}>
              · {budgets.total_breaches} over the limit
            </span>
          )}
        </div>
        {!budgets ? (
          <div className="empty">{!polled ? "loading…" : backendDown ? "Backend unreachable — retrying every 15s." : "No data yet."}</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {budgets.stages
              .filter((s) => s.count > 0)
              .map((s) => {
                const ratio = s.p95_ms && s.budget_ms ? s.p95_ms / s.budget_ms : 0;
                const barWidth = Math.min(100, Math.max(2, ratio * 100));
                const color = s.breach ? "var(--bc-block-line)" : ratio > 0.7 ? "var(--bc-flag-line)" : "var(--bc-pass-line)";
                return (
                  <div
                    key={s.name}
                    style={{
                      fontSize: 11,
                      display: "grid",
                      gridTemplateColumns: "150px 1fr 110px",
                      gap: 8,
                      alignItems: "center",
                      padding: "2px 0",
                    }}
                  >
                    <span style={{ color: s.breach ? "var(--bc-block-line)" : "var(--bc-text)" }} title={s.name}>
                      {s.breach ? "⚠ " : ""}{s.name.replace(/_/g, " ")}
                    </span>
                    <div
                      style={{
                        height: 6,
                        background: "var(--bc-surface)",
                        borderRadius: 3,
                        overflow: "hidden",
                      }}
                    >
                      <div style={{ width: `${barWidth}%`, height: "100%", background: color }} />
                    </div>
                    <span
                      className="muted"
                      style={{ textAlign: "right", fontFamily: "monospace" }}
                      title="p95 = the slowest 5% of requests for this step. We track the slow tail (not the average) because that is where customers actually wait. Shown as: this step's time / the time it's supposed to stay under (the SLA)."
                    >
                      p95 {s.p95_ms?.toFixed(1)}ms / {s.budget_ms?.toFixed(0)}ms
                    </span>
                  </div>
                );
              })}
            {budgets.stages.filter((s) => s.count > 0).length === 0 && (
              <div className="empty">no stage samples yet — fire a /query first</div>
            )}
            {budgets.total_breaches > 0 && (
              <div style={{ fontSize: 11, color: "var(--bc-block-text)", marginTop: 4 }}>
                Next step: alert the team that owns this step before customers feel it.
              </div>
            )}
          </div>
        )}
      </div>

      {/* Audit export */}
      <div style={{ marginBottom: 14 }}>
        <div
          className="muted"
          style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}
        >
          export audit (BCB 4893 retention)
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {(["memory", "disk"] as const).map((source) =>
            (["json", "csv"] as const).map((format) => (
              <button
                key={`${source}-${format}`}
                type="button"
                onClick={() => downloadAudit(format, source)}
                style={{ fontSize: 11, padding: "3px 8px" }}
                title={`Download ${source === "memory" ? "in-memory window" : "full SQLite history"} as ${format.toUpperCase()}`}
              >
                ⇩ {source === "memory" ? "memory" : "disk"} · {format}
              </button>
            )),
          )}
        </div>
        {exportErr && (
          <div role="alert" style={{ fontSize: 11, color: "var(--bc-block-line)", marginTop: 6 }}>{exportErr}</div>
        )}
      </div>

      {/* Drift auto-rebaseline control */}
      <div>
        <div
          className="muted"
          style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}
        >
          drift auto-rebaseline (0 = disabled)
        </div>
        <div style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 12 }}>
          <span>every</span>
          <input
            aria-label="auto-rebaseline every N queries"
            type="number"
            min={0}
            max={100000}
            step={1}
            value={rebaselineN}
            onChange={(e) => {
              // Allow the field to be cleared mid-edit; otherwise clamp to the
              // backend's accepted range [0, 100000] and drop negatives/NaN so
              // "-50" can't post an invalid value or strand a leading zero.
              const raw = e.target.value;
              if (raw === "") {
                setRebaselineN("");
                return;
              }
              const n = Math.trunc(Number(raw));
              if (Number.isFinite(n)) setRebaselineN(Math.min(100000, Math.max(0, n)));
            }}
            style={{ width: 80, padding: "2px 6px" }}
          />
          <span>queries</span>
          <button type="button" onClick={applyAutoRebaseline} disabled={rebaselining} style={{ fontSize: 11 }}>
            {rebaselining ? "…" : "apply"}
          </button>
          {rebaselineMsg && <span className="muted" style={{ fontSize: 11 }}>{rebaselineMsg}</span>}
        </div>
      </div>
    </div>
  );
}
