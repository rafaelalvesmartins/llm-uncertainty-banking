"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import type { Integrations, Provider } from "@/components/console/types";
import { useAppContext, OPERATORS } from "@/components/AppContextProvider";
import { apiErrorText } from "@/lib/apiError";
import { useDialogFocus } from "@/components/useDialogFocus";
import StateBadge from "@/components/StateBadge";
import ConnectionGovernance from "@/components/console/ConnectionGovernance";
import ConnectionCanvas, { type CanvasNode } from "@/components/console/ConnectionCanvas";

// Dot class for bc-dot
function statusDotClass(status: string): string {
  if (status === "active") return "bc-dot pass";
  if (status === "available" || status === "reachable") return "bc-dot info";
  if (status === "unreachable") return "bc-dot block";
  return "bc-dot";
}

// Human-readable status label
function statusLabel(status: string): string {
  return status.replace(/_/g, " ");
}

// Badge variant for bc-badge
function statusBadgeClass(status: string): string {
  if (status === "active") return "bc-badge pass";
  if (status === "available" || status === "reachable") return "bc-badge";
  if (status === "unreachable") return "bc-badge block";
  return "bc-badge";
}

// Model display: prefer configured_model for ollama, else models list, else "—"
function modelCell(p: Provider): string {
  if (p.configured_model) {
    const loaded =
      p.model_loaded === true ? " ✓" : p.model_loaded === false ? " (not loaded)" : "";
    return `${p.configured_model}${loaded}`;
  }
  if (p.models && p.models.length > 0) {
    return p.models.slice(0, 3).join(", ") + (p.models.length > 3 ? ` +${p.models.length - 3}` : "");
  }
  return "—";
}

// Map a topology provider to its governed-form vendor type (used by the manage modal).
function vendorType(p: Provider): string {
  const s = `${p.id} ${p.name}`.toLowerCase();
  if (s.includes("ollama")) return "ollama";
  if (s.includes("openai")) return "openai";
  if (s.includes("anthropic")) return "anthropic";
  return "fake";
}

// Plain-language meaning of each provider status, for the modal.
function statusMeaning(status: string): string {
  if (status === "active") return "this is the live backend right now.";
  if (status === "reachable" || status === "available") return "reachable, but not the live backend.";
  if (status === "unreachable") return "configured, but not responding right now.";
  if (status === "not_configured") return "no credentials yet — propose it to configure.";
  if (status === "configured") return "ready to use — a demo channel (loopback, no real send).";
  return statusLabel(status);
}

const REAL_VENDORS = new Set(["ollama", "openai", "anthropic"]);

// Config fields per provider vendor (channels aren't shown in the topology). Secret
// fields are masked at rest by the backend and never echoed back — re-enter on edit.
type VField = { name: string; label: string; secret?: boolean; placeholder?: string };
const PROVIDER_FIELDS: Record<string, VField[]> = {
  fake: [],
  ollama: [
    { name: "endpoint", label: "Endpoint", placeholder: "http://localhost:11434" },
    { name: "model", label: "Model", placeholder: "llama3.1:8b" },
  ],
  openai: [
    { name: "api_key", label: "API key", secret: true, placeholder: "sk-…" },
    { name: "model", label: "Model", placeholder: "gpt-4o" },
    { name: "base_url", label: "Base URL (optional)", placeholder: "https://api.openai.com/v1" },
  ],
  anthropic: [
    { name: "api_key", label: "API key", secret: true, placeholder: "sk-ant-…" },
    { name: "model", label: "Model", placeholder: "claude-sonnet-4-…" },
    { name: "base_url", label: "Base URL (optional)", placeholder: "https://api.anthropic.com" },
  ],
};

// Customer-facing channels shown on the LEFT of the diagram (input side). Real,
// send-capable ones (whatsapp/telegram) are refused on apply in demo-safe mode, like
// real providers. Keep in sync with the backend allow-list (_DEMO_SAFE_CHANNELS).
const CHANNEL_FIELDS: Record<string, VField[]> = {
  app: [],
  web: [],
  call_center: [],
  fakewhatsapp: [],
  whatsapp: [
    { name: "phone_number_id", label: "Phone number ID", placeholder: "100942…" },
    { name: "access_token", label: "Access token", secret: true, placeholder: "EAAB…" },
  ],
  telegram: [{ name: "bot_token", label: "Bot token", secret: true, placeholder: "123456:ABC-…" }],
};
const REAL_CHANNELS = new Set(["whatsapp", "telegram"]);
// The channel nodes drawn on the diagram (left → into Bridge).
const CANVAS_CHANNELS: { vtype: string; name: string }[] = [
  { vtype: "whatsapp", name: "WhatsApp" },
  { vtype: "app", name: "Mobile app" },
  { vtype: "web", name: "Web chat" },
  { vtype: "call_center", name: "Call center" },
];

