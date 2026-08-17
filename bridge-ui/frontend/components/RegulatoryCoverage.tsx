"use client";

import { useEffect, useState } from "react";
import StateBadge from "@/components/StateBadge";

interface Control {
  control_id: string;
  control_title: string;
  description: string;
}
interface Framework {
  key: string;
  title: string;
  jurisdiction: string;
  n_controls: number;
  controls: Control[];
}
interface CoverageData {
  frameworks: Framework[];
  n_frameworks: number;
  n_jurisdictions: number;
  n_controls_total: number;
  coverage_note?: string;
}

function Stat({ value, label }: { value: number; label: string }) {
  return (
    <div style={{ background: "var(--bc-bg)", border: "1px solid var(--bc-surface)", borderRadius: 6, padding: "8px 14px" }}>
      <div style={{ fontSize: 20, fontWeight: 700, color: "var(--bc-text)" }}>{value}</div>
      <div style={{ fontSize: 10, color: "var(--bc-text-dim)", textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</div>
    </div>
  );
}

export default function RegulatoryCoverage() {
  const [data, setData] = useState<CoverageData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | undefined;
    const attempt = () => {
      fetch("/api/compliance/frameworks", { cache: "no-store" })
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
        <h2>Regulatory Coverage</h2>
        <div className="empty error" role="alert">backend unreachable ({error})</div>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="card card--wide">
        <h2>Regulatory Coverage</h2>
        <div className="empty">loading…</div>
      </div>
    );
  }

  return (
    <div className="card card--wide">
      <h2>
        Regulatory Coverage
        <StateBadge feature="regulatory-coverage" />
        <span className="card-subtitle">
          Control crosswalk across multiple frameworks (lub)
        </span>
      </h2>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
        <Stat value={data.n_frameworks} label="frameworks" />
        <Stat value={data.n_jurisdictions} label="jurisdictions" />
        <Stat value={data.n_controls_total} label="mapped controls" />
      </div>
      {data.coverage_note && (
        <div style={{ fontSize: 11, color: "var(--bc-flag-line)", marginBottom: 8 }}>
          ⚠ {data.coverage_note}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 8 }}>
        {data.frameworks.map((fw) => {
          const isOpen = open === fw.key;
          return (
            <div
              key={fw.key}
              style={{
                background: "var(--bc-bg)",
                border: "1px solid var(--bc-surface)",
                borderRadius: 6,
                padding: "8px 10px",
                gridColumn: isOpen ? "1 / -1" : undefined,
              }}
            >
              <button
                type="button"
                onClick={() => setOpen(isOpen ? null : fw.key)}
                style={{
                  width: "100%",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: 8,
                  background: "transparent",
                  border: "none",
                  color: "var(--bc-text)",
                  cursor: "pointer",
                  padding: 0,
                  textAlign: "left",
                }}
                title={fw.title}
              >
                <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  <span style={{ fontSize: 10, color: "var(--bc-info-line)", textTransform: "uppercase", letterSpacing: 0.4 }}>
                    {fw.jurisdiction}
                  </span>
                  <strong style={{ fontSize: 12 }}>{fw.title}</strong>
                </span>
                <span style={{ display: "flex", gap: 6, alignItems: "center", whiteSpace: "nowrap" }}>
                  <span
                    style={{
                      fontSize: 11,
                      background: "var(--bc-surface)",
                      borderRadius: 10,
                      padding: "1px 8px",
                      color: "#cbd5e1",
                    }}
                  >
                    {fw.n_controls} controls
                  </span>
                  <span className="muted" style={{ fontSize: 11 }}>{isOpen ? "▾" : "▸"}</span>
                </span>
              </button>
              {isOpen && (
                <div style={{ marginTop: 8 }}>
                  {fw.controls.map((c) => (
                    <div
                      key={c.control_id}
                      style={{ fontSize: 11, color: "#cbd5e1", padding: "4px 0", borderTop: "1px solid #131c2e" }}
                    >
                      <code style={{ fontSize: 10, color: "var(--bc-text-dim)" }}>{c.control_id}</code>{" "}
                      <strong>{c.control_title}</strong>
                      <div className="muted">{c.description}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 10 }}>
        Controls are sourced from the real crosswalk in the <code>lub</code> library; the
        “Compliance SR 11-7” panel below details one of them (pillars + metrics).
      </div>
    </div>
  );
}
