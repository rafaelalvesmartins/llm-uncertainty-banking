"use client";

import { useEffect, useState } from "react";
import StateBadge from "@/components/StateBadge";
import { useAppContext } from "@/components/AppContextProvider";
import { decisionLabel, humanizeIntent } from "@/components/console/types";
import { decisionMeaning } from "@/components/console/DecisionLegend";

interface SessionEvent {
  seq: number | null;
  ts: number | null;
  query: string;
  intent: string;
  confidence: number | null;
  decision: string;
  cost_cents: number | null;
  pii_count: number;
  from_cache: boolean;
}
interface Session {
  customer_id: string;
  channels: string[];
  n_events: number;
  decisions: Record<string, number>;
  pii_events: number;
  cost_cents: number;
  first_ts: number | null;
  last_ts: number | null;
  events: SessionEvent[];
}
interface Data {
  n_sessions: number;
  n_events: number;
  sessions: Session[];
}

const DECISION_COLOR: Record<string, string> = {
  PASSTHROUGH: "var(--bc-pass-line)",
  FLAG: "var(--bc-flag-line)",
  REASK: "var(--bc-reask-line)",
  ESCALATE: "var(--bc-block-line)",
};

function downloadJSON(filename: string, obj: unknown): void {
  const blob = new Blob([JSON.stringify(obj, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

const DECISION_KEYS = ["PASSTHROUGH", "FLAG", "REASK", "ESCALATE"] as const;

// At-a-glance decision distribution across the currently listed customers.
// Aggregates the same `decisions` counts shown per row, so it stays in sync
// with the search / decision filter and the 15s live poll. Segments and legend
// items toggle the decision filter (click a colour to drill in, click again to
// clear).
function DecisionMixBar({
  sessions,
  active,
  onPick,
}: {
  sessions: Session[];
  active: string;
  onPick: (d: string) => void;
}) {
  const totals: Record<string, number> = { PASSTHROUGH: 0, FLAG: 0, REASK: 0, ESCALATE: 0 };
  for (const s of sessions) {
    for (const k of DECISION_KEYS) totals[k] += s.decisions[k] ?? 0;
  }
  const total = DECISION_KEYS.reduce((a, k) => a + totals[k], 0);
  if (total === 0) return null;

  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 5 }}>
        <span style={{ fontSize: 11, color: "var(--bc-text-mute)", textTransform: "uppercase", letterSpacing: 0.4 }}>
          Decision mix
        </span>
        <span style={{ fontSize: 11, color: "var(--bc-text-dim)" }}>
          {total} decisions across {sessions.length} {sessions.length === 1 ? "customer" : "customers"}
        </span>
      </div>
      <div
        style={{ display: "flex", width: "100%", height: 16, borderRadius: 8, overflow: "hidden", border: "1px solid var(--bc-border)" }}
        role="img"
        aria-label={`Decision distribution: ${DECISION_KEYS.map((k) => `${decisionLabel(k)} ${totals[k]}`).join(", ")}`}
      >
        {DECISION_KEYS.map((k) => {
          const pct = (totals[k] / total) * 100;
          if (pct === 0) return null;
          const dimmed = active !== "" && active !== k;
          return (
            <button
              key={k}
              type="button"
              onClick={() => onPick(k)}
              title={`${decisionLabel(k)}: ${totals[k]} (${pct.toFixed(0)}%) — click to ${active === k ? "clear filter" : "filter"}`}
              style={{
                width: `${pct}%`,
                height: "100%",
                border: "none",
                padding: 0,
                cursor: "pointer",
                background: DECISION_COLOR[k],
                opacity: dimmed ? 0.3 : 1,
                transition: "opacity .15s",
              }}
            />
          );
        })}
      </div>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 6 }}>
        {DECISION_KEYS.map((k) => {
          const pct = (totals[k] / total) * 100;
          const dimmed = active !== "" && active !== k;
          return (
            <button
              key={k}
              type="button"
              onClick={() => onPick(k)}
              title={`Click to ${active === k ? "clear filter" : `show only customers with a ${decisionLabel(k)}`}`}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 5,
                background: "transparent",
                border: "none",
                padding: 0,
                cursor: "pointer",
                opacity: dimmed ? 0.45 : 1,
                fontSize: 11,
              }}
            >
              <span style={{ width: 9, height: 9, borderRadius: 2, background: DECISION_COLOR[k] }} />
              <span style={{ color: "var(--bc-text)" }}>{decisionLabel(k)}</span>
              <span style={{ color: "var(--bc-text-dim)" }}>{totals[k]} · {pct.toFixed(0)}%</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// Per-conversation flow, shown when a customer row is expanded. One bar per
// event in chronological order: height = confidence, colour = the decision it
// drove. Makes the "confidence dipped → re-ask/escalate" pattern visible at a
// glance, without reading every row. Events with no confidence score render as
// a dashed ghost bar.
function SessionFlowChart({ events }: { events: SessionEvent[] }) {
  const evs = events.slice().sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0));
  if (evs.length < 2) return null; // a single point is not a flow
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 10, color: "var(--bc-text-mute)", textTransform: "uppercase", letterSpacing: 0.4 }}>Flow</span>
        <span style={{ fontSize: 10.5, color: "var(--bc-text-dim)" }}>bar height = confidence · colour = decision · left → right = order</span>
      </div>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 40, borderBottom: "1px solid var(--bc-border)" }}>
        {evs.map((e, i) => {
          const scored = e.confidence != null;
          const h = scored ? Math.max(8, Math.round((e.confidence as number) * 100)) : 100;
          const color = DECISION_COLOR[e.decision] || "var(--bc-text-mute)";
          return (
            <div
              key={e.seq ?? i}
              title={`#${e.seq ?? "—"} · ${humanizeIntent(e.intent)} · ${scored ? Math.round((e.confidence as number) * 100) + "% confidence" : "no score"} · ${decisionLabel(e.decision)}`}
              style={{
                flex: 1,
                minWidth: 3,
                height: `${h}%`,
                background: scored ? color : "transparent",
                border: scored ? "none" : `1px dashed ${color}`,
                borderRadius: "2px 2px 0 0",
                opacity: scored ? 0.85 : 0.4,
              }}
            />
          );
        })}
      </div>
    </div>
  );
}