// A connection the modal can manage — built from a provider OR a channel, so one
// governed modal drives both.
interface ConnTarget {
  kind: "provider" | "channel";
  name: string;
  vtype: string;
  isReal: boolean;
  isActive: boolean;
  fields: VField[];
  status: string;
  endpoint?: string;
  model?: string;
  note?: string;
}
function providerTarget(p: Provider, activeBackend: string): ConnTarget {
  const vt = vendorType(p);
  return {
    kind: "provider", name: p.name, vtype: vt, isReal: REAL_VENDORS.has(vt),
    isActive: p.id === activeBackend, fields: PROVIDER_FIELDS[vt] ?? [], status: p.status,
    endpoint: p.endpoint, model: p.configured_model ?? p.models?.[0] ?? undefined, note: p.note,
  };
}
function channelTarget(vtype: string, name: string): ConnTarget {
  const real = REAL_CHANNELS.has(vtype);
  return {
    kind: "channel", name, vtype, isReal: real, isActive: false,
    fields: CHANNEL_FIELDS[vtype] ?? [], status: real ? "not_configured" : "configured",
    note: real ? "Real, send-capable channel — demo-safe blocks the apply step." : "Demo channel (loopback, no real send).",
  };
}

interface ConnChange {
  id: number;
  kind: string;
  summary: string;
  submitted_by: string;
  status: string;
  reviewer: string | null;
  applied_by?: string | null;
  payload?: Record<string, unknown>;
}

