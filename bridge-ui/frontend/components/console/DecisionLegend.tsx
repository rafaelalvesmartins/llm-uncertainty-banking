"use client";

import { Fragment } from "react";
import { decisionLabel, decisionTone } from "@/components/console/types";

// Single source of truth for the plain-language meaning of each guard decision, so every
// tab (Metrics, Sessions, Policies…) explains Pass/Flag/Re-ask/Escalate the same way
// instead of showing the raw codes with no context.
export const DECISION_MEANING: Record<string, string> = {
  PASSTHROUGH: "Answered normally — the AI was confident enough.",
  FLAG: "Answered, but flagged for a human to review later.",
  REASK: "Held back on purpose — asks the customer to clarify (the AI wasn't sure enough).",
  ESCALATE: "Handed to a human agent — too risky or too low-confidence to answer.",
};

export function decisionMeaning(d: string): string {
  return DECISION_MEANING[(d || "").toUpperCase()] ?? "";
}

const ORDER = ["PASSTHROUGH", "FLAG", "REASK", "ESCALATE"];

/** A compact, reusable card that explains what the four guard decisions mean in plain
 *  language. Drop it near any view that shows Pass / Flag / Re-ask / Escalate. */
export default function DecisionLegend({ title = "What the decisions mean" }: { title?: string }) {
  return (
    <div style={{ background: "var(--bc-surface-2)", border: "1px solid var(--bc-border)", borderRadius: 8, padding: "10px 12px" }}>
      <div style={{ fontSize: 11, color: "var(--bc-text-mute)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
        {title}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 12px", fontSize: 12, alignItems: "center" }}>
        {ORDER.map((d) => (
          <Fragment key={d}>
            <span className={`bc-badge ${decisionTone(d)}`} style={{ fontSize: 11, whiteSpace: "nowrap" }}>
              {decisionLabel(d)}
            </span>
            <span style={{ color: "var(--bc-text-dim)" }}>{DECISION_MEANING[d]}</span>
          </Fragment>
        ))}
      </div>
    </div>
  );
}
