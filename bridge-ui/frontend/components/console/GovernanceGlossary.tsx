"use client";

import { Fragment } from "react";

// Single source of truth for the plain-language meaning of the governance/regulatory
// terms that show up across the console (SR 11-7, four-eyes, config_hash…), so every
// screen explains them the same way instead of assuming the reader is a compliance
// expert. Mirrors the DecisionLegend pattern.
export const GOV_TERMS: Record<string, string> = {
  "SR 11-7": "The US Federal Reserve / OCC supervisory guidance on model risk — the bar this evidence is built to meet (banks must govern, validate and monitor their models).",
  "Segregation of duties": "No one person can change a live system alone — different people propose, approve and apply a change.",
  "Four-eyes": "At least two different people must sign off before a change goes live (here it takes three).",
  "config_hash": "A fingerprint that locks an approval to the exact change — if anyone alters it later, auditors can tell.",
  "Effective challenge": "SR 11-7's core principle: critical review by qualified people independent of the model's builders, empowered to find its limits and force changes — not just an automated test.",
  "Audit trail": "A tamper-proof, append-only record of every decision and change — with the reason why.",
};

/** A compact, reusable card explaining the governance terms a screen uses. Pass `terms`
 *  to show only the relevant ones; omit to show them all. */
export default function GovernanceGlossary({
  terms,
  title = "Plain-language glossary",
}: {
  terms?: string[];
  title?: string;
}) {
  const rows = (terms ?? Object.keys(GOV_TERMS)).filter((t) => GOV_TERMS[t]);
  if (rows.length === 0) return null;
  return (
    <div style={{ background: "var(--bc-surface-2)", border: "1px solid var(--bc-border)", borderRadius: 8, padding: "10px 12px" }}>
      <div style={{ fontSize: 11, color: "var(--bc-text-mute)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
        {title}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 12px", fontSize: 12, alignItems: "baseline" }}>
        {rows.map((t) => (
          <Fragment key={t}>
            <span style={{ color: "var(--bc-text)", fontWeight: 600, whiteSpace: "nowrap" }}>{t}</span>
            <span style={{ color: "var(--bc-text-dim)", lineHeight: 1.5 }}>{GOV_TERMS[t]}</span>
          </Fragment>
        ))}
      </div>
    </div>
  );
}
