"use client";

import { useEffect, useState } from "react";
import { decisionLabel, humanizeIntent } from "@/components/console/types";
import { useDialogFocus } from "@/components/useDialogFocus";

interface Explanation {
  seq: number;
  ts: number;
  query_masked: string;
  query_was_masked: boolean;
  pii_count: number;
  intent: string;
  intent_family: string | null;
  intent_description: string | null;
  agent: string | null;
  confidence: number | null;
  decision: string;
  decision_rationale: string;
  answer_preview: string;
  answer_withheld?: boolean;
  channel: string;
  from_cache: boolean;
  chain: { seq: number; prev_hash: string; hash: string };
  lgpd_basis: string;
}

/** A governed CONFIG change (propose/approve/apply) — a HUMAN decision under segregation
 *  of duties, NOT an automated decision about a customer. The backend returns this shape
 *  for governance.* entries; rendering it through the LGPD template would show "Intent:
 *  Unknown / rationale not recorded" under an Art. 20 footer that legally does not apply. */
interface GovernanceExplanation {
  seq: number;
  ts: number;
  kind: "governance";
  /** A governed change went through four-eyes and has a change_id; a settings knob or a
   *  drift alert did NOT — labelling those "Governed change #" would claim a control that
   *  never ran. */
  operational_kind?: "governed_change" | "operational_event";
  event: string;
  change_id: number | null;
  change_kind: string | null;
  summary: string | null;
  decision: string;
  decision_rationale: string;
  decision_note: string | null;
  submitted_by: string | null;
  reviewer: string | null;
  applied_by: string | null;
  config_hash: string | null;
  chain: { seq: number; prev_hash: string; hash: string };
  legal_basis: string;
}

type AnyExplanation = Explanation | GovernanceExplanation;

function isGovernance(d: AnyExplanation): d is GovernanceExplanation {
  return (d as GovernanceExplanation).kind === "governance";
}

/**
 * Bloco A4 — surfaces the existing /audit/explain/{seq} endpoint as a modal.
 * LGPD Art. 20 "direito à explicação": shows why a logged decision was made
 * (intent + family + rationale) and pins it to the tamper-evident chain
 * (seq / prev_hash / hash). Open with the per-entry "explain" button; close
 * with ✕, Escape, or clicking the backdrop.
 */
