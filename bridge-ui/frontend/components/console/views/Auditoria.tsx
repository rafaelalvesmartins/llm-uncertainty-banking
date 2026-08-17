"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { getJSON } from "@/components/console/api";
import { decisionTone, decisionLabel, humanizeIntent } from "@/components/console/types";
import StateBadge from "@/components/StateBadge";
import ExplainModal from "@/components/ExplainModal";
import SessionsPanel from "@/components/SessionsPanel";
import AskInFlowLink from "@/components/console/AskInFlowLink";
import DecisionLegend from "@/components/console/DecisionLegend";

// ---- Local interfaces derived from exact backend shapes ----

interface AuditEntry {
  seq?: number;
  ts: number;
  intent: string;
  decision: string;
  hash?: string;
  query?: string;
  channel?: string;
  confidence?: number;
}

interface AuditResponse {
  entries: AuditEntry[];
  total: number;
  returned: number;
  chain_head_seq?: number;
  chain_head_hash?: string;
}

interface VerifyResponse {
  valid: boolean;
  checked: number;
  head_seq: number;
  head_hash: string;
  window_first_seq?: number;
  window_last_seq?: number;
  window_starts_post_rotation?: boolean;
  first_failure: { seq: number; reason: string } | null;
  note?: string;
}

interface TamperResult {
  target_seq: number;
  verify_before_tamper: { valid: boolean; checked: number };
  verify_during_tamper: { valid: boolean; checked: number; first_failure: { seq: number; reason: string } | null };
  verify_after_restore: { valid: boolean; checked: number };
  note?: string;
}

// ---- Helpers ----

