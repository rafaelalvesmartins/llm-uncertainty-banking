"use client";

import { useEffect, useState } from "react";
import StateBadge from "@/components/StateBadge";
import ExplainModal from "@/components/ExplainModal";
import { useConfirm } from "@/components/ConfirmProvider";
import { useAppContext } from "@/components/AppContextProvider";
import { decisionLabel, humanizeIntent } from "@/components/console/types";

interface MetricsData {
  queries_total: number;
  avg_confidence: number;
  avg_latency_ms: number;
  p50_latency_ms?: number;
  p95_latency_ms?: number;
  p99_latency_ms?: number;
  resolution_rate: number;
  escalation_rate: number;
  queries_by_intent: Record<string, number>;
  decisions: Record<string, number>;
  target_resolution: number;
  target_retention: number;
  target_accuracy: number;
}

interface AuditEntry {
  ts: number;
  query: string;
  intent: string;
  confidence: number;
  decision: string;
  channel: string;
  seq?: number;
  prev_hash?: string;
  hash?: string;
}

interface ChainStatus {
  valid: boolean;
  checked: number;
  head_seq: number;
  head_hash: string;
  first_failure: { seq: number; reason: string } | null;
}

interface Props {
  refreshKey: number;
}

function pctClass(value: number, target: number): string {
  if (value >= target) return "ok";
  if (value >= target * 0.85) return "warn";
  return "bad";
}

interface IntentMeta {
  family: string;
  agent: string;
  description: string;
  default_decision: string;
}

