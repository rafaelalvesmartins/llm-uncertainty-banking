"use client";

import { useEffect, useState } from "react";
import StateBadge from "@/components/StateBadge";

interface Signature {
  algorithm: string;
  key_id: string;
  public_key: string;
  signature: string;
  signed_payload: string;
  note: string;
}
interface Pkg {
  title: string;
  owner: string;
  generated_at: string;
  content_sha256: string;
  signature: Signature;
  frameworks_covered: number;
  controls_covered: number;
  note: string;
}

function Kv({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div style={{ background: "var(--bc-bg)", border: "1px solid var(--bc-surface)", borderRadius: 6, padding: "6px 10px" }}>
      <div style={{ fontSize: 10, color: "var(--bc-text-dim)", textTransform: "uppercase", letterSpacing: 0.4 }}>{k}</div>
      <div style={{ fontSize: 13, color: "var(--bc-text)", marginTop: 2, wordBreak: "break-all" }}>{children}</div>
    </div>
  );
}

export default function EvidencePackage() {
  const [meta, setMeta] = useState<Pkg | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [verifyResult, setVerifyResult] = useState<{ valid: boolean; tampered: boolean } | null>(null);

  useEffect(() => {
    // Poll until the first success, then stop — self-heal under the dashboard's
    // concurrent load like the other polling panels do.
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | undefined;
    const attempt = () => {
      fetch("/api/evidence/package", { cache: "no-store" })
        .then(async (r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then((j) => {
          if (cancelled) return;
          setMeta(j);
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

  async function download() {
    setBusy(true);
    try {
      // re-fetch so the exported package reflects the current runtime state
      const r = await fetch("/api/evidence/package", { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const full = await r.json();
      setMeta(full);
      setError(null);
      const blob = new Blob([JSON.stringify(full, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `bridge-model-risk-evidence-${String(full.content_sha256).slice(0, 12)}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  // Download the machine-readable OSCAL 1.1.2 component-definition — the GRC-
  // ingestible envelope built from the latest real benchmark run.
  async function downloadOscal() {
    setBusy(true);
    try {
      const r = await fetch("/api/evidence/oscal", { cache: "no-store" });
      if (!r.ok) {
        const j = await r.json().catch(() => null);
        setError(j?.detail || j?.error || `OSCAL export failed (HTTP ${r.status})`);
        return;
      }
      const text = await r.text();
      const blob = new Blob([text], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "lub-oscal-component-definition.json";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function verify(tamper: boolean) {
    if (!meta) return;
    setBusy(true);
    setVerifyResult(null);
    try {
      const hash = tamper
        ? (meta.content_sha256[0] === "0" ? "1" : "0") + meta.content_sha256.slice(1)
        : meta.content_sha256;
      const r = await fetch("/api/evidence/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content_sha256: hash,
          generated_at: meta.generated_at,
          signature: meta.signature.signature,
          public_key: meta.signature.public_key,
        }),
        cache: "no-store",
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = await r.json();
      setVerifyResult({ valid: j.valid, tampered: tamper });
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (error) {
    return (
      <div className="card card--wide">
        <h2>Evidence Package</h2>
        <div className="empty error" role="alert">backend unreachable ({error})</div>
      </div>
    );
  }
  if (!meta) {
    return (
      <div className="card card--wide">
        <h2>Evidence Package</h2>
        <div className="empty">loading…</div>
      </div>
    );
  }

  return (
    <div className="card card--wide">
      <h2>
        Evidence Package
        <StateBadge feature="evidence-package" />
        <span className="card-subtitle">Archivable model-risk record — SR 11-7 effective challenge</span>
      </h2>

      <div style={{ fontSize: 12, color: "var(--bc-text-dim)", marginBottom: 8 }}>
        A cryptographically signed archive of all model-risk evidence, ready to share with regulators.
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", marginBottom: 10 }}>
        <button
          type="button"
          onClick={download}
          disabled={busy}
          style={{
            background: "var(--bc-surface)",
            border: "1px solid var(--bc-border)",
            borderRadius: 6,
            padding: "7px 16px",
            color: "var(--bc-text)",
            cursor: busy ? "default" : "pointer",
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          {busy ? "generating…" : "⬇ Export package (.json)"}
        </button>
        <button
          type="button"
          onClick={() => window.open("/evidence-report", "_blank", "noopener")}
          title="Open the 2-page executive evidence pack, formatted to save as PDF — the leave-behind to forward to Risk / the CRO."
          style={{
            background: "transparent",
            border: "1px solid var(--bc-border)",
            borderRadius: 6,
            padding: "7px 16px",
            color: "var(--bc-text)",
            cursor: "pointer",
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          ⬇ Download PDF (2-page)
        </button>
        <button
          type="button"
          onClick={downloadOscal}
          disabled={busy}
          title="Download the machine-readable OSCAL 1.1.2 component-definition (built from the latest real benchmark run) — the format a GRC tool ingests."
          style={{
            background: "transparent",
            border: "1px solid var(--bc-border)",
            borderRadius: 6,
            padding: "7px 16px",
            color: "var(--bc-text)",
            cursor: busy ? "default" : "pointer",
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          ⬇ OSCAL (.json)
        </button>
        <span className="muted" style={{ fontSize: 12 }}>
          {meta.frameworks_covered} frameworks · {meta.controls_covered} controls · Model Card + calibration + crosswalk + SR 11-7
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 8 }}>
        <Kv k="Owner">{meta.owner}</Kv>
        <Kv k="Generated at">{meta.generated_at}</Kv>
        <Kv k="Content hash (sha256)">
          <code style={{ fontSize: 11 }}>{meta.content_sha256.slice(0, 32)}…</code>
        </Kv>
        <Kv k={`Signature ${meta.signature.algorithm} · key ${meta.signature.key_id}`}>
          <code style={{ fontSize: 11 }}>{meta.signature.signature.slice(0, 32)}…</code>
        </Kv>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", marginTop: 10 }}>
        <button
          type="button"
          onClick={() => verify(false)}
          disabled={busy}
          style={{ background: "var(--bc-surface)", border: "1px solid var(--bc-border)", borderRadius: 6, padding: "5px 12px", color: "var(--bc-text)", cursor: busy ? "default" : "pointer", fontSize: 12 }}
        >
          verify signature
        </button>
        <button
          type="button"
          onClick={() => verify(true)}
          disabled={busy}
          title="Safe — mutates one entry in memory, then restores it. Shows that any change breaks the signature."
          style={{ background: "transparent", border: "1px solid var(--bc-border)", borderRadius: 6, padding: "5px 12px", color: "var(--bc-text-dim)", cursor: busy ? "default" : "pointer", fontSize: 12 }}
        >
          [Demo] Tamper test
        </button>
        <span className="muted" style={{ fontSize: 11 }}>
          Safe — mutates one entry in memory, then restores it.
        </span>
        {verifyResult && (
          <span style={{ fontSize: 13, fontWeight: 600, color: verifyResult.valid ? "var(--bc-pass-line)" : "var(--bc-block-line)" }}>
            {verifyResult.valid
              ? "✓ signature valid"
              : verifyResult.tampered
                ? "✗ tampered — verification failed (expected)"
                : "✗ signature invalid"}
          </span>
        )}
      </div>

      <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 10 }}>
        <strong style={{ color: "var(--bc-text-dim)" }}>Next steps after export:</strong> download the file → store it
        securely → share it with Risk / Compliance → keep a copy in your audit trail (the permanent,
        time-ordered record of model-risk evidence).
      </div>

      <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 8 }}>{meta.note}</div>
    </div>
  );
}
