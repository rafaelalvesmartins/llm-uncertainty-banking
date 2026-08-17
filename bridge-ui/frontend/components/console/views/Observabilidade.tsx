"use client";

import Metrics from "@/components/Metrics";
import DriftPanel from "@/components/DriftPanel";
import OpsPanel from "@/components/OpsPanel";
import FleetInventory from "@/components/FleetInventory";
import ModelCard from "@/components/ModelCard";
import CalibrationPanel from "@/components/CalibrationPanel";
import VulnerabilityScan from "@/components/VulnerabilityScan";
import ExperimentsPanel from "@/components/ExperimentsPanel";
import AssistantPanel from "@/components/AssistantPanel";
import PlaygroundPanel from "@/components/PlaygroundPanel";
import Disclosure from "@/components/console/Disclosure";

// Snapshot export relocated here when the redundant Metrics rail tab was folded
// into the Dashboard (the deep metrics already live on this Observability page).
async function exportSnapshot() {
  const [m, s] = await Promise.all([
    fetch("/api/metrics", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).catch(() => null),
    fetch("/api/stats", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).catch(() => null),
  ]);
  const blob = new Blob(
    [JSON.stringify({ exported_at: new Date().toISOString(), metrics: m, throughput: s }, null, 2)],
    { type: "application/json" },
  );
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "bridge-metrics-snapshot.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// Plain-language glossary for the dense terms shown across this screen's cards.
// Rendered collapsed (a <details>), so it helps when confused without cluttering.
const GLOSSARY: [string, string][] = [
  ["Resolution", "Share of questions the AI fully handled on its own"],
  ["Escalation", "How often it handed off to a person"],
  ["Avg confidence", "How sure the AI was, on average"],
  ["Latency p50 (typical)", "The usual response speed — half of answers are faster than this, half slower"],
  ["Latency p95 (slowest 5%)", "Only 1 in 20 answers is slower than this — a sign of occasional slowness"],
  ["Latency p99 (worst tail)", "The worst-case wait — the slowest 1 in 100, where a customer really feels the delay"],
  ["Audit trail / verify chain", "A tamper-proof history of every decision, and the check that it was not altered"],
  ["Tamper test", "A safe demo proving any edit to the history gets caught"],
  ["Rotate window", "Archive the current history and start a fresh one"],
  ["Replay", "Re-run a past decision to confirm it comes out the same"],
  ["Drift / TV Distance", "Whether the mix of incoming questions has shifted from the usual pattern. If drift is high, review the new questions and consider resetting the 'normal' pattern (rebaseline)"],
  ["Baseline / rebaseline", "The 'normal' pattern we compare against (and resetting it)"],
  ["Ops panel (uptime / qps / error rate)", "Live running health: time online, traffic volume, error level"],
  ["Stage latency vs SLA (breach)", "Each step's speed versus its time limit; breach = too slow. If a step shows a breach, alert the team that owns it and have them check that step before customers feel it"],
  ["Fleet inventory", "List of all AI tools and who is responsible for each"],
  ["Model card", "The AI's ID sheet: what it is, what it is for, and its limits"],
  ["Fingerprint / hash (sha256)", "A unique code proving exactly which setup and documents were used"],
  ["Guard threshold", "The confidence cutoff below which the AI plays it safe"],
  ["RAG", "The reference documents the AI reads to answer"],
  ["DQ rules", "Quality checks on what goes in and what comes out"],
  ["Calibration / ECE", "Whether the AI's confidence matches how often it is actually right (lower ECE = more honest)"],
  ["Brier / AUROC / Sharpness", "Scores grading how trustworthy the confidence is"],
  ["95% CI (Wilson)", "The margin of uncertainty around each measurement"],
  ["Vulnerability scan", "Tests that try to trick the AI to check its defenses"],
  ["Experiments", "A graded test run on known answers to measure accuracy"],
];

export default function Observabilidade() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <p style={{ fontSize: 12.5, color: "var(--bc-text-mute)", margin: 0, lineHeight: 1.55 }}>
          <strong style={{ color: "var(--bc-text)" }}>What this does:</strong>{" "}
          {"This page shows how well the AI assistant is running right now and keeps proof that it can be trusted. You'll see live counts (questions handled, speed, how often it asked a human for help), a secure history of every decision it made, and checks that its confidence is honest and its answers hold up. Green means healthy; amber or red means something needs a look."}
        </p>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", fontSize: 11, color: "var(--bc-text-dim)" }}>
          <span><span style={{ color: "var(--bc-pass-line)" }}>●</span> <strong>Pass</strong> — answered</span>
          <span><span style={{ color: "var(--bc-flag-line)" }}>●</span> <strong>Flag</strong> — answered, marked for review</span>
          <span><span style={{ color: "var(--bc-reask-line)" }}>●</span> <strong>Re-ask</strong> — asked the customer to clarify</span>
          <span><span style={{ color: "var(--bc-block-line)" }}>●</span> <strong>Escalate</strong> — sent to a human</span>
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
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <button type="button" className="bc-btn ghost" style={{ fontSize: 12 }} onClick={exportSnapshot} title="Download a JSON snapshot of the current metrics + throughput">
          ⬇ Export snapshot
        </button>
      </div>
      <Metrics refreshKey={0} />
      <DriftPanel refreshKey={0} />
      <OpsPanel refreshKey={0} />
      <Disclosure title="Assistant & playground" hint="ask the copilot · try a query at different guard settings">
        <AssistantPanel />
        <PlaygroundPanel />
      </Disclosure>
      <Disclosure title="Evidence & deep-dives" hint="fleet · model card · calibration · vulnerability scan · experiments">
        <FleetInventory />
        <ModelCard />
        <CalibrationPanel />
        <VulnerabilityScan />
        <ExperimentsPanel />
      </Disclosure>
    </div>
  );
}
