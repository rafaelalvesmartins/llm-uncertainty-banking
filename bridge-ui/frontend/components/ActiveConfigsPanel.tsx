"use client";

import { useEffect, useRef, useState } from "react";
import StateBadge from "@/components/StateBadge";

// GET /api/governance/active-configs — the live system-of-record an approved+applied
// governed change actually wrote (masked, never raw secrets). This is the missing
// VIEW that lets an operator see the result of an `apply` on this page: for
// provider/channel kinds it is what /query reflects on the next request; for
// intent/dq_rule/agent/rag_doc it is recorded here as governed evidence but is not
// yet read by the runtime (see the note on the Policies tab).
interface ActiveConfig {
  domain: string;
  name: string;
  config: Record<string, unknown>;
  enabled: number;
  updated_by?: string;
  updated_at?: number;
}
interface Payload {
  n: number;
  configs: ActiveConfig[];
}

function fmtTs(ts: number | undefined): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function compactJson(o: Record<string, unknown>): string {
  try {
    return JSON.stringify(o);
  } catch {
    return String(o);
  }
}

/** Render a (masked) config as readable "key: value · key: value" instead of raw JSON.
 *  Arrays are joined; nested objects (masked secrets) show as ••••; the exact JSON stays
 *  available on the cell's hover tooltip for an auditor. */
function readableConfig(o: Record<string, unknown>): string {
  const fmt = (v: unknown): string => {
    if (Array.isArray(v)) return v.map(String).join(", ");
    if (v && typeof v === "object") return "••••";
    return String(v);
  };
  const parts = Object.entries(o).map(([k, v]) => `${k}: ${fmt(v)}`);
  return parts.length ? parts.join(" · ") : "—";
}

const cell: React.CSSProperties = { padding: "6px 8px", verticalAlign: "top" };
const cellH: React.CSSProperties = { padding: "6px 8px", fontWeight: 600 };

export default function ActiveConfigsPanel() {
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  async function load() {
    try {
      const r = await fetch("/api/governance/active-configs", { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = (await r.json()) as Payload;
      if (mounted.current) {
        setData(j);
        setError(null);
      }
    } catch (e) {
      // Keep the last-good table on a transient error rather than blanking it.
      if (mounted.current) setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    mounted.current = true;
    load();
    const id = setInterval(() => {
      if (!document.hidden) load();
    }, 15000);
    return () => {
      mounted.current = false;
      clearInterval(id);
    };
  }, []);

  if (error && !data) {
    return (
      <div className="card card--wide">
        <h2>
          Active configuration <StateBadge feature="governed-changes" />
        </h2>
        <div className="empty error" role="alert">backend unreachable ({error})</div>
      </div>
    );
  }

  return (
    <div className="card card--wide">
      <h2>
        Active settings
        <StateBadge feature="governed-changes" />
      </h2>
      <p className="muted" style={{ fontSize: 12, marginTop: 0, lineHeight: 1.5 }}>
        The live, masked record that an <strong>approved + applied</strong> governed change wrote. Provider / channel
        rows are what <code>/query</code> reflects on the next request; intent / DQ-rule / agent / rag_doc rows are
        recorded here as governed evidence but are not yet read by the runtime.
        {error && <span style={{ color: "var(--bc-flag-line, #f59e0b)", marginLeft: 6 }}>· refresh failed — showing last good</span>}
      </p>
      {!data || data.n === 0 ? (
        <div className="empty">
          No active configuration yet — approve &amp; apply a governed change above to populate this.
        </div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr style={{ textAlign: "left", color: "var(--bc-text-mute, #94a3b8)" }}>
                <th style={cellH}>Domain</th>
                <th style={cellH}>Name</th>
                <th style={cellH}>Config (masked)</th>
                <th style={cellH}>Enabled</th>
                <th style={cellH}>Updated by</th>
                <th style={cellH}>Updated</th>
              </tr>
            </thead>
            <tbody>
              {data.configs.map((c) => (
                <tr key={`${c.domain}/${c.name}`} style={{ borderTop: "1px solid var(--bc-border, #1f2937)" }}>
                  <td style={cell}>
                    <span className="state-badge">{c.domain}</span>
                  </td>
                  <td style={cell}>
                    <strong>{c.name}</strong>
                  </td>
                  <td
                    style={{
                      ...cell,
                      maxWidth: 360,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                    title={compactJson(c.config)}
                  >
                    {readableConfig(c.config)}
                  </td>
                  <td style={cell}>{c.enabled ? "yes" : "no"}</td>
                  <td style={cell}>{c.updated_by || "—"}</td>
                  <td style={cell}>{fmtTs(c.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
