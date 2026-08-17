"use client";

import { useEffect, useState } from "react";
import StateBadge from "@/components/StateBadge";
import { decisionLabel } from "@/components/console/types";

interface IntentEntry {
  name: string;
  family: "banking" | "fraud" | "safety";
  agent: string;
  default_decision: string;
  description: string;
  samples: string[];
  count: number;
  percent: number;
}

interface IntentsPayload {
  intents: IntentEntry[];
  families: Record<string, number>;
  total_queries: number;
  catalog_size: number;
}

interface Props {
  refreshKey: number;
}

const FAMILY_COLOR: Record<string, string> = {
  banking: "#10b981",
  fraud: "#f97316",
  safety: "#ef4444",
};

// Display-only PT labels; the raw keys ('all'/'banking'/...) stay as filter state.
const FAMILY_LABEL: Record<string, string> = {
  all: "all",
  banking: "banking",
  fraud: "fraud",
  safety: "safety",
};

// PASSTHROUGH/FLAG/REASK/ESCALATE map to plain words via the shared decisionLabel
// (matches the main decision badge); the "by-confidence" descriptor is localized here.
const DECISION_LABEL: Record<string, string> = {
  "by-confidence": "by confidence",
};

export default function IntentsPanel({ refreshKey }: Props) {
  const [data, setData] = useState<IntentsPayload | null>(null);
  const [filter, setFilter] = useState<"all" | "banking" | "fraud" | "safety">("all");
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await fetch("/api/intents", { cache: "no-store" });
        if (!r.ok) return;
        const j = await r.json();
        if (!cancelled) setData(j);
      } catch {
        /* swallow; panel just stays stale */
      }
    };
    tick();
    const id = setInterval(() => { if (!document.hidden) tick(); }, 15000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [refreshKey]);

  if (!data) {
    return (
      <div className="card card--wide">
        <h2>Intent Catalog</h2>
        <div className="empty">loading intent catalog...</div>
      </div>
    );
  }

  const shown = data.intents.filter(
    (i) => filter === "all" || i.family === filter,
  );

  return (
    <div className="card card--wide">
      <h2>
        Intent Catalog ({data.catalog_size})
        <StateBadge feature="intent-catalog" />
        <span
          className="muted"
          style={{ fontWeight: 400, fontSize: 11, marginLeft: 8, textTransform: "none", letterSpacing: 0 }}
        >
          {data.total_queries} queries since service start
        </span>
      </h2>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
        {(["all", "banking", "fraud", "safety"] as const).map((f) => {
          const active = f === filter;
          const fcount = f === "all" ? data.intents.length : data.intents.filter((i) => i.family === f).length;
          return (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              style={{
                padding: "4px 10px",
                fontSize: 11,
                background: active ? (f === "all" ? "var(--bc-border)" : FAMILY_COLOR[f]) : "var(--bc-bg)",
                color: active ? "#fff" : "var(--bc-text-dim)",
                border: `1px solid ${active ? "transparent" : "var(--bc-surface)"}`,
                borderRadius: 4,
                cursor: "pointer",
                textTransform: "uppercase",
                letterSpacing: 0.5,
              }}
            >
              {FAMILY_LABEL[f] ?? f} · {fcount}
            </button>
          );
        })}
      </div>
      <div className="intent-grid">
        {shown.map((i) => {
          const isOpen = expanded === i.name + ":" + i.family;
          const key = i.name + ":" + i.family;
          return (
            <div
              key={key}
              style={{
                padding: "6px 8px",
                background: "var(--bc-bg)",
                border: "1px solid var(--bc-surface)",
                borderRadius: 4,
                fontSize: 12,
                // an open row spans the whole grid so its detail stays readable
                gridColumn: isOpen ? "1 / -1" : undefined,
              }}
            >
              <button
                type="button"
                onClick={() => setExpanded(isOpen ? null : key)}
                style={{
                  width: "100%",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  background: "transparent",
                  border: "none",
                  color: "var(--bc-text)",
                  cursor: "pointer",
                  padding: 0,
                  textAlign: "left",
                }}
              >
                <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <span
                    style={{
                      width: 6,
                      height: 6,
                      borderRadius: "50%",
                      background: FAMILY_COLOR[i.family],
                      display: "inline-block",
                    }}
                  />
                  <strong>{i.name}</strong>
                  <span className="muted" style={{ fontSize: 11 }}>→ {i.agent}</span>
                  <span
                    style={{
                      fontSize: 10,
                      padding: "1px 6px",
                      borderRadius: 3,
                      background:
                        i.default_decision === "ESCALATE"
                          ? "var(--bc-block)"
                          : i.default_decision === "REASK"
                          ? "var(--bc-reask)"
                          : i.default_decision === "FLAG"
                          ? "var(--bc-flag)"
                          : "var(--bc-pass)",
                      color: "var(--bc-text)",
                      letterSpacing: 0.5,
                    }}
                  >
                    {DECISION_LABEL[i.default_decision] ?? decisionLabel(i.default_decision)}
                  </span>
                </span>
                <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  {i.count > 0 && (
                    <span className="muted" style={{ fontSize: 11 }}>
                      {i.count} ({i.percent}%)
                    </span>
                  )}
                  <span className="muted" style={{ fontSize: 11 }}>{isOpen ? "▾" : "▸"}</span>
                </span>
              </button>
              {isOpen && (
                <div style={{ marginTop: 6, paddingTop: 6, borderTop: "1px solid var(--bc-surface)" }}>
                  <div style={{ color: "#cbd5e1", marginBottom: 6 }}>{i.description}</div>
                  {i.samples.length > 0 && (
                    <div>
                      <div className="muted" style={{ fontSize: 10, marginBottom: 3, textTransform: "uppercase", letterSpacing: 0.5 }}>
                        sample queries
                      </div>
                      {i.samples.map((s, idx) => (
                        <div
                          key={idx}
                          style={{
                            fontFamily: "monospace",
                            fontSize: 11,
                            color: "var(--bc-text-dim)",
                            padding: "2px 6px",
                            background: "#020617",
                            borderRadius: 3,
                            marginBottom: 2,
                          }}
                        >
                          “{s}”
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