export default function SessionsPanel({ embedded = false }: { embedded?: boolean }) {
  const { client } = useAppContext();
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [decisionFilter, setDecisionFilter] = useState("");

  // Restore the filter on mount / global-search 'bridge:goto' (works even when already
  // on this page) and on refresh — sessionStorage survives a same-tab reload.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const apply = () => {
      const raw = window.sessionStorage.getItem("bridge:sessionFilter");
      if (raw) {
        try {
          const f = JSON.parse(raw) as { search?: string; decision?: string };
          setSearch(f.search ?? "");
          setDecisionFilter(f.decision ?? "");
        } catch {
          /* ignore a malformed stored filter */
        }
      }
    };
    apply();
    const onGoto = (e: Event) => {
      if ((e as CustomEvent).detail?.view === "sessions") apply();
    };
    window.addEventListener("bridge:goto", onGoto);
    return () => window.removeEventListener("bridge:goto", onGoto);
  }, []);

  // Persist the filter so it survives a refresh (and so the global search can prefill it).
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (search.trim() || decisionFilter) {
      window.sessionStorage.setItem("bridge:sessionFilter", JSON.stringify({ search, decision: decisionFilter }));
    } else {
      window.sessionStorage.removeItem("bridge:sessionFilter");
    }
  }, [search, decisionFilter]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | undefined;
    const attempt = () => {
      fetch("/api/sessions", { cache: "no-store" })
        .then(async (r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then((j) => {
          if (cancelled) return;
          setData(j);
          setError(null);
          // NOTE: do NOT clear the interval on success — this is a LIVE panel and
          // must keep polling. (Clearing here froze it on the first snapshot.)
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

  if (error && !data) {
    return (
      <div className={embedded ? "" : "card card--wide"}>
        {!embedded && <h2>Sessions by Customer</h2>}
        <div className="empty error" role="alert">backend unreachable ({error})</div>
      </div>
    );
  }
  if (!data) {
    return (
      <div className={embedded ? "" : "card card--wide"}>
        {!embedded && <h2>Sessions by Customer</h2>}
        <div className="empty">loading…</div>
      </div>
    );
  }

  const term = search.trim().toLowerCase();
  const filtered = data.sessions.filter((s) => {
    // Sessions are CUSTOMER conversations — hide the synthetic "—"/console grouping of
    // config-change (APPLIED) events, which otherwise reads as a corrupt, blank customer.
    if (!s.events.some((e) => e.decision !== "APPLIED")) return false;
    if (term && !s.customer_id.toLowerCase().includes(term)) return false;
    if (decisionFilter && (s.decisions[decisionFilter] ?? 0) <= 0) return false;
    return true;
  });

  return (
    <div className={embedded ? "" : "card card--wide"}>
      {!embedded && (
        <h2>
          Sessions by Customer
          <StateBadge feature="sessions" />
          <span className="card-subtitle">Audit decisions grouped by customer — click a decision to view its flow</span>
        </h2>
      )}

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 8 }}>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="search customer…"
          aria-label="search customer id"
          style={{ fontSize: 12, padding: "3px 8px", background: "var(--bc-surface-2)", border: "1px solid var(--bc-border)", borderRadius: 6, color: "var(--bc-text)", flex: 1, minWidth: 160 }}
        />
        <select
          value={decisionFilter}
          onChange={(e) => setDecisionFilter(e.target.value)}
          aria-label="filter by decision"
          style={{ fontSize: 12, padding: "3px 6px", background: "var(--bc-surface-2)", border: "1px solid var(--bc-border)", borderRadius: 6, color: "var(--bc-text)" }}
        >
          <option value="">any decision</option>
          <option value="PASSTHROUGH">has Pass</option>
          <option value="FLAG">has Flag</option>
          <option value="REASK">has Re-ask</option>
          <option value="ESCALATE">has Escalate</option>
        </select>
        {(search || decisionFilter) && (
          <button
            type="button"
            onClick={() => { setSearch(""); setDecisionFilter(""); }}
            style={{ fontSize: 12, padding: "3px 8px", background: "transparent", border: "1px solid var(--bc-border)", borderRadius: 6, color: "var(--bc-text-mute)", cursor: "pointer" }}
          >
            Clear
          </button>
        )}
        <button
          type="button"
          onClick={() => downloadJSON(`bridge-sessions-${filtered.length}.json`, { exported_at: new Date().toISOString(), n: filtered.length, sessions: filtered })}
          disabled={filtered.length === 0}
          title="Download the listed sessions as JSON (evidence / shift handover)"
          style={{ fontSize: 12, padding: "3px 8px", background: "transparent", border: "1px solid var(--bc-border)", borderRadius: 6, color: "var(--bc-text-mute)", cursor: filtered.length === 0 ? "default" : "pointer" }}
        >
          ⬇ Export
        </button>
        <span className="muted" style={{ fontSize: 12 }}>
          {filtered.length === data.sessions.length
            ? `${data.n_sessions} sessions · ${data.n_events} events`
            : `${filtered.length} of ${data.n_sessions} sessions`}
        </span>
      </div>

      <DecisionMixBar
        sessions={filtered}
        active={decisionFilter}
        onPick={(d) => setDecisionFilter(d === decisionFilter ? "" : d)}
      />

      {filtered.length === 0 ? (
        <div className="empty">No sessions match the filter.</div>
      ) : (
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {filtered.map((sess) => {
          const isOpen = open === sess.customer_id;
          return (
            <div key={sess.customer_id} style={{ background: "var(--bc-surface-2)", border: `1px solid ${sess.customer_id === client ? "var(--bc-accent)" : "var(--bc-border)"}`, borderRadius: 6 }}>
              <button
                type="button"
                onClick={() => setOpen(isOpen ? null : sess.customer_id)}
                aria-expanded={isOpen}
                style={{
                  width: "100%",
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  flexWrap: "wrap",
                  background: "transparent",
                  border: "none",
                  padding: "8px 10px",
                  color: "var(--bc-text)",
                  cursor: "pointer",
                  textAlign: "left",
                }}
              >
                <strong style={{ fontSize: 13 }}>{sess.customer_id}</strong>
                {sess.customer_id === client && (
                  <span style={{ fontSize: 9, color: "var(--bc-accent)", border: "1px solid var(--bc-accent)", borderRadius: 8, padding: "0 6px" }}>● active</span>
                )}
                <span className="muted" style={{ fontSize: 11 }}>{sess.channels.join(", ")}</span>
                <span className="muted" style={{ fontSize: 11 }}>{sess.n_events} events</span>
                <span style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                  {Object.entries(sess.decisions).map(([d, n]) => (
                    <span
                      key={d}
                      style={{
                        fontSize: 10,
                        color: DECISION_COLOR[d] || "var(--bc-text-mute)",
                        border: `1px solid ${DECISION_COLOR[d] || "var(--bc-border)"}`,
                        borderRadius: 10,
                        padding: "0 6px",
                      }}
                    >
                      {decisionLabel(d)} {n}
                    </span>
                  ))}
                </span>
                {sess.pii_events > 0 && (
                  <span style={{ fontSize: 10, color: "var(--bc-text-mute)" }} title="Personal data detected and masked before processing">PII: {sess.pii_events}</span>
                )}
                <span style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
                  <span className="muted" style={{ fontSize: 11 }}>{sess.cost_cents.toFixed(2)}¢</span>
                  <span className="muted" style={{ fontSize: 11 }}>{isOpen ? "▾" : "▸"}</span>
                </span>
              </button>
              {isOpen && (
                <div style={{ borderTop: "1px solid var(--bc-border)", padding: "8px 10px" }}>
                  <SessionFlowChart events={sess.events} />
                  {sess.events
                    .slice()
                    .reverse()
                    .map((ev, i) => (
                      <div
                        key={ev.seq ?? i}
                        style={{ display: "flex", gap: 8, alignItems: "baseline", padding: "4px 0", borderBottom: "1px solid var(--bc-border)", fontSize: 12 }}
                      >
                        <span className="muted" style={{ fontSize: 10, minWidth: 34 }}>#{ev.seq ?? "—"}</span>
                        <span style={{ flex: 1, color: "var(--bc-text-dim)" }}>{ev.query}</span>
                        <span className="muted" style={{ fontSize: 11 }}>{humanizeIntent(ev.intent)}</span>
                        <span className="muted" style={{ fontSize: 11, minWidth: 38, textAlign: "right" }} title="How confident the AI was about this answer">
                          {ev.confidence != null ? `${Math.round(ev.confidence * 100)}%` : "—"}
                        </span>
                        <span
                          title={decisionMeaning(ev.decision)}
                          style={{ color: DECISION_COLOR[ev.decision] || "var(--bc-text-mute)", fontWeight: 600, fontSize: 11, minWidth: 84, textAlign: "right", cursor: "help" }}
                        >
                          {decisionLabel(ev.decision)}
                        </span>
                        {ev.from_cache && <span style={{ fontSize: 9, color: "var(--bc-accent)" }} title="Reused from a previous identical answer — faster &amp; cheaper">cache</span>}
                      </div>
                    ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
      )}
    </div>
  );
}
