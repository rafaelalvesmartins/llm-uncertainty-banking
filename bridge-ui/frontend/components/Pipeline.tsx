"use client";

import { useState } from "react";
import { QueryResult } from "./QueryPanel";
import StateBadge from "@/components/StateBadge";
import { decisionLabel } from "@/components/console/types";

interface Props {
  result: QueryResult | null;
}

function tierClass(tier: string | null | undefined): string {
  switch ((tier || "").toUpperCase()) {
    case "SIMPLE":
      return "tier-simple";
    case "MEDIUM":
      return "tier-medium";
    case "COMPLEX":
      return "tier-complex";
    case "CACHED":
      return "tier-cached";
    default:
      return "";
  }
}

// Plain-language gloss for each guard band so a non-technical viewer reads the
// decision as a sentence, not just an uppercase code. Keyed by decision value.
const DECISION_VERDICT: Record<string, string> = {
  PASSTHROUGH: "Confidence sufficient — answered directly to the customer.",
  FLAG: "Confidence on the boundary — answered, but flagged for review.",
  REASK: "Not certain — asked the customer to rephrase.",
  ESCALATE: "Handed off to a human — the model declined to act.",
};

// What each pipeline stage does — shown when a stage is expanded. Makes the
// trace navigable (Phoenix-style drill-down) and self-explanatory in one move.
const STAGE_ROLE: Record<string, string> = {
  dq_input: "Input quality: blocks injection, credentials, and noise before processing.",
  data_governance: "Data governance: detects and masks PII (CPF, card, e-mail) — LGPD / BCB 4893.",
  semantic_cache: "Similarity cache: serves a stored answer when a near-identical query (lexical similarity) was already seen — not synonym-aware.",
  complexity: "Complexity routing: selects the tier (SIMPLE / MEDIUM / COMPLEX).",
  memory: "Customer memory: loads the account holder's preferences and risk profile.",
  rag: "RAG: retrieves corpus excerpts to ground the response.",
  retrieval: "RAG: retrieves corpus excerpts to ground the response.",
  intent: "Intent classification: identifies what the customer wants.",
  intent_classification: "Intent classification: identifies what the customer wants.",
  agent: "Agent: generates the response (with handoffs between agents when needed).",
  uncertainty_guard: "Uncertainty guard: decides PASSTHROUGH / FLAG / REASK / ESCALATE by confidence.",
  cache_store: "Stores in cache for future hits (releasable decisions only).",
  dq_output: "Output quality: validates the response before returning it to the customer.",
  audit: "Audit: records in the tamper-evident chain (chained hash).",
};

