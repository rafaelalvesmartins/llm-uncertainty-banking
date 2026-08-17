"use client";

import { useCallback, useEffect, useState } from "react";
import { useAppContext, OPERATORS } from "@/components/AppContextProvider";
import StateBadge from "@/components/StateBadge";
import { apiErrorText } from "@/lib/apiError";

interface Change {
  id: number;
  kind: string;
  summary: string;
  submitted_by: string;
  status: string;
  reviewer: string | null;
  applied_by?: string | null;
  payload?: Record<string, unknown>;
}
interface ChangesData {
  n: number;
  by_status: Record<string, number>;
  changes: Change[];
}
interface ActiveCfg {
  domain: string;
  name: string;
  config: Record<string, unknown>;
  updated_at: number;
  updated_by: string | null;
}
interface ActiveData {
  n: number;
  configs: ActiveCfg[];
}

const STATUS: Record<string, { color: string; label: string }> = {
  pending: { color: "var(--bc-flag-line)", label: "pending" },
  approved: { color: "var(--bc-pass-line)", label: "approved" },
  rejected: { color: "var(--bc-block-line)", label: "rejected" },
  applied: { color: "var(--bc-info-line)", label: "applied" },
};

// Only the connection-management kinds belong in this panel (the others live in the
// Governance view's generic Governed Changes panel).
const CONN_KINDS = new Set(["provider", "channel"]);

// Vendor types + the settings each one needs. Secret fields (api_key) are masked at
// rest by the backend; in demo-safe mode the apply executor refuses any real vendor, so
// real ones can be proposed/reviewed but only Fake actually applies.
type PField = { name: string; label: string; secret?: boolean; placeholder?: string };
const PROVIDER_TYPES: { value: string; label: string; real: boolean; fields: PField[] }[] = [
  { value: "fake", label: "Demo backend (fixed answers)", real: false, fields: [] },
  {
    value: "ollama",
    label: "Ollama (local LLM)",
    real: true,
    fields: [
      { name: "endpoint", label: "Endpoint", placeholder: "http://localhost:11434" },
      { name: "model", label: "Model", placeholder: "llama3.1:8b" },
    ],
  },
  {
    value: "openai",
    label: "OpenAI",
    real: true,
    fields: [
      { name: "api_key", label: "API key", secret: true, placeholder: "sk-…" },
      { name: "model", label: "Model", placeholder: "gpt-4o" },
      { name: "base_url", label: "Base URL (optional)", placeholder: "https://api.openai.com/v1" },
    ],
  },
  {
    value: "anthropic",
    label: "Anthropic",
    real: true,
    fields: [
      { name: "api_key", label: "API key", secret: true, placeholder: "sk-ant-…" },
      { name: "model", label: "Model", placeholder: "claude-sonnet-4-…" },
      { name: "base_url", label: "Base URL (optional)", placeholder: "https://api.anthropic.com" },
    ],
  },
];

// Customer-facing CHANNELS (vendors that consume the service — e.g. WhatsApp). A
// "send-capable" channel (real whatsapp/telegram/sms) is refused on apply in
// demo-safe mode; the loopback/demo ones (fakewhatsapp, app, web, call_center)
// apply fully so the governed flow can be demoed end-to-end. Keep in sync with the
// backend allow-list _DEMO_SAFE_CHANNELS (used by _is_real_binding) in
// routers/governance_changes.py — the server is the security gate, not this list.
const CHANNEL_TYPES: { value: string; label: string; real: boolean; fields: PField[] }[] = [
  { value: "fakewhatsapp", label: "WhatsApp (demo · loopback, no real send)", real: false, fields: [] },
  { value: "app", label: "Mobile app", real: false, fields: [] },
  { value: "web", label: "Web chat", real: false, fields: [] },
  { value: "call_center", label: "Call center", real: false, fields: [] },
  {
    value: "whatsapp",
    label: "WhatsApp Business API (real · send-capable)",
    real: true,
    fields: [
      { name: "phone_number_id", label: "Phone number ID", placeholder: "100942…" },
      { name: "access_token", label: "Access token", secret: true, placeholder: "EAAB…" },
    ],
  },
  {
    value: "telegram",
    label: "Telegram bot (real · send-capable)",
    real: true,
    fields: [{ name: "bot_token", label: "Bot token", secret: true, placeholder: "123456:ABC-…" }],
  },
];

