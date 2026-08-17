"use client";

import { useEffect, useState } from "react";
import StateBadge from "@/components/StateBadge";

interface Agent {
  id: string;
  name: string;
  domain: string;
  owner: string;
  risk_tier: "alto" | "médio" | "baixo";
  lifecycle: string;
  ece: number | null;
  cost_month_brl: number | null;
  last_review: string;
  frameworks: string[];
  live?: boolean;
}
interface FleetData {
  agents: Agent[];
  n_agents: number;
  n_production: number;
  n_high_risk: number;
  cost_month_total_brl: number;
  n_live: number;
}

const RISK_COLOR: Record<string, string> = { alto: "var(--bc-block-line)", médio: "var(--bc-reask-line)", baixo: "var(--bc-pass-line)" };
// The /api/fleet contract emits PT risk tiers; render English labels without
// changing the API values (RISK_COLOR stays keyed on the raw tier).
const RISK_LABEL: Record<string, string> = { alto: "High", médio: "Medium", baixo: "Low" };
// Lifecycle values also stay PT in the /api/fleet contract (counted + asserted
// server-side); show English labels here without changing the API values.
const LIFECYCLE_LABEL: Record<string, string> = {
  produção: "Production",
  homologação: "Staging",
  desenvolvimento: "Development",
  demo: "Demo",
};

function Stat({ value, label }: { value: string | number; label: string }) {
  return (
    <div style={{ background: "var(--bc-bg)", border: "1px solid var(--bc-surface)", borderRadius: 6, padding: "8px 14px" }}>
      <div style={{ fontSize: 18, fontWeight: 700, color: "var(--bc-text)" }}>{value}</div>
      <div style={{ fontSize: 10, color: "var(--bc-text-dim)", textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</div>
    </div>
  );
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
const TD: React.CSSProperties = { fontSize: 12, color: "var(--bc-text)", padding: "6px 8px", borderBottom: "1px solid var(--bc-border)", verticalAlign: "top" };

export default function FleetInventory() {
  const [data, setData] = useState<FleetData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | undefined;
    const attempt = () => {
      fetch("/api/fleet", { cache: "no-store" })
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
        <h2>Fleet Inventory</h2>
        <div className="empty error" role="alert">backend unreachable ({error})</div>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="card card--wide">
        <h2>Fleet Inventory</h2>
        <div className="empty">loading…</div>
      </div>
    );
  }

  const brl = (v: number | null) =>
    v === null ? "—" : `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;

  return (
    <div className="card card--wide">
      <h2>
        Fleet Inventory
        <StateBadge feature="fleet-inventory" />
        <span className="card-subtitle">Governed agent portfolio</span>
      </h2>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
        <Stat value={data.n_agents} label="agents" />
        <Stat value={data.n_production} label="in production" />
        <Stat value={data.n_high_risk} label="high risk" />
        <Stat value={brl(data.cost_month_total_brl)} label="cost/month" />
      </div>

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={TH}>Agent</th>
              <th style={TH}>Owner</th>
              <th style={TH}>Risk</th>
              <th style={TH}>Lifecycle</th>
              <th style={TH}>ECE</th>
              <th style={TH}>Cost/month</th>
              <th style={TH}>Review</th>
              <th style={TH}>Frameworks</th>
            </tr>
          </thead>
          <tbody>
            {data.agents.map((a) => (
              <tr key={a.id} style={a.live ? { background: "var(--bc-bg)" } : undefined}>
                <td style={TD}>
                  <strong>{a.name}</strong>
                  {a.live ? (
                    <span className="state-badge live" style={{ marginLeft: 6, fontSize: 9 }}>LIVE</span>
                  ) : (
                    <span className="state-badge mock" style={{ marginLeft: 6, fontSize: 9 }}>MOCK</span>
                  )}
                  <div className="muted" style={{ fontSize: 11 }}>{a.domain}</div>
                </td>
                <td style={{ ...TD, color: "var(--bc-text)" }}>{a.owner}</td>
                <td style={TD}>
                  <span style={{ color: RISK_COLOR[a.risk_tier] || "var(--bc-text-dim)", fontWeight: 600 }}>{RISK_LABEL[a.risk_tier] ?? a.risk_tier}</span>
                </td>
                <td style={{ ...TD, color: "var(--bc-text)" }}>{LIFECYCLE_LABEL[a.lifecycle] ?? a.lifecycle}</td>
                <td style={TD}>{a.ece === null ? "—" : a.ece.toFixed(3)}</td>
                <td style={{ ...TD, color: "var(--bc-text)" }}>{brl(a.cost_month_brl)}</td>
                <td style={{ ...TD, color: "var(--bc-text-dim)", fontSize: 11 }}>{a.last_review}</td>
                <td style={TD}>
                  <span style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                    {a.frameworks.map((f) => (
                      <span key={f} style={{ fontSize: 9, background: "var(--bc-surface)", color: "var(--bc-text)", borderRadius: 3, padding: "1px 5px" }}>
                        {f}
                      </span>
                    ))}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 10 }}>
        Only <strong>Bridge Banking AI</strong> (LIVE) is this deployment — real version and ECE. The
        remaining entries are <strong>seeded (MOCK)</strong> agents to illustrate the at-scale governance
        that a fleet inventory covers.
      </div>
    </div>
  );
}