function fmtTs(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function truncHash(h: string | undefined): string {
  if (!h) return "—";
  return h.slice(0, 10) + "…";
}

// ---- Component ----

export default function Auditoria() {
  const [audit, setAudit] = useState<AuditResponse | null>(null);
  const [auditErr, setAuditErr] = useState<string | null>(null);
  const [auditLoading, setAuditLoading] = useState(true);
  const [view, setView] = useState<"log" | "by-customer">("log");

  // Filters fed to the server-side /audit endpoint (it already filters by
  // decision/intent and substring-matches the masked query). Limit raised from 15
  // so Dashboard deep-links land more often.
  const [fDecision, setFDecision] = useState("");
  const [fIntent, setFIntent] = useState("");
  const [fQ, setFQ] = useState("");
  const [limit, setLimit] = useState(50);
  // Per-entry explanation (LGPD Art. 20) drill-in target.
  const [explainSeq, setExplainSeq] = useState<number | null>(null);

  const [verify, setVerify] = useState<VerifyResponse | null>(null);
  const [verifyErr, setVerifyErr] = useState<string | null>(null);
  const [verifyLoading, setVerifyLoading] = useState(true);

  // Tamper-test demo: mutate one entry in memory, prove the chain flags it, restore.
  const [tamper, setTamper] = useState<TamperResult | null>(null);
  const [tamperErr, setTamperErr] = useState<string | null>(null);
  const [tamperBusy, setTamperBusy] = useState(false);

  // Deep-link / global-search target (sessionStorage). Applied on mount AND on a
  // 'bridge:goto' event so a search lands even when already on this page; also restores
  // a persisted filter on refresh (sessionStorage survives a same-tab reload).
  const [focusSeq, setFocusSeq] = useState<number | null>(null);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const apply = () => {
      // A #sessions deep-link (now folded into Audit) preselects the by-customer view.
      if (window.sessionStorage.getItem("bridge:auditView") === "by-customer") {
        setView("by-customer");
        window.sessionStorage.removeItem("bridge:auditView");
      }
      const focus = window.sessionStorage.getItem("bridge:auditFocusSeq");
      if (focus) {
        setFocusSeq(Number(focus));
        window.sessionStorage.removeItem("bridge:auditFocusSeq");
      }
      const raw = window.sessionStorage.getItem("bridge:auditFilter");
      if (raw) {
        try {
          const f = JSON.parse(raw) as { decision?: string; intent?: string; q?: string };
          setFDecision(f.decision ?? "");
          setFIntent(f.intent ?? "");
          setFQ(f.q ?? "");
        } catch {
          /* ignore a malformed stored filter */
        }
      }
    };
    apply();
    const onGoto = (e: Event) => {
      if ((e as CustomEvent).detail?.view === "audit") apply();
    };
    window.addEventListener("bridge:goto", onGoto);
    return () => window.removeEventListener("bridge:goto", onGoto);
  }, []);

  // Persist the filter so it survives a refresh (and so the global search can prefill it).
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (fDecision || fIntent.trim() || fQ.trim()) {
      window.sessionStorage.setItem("bridge:auditFilter", JSON.stringify({ decision: fDecision, intent: fIntent, q: fQ }));
    } else {
      window.sessionStorage.removeItem("bridge:auditFilter");
    }
  }, [fDecision, fIntent, fQ]);

  // Guards setState-after-unmount on fast tab switches (StrictMode-safe: reset on mount).
  const mounted = useRef(false);
  // Scroll a deep-linked row into view ONCE per focus target — the ref callback is
  // recreated each render, so without this guard it re-scrolls on every re-render.
  const scrolledSeqRef = useRef<number | null | undefined>(null);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const loadAudit = useCallback(async () => {
    setAuditLoading(true);
    setAuditErr(null);
    try {
      const params = new URLSearchParams({ limit: String(limit) });
      if (fDecision) params.set("decision", fDecision);
      if (fIntent.trim()) params.set("intent", fIntent.trim());
      if (fQ.trim()) params.set("q", fQ.trim());
      const data = await getJSON<AuditResponse>(`/api/audit?${params.toString()}`);
      if (!mounted.current) return;
      setAudit(data);
    } catch (e) {
      if (mounted.current) setAuditErr(e instanceof Error ? e.message : "Error loading audit trail");
    } finally {
      if (mounted.current) setAuditLoading(false);
    }
  }, [fDecision, fIntent, fQ, limit]);

  const loadVerify = useCallback(async (source: "memory" | "disk" = "memory") => {
    setVerifyLoading(true);
    setVerifyErr(null);
    try {
      // source=disk re-walks the persisted SQLite chain — catches an at-rest tamper
      // of stored rows that an in-memory re-hash would miss.
      const data = await getJSON<VerifyResponse>(
        source === "disk" ? "/api/audit/verify?source=disk" : "/api/audit/verify",
      );
      if (!mounted.current) return;
      setVerify(data);
    } catch (e) {
      if (mounted.current) setVerifyErr(e instanceof Error ? e.message : "Error verifying chain");
    } finally {
      if (mounted.current) setVerifyLoading(false);
    }
  }, []);

  // Prove tamper-evidence live: POST /audit/tamper-test edits one entry in memory,
  // re-verifies (chain breaks), then restores it. The strongest trust artifact.
  const runTamperTest = useCallback(async () => {
    setTamperBusy(true);
    setTamperErr(null);
    setTamper(null);
    try {
      const r = await fetch("/api/audit/tamper-test", { method: "POST" });
      const data = await r.json().catch(() => null);
      if (!r.ok) throw new Error(data?.detail || data?.error || `HTTP ${r.status}`);
      if (!mounted.current) return;
      setTamper(data as TamperResult);
      loadVerify("memory"); // the entry is restored — the live verdict should be green again
    } catch (e) {
      if (mounted.current) setTamperErr(e instanceof Error ? e.message : "Error running tamper test");
    } finally {
      if (mounted.current) setTamperBusy(false);
    }
  }, [loadVerify]);

  // Debounce the audit fetch so typing in the intent/query filter doesn't hammer
  // the endpoint; verify runs independently (no need to re-verify on a filter change).
  useEffect(() => {
    const t = setTimeout(loadAudit, 300);
    return () => clearTimeout(t);
  }, [loadAudit]);
  useEffect(() => {
    loadVerify();
  }, [loadVerify]);

  // "LIVE": refetch on an interval so the trail stays current AND a transient backend
  // blip (e.g. a restart) self-heals instead of leaving a stuck error until a manual
  // reload. Skipped while the tab is hidden to avoid pointless background fetches.
  useEffect(() => {
    const t = setInterval(() => {
      if (!document.hidden) {
        loadAudit();
        loadVerify();
      }
    }, 15000);
    return () => clearInterval(t);
  }, [loadAudit, loadVerify]);

  const tone = verify ? (verify.valid ? "pass" : "block") : null;

  return (
    <div className="bc-card">
      {/* Header */}
      <div className="bc-card-h">
        <h2>
          Audit trail
          <StateBadge feature="audit-trail" />
        </h2>
      </div>

      <p style={{ fontSize: 12.5, color: "var(--bc-text-mute)", margin: "0 0 12px", lineHeight: 1.55 }}>
        <strong style={{ color: "var(--bc-text)" }}>What this does:</strong>{" "}
        {"A tamper-proof record of every decision the AI made. The check below confirms nothing in the history was altered — green means the full record is intact."}
      </p>

      {/* Plain-language integrity verdict — always visible; the forensic detail + verify buttons + export live in the collapsed section below. */}
      {verify && (
        <div
          style={{
            marginBottom: 12,
            padding: "9px 12px",
            borderRadius: 8,
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontSize: 13,
            background: verify.valid ? "var(--bc-pass)" : "var(--bc-block)",
            border: `1px solid ${verify.valid ? "var(--bc-pass-line)" : "var(--bc-block-line)"}`,
            color: verify.valid ? "var(--bc-pass-text)" : "var(--bc-block-text)",
          }}
        >
          <span className={`bc-dot ${verify.valid ? "pass" : "block"}`} />
          <span style={{ fontWeight: 600 }}>
            {verify.valid
              ? `All ${verify.checked} decision${verify.checked === 1 ? "" : "s"} logged and verified — nothing was altered.`
              : `Warning — tampering detected in the record (${verify.checked} checked).`}
          </span>
          <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--bc-text-mute)" }}>auto-checks every 15s</span>
        </div>
      )}

      {/* Technical details (chain forensics + verify + export) — collapsed by default so the screen stays calm. */}
      <details style={{ marginBottom: 14 }}>
        <summary
          style={{ cursor: "pointer", fontSize: 12, fontWeight: 600, color: "var(--bc-text-dim)", padding: "6px 0", userSelect: "none" }}
        >
          Technical details — chain verification &amp; export
        </summary>

      {/* Chain integrity status banner */}
      <div style={{ marginBottom: 14 }}>
        {verifyLoading && !verify ? (
          <div className="bc-loading">Verifying chain…</div>
        ) : verifyErr ? (
          <div className="bc-error">{verifyErr}</div>
        ) : verify ? (
          <div
            style={{
              display: "flex",
              alignItems: "flex-start",
              justifyContent: "space-between",
              flexWrap: "wrap",
              gap: 10,
              padding: "10px 12px",
              background: verify.valid ? "var(--bc-pass)" : "var(--bc-block)",
              border: `1px solid ${verify.valid ? "var(--bc-pass-line)" : "var(--bc-block-line)"}`,
              borderRadius: 8,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className={`bc-dot ${tone!}`} />
              <span className={`bc-badge ${tone!}`}>
                {verify.valid ? "Chain intact" : "Chain tampered"}
              </span>
              <span
                style={{
                  fontSize: 12,
                  color: verify.valid ? "var(--bc-pass-text)" : "var(--bc-block-text)",
                }}
              >
                {verify.checked} entr{verify.checked === 1 ? "y" : "ies"} verified
                {verify.head_seq != null && (
                  <> · head seq <strong>#{verify.head_seq}</strong></>
                )}
                {verify.window_first_seq != null && verify.window_last_seq != null && (
                  <> · window #{verify.window_first_seq}–#{verify.window_last_seq}</>
                )}
              </span>
            </div>
            {verify.head_hash && (
              <span
                style={{
                  fontFamily: "ui-monospace,monospace",
                  fontSize: 10,
                  color: "var(--bc-text-mute)",
                  wordBreak: "break-all",
                  maxWidth: 260,
                }}
                title={verify.head_hash}
              >
                head {truncHash(verify.head_hash)}
              </span>
            )}
            {!verify.valid && verify.first_failure && (
              <div
                style={{
                  width: "100%",
                  fontSize: 12,
                  color: "var(--bc-block-text)",
                  marginTop: 4,
                }}
              >
                First failure: seq #{verify.first_failure.seq} — {verify.first_failure.reason}
              </div>
            )}
            {verify.note && (
              <div style={{ width: "100%", fontSize: 11, color: "var(--bc-text-mute)", marginTop: 2 }}>
                {verify.note}
              </div>
            )}
          </div>
        ) : null}

        {/* Actions: verify (in-memory / at-rest disk) + export for retention/evidence */}
        <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <button
            type="button"
            className="bc-btn ghost"
            onClick={() => loadVerify("memory")}
            disabled={verifyLoading}
            style={{ fontSize: 13 }}
          >
            {verifyLoading ? "Verifying…" : "Verify (quick, in memory)"}
          </button>
          <button
            type="button"
            className="bc-btn ghost"
            onClick={() => loadVerify("disk")}
            disabled={verifyLoading}
            style={{ fontSize: 13 }}
            title="Double-check that the saved records on disk still match the originals — catches tampering the quick check would miss."
          >
            Verify saved files (disk)
          </button>
          <button
            type="button"
            className="bc-btn ghost"
            onClick={runTamperTest}
            disabled={tamperBusy || verifyLoading}
            style={{ fontSize: 13 }}
            title="Prove it: edit one saved record in memory, watch the chain flag exactly where, then restore it. The strongest evidence the log is tamper-evident."
          >
            {tamperBusy ? "Testing…" : "🔬 Prove tamper detection"}
          </button>
          <span style={{ flex: 1 }} />
          <button
            type="button"
            className="bc-btn ghost"
            onClick={() => { window.location.href = "/api/audit/export?format=json"; }}
            style={{ fontSize: 13 }}
            title="Download the full audit trail as JSON (BCB 4893 5-year retention / SR 11-7 evidence)."
          >
            ⬇ Export JSON
          </button>
          <button
            type="button"
            className="bc-btn ghost"
            onClick={() => { window.location.href = "/api/audit/export?format=csv"; }}
            style={{ fontSize: 13 }}
            title="Download the full audit trail as CSV."
          >
            ⬇ Export CSV
          </button>
        </div>

        {/* Tamper-test result — the "aha": edited → caught → restored, in 3 beats. */}
        {tamperErr && (
          <div className="bc-error" style={{ marginTop: 10, fontSize: 12.5 }}>{tamperErr}</div>
        )}
        {tamper && (
          <div style={{ marginTop: 12, border: "1px solid var(--bc-border)", borderRadius: 8, padding: "11px 13px", background: "var(--bc-surface-2)" }}>
            <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 8 }}>
              Live proof — entry #{tamper.target_seq} was edited in memory, then restored:
            </div>
            <ol style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, lineHeight: 1.85 }}>
              <li>
                <span className="bc-badge pass">intact</span>{" "}
                before — all {tamper.verify_before_tamper.checked} entries verified.
              </li>
              <li>
                <span className="bc-badge block">tampering caught</span>{" "}
                the moment entry #{tamper.target_seq} changed, the chain broke
                {tamper.verify_during_tamper.first_failure && (
                  <> at seq <strong>#{tamper.verify_during_tamper.first_failure.seq}</strong> — {tamper.verify_during_tamper.first_failure.reason}</>
                )}.
              </li>
              <li>
                <span className="bc-badge pass">restored</span>{" "}
                original value put back — {tamper.verify_after_restore.checked} entries verified again.
              </li>
            </ol>
            {tamper.note && (
              <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 7 }}>{tamper.note}</div>
            )}
          </div>
        )}
      </div>
      </details>

      {/* Same audit records, two views: chronological (newest first) or grouped by customer
          — this absorbs the old separate "Sessions" tab (see COORDINATION.md). */}
      <div style={{ display: "flex", gap: 6, marginBottom: 10, alignItems: "center" }}>
        <button
          type="button"
          className="bc-btn"
          onClick={() => setView("log")}
          style={{ fontSize: 12, ...(view === "log" ? { background: "var(--bc-accent, #2563eb)", borderColor: "var(--bc-accent, #2563eb)", color: "#fff", fontWeight: 600 } : {}) }}
        >
          Newest first
        </button>
        <button
          type="button"
          className="bc-btn"
          onClick={() => setView("by-customer")}
          style={{ fontSize: 12, ...(view === "by-customer" ? { background: "var(--bc-accent, #2563eb)", borderColor: "var(--bc-accent, #2563eb)", color: "#fff", fontWeight: 600 } : {}) }}
        >
          By customer
        </button>
        <span style={{ fontSize: 11, color: "var(--bc-text-mute)" }}>same records, two views</span>
      </div>

      <div style={{ marginBottom: 10 }}>
        <DecisionLegend title="What each AI decision means" />
      </div>

      {view === "by-customer" ? (
        <SessionsPanel embedded />
      ) : (
        <>
      {/* Filters — fed to the server-side /audit filter (decision / intent / masked-query search) */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 10 }}>
        <select
          value={fDecision}
          onChange={(e) => setFDecision(e.target.value)}
          className="bc-input"
          style={{ fontSize: 12, padding: "3px 6px" }}
          aria-label="filter by decision"
        >
          <option value="">All decisions</option>
          <option value="PASSTHROUGH">{decisionLabel("PASSTHROUGH")}</option>
          <option value="FLAG">{decisionLabel("FLAG")}</option>
          <option value="REASK">{decisionLabel("REASK")}</option>
          <option value="ESCALATE">{decisionLabel("ESCALATE")}</option>
          <option value="PENDING">{decisionLabel("PENDING")}</option>
          <option value="APPROVED">{decisionLabel("APPROVED")}</option>
          <option value="REJECTED">{decisionLabel("REJECTED")}</option>
          <option value="APPLIED">{decisionLabel("APPLIED")}</option>
        </select>
        <input
          value={fIntent}
          onChange={(e) => setFIntent(e.target.value)}
          placeholder="search intent — e.g. balance_inquiry"
          className="bc-input"
          style={{ fontSize: 12, padding: "3px 6px", width: 180 }}
          aria-label="filter by type"
        />
        <input
          value={fQ}
          onChange={(e) => setFQ(e.target.value)}
          placeholder="search what was asked…"
          className="bc-input"
          style={{ fontSize: 12, padding: "3px 6px", flex: 1, minWidth: 160 }}
          aria-label="search what was asked"
        />
        {(fDecision || fIntent || fQ) && (
          <button
            type="button"
            className="bc-btn ghost"
            onClick={() => { setFDecision(""); setFIntent(""); setFQ(""); }}
            style={{ fontSize: 12 }}
          >
            Clear filters
          </button>
        )}
      </div>

      {/* Audit entries table */}
      {auditLoading && !audit ? (
        <div className="bc-loading">Loading audit entries…</div>
      ) : auditErr ? (
        <div className="bc-error">{auditErr}</div>
      ) : !audit || audit.entries.length === 0 ? (
        <AskInFlowLink prefix="No audit entries recorded yet." />
      ) : (
        <>
          <div
            style={{
              fontSize: 11,
              color: "var(--bc-text-mute)",
              marginBottom: 8,
            }}
          >
            Showing {audit.entries.length} of {audit.total} entr{audit.total === 1 ? "y" : "ies"} (most recent first) · tip: click a row to see why
          </div>
          {focusSeq != null && (
            <div
              style={{
                fontSize: 11,
                marginBottom: 8,
                padding: "3px 8px",
                borderRadius: 4,
                background: "var(--bc-surface-2)",
                color: "var(--bc-text-dim)",
                border: "1px solid var(--bc-border)",
              }}
            >
              {audit.entries.some((e) => e.seq === focusSeq) ? (
                `Focused on #${focusSeq} (from Dashboard).`
              ) : (fDecision || fIntent.trim() || fQ.trim()) ? (
                <>
                  #{focusSeq} is not shown under the current filters.{" "}
                  <button type="button" className="link-btn" onClick={() => { setFDecision(""); setFIntent(""); setFQ(""); }}>
                    Clear filters
                  </button>
                </>
              ) : (
                `#${focusSeq} is not in the current audit window (it may have rotated).`
              )}
            </div>
          )}
          <div style={{ overflowX: "auto" }}>
            <table className="bc-table">
              <thead>
                <tr>
                  <th style={{ minWidth: 130 }}>When</th>
                  <th>What the customer asked</th>
                  <th style={{ width: 150 }}>Type</th>
                  <th style={{ width: 130 }}>AI decision</th>
                </tr>
              </thead>
              <tbody>
                {audit.entries.map((e, i) => {
                  const dk = String(e.decision ?? "").toUpperCase();
                  // Guard decisions get their semantic tone; governance/system events
                  // (APPLIED/REJECTED/…) are NOT guard denials — don't paint them red.
                  const tone =
                    dk === "PASSTHROUGH" || dk === "FLAG" || dk === "REASK" || dk === "ESCALATE"
                      ? decisionTone(String(e.decision))
                      : dk === "APPLIED"
                        ? "pass"
                        : "";
                  const isFocus = e.seq != null && e.seq === focusSeq;
                  return (
                    <tr
                      key={e.seq ?? i}
                      ref={
                        isFocus
                          ? (el) => {
                              if (el && scrolledSeqRef.current !== e.seq) {
                                scrolledSeqRef.current = e.seq ?? null;
                                el.scrollIntoView({ block: "center", behavior: "smooth" });
                              }
                            }
                          : undefined
                      }
                      onClick={() => { if (e.seq != null) setExplainSeq(e.seq); }}
                      tabIndex={e.seq != null ? 0 : undefined}
                      role={e.seq != null ? "button" : undefined}
                      aria-label={e.seq != null ? `Explain decision #${e.seq}` : undefined}
                      onKeyDown={(ev) => { if (e.seq != null && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); setExplainSeq(e.seq); } }}
                      title={e.seq != null ? "Click to see why the AI decided this — plain explanation + security details" : undefined}
                      style={{
                        cursor: e.seq != null ? "pointer" : "default",
                        ...(isFocus ? { outline: "2px solid var(--bc-accent)", background: "var(--bc-surface-2)" } : {}),
                      }}
                    >
                      <td style={{ fontSize: 12, color: "var(--bc-text-dim)", whiteSpace: "nowrap" }}>
                        {fmtTs(e.ts)}
                      </td>
                      <td
                        style={{ fontSize: 13, maxWidth: 360, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                        title={e.query ?? ""}
                      >
                        {e.query || <span style={{ color: "var(--bc-text-mute)" }}>—</span>}
                      </td>
                      <td>
                        <span className="bc-chip" style={{ fontSize: 11 }}>{e.intent ? humanizeIntent(String(e.intent)) : "—"}</span>
                      </td>
                      <td>
                        <span className={`bc-badge ${tone}`}>
                          {e.decision ? decisionLabel(String(e.decision)) : "—"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {audit.total > audit.entries.length && (
            <div style={{ marginTop: 10, textAlign: "center" }}>
              <button
                type="button"
                className="bc-btn ghost"
                onClick={() => setLimit((l) => l + 50)}
                disabled={auditLoading}
                style={{ fontSize: 12 }}
              >
                {auditLoading ? "Loading…" : `Load ${Math.min(50, audit.total - audit.entries.length)} more (${audit.total - audit.entries.length} older)`}
              </button>
            </div>
          )}
        </>
      )}
        </>
      )}
      <ExplainModal seq={explainSeq} onClose={() => setExplainSeq(null)} />
    </div>
  );
}
