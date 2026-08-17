"use client";

import { useEffect, useState } from "react";
import StateBadge from "@/components/StateBadge";

interface NameDetail {
  name: string;
  detail: string;
}

interface ModelCardData {
  title: string;
  sr_11_7_section: string;
  identity: {
    name: string;
    model_id: string;
    version: string;
    type: string;
    owner: string;
    lifecycle_stage: string;
  };
  runtime: {
    backend: string;
    backend_is_real: boolean;
    prompt_fingerprint: string;
    corpus_fingerprint: string;
    corpus_doc_count: number;
    dq_input_rules: number;
    dq_output_rules: number;
    guard_threshold: number;
  };
  intended_use: {
    purpose: string;
    users: string;
    in_scope: string;
    out_of_scope: string[];
  };
  architecture: NameDetail[];
  controls: NameDetail[];
  limitations: string[];
  governance: {
    owner: string;
    review_cadence: string;
    status: string;
    evidence: string;
  };
}

const BLOCK: React.CSSProperties = {
  background: "var(--bc-bg)",
  border: "1px solid var(--bc-surface)",
  borderRadius: 6,
  padding: "10px 12px",
};
const H: React.CSSProperties = {
  fontSize: 11,
  textTransform: "uppercase",
  letterSpacing: 0.5,
  color: "var(--bc-text-dim)",
  marginBottom: 6,
};
const KV: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 8,
  fontSize: 12,
  padding: "2px 0",
  color: "var(--bc-text)",
};
const ITEM: React.CSSProperties = {
  fontSize: 12,
  color: "var(--bc-text)",
  padding: "3px 0",
  borderTop: "1px solid var(--bc-border)",
};

function Kv({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div style={KV}>
      <span className="muted">{k}</span>
      <span style={{ textAlign: "right" }}>{children}</span>
    </div>
  );
}

export default function ModelCard() {
  const [data, setData] = useState<ModelCardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // Poll so the runtime fields (e.g. guard threshold from the Controls slider)
    // stay current even when this tab was mounted before the slider was moved.
    const load = () =>
      fetch("/api/model-card", { cache: "no-store" })
        .then(async (r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          const json = await r.json();
          if (!cancelled) {
            setData(json);
            setError(null);
          }
        })
        .catch((err: unknown) => {
          if (!cancelled) setError(err instanceof Error ? err.message : String(err));
        });
    load();
    const id = setInterval(() => { if (!document.hidden) load(); }, 15000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (error && !data) {
    return (
      <div className="card card--wide">
        <h2>Model Card</h2>
        <div className="empty error" role="alert">backend unreachable ({error})</div>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="card card--wide">
        <h2>Model Card</h2>
        <div className="empty">loading…</div>
      </div>
    );
  }

  const { identity: id, runtime: rt, intended_use: use, governance: gov } = data;

  return (
    <div className="card card--wide">
      <h2>
        Model Card
        <StateBadge feature="model-card" />
        <span className="card-subtitle" title={data.title}>
          Model inventory — SR 11-7 §{data.sr_11_7_section}
        </span>
      </h2>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
          gap: 10,
        }}
      >
        <section style={BLOCK}>
          <div style={H}>Identity</div>
          <Kv k="Name">
            <strong>{id.name}</strong>
          </Kv>
          <Kv k="Version">
            <strong>{id.version}</strong>
          </Kv>
          <Kv k="Type">{id.type}</Kv>
          <Kv k="Owner">{id.owner}</Kv>
          <Kv k="Stage">{id.lifecycle_stage}</Kv>
        </section>

        <section style={BLOCK}>
          <div style={H}>Fingerprints (runtime)</div>
          <Kv k="Backend">
            <code>
              {rt.backend} {rt.backend_is_real ? "(real model)" : "(canned)"}
            </code>
          </Kv>
          <Kv k="Prompt">
            <code>{rt.prompt_fingerprint}</code>
          </Kv>
          <Kv k="Corpus">
            <code>{rt.corpus_fingerprint}</code>
          </Kv>
          <Kv k="Reference docs">
            <strong>{rt.corpus_doc_count}</strong>
          </Kv>
          <Kv k="Quality checks">
            <strong>
              {rt.dq_input_rules} input · {rt.dq_output_rules} output
            </strong>
          </Kv>
          <Kv k="Guard threshold">
            <strong>{rt.guard_threshold.toFixed(2)}</strong>
          </Kv>
        </section>

        <section style={{ ...BLOCK, gridColumn: "1 / -1" }}>
          <div style={H}>Intended use</div>
          <div style={{ fontSize: 12, color: "var(--bc-text)", marginBottom: 6 }}>{use.purpose}</div>
          <Kv k="Users">{use.users}</Kv>
          <Kv k="In scope">{use.in_scope}</Kv>
          <div style={{ ...H, marginTop: 6, color: "var(--bc-reask-line)" }}>Out of scope</div>
          {use.out_of_scope.map((x, i) => (
            <div key={i} style={ITEM}>
              ✕ {x}
            </div>
          ))}
        </section>

        <section style={BLOCK}>
          <div style={H}>Architecture</div>
          {data.architecture.map((a, i) => (
            <div key={i} style={ITEM}>
              <strong style={{ color: "var(--bc-text)" }}>{a.name}</strong> — {a.detail}
            </div>
          ))}
        </section>

        <section style={BLOCK}>
          <div style={H}>Controls (governance)</div>
          {data.controls.map((c, i) => (
            <div key={i} style={ITEM}>
              <strong style={{ color: "var(--bc-pass-line)" }}>{c.name}</strong> — {c.detail}
            </div>
          ))}
        </section>

        <section style={{ ...BLOCK, gridColumn: "1 / -1" }}>
          <div style={H}>Known limitations</div>
          {data.limitations.map((x, i) => (
            <div key={i} style={ITEM}>
              ⚠ {x}
            </div>
          ))}
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 16,
              marginTop: 8,
              fontSize: 12,
              color: "var(--bc-text-dim)",
            }}
          >
            <span>
              Review: <strong style={{ color: "var(--bc-text)" }}>{gov.review_cadence}</strong>
            </span>
            <span>
              Status: <strong style={{ color: "var(--bc-text)" }}>{gov.status}</strong>
            </span>
          </div>
          <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 4 }}>{gov.evidence}</div>
        </section>
      </div>
    </div>
  );
}
