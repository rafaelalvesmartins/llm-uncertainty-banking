"use client";

import { useEffect, useState } from "react";
import StateBadge from "@/components/StateBadge";

interface Provider {
  id: string;
  name: string;
  kind: string;
  status: string;
  live?: boolean;
  reachable?: boolean;
  models?: string[];
  configured_model?: string | null;
  model_loaded?: boolean | null;
  endpoint?: string;
  note: string;
}
interface Integrations {
  active_backend: string;
  n_providers: number;
  n_available: number;
  providers: Provider[];
  switch_note: string;
  checked_at: string;
}

const STATUS_COLOR: Record<string, string> = {
  active: "var(--bc-pass-line)",
  available: "var(--bc-info-line)",
  reachable: "var(--bc-info-line)",
  degraded: "var(--bc-flag-line)",
  unreachable: "var(--bc-block-line)",
  not_configured: "var(--bc-text-mute)",
};

export default function IntegrationsPanel() {
  const [data, setData] = useState<Integrations | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | undefined;
    const attempt = () => {
      fetch("/api/integrations", { cache: "no-store" })
        .then(async (r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then((j) => {
          if (cancelled) return;
          setData(j);
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

  async function recheck() {
    setBusy(true);
    try {
      const r = await fetch("/api/integrations?refresh=1", { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData(await r.json());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (error && !data) {
    return (
      <div className="card card--wide">
        <h2>Integrations</h2>
        <div className="empty error" role="alert">backend unreachable ({error})</div>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="card card--wide">
        <h2>Integrations</h2>
        <div className="empty">loading…</div>
      </div>
    );
  }

  return (
    <div className="card card--wide">
      <h2>
        Integrations
        <StateBadge feature="integrations" />
        <span className="card-subtitle">LLM providers — configured via server env vars, never a key in the UI</span>
      </h2>

      <div style={{ fontSize: 12, color: "var(--bc-text-dim)", marginBottom: 12, lineHeight: 1.5 }}>
        Read-only view. To <strong>add, edit, or remove</strong> a connection — including
        channels like WhatsApp — under governance (propose → approve → apply),{" "}
        <a href="/console#connections" style={{ color: "var(--bc-info-line)", textDecoration: "underline" }}>
          open Console → Connections
        </a>.
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", marginBottom: 12 }}>
        <span style={{ fontSize: 13, color: "var(--bc-text)" }}>
          active backend: <strong style={{ color: "var(--bc-pass-line)" }} title={data.active_backend}>{data.active_backend === "fake" ? "Demo (fixed answers)" : data.active_backend}</strong>
        </span>
        <span className="muted" style={{ fontSize: 12 }}>{data.n_available}/{data.n_providers} available</span>
        {error && <span style={{ fontSize: 11, color: "var(--bc-flag-line)" }}>⚠ last refresh failed ({error}) — showing cached</span>}
        <button
          type="button"
          onClick={recheck}
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
          {busy ? "…" : "↻ recheck"}
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 8 }}>
        {data.providers.map((p) => (
          <div
            key={p.id}
            style={{
              background: "var(--bc-bg)",
              border: `1px solid ${p.live ? "var(--bc-pass)" : "var(--bc-surface)"}`,
              borderRadius: 6,
              padding: "8px 10px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
              <strong style={{ fontSize: 13, color: "var(--bc-text)" }}>{p.name}</strong>
              <span
                style={{
                  fontSize: 10,
                  textTransform: "uppercase",
                  letterSpacing: 0.4,
                  color: STATUS_COLOR[p.status] || "var(--bc-text-dim)",
                  border: `1px solid ${STATUS_COLOR[p.status] || "var(--bc-border)"}`,
                  borderRadius: 10,
                  padding: "1px 8px",
                }}
              >
                {p.status.replace(/_/g, " ")}
              </span>
            </div>
            <div className="muted" style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 0.4, marginTop: 2 }}>
              {p.kind}
            </div>
            {p.id === "ollama" && (
              <div style={{ fontSize: 11, color: "var(--bc-text-dim)", marginTop: 4 }}>
                {p.reachable ? `${p.models?.length ?? 0} models loaded` : "unreachable"}
                {p.configured_model ? (
                  <>
                    {" · "}configured: <code style={{ fontSize: 10 }}>{p.configured_model}</code>{" "}
                    {p.model_loaded === false ? "(not loaded)" : p.model_loaded ? "✓" : ""}
                  </>
                ) : null}
              </div>
            )}
            <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 4 }}>{p.note}</div>
          </div>
        ))}
      </div>

      <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 10 }}>
        {data.switch_note} <span className="muted">· checked {data.checked_at}</span>
      </div>
    </div>
  );
}
