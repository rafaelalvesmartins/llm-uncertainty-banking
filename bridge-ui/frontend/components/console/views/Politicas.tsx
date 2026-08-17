"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { getJSON } from "@/components/console/api";
import { apiErrorText } from "@/lib/apiError";
import { useAppContext } from "@/components/AppContextProvider";
import StateBadge from "@/components/StateBadge";
import ChannelFirewall from "@/components/console/ChannelFirewall";
import DecisionLegend from "@/components/console/DecisionLegend";
import { humanizeIntent } from "@/components/console/types";

// ---- Shape: GET /api/settings ----
interface Settings {
  guard_threshold: number;
  guard_threshold_default: number;
  guard_threshold_min: number;
  guard_threshold_max: number;
  cache_enabled: boolean;
  backend: string;
  backend_is_real: boolean;
  backend_mutable: boolean;
}

// ---- Shape: GET /api/intents ----
interface IntentEntry {
  name: string;
  family: "banking" | "fraud" | "safety";
  agent: string;
  default_decision: string;
  description: string;
  samples: string[];
  count: number;
  percent: number;
}

interface IntentsPayload {
  intents: IntentEntry[];
  families: Record<string, number>;
  total_queries: number;
  catalog_size: number;
}

// ---- Decision → badge class mapping ----
const DECISION_BADGE: Record<string, string> = {
  ESCALATE: "block",
  FLAG: "flag",
  REASK: "reask",
  PASSTHROUGH: "pass",
};

// "by-confidence" means the guard threshold decides — render as a dim chip, not a badge.
const DECISION_LABEL: Record<string, string> = {
  "by-confidence": "by confidence",
  ESCALATE: "Escalate",
  FLAG: "Flag",
  REASK: "Re-ask",
  PASSTHROUGH: "Pass",
};

const FAMILY_DOT: Record<string, string> = {
  banking: "pass",
  fraud: "flag",
  safety: "block",
};

const FAMILY_LABEL: Record<string, string> = {
  banking: "banking",
  fraud: "fraud",
  safety: "safety",
};

// ── "Propose a policy change" form spec. Policies are SECURITY-relevant, so a
// new/changed intent or DQ rule goes through the governed-change workflow
// (proposed → approved by a different operator → applied) rather than mutating
// live config. The guard threshold above is the one knob tuned directly (it's a
// runtime demo control, not a governed artifact).
type PField = { name: string; label: string; type?: "text" | "textarea" | "number" | "select"; options?: string[]; placeholder?: string };
type PFields = Record<string, string>;
const splitLines = (s: string): string[] => (s || "").split("\n").map((x) => x.trim()).filter(Boolean);
const toNum = (s: string): number | null => (s?.trim() ? Number(s) : null);

const POLICY_KINDS: Record<string, { label: string; fields: PField[]; required: string[]; summary: (f: PFields) => string; payload: (f: PFields) => Record<string, unknown> }> = {
  intent: {
    label: "Intent decision policy",
    fields: [
      { name: "name", label: "Intent name", placeholder: "e.g. pix_scheduled" },
      { name: "family", label: "Family", type: "select", options: ["banking", "fraud", "safety"] },
      { name: "default_decision", label: "Default decision", type: "select", options: ["by-confidence", "PASSTHROUGH", "FLAG", "REASK", "ESCALATE"] },
      { name: "threshold", label: "Override threshold (optional)", type: "number", placeholder: "0.00–1.00" },
      { name: "samples", label: "Sample utterances (one per line)", type: "textarea", placeholder: "schedule a pix for tomorrow" },
    ],
    required: ["name"],
    summary: (f) => `Policy: intent "${f.name}" → ${f.default_decision || "by-confidence"}`.slice(0, 300),
    payload: (f) => ({ name: f.name?.trim(), family: f.family || "banking", default_decision: f.default_decision || "by-confidence", threshold: toNum(f.threshold), samples: splitLines(f.samples) }),
  },
  dq_rule: {
    label: "Data-quality rule",
    fields: [
      { name: "name", label: "Rule name", placeholder: "e.g. max_message_length" },
      { name: "condition", label: "Condition", placeholder: "e.g. len(message) > threshold" },
      { name: "threshold", label: "Threshold", type: "number", placeholder: "e.g. 5000" },
      { name: "severity", label: "Severity", type: "select", options: ["warning", "blocking"] },
    ],
    required: ["name", "condition"],
    summary: (f) => `Policy: DQ rule "${f.name}": ${f.condition}`.slice(0, 300),
    payload: (f) => ({ name: f.name?.trim(), condition: f.condition?.trim(), threshold: toNum(f.threshold), severity: f.severity || "warning" }),
  },
};

