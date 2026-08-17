"use client";

// Print-optimized 2-page Model-Risk Evidence Pack — the leave-behind a champion
// forwards to their CRO. Renders the SIGNED /evidence/package (one source, covered
// by the content hash) as a clean A4 document; the browser's "Save as PDF" is the
// export path (no PDF dependency). Opened in a new tab from the EvidencePackage panel.

import { Fragment, useEffect, useState } from "react";

interface Signature { algorithm: string; key_id: string; public_key: string; signature: string; note: string }
interface Framework { key: string; title: string; jurisdiction: string; n_controls: number }
interface Calibration {
  title?: string; accuracy?: number; ece?: number; brier?: number; auroc?: number;
  sharpness?: number; n?: number; source?: string; honesty?: string;
}
interface Pkg {
  title: string; owner: string; generated_at: string; content_sha256: string;
  signature: Signature; frameworks_covered: number; controls_covered: number; note: string;
  content: {
    model_card: Record<string, unknown>;
    calibration: Calibration;
    regulatory_coverage: { frameworks: Framework[]; n_frameworks: number; n_jurisdictions?: number; n_controls_total: number };
    sr_11_7: { title?: string; pillars?: unknown };
  };
}

const num = (v: number | undefined, d = 3) => (typeof v === "number" ? v.toFixed(d) : "—");

function scalarRows(obj: unknown): [string, string][] {
  if (!obj || typeof obj !== "object") return [];
  return Object.entries(obj as Record<string, unknown>)
    .filter(([, v]) => v != null && (typeof v === "string" || typeof v === "number" || typeof v === "boolean"))
    .map(([k, v]) => [k.replace(/_/g, " "), String(v)]);
}