export default function ConnectionGovernance() {
  const { operator, setOperator } = useAppContext();
  const [changes, setChanges] = useState<ChangesData | null>(null);
  const [active, setActive] = useState<ActiveData | null>(null);
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"provider" | "channel">("provider");
  const [ptype, setPtype] = useState("fake");
  const [pfields, setPfields] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  // Two tones: errors are red (bc-error); informational notes (pre-fill, "removal
  // proposed", duplicate warning) are neutral so they never look like a failure.
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const clearNotes = () => {
    setError(null);
    setInfo(null);
  };
  const TYPES = kind === "channel" ? CHANNEL_TYPES : PROVIDER_TYPES;
  const currentSpec = TYPES.find((p) => p.value === ptype) ?? TYPES[0];

  const load = useCallback(async () => {
    const [c, a] = await Promise.all([
      fetch("/api/governance/changes", { cache: "no-store" }).then((r) => r.json() as Promise<ChangesData>),
      fetch("/api/governance/active-configs", { cache: "no-store" }).then(
        (r) => r.json() as Promise<ActiveData>,
      ),
    ]);
    setChanges(c);
    setActive(a);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      load().catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    };
    tick();
    const t = setInterval(() => { if (!document.hidden) tick(); }, 15000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [load]);

  // Clicking a node in the Connections topology (Conexoes.tsx) pre-fills this governed
  // form for that vendor — you select on the graph, but changing it is still propose →
  // approve → apply (never a free-form drag/create).
  useEffect(() => {
    const onPropose = (e: Event) => {
      const d = ((e as CustomEvent).detail || {}) as { type?: string; name?: string };
      const t = PROVIDER_TYPES.some((p) => p.value === d.type) ? (d.type as string) : "fake";
      const real = PROVIDER_TYPES.find((p) => p.value === t)?.real;
      setKind("provider");
      setPtype(t);
      setName(typeof d.name === "string" ? d.name : "");
      setPfields({});
      setError(null);
      setInfo(
        `Pre-filled a ${t} provider from the topology — adjust and propose a governed change` +
          (real ? " (real vendor: re-enter the secret; demo-safe blocks apply)." : "."),
      );
      const el = document.getElementById("propose-provider-name");
      el?.scrollIntoView({ behavior: "smooth", block: "center" });
      (el as HTMLInputElement | null)?.focus();
    };
    window.addEventListener("bridge:propose-provider", onPropose);
    return () => window.removeEventListener("bridge:propose-provider", onPropose);
  }, []);

  async function submitProvider() {
    const clean = name.trim();
    if (!clean) return;
    setBusy(true);
    clearNotes();
    // Collect the non-empty settings for the chosen vendor; secret fields (api_key) are
    // masked at rest by the backend, never echoed back.
    const cfg: Record<string, string> = {};
    for (const f of currentSpec.fields) {
      const v = (pfields[f.name] || "").trim();
      if (v) cfg[f.name] = v;
    }
    try {
      const r = await fetch("/api/governance/changes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind,
          summary: `Activate ${ptype} ${kind} "${clean}"`,
          submitted_by: operator,
          payload: { name: clean, type: ptype, is_real: currentSpec.real, ...cfg },
        }),
        cache: "no-store",
      });
      const j = await r.json().catch(() => null);
      if (!r.ok) {
        setError(apiErrorText(j, r.status));
      } else {
        setName("");
        setPfields({});
        await load();
        if (j?.duplicate_warning) setInfo(j.duplicate_warning);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  // Governed EDIT: pre-fill the propose form from an existing config (secrets can't be
  // recovered from the masked store, so they're re-entered). Submitting creates a NEW
  // versioned governed change — never an in-place mutation.
  function editConfig(cfg: ActiveCfg) {
    const c = cfg.config as Record<string, unknown>;
    const k = cfg.domain === "channel" ? "channel" : "provider";
    const types = k === "channel" ? CHANNEL_TYPES : PROVIDER_TYPES;
    const t = typeof c.type === "string" ? c.type : types[0].value;
    const spec = types.find((p) => p.value === t);
    setKind(k);
    setName(cfg.name);
    setPtype(t);
    const nf: Record<string, string> = {};
    if (spec) for (const f of spec.fields) {
      if (!f.secret && typeof c[f.name] === "string") nf[f.name] = c[f.name] as string;
    }
    setPfields(nf);
    setError(null);
    setInfo(
      `Editing "${cfg.name}" — adjust below and propose a new governed version` +
        (spec?.fields.some((f) => f.secret) ? " (re-enter the secret)." : "."),
    );
    document.getElementById("propose-provider-name")?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  // Governed REMOVE: propose a remove change; it takes effect only after approve + apply.
  async function removeConfig(cfg: ActiveCfg) {
    setBusy(true);
    clearNotes();
    try {
      const t = typeof cfg.config.type === "string" ? cfg.config.type : "fake";
      const dkind = cfg.domain === "channel" ? "channel" : "provider";
      const r = await fetch("/api/governance/changes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: dkind,
          summary: `Remove ${dkind} "${cfg.name}"`,
          submitted_by: operator,
          payload: { name: cfg.name, type: t, op: "remove" },
        }),
        cache: "no-store",
      });
      const j = await r.json().catch(() => null);
      if (!r.ok) setError(apiErrorText(j, r.status));
      else {
        await load();
        setInfo(`Removal of "${cfg.name}" proposed — approve + apply (3 distinct operators) to take effect.`);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  // asOperator lets the inline one-click buttons switch the acting operator AND act in a
  // single step — the state setter is async, so we pass the operator explicitly here
  // instead of reading the (stale) `operator` after setOperator().
  async function act(id: number, action: "approve" | "reject" | "apply", asOperator?: string) {
    setBusy(true);
    clearNotes();
    const who = asOperator ?? operator;
    if (asOperator && asOperator !== operator) setOperator(asOperator);
    try {
      const url =
        action === "apply"
          ? `/api/governance/changes/${id}/apply`
          : `/api/governance/changes/${id}/decision`;
      const body = action === "apply" ? { applier: who } : { decision: action, reviewer: who };
      const r = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        cache: "no-store",
      });
      const j = await r.json().catch(() => null);
      if (!r.ok) {
        setError(apiErrorText(j, r.status)); // surfaces SoD / replay / config_hash reason
      } else {
        await load();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const connChanges = (changes?.changes ?? []).filter((c) => CONN_KINDS.has(c.kind));
  // Split the trail so the one thing that needs a human (pending/approved) isn't buried
  // under a wall of finished changes (applied/rejected) — those collapse into "history".
  const isActionable = (c: Change) => c.status === "pending" || c.status === "approved";
  const actionable = connChanges.filter(isActionable);
  const history = connChanges.filter((c) => !isActionable(c));
  const visibleChanges = showHistory ? [...actionable, ...history] : actionable;

  return (
    <div className="bc-card" style={{ marginTop: 16 }}>
      <div className="bc-card-h">
        <h2>
          Governed connection management
          <StateBadge feature="governed-changes" />
        </h2>
        <span style={{ fontSize: 12, color: "var(--bc-text-mute)" }}>
          create → approve → apply · current operator: <strong>{operator}</strong> (switch at the top)
        </span>
      </div>

      {/* Quick connect — the whole vendor catalog as one-click chips (channels +
          providers), so the user picks visually instead of discovering the "kind"
          dropdown. A chip pre-fills the governed form; propose → approve → apply
          is unchanged. The selected chip is highlighted. */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 10 }}>
        <span style={{ fontSize: 11, color: "var(--bc-text-mute)" }}>
          Quick connect — pick a vendor, then name it and propose:
        </span>
        {[
          { group: "Channels", gk: "channel" as const, list: CHANNEL_TYPES },
          { group: "LLM providers", gk: "provider" as const, list: PROVIDER_TYPES },
        ].map(({ group, gk, list }) => (
          <div key={group} style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
            <span style={{ fontSize: 10, color: "var(--bc-text-dim)", minWidth: 84 }}>{group}</span>
            {list.map((v) => {
              const short = v.label.split(" (")[0];
              const active = kind === gk && ptype === v.value;
              return (
                <button
                  key={`${gk}:${v.value}`}
                  type="button"
                  className="bc-chip"
                  aria-pressed={active}
                  title={`Pre-fill the form to add ${v.label}`}
                  onClick={() => {
                    setKind(gk);
                    setPtype(v.value);
                    setPfields({});
                    setName(short);
                    const el = document.getElementById("propose-provider-name");
                    el?.scrollIntoView({ behavior: "smooth", block: "center" });
                    (el as HTMLInputElement | null)?.focus();
                  }}
                  style={{
                    fontSize: 11,
                    padding: "2px 8px",
                    cursor: "pointer",
                    border: active ? "1px solid var(--bc-accent)" : undefined,
                    background: active ? "var(--bc-accent-bg)" : undefined,
                  }}
                >
                  ＋ {short}{v.real ? " · real" : ""}
                </button>
              );
            })}
          </div>
        ))}
      </div>

      {/* Propose a provider: vendor type + its connection settings (governed change) */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 10 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <input
            // id is load-bearing — Conexoes.tsx's "New connection" button scrolls/focuses
            // it cross-component; see COORDINATION.md "Shared DOM contracts".
            id="propose-provider-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submitProvider()}
            placeholder="connection name…"
            className="bc-input"
            maxLength={120}
            style={{ flex: 1, minWidth: 160 }}
          />
          <select
            value={kind}
            onChange={(e) => {
              const k = e.target.value as "provider" | "channel";
              setKind(k);
              setPtype(k === "channel" ? "fakewhatsapp" : "fake");
              setPfields({});
            }}
            className="bc-input"
            aria-label="Connection kind"
            style={{ minWidth: 140 }}
          >
            <option value="provider">LLM provider</option>
            <option value="channel">Channel (e.g. WhatsApp)</option>
          </select>
          <select
            value={ptype}
            onChange={(e) => { setPtype(e.target.value); setPfields({}); }}
            className="bc-input"
            aria-label="Vendor type"
            style={{ minWidth: 180 }}
          >
            {TYPES.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
        </div>
        {currentSpec.fields.map((f) => (
          <input
            key={f.name}
            type={f.secret ? "password" : "text"}
            value={pfields[f.name] || ""}
            onChange={(e) => setPfields((prev) => ({ ...prev, [f.name]: e.target.value }))}
            placeholder={f.placeholder ? `${f.label} — ${f.placeholder}` : f.label}
            className="bc-input"
            maxLength={300}
            autoComplete="off"
          />
        ))}
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <button
            type="button"
            className="bc-btn"
            onClick={submitProvider}
            disabled={busy || !name.trim()}
            title={!name.trim() ? "Enter a connection name first" : undefined}
            style={{ fontSize: 13 }}
          >
            ＋ Propose {kind}
          </button>
          {currentSpec.real && (
            <span style={{ fontSize: 11, color: "var(--bc-flag-line)" }}>
              Real vendor — secrets are masked at rest; in demo-safe mode apply is blocked
              (set BRIDGE_DEMO_SAFE=off on the server to enable).
            </span>
          )}
        </div>
      </div>
      {!name.trim() && (
        <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: -4, marginBottom: 8 }}>
          Type a connection name above to enable the propose button.
        </div>
      )}
      {error && (
        <div className="bc-error" role="alert" style={{ marginBottom: 8, fontSize: 12 }}>
          {error}
        </div>
      )}
      {info && (
        <div
          role="status"
          style={{
            marginBottom: 8,
            fontSize: 12,
            color: "var(--bc-info-line)",
            background: "var(--bc-surface-2)",
            border: "1px solid var(--bc-border)",
            borderLeft: "3px solid var(--bc-info-line)",
            borderRadius: 6,
            padding: "8px 10px",
          }}
        >
          {info}
        </div>
      )}

      {/* Live system-of-record */}
      <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginBottom: 4 }}>
        Active config (system-of-record)
      </div>
      <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginBottom: 6, fontStyle: "italic" }}>
        Applying records the governed config; the live LLM backend is set by server env at startup, and
        channels are config-only in this demo (no live binding).
      </div>
      {active && active.n > 0 ? (
        <table className="bc-table" style={{ marginBottom: 14 }}>
          <thead>
            <tr>
              <th>Connection</th>
              <th>Kind · type</th>
              <th>Applied by</th>
              <th>Config (masked)</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {active.configs.map((cfg) => (
              <tr key={`${cfg.domain}:${cfg.name}`}>
                <td style={{ fontWeight: 600 }}>{cfg.name}</td>
                <td style={{ fontSize: 11, color: "var(--bc-text-dim)" }}>
                  {cfg.domain} · {String(cfg.config.type ?? "—")}
                </td>
                <td style={{ fontSize: 11, color: "var(--bc-text-dim)" }}>{cfg.updated_by ?? "—"}</td>
                <td style={{ fontFamily: "monospace", fontSize: 11, color: "var(--bc-text-mute)" }}>
                  {Object.entries(cfg.config).map(([k, v]) => `${k}: ${v && typeof v === "object" ? "••••" : String(v)}`).join(" · ")}
                </td>
                <td>
                  <span style={{ display: "flex", gap: 4 }}>
                    <button type="button" className="bc-btn ghost" onClick={() => editConfig(cfg)} disabled={busy} style={{ fontSize: 11, padding: "2px 8px" }}>
                      edit
                    </button>
                    <button type="button" className="bc-btn ghost" onClick={() => removeConfig(cfg)} disabled={busy} title="Propose a governed removal (approve + apply to take effect)" style={{ fontSize: 11, padding: "2px 8px" }}>
                      remove
                    </button>
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div style={{ fontSize: 12, color: "var(--bc-text-mute)", marginBottom: 14 }}>
          no active config yet — propose a connection, approve (with a different operator), and apply.
        </div>
      )}

      {/* Change ledger (connection kinds only) — needs-action first, history collapses */}
      <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginBottom: 4 }}>
        Connection changes — needs your action{actionable.length > 0 ? ` (${actionable.length})` : ""}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {connChanges.length > 0 && actionable.length === 0 && !showHistory && (
          <div style={{ fontSize: 12, color: "var(--bc-text-mute)", padding: "2px 0" }}>
            Nothing needs your attention right now — every change is applied or rejected.
          </div>
        )}
        {visibleChanges.slice(0, 12).map((c) => {
          const st = STATUS[c.status] ?? { color: "var(--bc-text-mute)", label: c.status };
          const isSubmitter = operator === c.submitted_by;
          const sodTitle = isSubmitter
            ? "You submitted this change — a different operator must review/apply (SR 11-7). Switch the operator at the top."
            : undefined;
          // Four-eyes on apply: the approver cannot also execute (mirrors the backend guard).
          const isReviewer = c.reviewer != null && operator === c.reviewer;
          const cannotApply = isSubmitter || isReviewer;
          const applyTitle = isSubmitter
            ? sodTitle
            : isReviewer
              ? "You approved this change — the approver cannot also apply it (four-eyes / SR 11-7). Switch the operator at the top."
              : undefined;
          // Accurate "applied" status: a removal is NOT in the active config, and an
          // activation can be superseded/removed by a later change — so only the change
          // that produced the CURRENT live config may claim "it is now in the Active
          // config above" (otherwise the trail contradicts the empty Active-config box).
          const tgtName = typeof c.payload?.name === "string" ? (c.payload.name as string) : null;
          const isRemoval = c.payload?.op === "remove";
          const supersededByLater =
            tgtName != null &&
            connChanges.some(
              (o) => o.id > c.id && o.status === "applied" && o.kind === c.kind && o.payload?.name === tgtName,
            );
          const isLiveConfig =
            !isRemoval &&
            !supersededByLater &&
            tgtName != null &&
            (active?.configs.some((cfg) => cfg.domain === c.kind && cfg.name === tgtName) ?? false);
          // Visible "what to do next" — so a greyed-out button never looks broken.
          // The four-eyes flow is the #1 source of "nothing works"; spell out the move.
          const nextStep: { text: string; color: string } | null =
            c.status === "pending"
              ? isSubmitter
                ? { text: "You submitted this — approve as a different operator with the one-click buttons below (segregation of duties).", color: "var(--bc-flag-line)" }
                : { text: "Ready to review — click approve or reject.", color: "var(--bc-info-line)" }
              : c.status === "approved"
                ? cannotApply
                  ? { text: "Approved already — apply as a third operator (not the submitter or the reviewer) with the buttons below (four-eyes).", color: "var(--bc-flag-line)" }
                  : { text: "Ready to apply — click apply.", color: "var(--bc-info-line)" }
                : c.status === "applied"
                  ? isRemoval
                    ? { text: "Applied — removed from the Active config.", color: "var(--bc-text-mute)" }
                    : isLiveConfig
                      ? { text: "Applied — it is now in the Active config above.", color: "var(--bc-pass-line)" }
                      : { text: "Applied — no longer the active config (replaced or removed by a later change).", color: "var(--bc-text-mute)" }
                  : c.status === "rejected"
                    ? { text: "Rejected — it did not enter the active config.", color: "var(--bc-text-mute)" }
                    : null;
          // One-click "switch operator + act" right here — so the client never has to
          // hunt for the top selector. Only operators eligible for the NEXT action.
          const inlineAction: "approve" | "apply" | null =
            c.status === "pending" && isSubmitter
              ? "approve"
              : c.status === "approved" && cannotApply
                ? "apply"
                : null;
          const switchTo: string[] =
            inlineAction === "approve"
              ? OPERATORS.filter((o) => o !== c.submitted_by)
              : inlineAction === "apply"
                ? OPERATORS.filter((o) => o !== c.submitted_by && o !== c.reviewer)
                : [];
          return (
            <div
              key={c.id}
              style={{
                background: "var(--bc-surface-2)",
                border: "1px solid var(--bc-border)",
                borderRadius: 6,
                padding: "6px 10px",
                opacity: isActionable(c) ? 1 : 0.55,
              }}
            >
              <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
                <span style={{ fontSize: 9, color: "var(--bc-text-mute)", textTransform: "uppercase" }}>
                  {c.kind}
                </span>
                <span style={{ flex: 1, fontSize: 12, color: "var(--bc-text)" }}>{c.summary}</span>
                <span style={{ fontSize: 10, fontWeight: 700, color: st.color, textTransform: "uppercase" }}>
                  {st.label}
                </span>
                {c.status === "pending" && (
                  <span style={{ display: "flex", gap: 4 }}>
                    <button type="button" className="bc-btn ghost" onClick={() => act(c.id, "approve")} disabled={busy || isSubmitter} title={sodTitle} style={{ fontSize: 11, padding: "2px 8px" }}>
                      approve
                    </button>
                    <button type="button" className="bc-btn ghost" onClick={() => act(c.id, "reject")} disabled={busy || isSubmitter} title={sodTitle} style={{ fontSize: 11, padding: "2px 8px" }}>
                      reject
                    </button>
                  </span>
                )}
                {c.status === "approved" && (
                  <button type="button" className="bc-btn" onClick={() => act(c.id, "apply")} disabled={busy || cannotApply} title={applyTitle} style={{ fontSize: 11, padding: "2px 10px" }}>
                    apply
                  </button>
                )}
              </div>
              <div style={{ fontSize: 10, color: "var(--bc-text-mute)", marginTop: 2 }}>
                submitted by {c.submitted_by}
                {c.reviewer ? ` · reviewed by ${c.reviewer}` : ""}
                {c.applied_by ? ` · applied by ${c.applied_by}` : ""}
              </div>
              {nextStep && (
                <div style={{ fontSize: 11, color: nextStep.color, marginTop: 3 }}>
                  → {nextStep.text}
                </div>
              )}
              {inlineAction && switchTo.length > 0 && (
                <div style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 4, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 10, color: "var(--bc-text-mute)" }}>
                    one click ({inlineAction === "approve" ? "switch + approve" : "switch + apply"}):
                  </span>
                  {switchTo.map((o) => (
                    <button
                      key={o}
                      type="button"
                      className="bc-chip"
                      onClick={() => act(c.id, inlineAction, o)}
                      disabled={busy}
                      title={`Switch the operator to ${o} and ${inlineAction} this change in one step`}
                      style={{ fontSize: 10, padding: "1px 8px", cursor: "pointer" }}
                    >
                      {inlineAction === "approve" ? "Approve as " : "Apply as "}
                      {o}
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}
        {connChanges.length === 0 && (
          <div style={{ fontSize: 12, color: "var(--bc-text-mute)" }}>
            no connection changes yet — propose a provider or channel above.
          </div>
        )}
        {history.length > 0 && (
          <button
            type="button"
            className="bc-btn ghost"
            onClick={() => setShowHistory((v) => !v)}
            style={{ fontSize: 11, padding: "3px 10px", alignSelf: "flex-start", marginTop: 2 }}
          >
            {showHistory ? `▲ Hide history (${history.length})` : `▼ Show history (${history.length})`}
          </button>
        )}
      </div>

      <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 8 }}>
        Segregation of duties: the reviewer and the applier must each be a different operator from the
        submitter (use the one-click buttons on a change, or the operator selector at the top). Secrets are
        masked; in demo-safe mode, real providers are rejected.
      </div>
    </div>
  );
}