export default function Politicas() {
  const { operator } = useAppContext();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [settingsErr, setSettingsErr] = useState<string | null>(null);

  const [intents, setIntents] = useState<IntentsPayload | null>(null);
  const [intentsErr, setIntentsErr] = useState<string | null>(null);

  // Guard-threshold adjuster (runtime control — PUT /api/settings).
  const [pendingThreshold, setPendingThreshold] = useState<number | null>(null);
  const [savingThreshold, setSavingThreshold] = useState(false);
  const [thresholdNote, setThresholdNote] = useState<{ ok: boolean; text: string } | null>(null);
  // Live mirror of pendingThreshold so the 15s settings poll doesn't clobber an
  // in-progress slider edit (it skips setSettings while an edit is pending).
  const pendingRef = useRef<number | null>(null);
  pendingRef.current = pendingThreshold;

  // Propose-a-policy form (governed change).
  const [policyKind, setPolicyKind] = useState<keyof typeof POLICY_KINDS>("intent");
  const [policyFields, setPolicyFields] = useState<PFields>({});
  const [proposing, setProposing] = useState(false);
  const [proposeNote, setProposeNote] = useState<{ ok: boolean; text: string } | null>(null);

  // Independent fetches — one error does not block the other section.
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      getJSON<Settings>("/api/settings")
        .then((d) => { if (!cancelled) { if (pendingRef.current === null) setSettings(d); setSettingsErr(null); } })
        .catch((e: unknown) => {
          if (!cancelled) setSettingsErr(e instanceof Error ? e.message : "unknown error");
        });
    load();
    // Poll so out-of-band changes surface without a manual tab revisit.
    const id = setInterval(() => { if (!document.hidden) load(); }, 15000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      getJSON<IntentsPayload>("/api/intents")
        .then((d) => { if (!cancelled) setIntents(d); })
        .catch((e: unknown) => {
          if (!cancelled) setIntentsErr(e instanceof Error ? e.message : "unknown error");
        });
    load();
    const id = setInterval(() => { if (!document.hidden) load(); }, 15000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  // Persist a moved threshold a beat after the last change (keyboard + drag both work).
  const settingsRef = useRef(settings);
  settingsRef.current = settings;
  useEffect(() => {
    if (pendingThreshold === null) return;
    const cur = settingsRef.current;
    if (cur && pendingThreshold === cur.guard_threshold) return;
    const t = setTimeout(async () => {
      setSavingThreshold(true);
      setThresholdNote(null);
      try {
        const r = await fetch("/api/settings", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          // Attribute the change so it lands on the audit hash-chain with an operator.
          body: JSON.stringify({ guard_threshold: pendingThreshold, operator }),
        });
        const j = await r.json().catch(() => null);
        if (!r.ok) {
          // Revert the thumb to the real server value so the slider reflects
          // reality and a same-value retry is possible (React bails on an
          // identical setState, so a stuck pending value would block retries).
          setThresholdNote({ ok: false, text: apiErrorText(j, r.status) });
          setPendingThreshold(null);
        } else {
          setSettings(j);
          setPendingThreshold(null);
          setThresholdNote({ ok: true, text: `threshold policy set to ${Number(j.guard_threshold).toFixed(2)} — applies to the next query` });
        }
      } catch (e) {
        setThresholdNote({ ok: false, text: e instanceof Error ? e.message : String(e) });
        setPendingThreshold(null);
      } finally {
        setSavingThreshold(false);
      }
    }, 350);
    return () => clearTimeout(t);
  }, [pendingThreshold, operator]);

  const pspec = POLICY_KINDS[policyKind];
  const policyValid = pspec.required.every((r) => (policyFields[r] || "").trim());
  const policyPayload = useMemo(() => pspec.payload(policyFields), [pspec, policyFields]);
  const policySummary = useMemo(() => pspec.summary(policyFields), [pspec, policyFields]);

  function setPolicyField(name: string, value: string) {
    setPolicyFields((f) => ({ ...f, [name]: value }));
  }
  function selectPolicyKind(k: keyof typeof POLICY_KINDS) {
    setPolicyKind(k);
    setPolicyFields({});
    setProposeNote(null);
  }
  // Pre-fill the form to PROPOSE changing an existing intent's decision policy.
  function proposeForIntent(it: IntentEntry) {
    setPolicyKind("intent");
    setPolicyFields({
      name: it.name,
      family: it.family,
      default_decision: it.default_decision,
      threshold: "",
      samples: (it.samples || []).join("\n"),
    });
    setProposeNote(null);
  }

  async function proposePolicy() {
    if (!policyValid || proposing) return;
    setProposing(true);
    setProposeNote(null);
    try {
      const r = await fetch("/api/governance/changes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: policyKind, summary: policySummary.trim(), submitted_by: operator, payload: policyPayload }),
        cache: "no-store",
      });
      const j = await r.json().catch(() => null);
      if (!r.ok) {
        setProposeNote({ ok: false, text: apiErrorText(j, r.status) });
        return;
      }
      setPolicyFields({});
      const dup = j?.duplicate_warning ? ` ${j.duplicate_warning}` : "";
      setProposeNote({
        ok: true,
        text:
          `Proposed as change #${j?.id} (${String(j?.config_hash || "").slice(0, 12)}…). ` +
          "Next: a different person approves it, and a third applies it (in the Governance tab) — so no one changes a policy alone. " +
          (policyKind === "intent"
            ? "Once applied, this intent policy takes effect on the next queries (within a few seconds)."
            : "Once applied, this DQ-rule change is recorded as governed evidence (not yet enforced at runtime).") + dup,
      });
    } catch (e) {
      setProposeNote({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setProposing(false);
    }
  }

  const shownThreshold = pendingThreshold ?? settings?.guard_threshold ?? 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <p style={{ fontSize: 12.5, color: "var(--bc-text-mute)", margin: 0, lineHeight: 1.55 }}>
        <strong style={{ color: "var(--bc-text)" }}>What this does:</strong>{" "}
        {"Set what each channel is allowed to do — just follow the numbered steps below. The global cautiousness setting and the full rule reference are under 'Advanced', so this screen stays simple."}
      </p>

      {/* ── Channel firewall (per-channel intent allow-list, governed) — the headline policy ── */}
      <ChannelFirewall />

      {/* Everything below is secondary — collapsed by default so the screen stays simple. */}
      <details>
        <summary
          style={{
            cursor: "pointer",
            fontSize: 13,
            fontWeight: 600,
            color: "var(--bc-text-dim)",
            padding: "8px 2px",
            userSelect: "none",
          }}
        >
          Advanced — global cautiousness, rule catalog &amp; legend
        </summary>
        <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 8 }}>

      {/* ── Card 1: Guard configuration (threshold is adjustable here) ── */}
      <div className="bc-card">
        <div className="bc-card-h">
          <h2>
            Guard Configuration
            <StateBadge feature="demo-controls" />
          </h2>
          <span style={{ fontSize: 11, color: "var(--bc-text-mute)" }}>
            adjust the threshold policy here — applies to the next query
          </span>
        </div>

        {settingsErr && !settings && (
          <div className="bc-error">Backend unreachable: {settingsErr}</div>
        )}

        {!settings && !settingsErr && (
          <div className="bc-loading">loading configuration…</div>
        )}

        {settings && (
          <>
            {/* Interactive threshold slider — the headline policy knob */}
            <div className="bc-metric" style={{ marginBottom: 12 }}>
              <div className="bc-metric-label">
                Guard threshold policy {savingThreshold && <span style={{ color: "var(--bc-text-mute)" }}>· applying…</span>}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 6, flexWrap: "wrap" }}>
                <input
                  type="range"
                  min={settings.guard_threshold_min}
                  max={settings.guard_threshold_max}
                  step={0.05}
                  value={shownThreshold}
                  onChange={(e) => setPendingThreshold(parseFloat(e.target.value))}
                  aria-label="guard threshold"
                  style={{ flex: 1, minWidth: 200 }}
                />
                <span className="bc-metric-value" style={{ fontVariantNumeric: "tabular-nums", minWidth: 56 }}>
                  {shownThreshold.toFixed(2)}
                </span>
              </div>
              <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 4 }}>
                default {settings.guard_threshold_default.toFixed(2)} · range [{settings.guard_threshold_min.toFixed(2)}, {settings.guard_threshold_max.toFixed(2)}]
                · lower → the AI answers more on its own · higher → more get reviewed, re-asked, or sent to a human · also in Config
              </div>
              {thresholdNote && (
                <div style={{ fontSize: 11, marginTop: 4, color: thresholdNote.ok ? "var(--bc-pass-text)" : "var(--bc-block-text)" }}>
                  {thresholdNote.ok ? "✓ " : "⚠ "}{thresholdNote.text}
                </div>
              )}
            </div>

            <div className="bc-grid-2" style={{ gap: 12 }}>
              <div className="bc-metric">
                <div className="bc-metric-label">Similarity cache</div>
                <div className={`bc-metric-value ${settings.cache_enabled ? "pass" : "block"}`}>
                  {settings.cache_enabled ? "ON" : "OFF"}
                </div>
                <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 4 }}>
                  {settings.cache_enabled ? "repeated queries are short-circuited" : "every query re-executes the full pipeline"}
                </div>
              </div>

              <div className="bc-metric">
                <div className="bc-metric-label">Backend LLM</div>
                <div className="bc-metric-value" style={{ fontSize: 16 }} title={settings.backend}>{settings.backend === "fake" ? "Demo (fixed answers)" : settings.backend}</div>
                <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 4 }}>
                  {settings.backend_is_real ? "real LLM" : "canned responses"}&nbsp;·&nbsp;fixed for this demo
                </div>
              </div>

              <div className="bc-metric">
                <div className="bc-metric-label">Threshold policy</div>
                <div style={{ fontSize: 13, color: "var(--bc-text-dim)", marginTop: 6, lineHeight: 1.6 }}>
                  Confidence &ge; threshold → <span className="bc-badge pass" style={{ fontSize: 11, padding: "1px 6px" }}>PASSTHROUGH</span>
                  <br />
                  Below → <span className="bc-badge flag" style={{ fontSize: 11, padding: "1px 6px" }}>FLAG</span>
                  &nbsp;/&nbsp;
                  <span className="bc-badge reask" style={{ fontSize: 11, padding: "1px 6px" }}>REASK</span>
                  <br />
                  High-risk intents → <span className="bc-badge block" style={{ fontSize: 11, padding: "1px 6px" }}>ESCALATE</span> always
                </div>
              </div>
            </div>
          </>
        )}
      </div>

      {/* ── Card 2: Propose a policy change (governed) ── */}
      {/* id is load-bearing: the firewall wizard's "Add a request type" link scrolls here (see COORDINATION.md). */}
      <div className="bc-card" id="propose-policy-form">
        <div className="bc-card-h">
          <h2>
            Propose a Policy Change
            <StateBadge feature="governed-changes" />
          </h2>
          <span style={{ fontSize: 11, color: "var(--bc-text-mute)" }}>
            governed: proposed → approved (different operator) → applied
          </span>
        </div>

        <div style={{ fontSize: 11, color: "var(--bc-text-dim)", background: "var(--bc-surface-2)", border: "1px solid var(--bc-border)", borderRadius: 6, padding: "7px 9px", marginBottom: 10, lineHeight: 1.5 }}>
          ⓘ <strong>Intent decision policies take effect</strong> on the live pipeline within a few seconds of being applied — the <code>/query</code> path consults the governed system-of-record, so a new intent becomes classifiable (by its samples) and any intent gets its governed decision/threshold. <strong>Data-quality rule</strong> proposals are recorded as governed evidence and are <strong>not yet enforced</strong> at runtime. Provider &amp; channel connections (Connections tab) also write the live system-of-record.
        </div>

        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
          {Object.entries(POLICY_KINDS).map(([k, s]) => (
            <button
              key={k}
              type="button"
              className="bc-btn"
              onClick={() => selectPolicyKind(k as keyof typeof POLICY_KINDS)}
              style={{ fontSize: 12, fontWeight: policyKind === k ? 700 : 400, opacity: policyKind === k ? 1 : 0.7 }}
            >
              {s.label}
            </button>
          ))}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
          {pspec.fields.map((f) => (
            <div key={f.name} style={{ gridColumn: f.type === "textarea" ? "1 / -1" : undefined }}>
              <label style={{ fontSize: 10, color: "var(--bc-text-mute)", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 3, display: "block" }}>
                {f.label}{pspec.required.includes(f.name) ? " *" : ""}
              </label>
              {f.type === "select" ? (
                <select className="bc-input" aria-label={f.label} value={policyFields[f.name] ?? f.options?.[0] ?? ""} onChange={(e) => setPolicyField(f.name, e.target.value)} style={{ width: "100%" }}>
                  {f.options?.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              ) : f.type === "textarea" ? (
                <textarea className="bc-input" value={policyFields[f.name] ?? ""} onChange={(e) => setPolicyField(f.name, e.target.value)} placeholder={f.placeholder} rows={3} style={{ width: "100%", resize: "vertical" }} />
              ) : (
                <input className="bc-input" type={f.type === "number" ? "number" : "text"} value={policyFields[f.name] ?? ""} onChange={(e) => setPolicyField(f.name, e.target.value)} placeholder={f.placeholder} style={{ width: "100%" }} />
              )}
            </div>
          ))}
        </div>

        <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginBottom: 8 }}>
          will record: <span style={{ color: "var(--bc-text-dim)" }}>{policyValid ? policySummary : "fill the required fields…"}</span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button type="button" className="bc-btn" onClick={proposePolicy} disabled={proposing || !policyValid} style={{ fontSize: 13 }}>
            Propose as {operator}
          </button>
          {!policyValid && (
            <span style={{ fontSize: 11, color: "var(--bc-text-mute)" }}>Fill {pspec.required.join(" + ")} to enable.</span>
          )}
        </div>
        {proposeNote && (
          <div
            style={{
              marginTop: 8,
              fontSize: 12,
              padding: "8px 10px",
              borderRadius: 6,
              background: proposeNote.ok ? "var(--bc-pass)" : "var(--bc-block)",
              border: `1px solid ${proposeNote.ok ? "var(--bc-pass-line)" : "var(--bc-block-line)"}`,
              color: proposeNote.ok ? "var(--bc-pass-text)" : "var(--bc-block-text)",
            }}
          >
            {proposeNote.ok ? "✓ " : "⚠ "}{proposeNote.text}
            {proposeNote.ok && (
              <>
                {" "}
                <button
                  type="button"
                  className="link-btn"
                  onClick={() => {
                    if (typeof window === "undefined") return;
                    window.location.hash = "governance";
                    window.dispatchEvent(new CustomEvent("bridge:goto", { detail: { view: "governance" } }));
                  }}
                >
                  Open Governance →
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {/* ── Card 3: Intent catalog / rule set ── */}
      <div className="bc-card">
        <div className="bc-card-h">
          <h2>
            Intent Catalog / Rules
            <StateBadge feature="intent-catalog" />
          </h2>
          {intents && (
            <span style={{ fontSize: 11, color: "var(--bc-text-mute)" }}>
              {intents.catalog_size} rules · {intents.total_queries} queries since service start
            </span>
          )}
        </div>

        {intentsErr && !intents && (
          <div className="bc-error">Could not load intents: {intentsErr}</div>
        )}

        {!intents && !intentsErr && (
          <div className="bc-loading">loading intent catalog…</div>
        )}

        {intents && intents.intents.length === 0 && (
          <div className="bc-empty">Catalog is empty.</div>
        )}

        {intents && intents.intents.length > 0 && (
          <table className="bc-table">
            <thead>
              <tr>
                <th>Intent</th>
                <th>Family</th>
                <th>Agent</th>
                <th>Default decision</th>
                <th style={{ textAlign: "right" }}>Hits</th>
                <th style={{ textAlign: "right" }}>Policy</th>
              </tr>
            </thead>
            <tbody>
              {intents.intents.map((intent, idx) => {
                const decisionKey = intent.default_decision;
                const badgeClass = DECISION_BADGE[decisionKey] ?? "";
                const isHardRule = decisionKey !== "by-confidence";
                return (
                  <tr key={`${intent.name}-${intent.family}-${idx}`}>
                    <td>
                      <span style={{ fontWeight: 600, color: "var(--bc-text)" }} title={intent.name}>{humanizeIntent(intent.name)}</span>
                    </td>
                    <td>
                      <span className="bc-chip" style={{ gap: 4, padding: "2px 8px", fontSize: 11 }}>
                        <span className={`bc-dot ${FAMILY_DOT[intent.family] ?? ""}`} />
                        {FAMILY_LABEL[intent.family] ?? intent.family}
                      </span>
                    </td>
                    <td style={{ color: "var(--bc-text-dim)", fontSize: 12 }}>{intent.agent}</td>
                    <td>
                      {isHardRule ? (
                        <span className={`bc-badge ${badgeClass}`} style={{ fontSize: 11 }}>
                          {DECISION_LABEL[decisionKey] ?? decisionKey}
                        </span>
                      ) : (
                        <span style={{ fontSize: 11, color: "var(--bc-text-mute)" }} title="No fixed rule — the caution slider decides (Pass / Flag / Re-ask / Escalate) from the AI's confidence.">{DECISION_LABEL[decisionKey]}</span>
                      )}
                    </td>
                    <td style={{ textAlign: "right", color: "var(--bc-text-dim)", fontSize: 12 }}>
                      {intent.count > 0 ? (
                        <>
                          {intent.count}
                          <span style={{ color: "var(--bc-text-mute)", marginLeft: 4 }}>({intent.percent}%)</span>
                        </>
                      ) : (
                        <span style={{ color: "var(--bc-text-mute)" }}>—</span>
                      )}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <button
                        type="button"
                        className="bc-btn ghost"
                        onClick={() => proposeForIntent(intent)}
                        title="Pre-fill the proposal form above to change this intent's decision policy (governed)."
                        style={{ fontSize: 11, padding: "2px 8px" }}
                      >
                        change
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* ── Card 4: Decision policy legend (shared, plain-language) ── */}
      <div className="bc-card">
        <div className="bc-card-h">
          <h2>Legend — Decision Policy</h2>
        </div>
        <DecisionLegend title="What each decision means" />
      </div>
        </div>
      </details>

    </div>
  );
}