export default function EvidenceReport() {
  const [pkg, setPkg] = useState<Pkg | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/evidence/package", { cache: "no-store" })
      .then(async (r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(setPkg)
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, []);

  if (err) return <div style={{ padding: 40, fontFamily: "system-ui" }}>Could not load the evidence package: {err}. Is the backend running on :8000?</div>;
  if (!pkg) return <div style={{ padding: 40, fontFamily: "system-ui" }}>Assembling the signed evidence package…</div>;

  const c = pkg.content;
  const cal = c.calibration || {};
  const mc = c.model_card || {};
  const idRows = scalarRows(mc.identity).slice(0, 6);
  const rtRows = scalarRows(mc.runtime).slice(0, 6);
  const frameworks = c.regulatory_coverage?.frameworks || [];
  const pillars = Array.isArray(c.sr_11_7?.pillars) ? (c.sr_11_7.pillars as Record<string, unknown>[]) : [];
  const hash8 = pkg.content_sha256.slice(0, 12);

  return (
    <>
      <style>{`
        @page { size: A4; margin: 16mm 15mm; }
        html, body { background: #eceef1; }
        * { box-sizing: border-box; }
        .er-toolbar { position: sticky; top: 0; display: flex; gap: 10px; align-items: center;
          justify-content: center; padding: 12px; background: #1e293b; color: #e2e8f0;
          font-family: system-ui, sans-serif; font-size: 13px; }
        .er-toolbar button { background: #2563eb; color: #fff; border: 0; border-radius: 6px;
          padding: 8px 18px; font-size: 13px; font-weight: 600; cursor: pointer; }
        .er-toolbar button.ghost { background: transparent; border: 1px solid #475569; color: #cbd5e1; }
        .page { width: 210mm; min-height: 297mm; margin: 16px auto; background: #fff; color: #14181f;
          padding: 16mm 15mm; font-family: Georgia, "Times New Roman", serif; font-size: 10.5pt;
          line-height: 1.5; box-shadow: 0 2px 18px rgba(0,0,0,.15); }
        .page + .page { page-break-before: always; }
        .doc-h { border-bottom: 2px solid #14181f; padding-bottom: 10px; margin-bottom: 16px; }
        .doc-h .eyebrow { font-family: ui-sans-serif, system-ui, sans-serif; font-size: 8pt;
          letter-spacing: .16em; text-transform: uppercase; color: #5b6472; font-weight: 700; }
        .doc-h h1 { font-size: 18pt; margin: 3px 0 4px; letter-spacing: -.01em; }
        .doc-h .meta { font-family: ui-sans-serif, system-ui, sans-serif; font-size: 8.5pt; color: #5b6472; }
        h2 { font-family: ui-sans-serif, system-ui, sans-serif; font-size: 10.5pt; letter-spacing: .02em;
          text-transform: uppercase; color: #0b3a45; border-bottom: 1px solid #cfd6de;
          padding-bottom: 4px; margin: 18px 0 9px; }
        .kv { display: grid; grid-template-columns: 40mm 1fr; gap: 3px 10px; font-size: 9.5pt; }
        .kv dt { font-family: ui-sans-serif, system-ui, sans-serif; color: #5b6472; text-transform: capitalize; }
        .kv dd { margin: 0; word-break: break-word; }
        .mono { font-family: ui-monospace, "Courier New", monospace; font-size: 8.5pt; word-break: break-all; }
        .metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 6px 0; }
        .metric { border: 1px solid #cfd6de; border-radius: 5px; padding: 8px 10px; }
        .metric .m-v { font-family: ui-sans-serif, system-ui, sans-serif; font-size: 15pt; font-weight: 700;
          font-variant-numeric: tabular-nums; }
        .metric .m-l { font-family: ui-sans-serif, system-ui, sans-serif; font-size: 7.5pt; color: #5b6472;
          text-transform: uppercase; letter-spacing: .05em; margin-top: 2px; }
        table { width: 100%; border-collapse: collapse; font-size: 9pt; margin-top: 4px; }
        th { font-family: ui-sans-serif, system-ui, sans-serif; text-align: left; font-size: 7.5pt;
          text-transform: uppercase; letter-spacing: .05em; color: #5b6472; border-bottom: 1.5px solid #14181f; padding: 5px 6px; }
        td { padding: 5px 6px; border-bottom: 1px solid #e0e5ea; vertical-align: top; }
        .integrity { background: #f4f7f9; border: 1px solid #cfd6de; border-radius: 6px; padding: 11px 13px; }
        .seal { font-family: ui-sans-serif, system-ui, sans-serif; font-size: 8.5pt; color: #0b3a45; font-weight: 700; }
        .note { font-family: ui-sans-serif, system-ui, sans-serif; font-size: 8pt; color: #5b6472;
          line-height: 1.5; margin-top: 6px; }
        .foot { margin-top: 20px; padding-top: 8px; border-top: 1px solid #cfd6de;
          font-family: ui-sans-serif, system-ui, sans-serif; font-size: 7.5pt; color: #5b6472; }
        @media print { .er-toolbar { display: none; } html, body { background: #fff; }
          .page { margin: 0; box-shadow: none; width: auto; min-height: auto; padding: 0; } }
      `}</style>

      <div className="er-toolbar">
        <button type="button" onClick={() => window.print()}>⬇ Save as PDF / Print</button>
        <button type="button" className="ghost" onClick={() => window.close()}>Close</button>
        <span style={{ opacity: .8 }}>2-page model-risk evidence pack · use your browser&rsquo;s &ldquo;Save as PDF&rdquo;</span>
      </div>

      {/* ---- Page 1 — executive ---- */}
      <div className="page">
        <div className="doc-h">
          <div className="eyebrow">Model-Risk Evidence Package · SR 11-7 Effective Challenge</div>
          <h1>{pkg.title}</h1>
          <div className="meta">
            Owner: {pkg.owner} &nbsp;·&nbsp; Generated: {pkg.generated_at} &nbsp;·&nbsp; Reference: {hash8}
          </div>
        </div>

        <h2>Integrity &amp; authenticity</h2>
        <div className="integrity">
          <div className="seal">✓ Dated &amp; tamper-evident — {pkg.signature.algorithm} signature over (content hash | timestamp)</div>
          <dl className="kv" style={{ marginTop: 8 }}>
            <dt>Content hash</dt><dd className="mono">{pkg.content_sha256}</dd>
            <dt>Signature</dt><dd className="mono">{pkg.signature.signature?.slice(0, 64)}…</dd>
            <dt>Key id</dt><dd className="mono">{pkg.signature.key_id}</dd>
          </dl>
          <div className="note">Any change to the underlying evidence changes the hash and breaks the signature. Verify independently with the public key in the machine-readable package, or via <span className="mono">/evidence/verify</span>. (Demo uses an ephemeral key; production would use a managed/HSM key + an RFC&nbsp;3161 timestamp.)</div>
        </div>

        <h2>Model identity &amp; intended use</h2>
        <dl className="kv">
          {idRows.map(([k, v]) => (<Fragment key={`id-${k}`}><dt>{k}</dt><dd>{v}</dd></Fragment>))}
          {rtRows.map(([k, v]) => (<Fragment key={`rt-${k}`}><dt>{k}</dt><dd className="mono">{v}</dd></Fragment>))}
          {typeof mc.intended_use === "string" && (<Fragment><dt>intended use</dt><dd>{mc.intended_use as string}</dd></Fragment>)}
        </dl>

        <h2>Risk posture — calibration (outcome analysis)</h2>
        <div className="metrics">
          <div className="metric"><div className="m-v">{num(cal.accuracy)}</div><div className="m-l">Accuracy</div></div>
          <div className="metric"><div className="m-v">{num(cal.ece)}</div><div className="m-l">ECE ↓ (lower = better calibrated)</div></div>
          <div className="metric"><div className="m-v">{num(cal.brier)}</div><div className="m-l">Brier ↓</div></div>
          <div className="metric"><div className="m-v">{num(cal.auroc)}</div><div className="m-l">Refusal AUROC ↑</div></div>
        </div>
        {cal.honesty && <div className="note">Measured over {cal.n ?? "—"} labelled samples. {cal.honesty}</div>}

        <div className="foot">Page 1 of 2 · {pkg.title} · {hash8} · Confidential — for the recipient&rsquo;s model-risk function.</div>
      </div>

      {/* ---- Page 2 — regulatory ---- */}
      <div className="page">
        <h2>Regulatory coverage — {pkg.frameworks_covered} frameworks · {pkg.controls_covered} controls</h2>
        <table>
          <thead><tr><th>Framework</th><th>Jurisdiction</th><th style={{ textAlign: "right" }}>Controls</th></tr></thead>
          <tbody>
            {frameworks.map((f) => (
              <tr key={f.key}>
                <td>{f.title || f.key}</td>
                <td>{f.jurisdiction || "—"}</td>
                <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{f.n_controls}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {pillars.length > 0 && (
          <>
            <h2>SR 11-7 pillar mapping</h2>
            <table>
              <thead><tr><th>Pillar</th><th>Mapped evidence</th></tr></thead>
              <tbody>
                {pillars.map((p, i) => {
                  const name = (p.name || p.title || p.pillar || `Pillar ${i + 1}`) as string;
                  const metrics = Array.isArray(p.metrics) ? (p.metrics as unknown[]).length
                    : Array.isArray(p.controls) ? (p.controls as unknown[]).length : undefined;
                  const detail = (p.description || p.summary || "") as string;
                  return (
                    <tr key={`p-${i}`}>
                      <td>{name}</td>
                      <td>{detail || (metrics != null ? `${metrics} mapped metric(s)/control(s)` : "—")}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </>
        )}

        <h2>Scope &amp; limitations</h2>
        <div className="note" style={{ fontSize: "9pt", lineHeight: 1.6 }}>
          <p style={{ margin: "0 0 6px" }}><strong>Scope limit.</strong> This package is evidence <em>for</em> an SR 11-7 effective challenge — the reproducible, machine-readable artifact a second-line validator places in the model-risk file. It does <em>not</em> constitute the independent validation review itself, nor a legal opinion of compliance.</p>
          <p style={{ margin: 0 }}>{pkg.note}</p>
        </div>

        <div className="foot">
          Page 2 of 2 · Renders signed package <span className="mono">{hash8}</span> · Reconcile line-for-line against the machine-readable <span className="mono">.json</span> export (same content hash). Framework/section letters are lub&rsquo;s crosswalk convention, not verbatim regulatory citations.
        </div>
      </div>
    </>
  );
}