// Clicking a topology node opens this modal — a self-contained "manage this connection"
// panel: it loads the provider's live info and runs the whole governed flow IN PLACE
// (propose → approve → apply), so you never have to leave for the form/trail below. The
// governance rules (SoD, four-eyes, demo-safe) are still enforced server-side.
function ProviderModal({
  target,
  backendIsReal,
  onClose,
}: {
  target: ConnTarget | null;
  backendIsReal: boolean;
  onClose: () => void;
}) {
  const { operator, setOperator } = useAppContext();
  const [changes, setChanges] = useState<ConnChange[]>([]);
  const [pfields, setPfields] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [justApplied, setJustApplied] = useState(false);
  const [editing, setEditing] = useState(false);
  const [autoStep, setAutoStep] = useState<"propose" | "approve" | "apply" | null>(null);

  const vtype = target?.vtype ?? "fake";
  const kind = target?.kind ?? "provider";
  const fields = target?.fields ?? [];
  const isReal = target?.isReal ?? false;
  // In demo mode (no real LLM backend) the server refuses to APPLY a real vendor — so we
  // block it up front instead of letting the user do all the work and hit a 409 dead-end.
  const demoBlocksReal = isReal && !backendIsReal;

  const loadChanges = useCallback(async () => {
    try {
      const r = await fetch("/api/governance/changes", { cache: "no-store" });
      const j = await r.json();
      setChanges(Array.isArray(j?.changes) ? j.changes : []);
    } catch {
      /* keep last good list */
    }
  }, []);

  // On open: reset the form, load the change ledger; Escape closes.
  useEffect(() => {
    if (!target) return;
    setPfields({});
    setErr(null);
    setInfo(null);
    setJustApplied(false);
    setEditing(false);
    setAutoStep(null);
    loadChanges();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [target, onClose, loadChanges]);

  const dialogRef = useDialogFocus<HTMLDivElement>(target !== null);

  if (!target) return null;
  const isActive = target.isActive;

  // The in-flight governed change for THIS connection (if any) drives the modal's step:
  // none → propose form; pending → approve step; approved → apply step. Pick the NEWEST
  // in-flight one so a re-proposed version (after "Adjust config") takes over.
  const inFlight = changes
    .filter(
      (c) =>
        c.kind === kind &&
        c.payload?.name === target.name &&
        (c.status === "pending" || c.status === "approved"),
    )
    .sort((a, b) => b.id - a.id)[0];

  async function propose() {
    if (busy || !target) return;
    setBusy(true); setErr(null); setInfo(null);
    const cfg: Record<string, string> = {};
    for (const f of fields) { const v = (pfields[f.name] || "").trim(); if (v) cfg[f.name] = v; }
    try {
      const r = await fetch("/api/governance/changes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind,
          summary: `Activate ${vtype} ${kind} "${target.name}"`,
          submitted_by: operator,
          payload: { name: target.name, type: vtype, is_real: isReal, ...cfg },
        }),
        cache: "no-store",
      });
      const j = await r.json().catch(() => null);
      if (!r.ok) setErr(apiErrorText(j, r.status));
      else { setEditing(false); setInfo("Proposed ✓ — now approve as a different operator below."); await loadChanges(); }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  // "Adjust config": go back to the settings form, pre-filled from the in-flight change.
  // A pending proposal is cleanly withdrawn first (reject); an approved one is locked by
  // the backend, so we keep it and propose a NEW version over it (the newer one wins).
  async function startEdit() {
    if (busy || !inFlight || !target) return;
    const pl = inFlight.payload || {};
    const nf: Record<string, string> = {};
    for (const f of fields) {
      if (!f.secret && typeof pl[f.name] === "string") nf[f.name] = pl[f.name] as string;
    }
    const wasPending = inFlight.status === "pending";
    if (wasPending) {
      const who = OPERATORS.find((o) => o !== inFlight!.submitted_by);
      if (who) await act("reject", who); // withdraw the proposal — no stale pending left behind
    }
    setPfields(nf);
    setEditing(true);
    setErr(null);
    setInfo(
      wasPending
        ? "Withdrew the proposal — change the settings and propose again."
        : "Adjust the settings and propose a new version (the previous approved one stays in the ledger).",
    );
  }

  async function act(action: "approve" | "reject" | "apply", asOperator: string) {
    if (busy || !inFlight || !target) return;
    setBusy(true); setErr(null); setInfo(null);
    setOperator(asOperator); // keep the global operator in sync with who acted
    try {
      const url = action === "apply"
        ? `/api/governance/changes/${inFlight.id}/apply`
        : `/api/governance/changes/${inFlight.id}/decision`;
      const body = action === "apply" ? { applier: asOperator } : { decision: action, reviewer: asOperator };
      const r = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        cache: "no-store",
      });
      const j = await r.json().catch(() => null);
      if (!r.ok) setErr(apiErrorText(j, r.status)); // SoD / four-eyes / demo-safe reason
      else {
        await loadChanges();
        if (action === "apply") { setJustApplied(true); setInfo(null); }
        else if (action === "approve") setInfo("Approved ✓ — now apply as a third, different operator.");
        else setInfo("Rejected — it did not enter the active config.");
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  // One-click demo: run the whole governed flow with three distinct operators, so a
  // viewer sees propose → approve → apply without driving the persona switches by hand.
  // Stops at the (blocked) apply for a real vendor in demo mode and explains why.
  async function runWholeFlow() {
    if (busy || !target) return;
    const submitter = OPERATORS[0];
    const approver = OPERATORS.find((o) => o !== submitter) ?? OPERATORS[1];
    const applier = OPERATORS.find((o) => o !== submitter && o !== approver) ?? OPERATORS[2];
    const cfg: Record<string, string> = {};
    for (const f of fields) { const v = (pfields[f.name] || "").trim(); if (v) cfg[f.name] = v; }
    setBusy(true); setErr(null); setInfo(null); setEditing(false); setJustApplied(false);
    const post = (url: string, body: unknown) =>
      fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), cache: "no-store" });
    try {
      // 1. propose
      setAutoStep("propose");
      setOperator(submitter);
      const pr = await post("/api/governance/changes", {
        kind,
        summary: `Activate ${vtype} ${kind} "${target.name}"`,
        submitted_by: submitter,
        payload: { name: target.name, type: vtype, is_real: isReal, ...cfg },
      });
      const pj = await pr.json().catch(() => null);
      if (!pr.ok || !pj?.id) { setErr(apiErrorText(pj, pr.status)); setAutoStep(null); return; }
      const id = pj.id as number;
      // 2. approve (a different operator)
      setAutoStep("approve");
      setOperator(approver);
      const ar = await post(`/api/governance/changes/${id}/decision`, { decision: "approve", reviewer: approver });
      if (!ar.ok) { setErr(apiErrorText(await ar.json().catch(() => null), ar.status)); setAutoStep(null); await loadChanges(); return; }
      // 3. apply (a third operator) — unless a real vendor is blocked in demo mode
      setOperator(applier);
      if (demoBlocksReal) {
        setAutoStep(null);
        await loadChanges();
        setInfo("Proposed ✓ and approved ✓ automatically. Apply is blocked for a real vendor in demo mode — open FakeBackend to see the final step succeed too.");
        return;
      }
      setAutoStep("apply");
      const apr = await post(`/api/governance/changes/${id}/apply`, { applier });
      if (!apr.ok) { setErr(apiErrorText(await apr.json().catch(() => null), apr.status)); setAutoStep(null); await loadChanges(); return; }
      await loadChanges();
      setAutoStep(null);
      setJustApplied(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setAutoStep(null);
    } finally { setBusy(false); }
  }

  // Operators eligible for the next step (SoD on approve; four-eyes on apply).
  const approvers = inFlight ? OPERATORS.filter((o) => o !== inFlight.submitted_by) : [];
  const appliers = inFlight
    ? OPERATORS.filter((o) => o !== inFlight.submitted_by && o !== inFlight.reviewer)
    : [];
  // 1 propose · 2 approve · 3 apply · 4 done — drives the progress chips.
  const stepNum = justApplied ? 4 : (editing || !inFlight) ? 1 : inFlight.status === "pending" ? 2 : 3;

  const infoRows: [string, string][] = [
    ["Type", `${vtype}${isReal ? " · real vendor" : " · demo"}`],
    ["Status", statusMeaning(target.status)],
    ["Endpoint", target.endpoint ?? "—"],
    ["Model", target.model ?? "—"],
  ];

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div ref={dialogRef} tabIndex={-1} className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label={`Connection: ${target.name}`}>
        <div className="modal-header">
          <h3 style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {target.name}
            <span className={statusBadgeClass(target.status)} style={{ fontSize: 11 }}>
              <span className={statusDotClass(target.status)} />
              {statusLabel(target.status)}
            </span>
            {isActive && <span style={{ fontSize: 11, color: "var(--bc-pass-line)" }}>★ live</span>}
          </h3>
          <button type="button" className="modal-close" onClick={onClose} aria-label="close">
            ×
          </button>
        </div>

        <div className="modal-body">
          {/* Loaded info */}
          <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "3px 14px", fontSize: 12, marginBottom: 12 }}>
            {infoRows.map(([k, v]) => (
              <Fragment key={k}>
                <span style={{ color: "var(--bc-text-mute)" }}>{k}</span>
                <span style={{ color: "var(--bc-text-dim)", fontFamily: k === "Endpoint" || k === "Model" ? "monospace" : undefined }}>{v}</span>
              </Fragment>
            ))}
          </div>
          {target.note && (
            <div style={{ fontSize: 11.5, color: "var(--bc-text-mute)", marginBottom: 12, lineHeight: 1.5 }}>{target.note}</div>
          )}

          {/* Plain-language explainer — "propose / approve / apply" are jargon to a
              first-timer, so spell out what each word means and why the flow exists. */}
          <div style={{ fontSize: 12, color: "var(--bc-text-dim)", background: "var(--bc-surface-2)", border: "1px solid var(--bc-border)", borderRadius: 6, padding: "9px 11px", marginBottom: 12, lineHeight: 1.55 }}>
            <strong style={{ color: "var(--bc-text)" }}>Why three steps?</strong> Turning a connection on takes{" "}
            <strong>three different people</strong>, so no one changes a live AI connection alone:
            <div style={{ marginTop: 6, display: "grid", gridTemplateColumns: "auto 1fr", gap: "3px 8px" }}>
              <span style={{ color: "var(--bc-accent)", fontWeight: 600 }}>1 · Propose</span>
              <span>describe the change and its settings.</span>
              <span style={{ color: "var(--bc-accent)", fontWeight: 600 }}>2 · Approve</span>
              <span>a second person reviews it and says OK.</span>
              <span style={{ color: "var(--bc-accent)", fontWeight: 600 }}>3 · Apply</span>
              <span>a third person turns it on.</span>
            </div>
            <div style={{ marginTop: 6, color: "var(--bc-text-mute)" }}>In this demo you play all three.</div>
          </div>

          {/* Real-vendor heads-up, up front — so it isn't a surprise after typing a key. */}
          {isReal && (
            <div style={{ fontSize: 11.5, color: "var(--bc-flag-line)", background: "var(--bc-surface-2)", border: "1px solid var(--bc-border)", borderLeft: "3px solid var(--bc-flag-line)", borderRadius: 6, padding: "8px 10px", marginBottom: 12, lineHeight: 1.5 }}>
              <strong>{vtype} is a real vendor.</strong>{" "}
              {demoBlocksReal
                ? "This system runs in demo mode, so applying a real vendor is intentionally blocked — only FakeBackend goes live. You can still propose and approve it here; pick FakeBackend to watch the whole flow finish."
                : "Secrets are masked at rest and never shown again — re-enter them on edit."}
            </div>
          )}

          {/* Progress: propose → approve → apply (current step highlighted). */}
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, marginBottom: 14 }}>
            {[{ n: 1, label: "Propose" }, { n: 2, label: "Approve" }, { n: 3, label: "Apply" }].map((s, i) => {
              const state = s.n < stepNum ? "done" : s.n === stepNum ? "active" : "todo";
              return (
                <Fragment key={s.n}>
                  {i > 0 && <span style={{ color: "var(--bc-text-mute)" }}>→</span>}
                  <span
                    style={{
                      display: "inline-flex", alignItems: "center", gap: 4, padding: "2px 9px", borderRadius: 12,
                      fontWeight: state === "active" ? 700 : 400,
                      color: state === "todo" ? "var(--bc-text-mute)" : state === "active" ? "var(--bc-accent)" : "var(--bc-pass-line)",
                      border: `1px solid ${state === "active" ? "var(--bc-accent)" : "var(--bc-border)"}`,
                    }}
                  >
                    {state === "done" ? "✓" : s.n} {s.label}
                  </span>
                </Fragment>
              );
            })}
          </div>

          {/* Governed flow body — auto-run progress, else the step for the in-flight change. */}
          {autoStep ? (
            <div style={{ padding: "4px 0" }}>
              <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--bc-text)", marginBottom: 10 }}>
                ▶ Running the governed flow…
              </div>
              {[{ key: "propose", label: "Propose" }, { key: "approve", label: "Approve" }, { key: "apply", label: "Apply" }].map((s, i) => {
                const ci = ["propose", "approve", "apply"].indexOf(autoStep);
                const done = i < ci;
                const running = i === ci;
                return (
                  <div key={s.key} style={{ fontSize: 12.5, marginBottom: 5, color: done ? "var(--bc-pass-line)" : running ? "var(--bc-accent)" : "var(--bc-text-mute)" }}>
                    {done ? "✓" : running ? "⟳" : "·"} {s.label}{" "}
                    <span style={{ color: "var(--bc-text-mute)" }}>(as {OPERATORS[i]})</span>
                  </div>
                );
              })}
            </div>
          ) : justApplied ? (
            <div style={{ textAlign: "center", padding: "8px 0 4px" }}>
              <div style={{ fontSize: 30, color: "var(--bc-pass-line)", lineHeight: 1 }}>✓</div>
              <div style={{ fontSize: 14, fontWeight: 600, color: "var(--bc-text)", marginTop: 6 }}>Done — change applied</div>
              <div style={{ fontSize: 12, color: "var(--bc-text-dim)", marginTop: 6, lineHeight: 1.55 }}>
                All three steps completed by three different people. &quot;{target.name}&quot; is now in the active configuration and recorded in the change ledger — open &quot;Show advanced&quot; below to see the full trail.
              </div>
              <button type="button" className="bc-btn ghost" onClick={() => setJustApplied(false)} style={{ fontSize: 12, marginTop: 14 }}>
                Propose another change
              </button>
            </div>
          ) : (editing || !inFlight) ? (
            <>
              <div style={{ fontSize: 11, color: "var(--bc-text-mute)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
                {editing ? "Step 1 · Adjust settings" : "Step 1 · Propose a change"}
              </div>
              {!editing && (
                <>
                  <button type="button" className="bc-btn" onClick={runWholeFlow} disabled={busy} style={{ fontSize: 13, width: "100%", marginBottom: 6 }}>
                    ▶ Run the whole flow for me
                  </button>
                  <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginBottom: 12, textAlign: "center", lineHeight: 1.5 }}>
                    Watch propose → approve → apply happen with the 3 people — or set it up yourself below.
                  </div>
                </>
              )}
              {fields.map((f) => (
                <input
                  key={f.name}
                  type={f.secret ? "password" : "text"}
                  value={pfields[f.name] || ""}
                  onChange={(e) => setPfields((p) => ({ ...p, [f.name]: e.target.value }))}
                  placeholder={f.placeholder ? `${f.label} — ${f.placeholder}` : f.label}
                  className="bc-input"
                  maxLength={300}
                  autoComplete="off"
                  style={{ marginBottom: 8, width: "100%" }}
                />
              ))}
              {fields.length === 0 && (
                <div style={{ fontSize: 12, color: "var(--bc-text-mute)", marginBottom: 8 }}>
                  No settings needed for {vtype} — just propose it.
                </div>
              )}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button type="button" className="bc-btn" onClick={propose} disabled={busy} style={{ fontSize: 13 }}>
                  {editing ? "Propose updated change →" : "Propose governed change →"}
                </button>
                {editing && (
                  <button type="button" className="bc-btn ghost" onClick={() => { setEditing(false); setPfields({}); setInfo(null); }} disabled={busy} style={{ fontSize: 13 }}>
                    Cancel
                  </button>
                )}
              </div>
            </>
          ) : (
            <>
              <div style={{ fontSize: 11, color: "var(--bc-text-mute)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
                {inFlight.status === "pending" ? "Step 2 · Approve" : "Step 3 · Apply"}
              </div>
              <div style={{ fontSize: 12, color: "var(--bc-text-dim)", marginBottom: 3 }}>{inFlight.summary}</div>
              <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginBottom: 10 }}>
                submitted by {inFlight.submitted_by}
                {inFlight.reviewer ? ` · approved by ${inFlight.reviewer}` : ""}
              </div>
              {inFlight.status === "pending" ? (
                <>
                  <div style={{ fontSize: 12, color: "var(--bc-text-dim)", marginBottom: 6 }}>
                    A <strong>different</strong> person must approve — so no one changes a live connection on their own:
                  </div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
                    {approvers.map((o) => (
                      <button key={o} type="button" className="bc-btn" disabled={busy} onClick={() => act("approve", o)} style={{ fontSize: 12 }}>
                        Approve as {o}
                      </button>
                    ))}
                  </div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button type="button" className="bc-btn ghost" disabled={busy} onClick={startEdit} style={{ fontSize: 11 }}>
                      Adjust config
                    </button>
                    <button type="button" className="bc-btn ghost" disabled={busy || approvers.length === 0} onClick={() => act("reject", approvers[0])} style={{ fontSize: 11 }}>
                      Reject
                    </button>
                  </div>
                </>
              ) : demoBlocksReal ? (
                <>
                  <div style={{ fontSize: 12, color: "var(--bc-flag-line)", background: "var(--bc-surface-2)", border: "1px solid var(--bc-border)", borderLeft: "3px solid var(--bc-flag-line)", borderRadius: 6, padding: "8px 10px", lineHeight: 1.55, marginBottom: 8 }}>
                    Proposed ✓ and approved ✓. Applying is <strong>blocked for a real vendor in demo mode</strong> — only FakeBackend goes live. To finish for real, the server admin sets <code>BRIDGE_DEMO_SAFE=off</code>; or try FakeBackend to watch the apply step succeed.
                  </div>
                  <button type="button" className="bc-btn ghost" disabled={busy} onClick={startEdit} style={{ fontSize: 11 }}>
                    Adjust config (propose a new version)
                  </button>
                </>
              ) : (
                <>
                  <div style={{ fontSize: 12, color: "var(--bc-text-dim)", marginBottom: 6 }}>
                    A <strong>third</strong> person (not the first two) must apply — a separate set of eyes before it goes live:
                  </div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
                    {appliers.map((o) => (
                      <button key={o} type="button" className="bc-btn" disabled={busy} onClick={() => act("apply", o)} style={{ fontSize: 12 }}>
                        Apply as {o}
                      </button>
                    ))}
                  </div>
                  <button type="button" className="bc-btn ghost" disabled={busy} onClick={startEdit} style={{ fontSize: 11 }}>
                    Adjust config
                  </button>
                </>
              )}
            </>
          )}

          {err && <div className="bc-error" role="alert" style={{ marginTop: 12, fontSize: 12 }}>{err}</div>}
          {info && (
            <div role="status" style={{ marginTop: 12, fontSize: 12, color: "var(--bc-info-line)", background: "var(--bc-surface-2)", border: "1px solid var(--bc-border)", borderLeft: "3px solid var(--bc-info-line)", borderRadius: 6, padding: "8px 10px" }}>
              {info}
            </div>
          )}
        </div>

        <div className="modal-footer" style={{ display: "flex", gap: 12, justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontSize: 10.5, color: "var(--bc-text-mute)" }}>
            The 3-different-people rule is enforced on the server, not just in this UI.
          </span>
          <button type="button" className="bc-btn ghost" onClick={onClose} style={{ fontSize: 13 }}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

