"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import StateBadge from "@/components/StateBadge";
import { useAppContext, OPERATORS } from "@/components/AppContextProvider";
import { apiErrorText } from "@/lib/apiError";
import { humanizeIntent } from "@/components/console/types";

// Customer-facing channels the pipeline branches on (QueryRequest.channel). A
// channel_policy is keyed by these values.
const CHANNELS: { value: string; label: string }[] = [
  { value: "app", label: "Mobile app" },
  { value: "whatsapp", label: "WhatsApp" },
  { value: "web", label: "Web chat" },
  { value: "call_center", label: "Call center" },
];

const FAMILY_LABEL: Record<string, string> = {
  banking: "Banking",
  fraud: "Fraud",
  safety: "Safety",
};

const STEPS = [
  { n: 1, title: "Channel" },
  { n: 2, title: "Allow" },
  { n: 3, title: "Test" },
  { n: 4, title: "Propose" },
  { n: 5, title: "Approve" },
];

interface Intent {
  name: string;
  family: string;
}

interface Change {
  id: number;
  kind: string;
  summary: string;
  submitted_by: string;
  status: string;
  reviewer: string | null;
}

const STATUS_COLOR: Record<string, string> = {
  pending: "var(--bc-flag-line)",
  approved: "var(--bc-pass-line)",
  applied: "var(--bc-info-line)",
  rejected: "var(--bc-block-line)",
};

/** Open the governed "Propose a Policy Change → Intent" form (it lives in Politicas's
 *  collapsed "Advanced" section — another session's file) by reaching the rendered DOM:
 *  open that <details> and scroll to the form. Lets an operator register a NEW request
 *  type without leaving the firewall, and without us editing their component. */
function openAddRequestType(): void {
  // Prefer the stable anchor Politicas exposes (id="propose-policy-form", see
  // COORDINATION.md); fall back to a heading-text match if it's ever missing.
  let target: HTMLElement | null = document.getElementById("propose-policy-form");
  if (!target) {
    const advSummary = Array.from(document.querySelectorAll<HTMLElement>("details > summary")).find(
      (s) => /advanced/i.test(s.textContent || ""),
    );
    const adv = advSummary?.closest("details");
    target =
      (adv && Array.from(adv.querySelectorAll<HTMLElement>("h2")).find((h) => /propose a policy/i.test(h.textContent || ""))) ||
      advSummary ||
      null;
  }
  if (!target) return;
  const details = target.closest("details") as HTMLDetailsElement | null;
  if (details) details.open = true;
  target.scrollIntoView({ behavior: "smooth", block: "start" });
}

/**
 * Channel firewall — per-channel intent allow-list, governed. A one-step-at-a-time
 * wizard: (1) pick a channel, (2) choose what it may handle, (3) test, (4) propose,
 * (5) approve & apply — all governed (channel_policy → /query pipeline enforces it).
 */
