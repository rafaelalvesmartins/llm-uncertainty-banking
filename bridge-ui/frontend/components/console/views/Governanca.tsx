"use client";

import Compliance from "@/components/Compliance";
import ChallengeNightlyPanel from "@/components/ChallengeNightlyPanel";
import RegulatoryCoverage from "@/components/RegulatoryCoverage";
import EvidencePackage from "@/components/EvidencePackage";
import GovernedChangesPanel from "@/components/GovernedChangesPanel";
import ActiveConfigsPanel from "@/components/ActiveConfigsPanel";
import VisibilityPanel from "@/components/VisibilityPanel";
import IntentsPanel from "@/components/IntentsPanel";
import Disclosure from "@/components/console/Disclosure";

// Plain-language glossary for the dense terms across this screen's cards (incl. the
// AI Visibility card). Rendered collapsed (a <details>) so it helps without cluttering.
const GLOSSARY: [string, string][] = [
  ["SR 11-7 / BCB 4893 / LGPD", "The banking and privacy rulebooks this evidence is built to satisfy"],
  ["Regulatory coverage / crosswalk", "A map linking each of our checks to the rule it satisfies"],
  ["Evidence package", "A downloadable audit record that auditors can independently verify"],
  ["Content hash (sha256)", "A unique fingerprint of the record; it changes if even one character is altered"],
  ["Signature (Ed25519)", "A digital seal proving the record is genuine and unaltered"],
  ["Governed changes", "Changes that need a second person's sign-off before they take effect"],
  ["config_hash", "A fingerprint that locks an approval to the exact change that was approved"],
  ["Segregation of duties", "The approver and applier must each be a different person from the proposer"],
  ["Append-only ledger", "A record book where entries can be added but never edited or erased"],
  ["Intent catalog", "The list of customer request types the AI knows how to handle"],
  ["Continuous effective challenge", "A recurring re-check of whether the AI's stated confidence still matches how often it is actually right"],
  ["Calibration error (ECE)", "The average gap between how sure the AI says it is and how often it turns out correct"],
  ["INCONCLUSIVE", "Not enough labelled evidence to judge — deliberately not counted as a pass"],
  ["Share of Voice (SoV)", "Your share of brand mentions in AI answers vs. competitors"],
  ["Presence / position", "How often your brand is named, and how high it ranks in the answer"],
];

export default function Governanca() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <p style={{ fontSize: 12.5, color: "var(--bc-text-mute)", margin: 0, lineHeight: 1.55 }}>
          <strong style={{ color: "var(--bc-text)" }}>What this does:</strong>{" "}
          {"This page collects the evidence that the AI is run safely under banking rules. It lists the rules this evidence maps to, lets you download a signed record that auditors can trust, and makes sure no change happens unless a second person approves it. Everything here is built so nothing can be quietly altered after the fact."}
        </p>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", fontSize: 11, color: "var(--bc-text-dim)" }}>
          <span><span style={{ color: "var(--bc-flag-line)" }}>●</span> <strong>Pending</strong> — waiting for a second person</span>
          <span><span style={{ color: "var(--bc-pass-line)" }}>●</span> <strong>Approved</strong> — a different reviewer signed off</span>
          <span><span style={{ color: "var(--bc-block-line)" }}>●</span> <strong>Rejected</strong> — reviewer turned it down</span>
          <span><span style={{ color: "var(--bc-info-line)" }}>●</span> <strong>Applied</strong> — the change is now in effect</span>
        </div>
        <details style={{ fontSize: 11, color: "var(--bc-text-dim)" }}>
          <summary style={{ cursor: "pointer", color: "var(--bc-text-mute)" }}>Glossary — plain meaning of the terms on this page</summary>
          <div style={{ marginTop: 6 }}>
            {GLOSSARY.map(([t, m]) => (
              <div key={t} style={{ marginTop: 3 }}>
                <strong style={{ color: "var(--bc-text)" }}>{t}</strong> — {m}
              </div>
            ))}
          </div>
        </details>
      </div>
      <ChallengeNightlyPanel />
      <Compliance />
      <Disclosure title="Regulatory coverage & evidence package" hint="framework crosswalk + signed download" defaultOpen>
        <RegulatoryCoverage />
        <EvidencePackage />
      </Disclosure>
      <GovernedChangesPanel />
      <ActiveConfigsPanel />
      <Disclosure title="AI visibility & intent catalog">
        <VisibilityPanel />
        <IntentsPanel refreshKey={0} />
      </Disclosure>
    </div>
  );
}