export default function Pipeline({ result }: Props) {
  const [expanded, setExpanded] = useState<number | null>(null);
  const [copiedName, setCopiedName] = useState<string | null>(null);

  if (!result) {
    return (
      <div className="card">
        <h2>Pipeline Trace<StateBadge feature="pipeline-trace" /></h2>
        <div className="empty">
          <div className="empty-cta">
            Type a question on the right, click an example below
            <span aria-hidden> ⬇</span>, or press{" "}
            <strong>▶ Run demo</strong> to get started.
          </div>
          <div className="empty-stages">
            The 12 stages you will see: dq_input → data_governance → cache →
            complexity → memory → RAG → intent → agent (with handoffs) → guard →
            cache_store → dq_output → audit
          </div>
        </div>
      </div>
    );
  }

  const hasHandoff = result.handoff_chain && result.handoff_chain.length > 1;
  const maxDur = Math.max(...result.stages.map((s) => s.duration_ms), 1);

  return (
    <div className="card">
      <h2>Pipeline Trace<StateBadge feature="pipeline-trace" /></h2>

      {/* HIGHLIGHTS: what's special about this query */}
      <div className="highlights">
        {result.cache_hit && (
          <div className="highlight cache">
            <strong>CACHE HIT</strong>
            <span>similarity {((result.cache_similarity || 0) * 100).toFixed(0)}%</span>
          </div>
        )}
        {result.tier && (
          <div className={`highlight ${tierClass(result.tier)}`}>
            <strong>{result.tier}</strong>
            <span>{result.cost_cents !== null ? `$${result.cost_cents?.toFixed(2)}¢` : ""}</span>
          </div>
        )}
        {hasHandoff && (
          <div className="highlight handoff">
            <strong>HANDOFF</strong>
            <span>{result.handoff_chain?.join(" → ")}</span>
          </div>
        )}
        {result.agent_used && !hasHandoff && (
          <div className="highlight agent">
            <strong>{result.agent_used}</strong>
            <span>single agent</span>
          </div>
        )}
      </div>

      {/* RAG citations */}
      {result.citations && result.citations.length > 0 && (
        <div className="citations">
          <div className="section-label">Grounded on</div>
          {result.citations.map((c, i) => (
            <span key={i} className="citation-pill">
              📄 {c}
            </span>
          ))}
        </div>
      )}

      {/* Customer memory loaded */}
      {result.memory_blocks && result.memory_blocks.length > 0 && (
        <div className="citations">
          <div className="section-label">Customer memory loaded</div>
          {result.memory_blocks.map((b, i) => (
            <span key={i} className="memory-pill">
              🧠 {b}
            </span>
          ))}
        </div>
      )}

      {/* Stage trace — click a stage to drill into what it did */}
      <div className="pipeline">
        {result.stages.map((s, i) => {
          const open = expanded === i;
          return (
            <div key={i} className={`stage ${s.status}`}>
              <button
                type="button"
                aria-expanded={open}
                onClick={() => setExpanded(open ? null : i)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  width: "100%",
                  background: "transparent",
                  border: "none",
                  padding: 0,
                  textAlign: "left",
                  color: "inherit",
                  cursor: "pointer",
                }}
              >
                <div className="dot" />
                <div className="info">
                  <div className="name">
                    {s.name} <span className="muted" style={{ fontSize: 10 }}>{open ? "▾" : "▸"}</span>
                  </div>
                  <div className="detail">{s.detail}</div>
                </div>
                <div className="meta">
                  {s.confidence !== null && (
                    <span className="conf">{(s.confidence * 100).toFixed(0)}%</span>
                  )}
                  <span>{s.duration_ms.toFixed(1)}ms</span>
                </div>
              </button>
              {open && (
                <div
                  style={{
                    margin: "4px 0 8px 22px",
                    padding: "8px 10px",
                    background: "#0f172a",
                    border: "1px solid #1e293b",
                    borderRadius: 6,
                  }}
                >
                  <div style={{ fontSize: 12, color: "#cbd5e1", marginBottom: 8 }}>
                    {STAGE_ROLE[s.name] || "Pipeline stage."}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11, color: "#94a3b8" }}>
                    <span>latency</span>
                    <div style={{ flex: 1, height: 6, background: "#1e293b", borderRadius: 3, overflow: "hidden" }}>
                      <div style={{ width: `${Math.max(2, (s.duration_ms / maxDur) * 100)}%`, height: "100%", background: "#60a5fa" }} />
                    </div>
                    <span>{s.duration_ms.toFixed(1)}ms</span>
                  </div>
                  <div style={{ marginTop: 6, fontSize: 11, color: "#64748b" }}>
                    status: {s.status}
                    {s.confidence !== null && s.confidence !== undefined
                      ? ` · stage confidence: ${(s.confidence * 100).toFixed(0)}%`
                      : ""}
                  </div>
                  <button
                    type="button"
                    className="link-btn"
                    title="Copy this stage's log to the clipboard"
                    onClick={(e) => {
                      e.stopPropagation();
                      const text = [
                        `stage: ${s.name}`,
                        `status: ${s.status}`,
                        s.detail ? `detail: ${s.detail}` : null,
                        s.confidence != null ? `confidence: ${(s.confidence * 100).toFixed(0)}%` : null,
                        `duration: ${s.duration_ms.toFixed(1)}ms`,
                      ].filter(Boolean).join("\n");
                      navigator.clipboard
                        ?.writeText(text)
                        .then(() => {
                          setCopiedName(s.name);
                          setTimeout(() => setCopiedName((c) => (c === s.name ? null : c)), 1200);
                        })
                        .catch(() => {});
                    }}
                    style={{ marginTop: 8, fontSize: 11 }}
                  >
                    {copiedName === s.name ? "✓ copied" : "⧉ copy stage log"}
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div
        className={`answer-box ${result.decision === "ESCALATE" ? "escalate" : ""}`}
      >
        <div
          style={{
            fontSize: 11,
            color: "#64748b",
            marginBottom: 6,
            textTransform: "uppercase",
            letterSpacing: "0.05em",
          }}
        >
          Final Answer ·{" "}
          <span
            className={`badge ${result.decision.toLowerCase()}`}
            title={DECISION_VERDICT[result.decision] || result.decision}
          >
            {decisionLabel(result.decision)}
          </span>{" "}
          · {result.latency_ms.toFixed(0)}ms total
        </div>
        {DECISION_VERDICT[result.decision] && (
          <div className="decision-verdict">{DECISION_VERDICT[result.decision]}</div>
        )}
        {result.answer}
      </div>
    </div>
  );
}