export default function ChannelFirewall() {
  const { operator, setOperator } = useAppContext();
  const [step, setStep] = useState(1);
  const [intents, setIntents] = useState<Intent[]>([]);
  const [policies, setPolicies] = useState<Record<string, string[]>>({});
  const [changes, setChanges] = useState<Change[]>([]);
  const [selected, setSelected] = useState("whatsapp");
  const [draft, setDraft] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);

  const [sim, setSim] = useState("");
  const [simBusy, setSimBusy] = useState(false);
  const [simOut, setSimOut] = useState<{ intent: string; allowed: boolean } | null>(null);

  const load = useCallback(async () => {
    const [ic, ac, ch] = await Promise.all([
      fetch("/api/intents", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).catch(() => null),
      fetch("/api/governance/active-configs?domain=channel_policy", { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null),
      fetch("/api/governance/changes", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).catch(() => null),
    ]);
    if (ic?.intents) setIntents(ic.intents.map((i: Intent) => ({ name: i.name, family: i.family })));
    const map: Record<string, string[]> = {};
    for (const c of ac?.configs ?? []) {
      const al = (c.config as Record<string, unknown> | undefined)?.allowed_intents;
      if (Array.isArray(al)) map[c.name] = al.map(String);
    }
    setPolicies(map);
    setChanges((ch?.changes ?? []).filter((c: Change) => c.kind === "channel_policy"));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Reset the editable draft to the channel's APPLIED allow-list whenever the
  // selection or the loaded policies change.
  useEffect(() => {
    setDraft(new Set(policies[selected] ?? []));
    setNote(null);
    setSimOut(null);
  }, [selected, policies]);

  const applied = policies[selected] ?? null;
  const dirty = useMemo(() => {
    const a = new Set(applied ?? []);
    if (a.size !== draft.size) return true;
    for (const x of draft) if (!a.has(x)) return true;
    return false;
  }, [applied, draft]);

  const byFamily = useMemo(() => {
    const g: Record<string, Intent[]> = {};
    for (const it of intents) (g[it.family] ??= []).push(it);
    return g;
  }, [intents]);

  function toggle(name: string) {
    setDraft((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  async function propose() {
    setBusy(true);
    setNote(null);
    try {
      const allowed = [...draft].sort();
      const r = await fetch("/api/governance/changes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: "channel_policy",
          summary: `Channel firewall: ${selected} allows [${allowed.join(", ") || "—"}]`,
          submitted_by: operator,
          payload: { name: selected, allowed_intents: allowed },
        }),
        cache: "no-store",
      });
      const j = await r.json().catch(() => null);
      if (!r.ok) {
        setNote({ ok: false, text: apiErrorText(j, r.status) });
      } else {
        setNote({ ok: true, text: `Proposed as change #${j?.id}. Now approve it as a different operator, then apply as a third.` });
        await load();
        setStep(5); // jump to approve & apply
        return;
      }
      await load();
    } catch (e) {
      setNote({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }

  // Inline governed action so the operator never leaves this card. Mirrors the
  // ConnectionGovernance endpoints + four-eyes (decision: reviewer ≠ submitter;
  // apply: applier ≠ submitter and ≠ reviewer) — the server enforces it too.
  async function act(id: number, action: "approve" | "reject" | "apply") {
    setBusy(true);
    setNote(null);
    try {
      const url =
        action === "apply"
          ? `/api/governance/changes/${id}/apply`
          : `/api/governance/changes/${id}/decision`;
      const body = action === "apply" ? { applier: operator } : { decision: action, reviewer: operator };
      const r = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        cache: "no-store",
      });
      const j = await r.json().catch(() => null);
      if (!r.ok) setNote({ ok: false, text: apiErrorText(j, r.status) });
      else setNote({ ok: true, text: action === "apply" ? `Applied — the firewall on this channel is now live.` : `Change #${id} ${action}d.` });
      await load();
    } catch (e) {
      setNote({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }

  async function simulate() {
    const text = sim.trim();
    if (!text) return;
    setSimBusy(true);
    setSimOut(null);
    try {
      const r = await fetch("/api/playground/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: text }),
        cache: "no-store",
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = await r.json();
      const intent = String(j.intent ?? "");
      // Mirror the backend rule: a NON-EMPTY draft is the allow-list; an empty draft
      // means "no restriction". Off-list → would be escalated.
      const allowed = draft.size === 0 || draft.has(intent);
      setSimOut({ intent, allowed });
    } catch {
      setSimOut(null);
    } finally {
      setSimBusy(false);
    }
  }

  const cell = { fontSize: 12, display: "flex", alignItems: "center", gap: 6, cursor: "pointer" } as const;
  const primary = { background: "var(--bc-accent, #2563eb)", borderColor: "var(--bc-accent, #2563eb)", color: "#fff", fontWeight: 600 } as const;

  return (
    <div className="bc-card">
      <div className="bc-card-h">
        <h2>
          Channel rules (firewall)
          <StateBadge feature="governed-changes" />
        </h2>
        <span style={{ fontSize: 11, color: "var(--bc-text-mute)" }}>one step at a time — which request types a channel may handle (add the channel itself in Connections)</span>
      </div>

      {/* Overview — see every channel's rule at a glance; edit one or add a rule to a
          channel that has none. Each button jumps the wizard to that channel's "Allow" step. */}
      <div style={{ marginBottom: 16, border: "1px solid var(--bc-border)", borderRadius: 8, overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 12px", background: "var(--bc-surface-2)" }}>
          <strong style={{ fontSize: 12.5 }}>Channel rules</strong>
          <span style={{ fontSize: 11, color: "var(--bc-text-mute)" }}>
            {CHANNELS.filter((c) => (policies[c.value]?.length ?? 0) > 0).length} of {CHANNELS.length} channels restricted
          </span>
        </div>
        {CHANNELS.map((c) => {
          const allow = policies[c.value];
          const has = Array.isArray(allow) && allow.length > 0;
          return (
            <div key={c.value} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 12px", borderTop: "1px solid var(--bc-border)" }}>
              <strong style={{ fontSize: 13, minWidth: 96 }}>{c.label}</strong>
              <span style={{ flex: 1, fontSize: 12, color: has ? "var(--bc-text-dim)" : "var(--bc-text-mute)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {has ? `Allows ${allow.length}: ${allow.map(humanizeIntent).join(", ")}` : "No rule — every request type passes"}
              </span>
              <button
                type="button"
                className="bc-btn ghost"
                onClick={() => { setSelected(c.value); setStep(2); }}
                style={{ fontSize: 12, whiteSpace: "nowrap", ...(has ? {} : primary) }}
                title={has ? `Edit ${c.label}'s rule` : `Add a rule for ${c.label}`}
              >
                {has ? "Edit" : "＋ Add rule"}
              </button>
            </div>
          );
        })}
      </div>

      {/* Progress stepper */}
      <div style={{ display: "flex", alignItems: "center", gap: 2, flexWrap: "wrap", marginBottom: 16 }}>
        {STEPS.map((s, i) => {
          const active = s.n === step;
          const done = s.n < step;
          return (
            <span key={s.n} style={{ display: "flex", alignItems: "center" }}>
              <button
                type="button"
                onClick={() => setStep(s.n)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  padding: "2px 4px",
                }}
                title={`Step ${s.n}: ${s.title}`}
              >
                <span
                  style={{
                    width: 22,
                    height: 22,
                    borderRadius: "50%",
                    background: active ? "var(--bc-accent, #2563eb)" : done ? "var(--bc-pass-line)" : "var(--bc-surface-2)",
                    color: active || done ? "#fff" : "var(--bc-text-mute)",
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 12,
                    fontWeight: 700,
                    flexShrink: 0,
                  }}
                >
                  {done ? "✓" : s.n}
                </span>
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: active ? 700 : 500,
                    color: active ? "var(--bc-text)" : "var(--bc-text-dim)",
                  }}
                >
                  {s.title}
                </span>
              </button>
              {i < STEPS.length - 1 && <span style={{ color: "var(--bc-text-mute)", fontSize: 11, margin: "0 2px" }}>→</span>}
            </span>
          );
        })}
      </div>

      {/* ── Step 1: pick a channel ── */}
      {step === 1 && (
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--bc-text)", marginBottom: 8 }}>
            Which channel are you setting rules for?
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {CHANNELS.map((c) => {
              const has = (policies[c.value]?.length ?? 0) > 0;
              const active = c.value === selected;
              return (
                <button
                  key={c.value}
                  type="button"
                  className="bc-btn"
                  onClick={() => setSelected(c.value)}
                  style={{
                    fontSize: 12,
                    fontWeight: active ? 700 : 400,
                    opacity: active ? 1 : 0.7,
                    borderColor: active ? "var(--bc-accent, #2563eb)" : undefined,
                  }}
                  title={has ? "has an active firewall policy" : "no policy yet — unrestricted"}
                >
                  {has ? "🛡 " : ""}
                  {c.label}
                </button>
              );
            })}
          </div>
          <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 10 }}>
            {applied && applied.length > 0 ? (
              <>
                Live on <strong style={{ color: "var(--bc-text)" }}>{selected}</strong>: allows {applied.length} request type
                {applied.length === 1 ? "" : "s"} — the rest escalate.
              </>
            ) : (
              <>
                <strong style={{ color: "var(--bc-text)" }}>{selected}</strong> has no rules yet — currently anything passes.
              </>
            )}
          </div>
        </div>
      )}

      {/* ── Step 2: choose allowed request types ── */}
      {step === 2 && (
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--bc-text)", marginBottom: 8 }}>
            What can <span style={{ color: "var(--bc-accent, #2563eb)" }}>{selected}</span> do? Check what to allow — the rest escalates.
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {Object.entries(byFamily).map(([fam, list]) => (
              <div key={fam}>
                <div style={{ fontSize: 10, textTransform: "uppercase", color: "var(--bc-text-mute)", marginBottom: 4 }}>
                  {FAMILY_LABEL[fam] ?? fam}
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: "2px 12px" }}>
                  {list.map((it) => (
                    <label key={it.name} style={cell}>
                      <input type="checkbox" checked={draft.has(it.name)} onChange={() => toggle(it.name)} />
                      <span style={{ color: draft.has(it.name) ? "var(--bc-text)" : "var(--bc-text-dim)" }}>
                        {humanizeIntent(it.name)}
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </div>
          {draft.size === 0 && (
            <div
              style={{
                fontSize: 11,
                color: "var(--bc-flag-text, #f59e0b)",
                background: "var(--bc-surface-2)",
                border: "1px solid var(--bc-flag-line, #f59e0b)",
                borderRadius: 6,
                padding: "6px 9px",
                marginTop: 8,
              }}
            >
              ⚠ Nothing selected = <strong>no restriction</strong> — every request type passes. To lock it down, check the
              request types to <strong>allow</strong>.
            </div>
          )}
          <button
            type="button"
            className="bc-btn ghost"
            onClick={openAddRequestType}
            title="Register a new request type through the governed propose → approve → apply flow"
            style={{ fontSize: 11, marginTop: 10, color: "var(--bc-accent, #2563eb)" }}
          >
            ＋ Don&apos;t see the request type? Add one (governed)
          </button>
        </div>
      )}

      {/* ── Step 3: test (optional) ── */}
      {step === 3 && (
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--bc-text)", marginBottom: 8 }}>
            Test a message <span style={{ fontWeight: 400, color: "var(--bc-text-mute)" }}>(optional — no side effects)</span>
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <input
              className="bc-input"
              value={sim}
              onChange={(e) => setSim(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && simulate()}
              placeholder="e.g. mandar pix de 100 para o joão"
              style={{ flex: 1, minWidth: 220 }}
            />
            <button type="button" className="bc-btn" onClick={simulate} disabled={simBusy || !sim.trim()} style={{ fontSize: 12 }}>
              {simBusy ? "testing…" : "Test"}
            </button>
          </div>
          {simOut && (
            <div style={{ fontSize: 12, marginTop: 8 }}>
              Intent <strong>{humanizeIntent(simOut.intent)}</strong> on <strong>{selected}</strong> →{" "}
              {simOut.allowed ? (
                <span className="bc-badge pass" style={{ fontSize: 11, padding: "1px 8px" }}>allowed</span>
              ) : (
                <span className="bc-badge block" style={{ fontSize: 11, padding: "1px 8px" }}>ESCALATE (off-list)</span>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Step 4: propose ── */}
      {step === 4 && (
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--bc-text)", marginBottom: 8 }}>
            Propose the change <span style={{ fontWeight: 400, color: "var(--bc-text-mute)" }}>— nothing goes live yet</span>
          </div>
          <div style={{ fontSize: 12, color: "var(--bc-text-dim)", marginBottom: 10 }}>
            {selected}:{" "}
            {draft.size === 0 ? (
              <em>no restriction (all pass)</em>
            ) : (
              <strong>{[...draft].map(humanizeIntent).join(", ")}</strong>
            )}
          </div>
          <button
            type="button"
            className="bc-btn"
            onClick={propose}
            disabled={busy || !dirty || !operator}
            style={{ fontSize: 13, ...primary, opacity: busy || !dirty || !operator ? 0.5 : 1 }}
          >
            {busy ? "proposing…" : !dirty ? "no change to propose" : `Propose rules for ${selected}`}
          </button>
        </div>
      )}

      {/* ── Step 5: approve & apply ── */}
      {step === 5 && (
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--bc-text)", marginBottom: 8 }}>
            Approve &amp; apply <span style={{ fontWeight: 400, color: "var(--bc-text-mute)" }}>— three different people</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
            <span style={{ fontSize: 11, color: "var(--bc-text-mute)" }}>Acting as</span>
            <select
              value={operator}
              onChange={(e) => setOperator(e.target.value)}
              className="bc-input"
              style={{ fontSize: 11, padding: "2px 6px" }}
              title="Switch operator — four-eyes needs three different people"
            >
              {OPERATORS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </div>
          {changes.length === 0 ? (
            <div style={{ fontSize: 11, color: "var(--bc-text-mute)" }}>
              No proposed changes yet — go back to step 4 and propose one.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {changes.slice(0, 6).map((c) => {
                const isSubmitter = operator === c.submitted_by;
                const cannotApply = isSubmitter || (c.reviewer != null && operator === c.reviewer);
                return (
                  <div
                    key={c.id}
                    style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", fontSize: 11, background: "var(--bc-surface-2)", borderRadius: 6, padding: "5px 8px" }}
                  >
                    <span style={{ flex: 1, color: "var(--bc-text-dim)" }}>{c.summary}</span>
                    <span style={{ fontWeight: 700, textTransform: "uppercase", fontSize: 10, color: STATUS_COLOR[c.status] ?? "var(--bc-text-mute)" }}>
                      {c.status}
                    </span>
                    {c.status === "pending" && (
                      <>
                        <button
                          type="button"
                          className="bc-btn"
                          onClick={() => act(c.id, "approve")}
                          disabled={busy || isSubmitter}
                          title={isSubmitter ? "You proposed this — switch operator above to approve" : undefined}
                          style={{ fontSize: 11, padding: "2px 8px" }}
                        >
                          approve
                        </button>
                        <button
                          type="button"
                          className="bc-btn"
                          onClick={() => act(c.id, "reject")}
                          disabled={busy || isSubmitter}
                          style={{ fontSize: 11, padding: "2px 8px" }}
                        >
                          reject
                        </button>
                      </>
                    )}
                    {c.status === "approved" && (
                      <button
                        type="button"
                        className="bc-btn"
                        onClick={() => act(c.id, "apply")}
                        disabled={busy || cannotApply}
                        title={cannotApply ? "The proposer/approver can't apply — switch operator above" : "Apply → the firewall goes live"}
                        style={{ fontSize: 11, padding: "2px 10px", ...primary, opacity: busy || cannotApply ? 0.5 : 1 }}
                      >
                        apply
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Inline note (propose/approve result) */}
      {note && (
        <div role="status" style={{ fontSize: 11, marginTop: 10, color: note.ok ? "var(--bc-pass-text)" : "var(--bc-block-text)" }}>
          {note.ok ? "✓ " : "⚠ "}
          {note.text}
        </div>
      )}

      {/* Back / Next nav */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 16, borderTop: "1px solid var(--bc-border)", paddingTop: 12 }}>
        <button
          type="button"
          className="bc-btn"
          onClick={() => setStep((s) => Math.max(1, s - 1))}
          disabled={step === 1}
          style={{ fontSize: 12, opacity: step === 1 ? 0.4 : 1 }}
        >
          ← Back
        </button>
        <span style={{ fontSize: 11, color: "var(--bc-text-mute)" }}>
          Step {step} of {STEPS.length}
        </span>
        {step < STEPS.length ? (
          <button type="button" className="bc-btn" onClick={() => setStep((s) => Math.min(STEPS.length, s + 1))} style={{ fontSize: 12, ...primary }}>
            Next →
          </button>
        ) : (
          <span style={{ width: 64 }} />
        )}
      </div>
    </div>
  );
}