// ---- Main view ----

export default function Conexoes() {
  const [data, setData] = useState<Integrations | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<ConnTarget | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | undefined;
    const attempt = () => {
      fetch("/api/integrations", { cache: "no-store" })
        .then(async (r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json() as Promise<Integrations>;
        })
        .then((j) => {
          if (cancelled) return;
          setData(j);
          setError(null);
        })
        .catch((e: unknown) => {
          if (!cancelled) setError(e instanceof Error ? e.message : String(e));
        });
    };
    attempt();
    timer = setInterval(() => { if (!document.hidden) attempt(); }, 15000);
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, []);

  async function handleRefresh() {
    setBusy(true);
    try {
      const r = await fetch("/api/integrations?refresh=1", { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData(await r.json() as Integrations);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  // ---- Error state ----
  if (error && !data) {
    return (
      <div className="bc-card">
        <div className="bc-card-h">
          <h2>
            Connections
            <StateBadge feature="integrations" />
          </h2>
        </div>
        <div className="bc-error">backend unreachable — {error}</div>
      </div>
    );
  }

  // ---- Loading state ----
  if (!data) {
    return (
      <div className="bc-card">
        <div className="bc-card-h">
          <h2>
            Connections
            <StateBadge feature="integrations" />
          </h2>
        </div>
        <div className="bc-loading">loading providers…</div>
      </div>
    );
  }

  const providers = data.providers ?? [];

  // ---- Empty providers ----
  if (providers.length === 0) {
    return (
      <div className="bc-card">
        <div className="bc-card-h">
          <h2>
            Connections
            <StateBadge feature="integrations" />
          </h2>
        </div>
        <div className="bc-empty">no providers found.</div>
      </div>
    );
  }

  return (
    <>
    <p style={{ fontSize: 12.5, color: "var(--bc-text-mute)", margin: "0 0 12px", lineHeight: 1.55 }}>
      <strong style={{ color: "var(--bc-text)" }}>What this does:</strong>{" "}
      {"The channels customers reach you on (WhatsApp, app, web, call center) → Bridge → the AI providers that answer, and which one is live. To connect or change any of them, a governed flow keeps it safe: one person proposes, a different one approves, and a third applies — so no connection changes on one person's say-so."}
    </p>
    <div className="bc-card">
      {/* Header */}
      <div className="bc-card-h">
        <h2>
          Connections
          <StateBadge feature="integrations" />
        </h2>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 12, color: "var(--bc-text-dim)" }}>
            active backend:{" "}
            <strong style={{ color: "var(--bc-pass-line)" }} title={data.active_backend}>{data.active_backend === "fake" ? "Demo (fixed answers)" : data.active_backend}</strong>
          </span>
          <span style={{ fontSize: 12, color: "var(--bc-text-mute)" }}>
            {data.n_available}/{data.n_providers} available
          </span>
          <button
            type="button"
            className="bc-btn ghost"
            onClick={handleRefresh}
            disabled={busy}
            style={{ padding: "5px 12px", fontSize: 12 }}
          >
            {busy ? "…" : "↻ Refresh"}
          </button>
        </div>
      </div>

      {/* Draggable map — channels (WhatsApp/app/web/call) → Bridge → AI vendors. Drag a
          node to rearrange; click it to open the same governed flow as the cards below. */}
      <div style={{ marginBottom: 16 }}>
        <ConnectionCanvas
          channels={CANVAS_CHANNELS.map((c) => ({ id: `ch:${c.vtype}`, name: c.name, kind: "channel", status: REAL_CHANNELS.has(c.vtype) ? "not_configured" : "configured", vtype: c.vtype }) as CanvasNode)}
          providers={providers.map((p) => ({ id: p.id, name: p.name, kind: "provider", status: p.status, vtype: vendorType(p) }) as CanvasNode)}
          activeBackend={data.active_backend}
          onSelect={(n) => {
            if (n.kind === "provider") {
              const p = providers.find((x) => x.id === n.id);
              if (p) setSelected(providerTarget(p, data.active_backend));
            } else {
              setSelected(channelTarget(n.vtype, n.name));
            }
          }}
        />
      </div>

      {/* One card per AI vendor — one click to connect/manage it (governed flow). */}
      <div className="bc-grid-2" style={{ gap: 12, marginBottom: 18 }}>
        {providers.map((p) => {
          const isActive = p.id === data.active_backend;
          return (
            <div
              key={p.id}
              style={{
                background: "var(--bc-surface-2)",
                border: `1.5px solid ${isActive ? "var(--bc-accent)" : "var(--bc-border)"}`,
                borderRadius: 10,
                padding: "12px 14px",
                display: "flex",
                flexDirection: "column",
                gap: 8,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <span style={{ fontSize: 14, fontWeight: 600, color: "var(--bc-text)" }}>{p.name}</span>
                {isActive && <span style={{ fontSize: 11, color: "var(--bc-pass-line)" }}>★ live</span>}
                <span className={statusBadgeClass(p.status)} style={{ fontSize: 11, marginLeft: "auto" }}>
                  <span className={statusDotClass(p.status)} />
                  {statusLabel(p.status)}
                </span>
              </div>
              <div style={{ fontSize: 11.5, color: "var(--bc-text-mute)", fontFamily: "monospace", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {modelCell(p)} · {p.endpoint ?? "—"}
              </div>
              <button
                type="button"
                className="bc-btn"
                onClick={() => setSelected(providerTarget(p, data.active_backend))}
                style={{ fontSize: 13, alignSelf: "flex-start" }}
              >
                {p.status === "not_configured" ? "Connect →" : "Manage →"}
              </button>
            </div>
          );
        })}
      </div>

      {/* Providers table */}
      <table className="bc-table">
        <thead>
          <tr>
            <th>Provider</th>
            <th>Type</th>
            <th>Status</th>
            <th>Model / configured</th>
            <th>Endpoint</th>
            <th>Note</th>
          </tr>
        </thead>
        <tbody>
          {providers.map((p) => (
            <tr key={p.id}>
              <td>
                <span style={{ fontWeight: p.id === data.active_backend ? 700 : 400, color: "var(--bc-text)" }}>
                  {p.name}
                </span>
              </td>
              <td style={{ color: "var(--bc-text-dim)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                {p.kind}
              </td>
              <td>
                <span className={statusBadgeClass(p.status)} style={{ fontSize: 11 }}>
                  <span className={statusDotClass(p.status)} />
                  {statusLabel(p.status)}
                </span>
              </td>
              <td style={{ color: "var(--bc-text-dim)", fontFamily: "monospace", fontSize: 12 }}>
                {modelCell(p)}
              </td>
              <td style={{ color: "var(--bc-text-mute)", fontSize: 11, fontFamily: "monospace" }}>
                {p.endpoint ?? "—"}
              </td>
              <td style={{ color: "var(--bc-text-mute)", fontSize: 11, maxWidth: 260 }}>
                {p.note ?? ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* New connection → jump to the governed "Propose provider" form below */}
      <div style={{ marginTop: 16, display: "flex", alignItems: "center", gap: 12 }}>
        <button
          type="button"
          className="bc-btn"
          title="Add a connection through the governed flow below"
          onClick={() => {
            // The propose form lives inside the advanced section, which is collapsed
            // by default — expand it first, then look the input up after it mounts.
            setShowAdvanced(true);
            requestAnimationFrame(() => {
              const el = document.getElementById("propose-provider-name") as HTMLInputElement | null;
              el?.scrollIntoView({ behavior: "smooth", block: "center" });
              el?.focus();
              // Flash a highlight on the form's name field so it's obvious WHERE the
              // connection is created (the button used to just scroll — felt like a no-op).
              if (el) {
                el.style.transition = "box-shadow 0.25s";
                el.style.boxShadow = "0 0 0 3px var(--bc-accent)";
                setTimeout(() => { el.style.boxShadow = ""; }, 1500);
              }
            });
          }}
          style={{ fontSize: 13 }}
        >
          ＋ New connection
        </button>
        <span style={{ fontSize: 11, color: "var(--bc-text-mute)", maxWidth: 480 }}>
          Adding a connection goes through the governed flow below (propose → approve → apply). {data.switch_note}
        </span>
      </div>

      {/* Footer: checked_at */}
      <div style={{ marginTop: 12, fontSize: 11, color: "var(--bc-text-mute)" }}>
        checked {data.checked_at}
        {error && (
          <span style={{ color: "var(--bc-block-line)", marginLeft: 8 }}>
            · last poll failed: {error}
          </span>
        )}
      </div>
    </div>
    <ProviderModal
      target={selected}
      backendIsReal={data.active_backend !== "fake"}
      onClose={() => setSelected(null)}
    />
    {/* The topology modal above is the guided path; this is the same governed flow as a
        full form + ledger. Collapsed by default so the page isn't two ways to do one thing. */}
    <div style={{ marginTop: 18 }}>
      <button
        type="button"
        className="bc-btn ghost"
        onClick={() => setShowAdvanced((v) => !v)}
        style={{ fontSize: 12 }}
      >
        {showAdvanced ? "▲ Hide advanced" : "▼ Show advanced — full form & change ledger"}
      </button>
      <span style={{ fontSize: 11, color: "var(--bc-text-mute)", marginLeft: 10 }}>
        The easy way: click a provider in the diagram above. This panel is the full form + ledger for power users.
      </span>
      {showAdvanced && (
        <div style={{ marginTop: 12 }}>
          <ConnectionGovernance />
        </div>
      )}
    </div>
    </>
  );
}