export default function ExplainModal({
  seq,
  onClose,
}: {
  seq: number | null;
  onClose: () => void;
}) {
  const [data, setData] = useState<AnyExplanation | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (seq === null) {
      setData(null);
      setError(null);
      return;
    }
    setData(null);
    setError(null);
    fetch(`/api/audit/explain/${seq}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then(setData)
      .catch(() =>
        setError("Could not load the explanation (the audit window may have rotated)."),
      );
  }, [seq]);

  useEffect(() => {
    if (seq === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [seq, onClose]);

  const dialogRef = useDialogFocus<HTMLDivElement>(seq !== null);

  if (seq === null) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div ref={dialogRef} tabIndex={-1} className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label={`Explain audit entry #${seq}`}>
        <div className="modal-header">
          <h3>Explain · audit seq #{seq}</h3>
          <button type="button" className="modal-close" onClick={onClose} aria-label="close">
            ×
          </button>
        </div>

        {error ? (
          <div className="empty">{error}</div>
        ) : !data ? (
          <div className="empty">loading explanation…</div>
        ) : isGovernance(data) ? (
          <div className="modal-body">
            {data.operational_kind === "operational_event" ? (
              <div className="explain-row">
                <span className="muted">Operational event</span>
                <strong>{data.event}</strong>
                <span className="muted" style={{ fontSize: 11 }}>
                  {" "}
                  · not a governed change (no four-eyes approval)
                </span>
              </div>
            ) : (
              <div className="explain-row">
                <span className="muted">Governed change</span>
                <strong>#{data.change_id}</strong>
                {data.change_kind && <span className="intent-pill">{data.change_kind}</span>}
              </div>
            )}
            {data.summary && (
              <div className="explain-row" style={{ fontSize: 12 }}>
                {data.summary}
              </div>
            )}
            <div className="explain-row">
              <span className="muted">Step</span>
              <span className={`badge ${data.decision.toLowerCase()}`}>{data.decision}</span>
            </div>
            <div className="explain-row" style={{ fontSize: 12 }}>
              {data.decision_rationale}
            </div>
            {data.decision_note && (
              <div className="explain-row">
                <span className="muted">Reviewer note</span>
                <span style={{ fontSize: 12 }}>{data.decision_note}</span>
              </div>
            )}
            <div className="explain-row">
              <span className="muted">Who</span>
              <span style={{ fontSize: 12 }}>
                proposed by <strong>{data.submitted_by || "—"}</strong>
                {data.reviewer && <> · decided by <strong>{data.reviewer}</strong></>}
                {data.applied_by && <> · applied by <strong>{data.applied_by}</strong></>}
              </span>
            </div>
            {data.config_hash && (
              <div className="explain-row">
                <span className="muted">config_hash</span>
                <code style={{ fontSize: 11 }}>{data.config_hash.slice(0, 32)}…</code>
              </div>
            )}
            <div className="explain-chain">
              <div className="muted" style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5 }}>
                Tamper-evident chain
              </div>
              <div className="explain-hash">
                <span className="muted">seq</span> #{data.chain.seq}
              </div>
              <div className="explain-hash">
                <span className="muted">prev_hash</span> {data.chain.prev_hash}
              </div>
              <div className="explain-hash">
                <span className="muted">hash</span> {data.chain.hash}
              </div>
            </div>
            <div className="explain-row muted" style={{ fontSize: 11, marginTop: 8 }}>
              {data.legal_basis}
            </div>
          </div>
        ) : (
          <div className="modal-body">
            <div className="explain-row">
              <span className="muted">Query (masked)</span>
              <code>{data.query_masked}</code>
              {data.query_was_masked && (
                <span className="warn" style={{ fontSize: 11 }}>
                  {" "}
                  · {data.pii_count} PII fragment(s) masked
                </span>
              )}
            </div>
            <div className="explain-row">
              <span className="muted">Intent</span>
              <strong title={data.intent}>{humanizeIntent(data.intent)}</strong>
              {data.intent_family && <span className="intent-pill">{data.intent_family}</span>}
              {data.agent && <span className="muted"> → {data.agent}</span>}
            </div>
            {data.intent_description && (
              <div className="explain-row muted" style={{ fontSize: 12 }}>
                {data.intent_description}
              </div>
            )}
            <div className="explain-row">
              <span className="muted">Decision</span>
              <span className={`badge ${data.decision.toLowerCase()}`}>{decisionLabel(data.decision)}</span>
              {data.confidence !== null && (
                <span className="muted"> · confidence {(data.confidence * 100).toFixed(0)}%</span>
              )}
            </div>
            <div className="explain-row" style={{ fontSize: 12 }}>
              {data.decision_rationale}
            </div>
            <div className="explain-row">
              <span className="muted">Answer preview</span>
              {data.answer_withheld ? (
                <span className="warn" style={{ fontSize: 12 }}>
                  withheld — the guard did not release an answer for this decision
                </span>
              ) : (
                <span style={{ fontSize: 12 }}>{data.answer_preview || "—"}</span>
              )}
            </div>
            <div className="explain-row">
              <span className="muted">Channel</span>
              <span>{data.channel}</span>
              <span className="muted"> · from cache: {data.from_cache ? "yes" : "no"}</span>
            </div>
            <div className="explain-chain">
              <div className="muted" style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5 }}>
                Tamper-evident chain
              </div>
              <div className="explain-hash">
                <span className="muted">seq</span> #{data.chain.seq}
              </div>
              <div className="explain-hash">
                <span className="muted">prev_hash</span> {data.chain.prev_hash}
              </div>
              <div className="explain-hash">
                <span className="muted">hash</span> {data.chain.hash}
              </div>
            </div>
          </div>
        )}

        {/* The LGPD Art. 20 footer belongs ONLY to an automated decision about a customer.
            A governed config change renders its own SR 11-7 basis inside its branch — this
            footer used to stamp "automated decision" on human approvals too. */}
        {data && !isGovernance(data) && <div className="modal-footer muted">{data.lgpd_basis}</div>}
      </div>
    </div>
  );
}