export default function Metrics({ refreshKey }: Props) {
  const confirm = useConfirm();
  const { operator } = useAppContext();
  const [data, setData] = useState<MetricsData | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [auditTotal, setAuditTotal] = useState<number>(0);
  const [healthy, setHealthy] = useState(true);
  const [chain, setChain] = useState<ChainStatus | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [verifyErr, setVerifyErr] = useState<string | null>(null);
  // v14 P2 — join audit rows with intent catalog so hovering a row reveals
  // family / agent / description without a round-trip per hover. Cached once
  // at mount; refreshes naturally when component re-mounts on refreshKey.
  const [intentMeta, setIntentMeta] = useState<Record<string, IntentMeta>>({});
  // v15 audit filter — when any non-empty, switch from the bundled audit
  // payload (in /api/metrics) to a filtered /api/audit fetch.
  const [filterIntent, setFilterIntent] = useState("");
  const [filterDecision, setFilterDecision] = useState("");
  const [filterQ, setFilterQ] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetch("/api/intents", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : { intents: [] }))
      .then((j) => {
        if (cancelled) return;
        const map: Record<string, IntentMeta> = {};
        for (const i of j.intents || []) {
          // Family/agent/decision can differ for same name across families
          // (e.g. "complaint" lives in banking AND fraud). Keep the first
          // entry; tooltips are informational, not load-bearing.
          if (!map[i.name]) {
            map[i.name] = {
              family: i.family,
              agent: i.agent,
              description: i.description,
              default_decision: i.default_decision,
            };
          }
        }
        setIntentMeta(map);
      })
      .catch(() => {
        /* swallow — tooltips just won't render */
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);
  const [replayed, setReplayed] = useState<Record<number, {
    intent: string;
    decision: string;
    deterministic: boolean | null;
    replayable?: boolean;
    age_seconds: number | null;
    prompt_template_hash?: string;
  }>>({});
  const [replaying, setReplaying] = useState<number | null>(null);
  const [tamperResult, setTamperResult] = useState<{
    target_seq: number;
    verify_before_tamper: { valid: boolean; checked: number };
    verify_during_tamper: { valid: boolean; checked: number; first_failure: { seq: number; reason: string; stored?: string; recomputed?: string } | null };
    verify_after_restore: { valid: boolean; checked: number };
    note: string;
  } | null>(null);
  const [tampering, setTampering] = useState(false);
  const [explainSeq, setExplainSeq] = useState<number | null>(null);

  async function runTamperTest() {
    if (!(await confirm("Run tamper-test demo? Mutates one audit entry in memory, checks whether the chain detects it, then restores. Non-destructive."))) return;
    setTampering(true);
    setVerifyErr(null);
    try {
      const r = await fetch("/api/audit/tamper-test", { method: "POST" });
      if (r.ok) {
        setTamperResult(await r.json());
        await verifyChain();
      } else {
        // Don't let the demo's aha moment die silently (backend down / auth on).
        setVerifyErr(`tamper test failed (HTTP ${r.status})`);
      }
    } catch (e) {
      setVerifyErr(`tamper test failed (${e instanceof Error ? e.message : String(e)})`);
    } finally {
      setTampering(false);
    }
  }

  async function replayEntry(seq: number) {
    setReplaying(seq);
    try {
      const r = await fetch(`/api/audit/replay/${seq}`, { cache: "no-store" });
      if (r.ok) {
        const j = await r.json();
        setReplayed((prev) => ({
          ...prev,
          [seq]: {
            intent: j.replay?.intent,
            decision: j.replay?.decision,
            deterministic: j.deterministic,
            replayable: j.replayable,
            age_seconds: j.age_seconds ?? null,
            prompt_template_hash: j.replay_against_version?.prompt_template_hash,
          },
        }));
      }
    } catch {
      /* swallow */
    } finally {
      setReplaying(null);
    }
  }

  async function verifyChain() {
    setVerifying(true);
    setVerifyErr(null);
    try {
      const r = await fetch("/api/audit/verify", { cache: "no-store" });
      if (r.ok) {
        setChain(await r.json());
      } else {
        // Never leave a stale "Chain intact" reading after a failed re-verify —
        // that is a false reassurance on a tamper-evidence panel.
        setVerifyErr(`verify failed (HTTP ${r.status}) — the banner below may be stale`);
      }
    } catch (e) {
      setVerifyErr(`verify failed (${e instanceof Error ? e.message : String(e)}) — the banner below may be stale`);
    } finally {
      setVerifying(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await fetch("/api/metrics", { cache: "no-store" });
        if (!r.ok) {
          if (!cancelled) setHealthy(false);
          return;
        }
        const json = await r.json();
        if (cancelled) return;
        setData(json.metrics);
        setHealthy(true);
        // Audit list: bundled from /api/metrics when no filter, else fetch
        // with filter params via /api/audit so the backend filters in-place.
        const filterActive = filterIntent || filterDecision || filterQ;
        if (!filterActive) {
          setAudit(json.audit?.entries || []);
          setAuditTotal(json.audit?.total ?? 0);
        } else {
          const params = new URLSearchParams({ limit: "10" });
          if (filterIntent) params.set("intent", filterIntent);
          if (filterDecision) params.set("decision", filterDecision);
          if (filterQ) params.set("q", filterQ);
          const ar = await fetch(`/api/audit?${params.toString()}`, { cache: "no-store" });
          if (ar.ok) {
            const aj = await ar.json();
            if (!cancelled) {
              setAudit(aj.entries || []);
              setAuditTotal(aj.total ?? 0);
            }
          }
        }
      } catch {
        if (!cancelled) setHealthy(false);
      }
    };
    tick();
    const interval = setInterval(() => { if (!document.hidden) tick(); }, 15000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [refreshKey, filterIntent, filterDecision, filterQ]);

  // A chain verification / tamper-test describes the FULL window — clear its banner
  // when the audit filter changes so it can't be misread as describing the filtered rows.
  useEffect(() => {
    setChain(null);
    setTamperResult(null);
    setVerifyErr(null);
  }, [filterIntent, filterDecision, filterQ]);

  if (!data) {
    return (
      <div className="card">
        <h2>Metrics</h2>
        <div className="empty">
          {healthy ? "Loading metrics..." : "Service temporarily unavailable. Please try again in a moment."}
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="card">
        <h2>Bridge Metrics (live)<StateBadge feature="bridge-metrics" /></h2>
        <div className="metric-grid">
          <div className="metric">
            <div className="label">Queries</div>
            <div className="value">{data.queries_total}</div>
            <div className="target">processed</div>
          </div>
          <div className="metric">
            <div className="label">Resolution</div>
            <div className={`value ${pctClass(data.resolution_rate, data.target_resolution)}`}>
              {(data.resolution_rate * 100).toFixed(0)}%
            </div>
            <div className="target">target {(data.target_resolution * 100).toFixed(0)}%</div>
          </div>
          <div className="metric">
            <div className="label">Escalation</div>
            <div className={`value ${data.escalation_rate <= 0.10 ? "ok" : "warn"}`}>
              {(data.escalation_rate * 100).toFixed(0)}%
            </div>
            <div className="target">lower is better</div>
          </div>
          <div className="metric">
            <div className="label">Avg Confidence</div>
            <div className={`value ${pctClass(data.avg_confidence, 0.7)}`}>
              {(data.avg_confidence * 100).toFixed(0)}%
            </div>
            <div className="target">threshold 70%</div>
          </div>
          <div className="metric">
            <div className="label">Avg Latency</div>
            <div className="value">{data.avg_latency_ms.toFixed(0)}ms</div>
            <div className="target">end-to-end</div>
          </div>
        </div>
        {(data.p50_latency_ms !== undefined ||
          data.p95_latency_ms !== undefined ||
          data.p99_latency_ms !== undefined) && (
          <div
            style={{
              marginTop: 12,
              padding: "10px 12px",
              background: "var(--bc-bg)",
              border: "1px solid var(--bc-surface)",
              borderRadius: 6,
              fontSize: 12,
              display: "flex",
              gap: 20,
              flexWrap: "wrap",
              alignItems: "baseline",
            }}
          >
            <span className="muted" style={{ textTransform: "uppercase", letterSpacing: 0.5 }}>
              Response time
            </span>
            <span title="Half of answers are faster than this (median, p50)">
              <strong style={{ color: "var(--bc-text-dim)" }}>Typical</strong>{" "}
              {(data.p50_latency_ms ?? 0).toFixed(0)}ms{" "}
              <span className="muted" style={{ fontSize: 10 }}>p50</span>
            </span>
            <span title="The slowest 1 in 20 answers (p95)">
              <strong style={{ color: "#fbbf24" }}>Slowest 5%</strong>{" "}
              {(data.p95_latency_ms ?? 0).toFixed(0)}ms{" "}
              <span className="muted" style={{ fontSize: 10 }}>p95</span>
            </span>
            <span title="The slowest 1 in 100 answers (p99)">
              <strong style={{ color: "#f87171" }}>Worst 1%</strong>{" "}
              {(data.p99_latency_ms ?? 0).toFixed(0)}ms{" "}
              <span className="muted" style={{ fontSize: 10 }}>p99</span>
            </span>
            <span className="muted" style={{ fontSize: 11 }}>
              the slow answers matter more than the average — that&rsquo;s what customers feel (SR 11-7)
            </span>
          </div>
        )}
        <div style={{ marginTop: 16, display: "flex", gap: 8, flexWrap: "wrap", fontSize: 12 }}>
          {Object.entries(data.decisions).map(([k, v]) => (
            <span key={k} className={`badge ${k.toLowerCase()}`}>
              {decisionLabel(k)}: {v}
            </span>
          ))}
        </div>
      </div>

      <div className="card">
        <h2>
          Recent Audit Trail
          <StateBadge feature="audit-trail" />
          {auditTotal > 0 && (
            <span
              className="muted"
              style={{ fontWeight: 400, fontSize: 11, marginLeft: 8, textTransform: "none", letterSpacing: 0 }}
            >
              showing last {audit.length} of {auditTotal}
            </span>
          )}
          {audit.length > 0 && (
            <>
              <button
                type="button"
                className="link-btn"
                onClick={verifyChain}
                title="Recomputes the in-memory window hash and verifies the tamper-evident chain (BCB 4893)"
                style={{ marginLeft: 8 }}
              >
                {verifying ? "verifying…" : "verify chain"}
              </button>
              {verifyErr && <span style={{ color: "var(--bc-block-line)", fontSize: 11, marginLeft: 8 }}>⚠ {verifyErr}</span>}
              <button
                type="button"
                className="link-btn"
                onClick={runTamperTest}
                disabled={tampering}
                title="Demo: mutates one entry in memory, watches the chain detect it, then restores."
                style={{ marginLeft: 8 }}
              >
                {tampering ? "running tamper test…" : "tamper test"}
              </button>
              <button
                type="button"
                className="link-btn"
                onClick={async () => {
                  if (
                    await confirm(
                      "Rotate the audit window? Current entries are removed from in-memory storage. " +
                        "In production they would be archived to cold storage with 5-year retention (BCB 4893). " +
                        "A rotation marker entry starts the new window, preserving the audit-of-audit.",
                    )
                  ) {
                    // A failed rotation must be VISIBLE, and a successful one must
                    // refresh the integrity banner immediately (not wait 15s) — mirror
                    // the file's own verify/tamper handlers instead of swallowing.
                    try {
                      const r = await fetch(`/api/audit?operator=${encodeURIComponent(operator)}`, { method: "DELETE" });
                      if (r.ok) {
                        await verifyChain();
                      } else {
                        setVerifyErr(`rotate failed (HTTP ${r.status}) — the audit window was not rotated`);
                      }
                    } catch (e) {
                      setVerifyErr(`rotate failed (${e instanceof Error ? e.message : String(e)})`);
                    }
                  }
                }}
                title="Archive current entries + start new audit window (admin)"
              >
                rotate window
              </button>
            </>
          )}
        </h2>
        {chain && (
          <div
            style={{
              marginBottom: 10,
              padding: "8px 10px",
              background: chain.valid ? "#052e16" : "#450a0a",
              border: `1px solid ${chain.valid ? "#166534" : "var(--bc-block)"}`,
              borderRadius: 4,
              fontSize: 12,
              color: chain.valid ? "var(--bc-pass-text)" : "#fca5a5",
            }}
          >
            <strong>{chain.valid ? "✓ Chain intact" : "✗ Chain BROKEN"}</strong>{" "}
            · {chain.checked} entries verified · head seq #{chain.head_seq}
            <div
              style={{
                fontFamily: "monospace",
                fontSize: 10,
                color: "var(--bc-text-dim)",
                marginTop: 4,
                wordBreak: "break-all",
              }}
            >
              head_hash {chain.head_hash}
            </div>
            {!chain.valid && chain.first_failure && (
              <div style={{ marginTop: 4 }}>
                First failure at seq #{chain.first_failure.seq}: {chain.first_failure.reason}
              </div>
            )}
          </div>
        )}
        {tamperResult && (
          <div
            style={{
              marginBottom: 10,
              padding: "8px 10px",
              background: "#1c1917",
              border: "1px solid #57534e",
              borderRadius: 4,
              fontSize: 12,
              color: "#e7e5e4",
            }}
          >
            <strong>Tamper test (seq #{tamperResult.target_seq})</strong>
            <ol style={{ margin: "4px 0 4px 18px", padding: 0 }}>
              <li>
                Before tamper:{" "}
                <span style={{ color: tamperResult.verify_before_tamper.valid ? "var(--bc-pass-text)" : "#fca5a5" }}>
                  {tamperResult.verify_before_tamper.valid ? "intact ✓" : "broken ✗"}
                </span>{" "}
                ({tamperResult.verify_before_tamper.checked} entries)
              </li>
              <li>
                During tamper:{" "}
                <span style={{ color: tamperResult.verify_during_tamper.valid ? "var(--bc-pass-text)" : "#fca5a5" }}>
                  {tamperResult.verify_during_tamper.valid ? "intact ✓ (BUG — should have failed)" : "broken ✗ (chain detected it)"}
                </span>
                {tamperResult.verify_during_tamper.first_failure && (
                  <div style={{ fontSize: 11, color: "#fca5a5", marginLeft: 14 }}>
                    failure at seq #{tamperResult.verify_during_tamper.first_failure.seq}:{" "}
                    {tamperResult.verify_during_tamper.first_failure.reason}
                    {tamperResult.verify_during_tamper.first_failure.stored && (
                      <div style={{ fontFamily: "monospace", fontSize: 10, color: "#a8a29e", marginTop: 2, wordBreak: "break-all" }}>
                        stored&nbsp;{tamperResult.verify_during_tamper.first_failure.stored}
                        <br />
                        recomputed {tamperResult.verify_during_tamper.first_failure.recomputed}
                      </div>
                    )}
                  </div>
                )}
              </li>
              <li>
                After restore:{" "}
                <span style={{ color: tamperResult.verify_after_restore.valid ? "var(--bc-pass-text)" : "#fca5a5" }}>
                  {tamperResult.verify_after_restore.valid ? "intact ✓ (reverted)" : "broken ✗"}
                </span>
              </li>
            </ol>
            <div style={{ fontSize: 10, color: "#a8a29e" }}>{tamperResult.note}</div>
          </div>
        )}
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8, fontSize: 11 }}>
          <input
            type="text"
            placeholder="filter by intent"
            value={filterIntent}
            onChange={(e) => setFilterIntent(e.target.value)}
            style={{ width: 120, padding: "2px 6px" }}
          />
          <select
            aria-label="filter by decision"
            value={filterDecision}
            onChange={(e) => setFilterDecision(e.target.value)}
            style={{ width: 110, padding: "2px 6px" }}
          >
            <option value="">any decision</option>
            <option value="PASSTHROUGH">{decisionLabel("PASSTHROUGH")}</option>
            <option value="FLAG">{decisionLabel("FLAG")}</option>
            <option value="REASK">{decisionLabel("REASK")}</option>
            <option value="ESCALATE">{decisionLabel("ESCALATE")}</option>
          </select>
          <input
            type="text"
            placeholder="search masked query"
            value={filterQ}
            onChange={(e) => setFilterQ(e.target.value)}
            style={{ flex: 1, minWidth: 140, padding: "2px 6px" }}
          />
          {(filterIntent || filterDecision || filterQ) && (
            <button
              type="button"
              className="link-btn"
              onClick={() => {
                setFilterIntent("");
                setFilterDecision("");
                setFilterQ("");
              }}
              style={{ fontSize: 11 }}
            >
              clear
            </button>
          )}
        </div>
        {audit.length === 0 ? (
          <div className="empty">
            No entries in the current audit window (it may have been rotated; the metrics above
            count the whole session).
          </div>
        ) : (
          <div className="audit-list">
            {audit.map((e, i) => {
              const rep = e.seq !== undefined ? replayed[e.seq] : undefined;
              return (
                <div key={i} className="audit-entry">
                  <div className="row">
                    <span>
                      {e.seq !== undefined && (
                        <span
                          className="muted"
                          style={{
                            fontFamily: "monospace",
                            fontSize: 10,
                            marginRight: 6,
                            padding: "1px 4px",
                            background: "var(--bc-bg)",
                            borderRadius: 2,
                          }}
                          title={e.hash ? `hash ${e.hash}` : ""}
                        >
                          #{e.seq}
                        </span>
                      )}
                      {new Date(e.ts * 1000).toLocaleTimeString()} · {e.channel} · intent:{" "}
                      {(() => {
                        const meta = intentMeta[e.intent];
                        const tip = meta
                          ? `${e.intent} · family=${meta.family} · agent=${meta.agent}` +
                            ` · default=${meta.default_decision}\n${meta.description}`
                          : e.intent;
                        return (
                          <strong
                            title={tip}
                            style={{
                              borderBottom: meta ? "1px dotted var(--bc-text-mute)" : undefined,
                              cursor: meta ? "help" : "default",
                            }}
                          >
                            {humanizeIntent(e.intent)}
                          </strong>
                        );
                      })()}
                    </span>
                    <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
                      <span className={`badge ${e.decision.toLowerCase()}`}>{decisionLabel(e.decision)}</span>
                      {e.seq !== undefined && (
                        <button
                          type="button"
                          className="link-btn"
                          style={{ fontSize: 10 }}
                          onClick={() => replayEntry(e.seq!)}
                          disabled={replaying === e.seq}
                          title="Re-runs classify_intent + apply_guard on this stored query (no LLM, no new audit record)"
                        >
                          {replaying === e.seq ? "replaying…" : "replay"}
                        </button>
                      )}
                      {e.seq !== undefined && (
                        <button
                          type="button"
                          className="link-btn"
                          style={{ fontSize: 10 }}
                          onClick={() => setExplainSeq(e.seq!)}
                          title="LGPD Art. 20: why this decision was made + chain proof (modal)"
                        >
                          explain
                        </button>
                      )}
                    </span>
                  </div>
                  <div className="query">{e.query}</div>
                  {rep && (
                    <div
                      style={{
                        fontSize: 11,
                        marginTop: 4,
                        padding: "3px 6px",
                        background: rep.replayable === false ? "var(--bc-surface)" : rep.deterministic ? "#052e16" : "#450a0a",
                        color: rep.replayable === false ? "var(--bc-text-dim)" : rep.deterministic ? "var(--bc-pass-text)" : "#fca5a5",
                        borderRadius: 3,
                        border: `1px solid ${rep.replayable === false ? "var(--bc-border)" : rep.deterministic ? "#166534" : "var(--bc-block)"}`,
                      }}
                    >
                      {rep.replayable === false ? "—" : rep.deterministic ? "✓" : "✗"} replay → intent={rep.intent} decision={rep.decision}{" "}
                      {rep.replayable === false
                        ? "(N/A — entry did not go through the /query classifier)"
                        : rep.deterministic
                          ? "(matches original)"
                          : "(DEVIATION from original)"}
                      <div style={{ fontSize: 10, color: "var(--bc-text-dim)", marginTop: 2 }}>
                        original processed{" "}
                        {rep.age_seconds !== null
                          ? rep.age_seconds < 60
                            ? `${Math.round(rep.age_seconds)}s ago`
                            : rep.age_seconds < 3600
                            ? `${Math.round(rep.age_seconds / 60)}min ago`
                            : `${Math.round(rep.age_seconds / 3600)}h ago`
                          : "unknown"}
                        {rep.prompt_template_hash &&
                          ` · replayed with prompt ${rep.prompt_template_hash.slice(0, 8)}`}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <ExplainModal seq={explainSeq} onClose={() => setExplainSeq(null)} />
    </>
  );
}
