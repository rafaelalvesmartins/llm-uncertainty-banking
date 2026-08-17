"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import StateBadge from "@/components/StateBadge";
import { useAppContext } from "@/components/AppContextProvider";
import { apiErrorText } from "@/lib/apiError";

interface Change {
  id: number;
  kind: string;
  summary: string;
  submitted_by: string;
  submitted_at: number;
  status: string;
  reviewer: string | null;
  decided_at: number | null;
  decision_note: string | null;
  payload?: Record<string, unknown>;
}
interface Data {
  n: number;
  by_status: Record<string, number>;
  changes: Change[];
}

const STATUS_COLOR: Record<string, string> = { pending: "var(--bc-flag-line)", approved: "var(--bc-pass-line)", rejected: "var(--bc-block-line)", applied: "var(--bc-info-line)" };

// Lifecycle order, plain labels + a one-line hint of where each status sits in the
// propose → approve → apply chain (so the operator reads the stacked bar as progress).
const STATUS_KEYS = ["pending", "approved", "applied", "rejected"] as const;
const STATUS_LABEL: Record<string, string> = { pending: "Pending", approved: "Approved", applied: "Applied", rejected: "Rejected" };
const STATUS_HINT: Record<string, string> = {
  pending: "waiting on a second person to approve",
  approved: "approved — waiting on a third person to apply",
  applied: "applied — live",
  rejected: "rejected",
};

// At-a-glance picture of where every change sits in the propose → approve → apply
// lifecycle. Same stacked-bar pattern as the Sessions decision-mix; segments and legend
// toggle the status filter. Turns the whole point of this screen (a multi-person approval
// chain) from gray prose into one glanceable bar.
function StatusMixBar({
  byStatus,
  total,
  active,
  onPick,
}: {
  byStatus: Record<string, number>;
  total: number;
  active: string;
  onPick: (s: string) => void;
}) {
  const counts = STATUS_KEYS.map((k) => byStatus?.[k] ?? 0);
  const sum = counts.reduce((a, b) => a + b, 0);
  if (sum === 0) return null;
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 5 }}>
        <span style={{ fontSize: 11, color: "var(--bc-text-mute)", textTransform: "uppercase", letterSpacing: 0.4 }}>Change status</span>
        <span style={{ fontSize: 11, color: "var(--bc-text-dim)" }}>propose → approve → apply, by three different people</span>
      </div>
      <div
        style={{ display: "flex", width: "100%", height: 16, borderRadius: 8, overflow: "hidden", border: "1px solid var(--bc-border)" }}
        role="img"
        aria-label={`Change status: ${STATUS_KEYS.map((k, i) => `${STATUS_LABEL[k]} ${counts[i]}`).join(", ")}`}
      >
        {STATUS_KEYS.map((k, i) => {
          const pct = (counts[i] / sum) * 100;
          if (pct === 0) return null;
          const dimmed = active !== "" && active !== k;
          return (
            <button
              key={k}
              type="button"
              onClick={() => onPick(k)}
              title={`${STATUS_LABEL[k]} (${STATUS_HINT[k]}): ${counts[i]} (${pct.toFixed(0)}%)`}
              style={{ width: `${pct}%`, height: "100%", border: "none", padding: 0, cursor: "pointer", background: STATUS_COLOR[k], opacity: dimmed ? 0.3 : 1, transition: "opacity .15s" }}
            />
          );
        })}
      </div>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 6 }}>
        {STATUS_KEYS.map((k, i) => {
          if (counts[i] === 0) return null;
          const pct = (counts[i] / sum) * 100;
          const dimmed = active !== "" && active !== k;
          return (
            <button
              key={k}
              type="button"
              onClick={() => onPick(k)}
              title={STATUS_HINT[k]}
              style={{ display: "flex", alignItems: "center", gap: 5, background: "transparent", border: "none", padding: 0, cursor: "pointer", opacity: dimmed ? 0.45 : 1, fontSize: 11 }}
            >
              <span style={{ width: 9, height: 9, borderRadius: 2, background: STATUS_COLOR[k] }} />
              <span style={{ color: "var(--bc-text)" }}>{STATUS_LABEL[k]}</span>
              <span style={{ color: "var(--bc-text-dim)" }}>{counts[i]} · {pct.toFixed(0)}%</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// Per-kind form spec. Each kind now collects STRUCTURED fields that become the
// change `payload` — so the backend's config_hash binds to the actual content
// (SR 11-7 tamper-evidence). Before this, every Agent/Intent/DQ/RAG change sent
// an empty payload, so config_hash was always SHA256("{}") and meant nothing.
type FieldSpec = {
  name: string;
  label: string;
  type?: "text" | "textarea" | "number" | "select";
  options?: string[];
  placeholder?: string;
};
type Fields = Record<string, string>;
interface KindSpec {
  label: string;
  fields: FieldSpec[];
  required: string[];
  summary: (f: Fields) => string;
  payload: (f: Fields) => Record<string, unknown>;
}

const lines = (s: string): string[] =>
  (s || "").split("\n").map((x) => x.trim()).filter(Boolean);
const num = (s: string): number | null => (s?.trim() ? Number(s) : null);

const KIND_SPECS: Record<string, KindSpec> = {
  agent: {
    label: "Agent",
    fields: [
      { name: "name", label: "Name", placeholder: "e.g. pj-collections" },
      { name: "model", label: "Model", placeholder: "e.g. llama3.1:8b" },
      { name: "system_prompt", label: "System prompt", type: "textarea", placeholder: "Role + guardrails…" },
    ],
    required: ["name"],
    summary: (f) => `Add agent "${f.name}"${f.model ? ` on ${f.model}` : ""}`,
    payload: (f) => ({ name: f.name?.trim(), model: f.model?.trim() || null, system_prompt: f.system_prompt?.trim() || "" }),
  },
  intent: {
    label: "Intent",
    fields: [
      { name: "name", label: "Intent name", placeholder: "e.g. pix_scheduled" },
      { name: "family", label: "Family", type: "select", options: ["banking", "fraud", "safety"] },
      { name: "threshold", label: "Confidence threshold", type: "number", placeholder: "0.00–1.00" },
      { name: "samples", label: "Sample utterances (one per line)", type: "textarea", placeholder: "schedule a pix for tomorrow\nrecurring transfer every month" },
    ],
    required: ["name"],
    summary: (f) => `Add intent "${f.name}" (${f.family || "banking"})`,
    payload: (f) => ({ name: f.name?.trim(), family: f.family || "banking", threshold: num(f.threshold), samples: lines(f.samples) }),
  },
  dq_rule: {
    label: "DQ Rule",
    fields: [
      { name: "name", label: "Rule name", placeholder: "e.g. max_message_length" },
      { name: "condition", label: "Condition", placeholder: "e.g. len(message) > threshold" },
      { name: "threshold", label: "Threshold", type: "number", placeholder: "e.g. 5000" },
      { name: "severity", label: "Severity", type: "select", options: ["warning", "blocking"] },
    ],
    required: ["name", "condition"],
    summary: (f) => `Add DQ rule "${f.name}": ${f.condition}`.slice(0, 300),
    payload: (f) => ({ name: f.name?.trim(), condition: f.condition?.trim(), threshold: num(f.threshold), severity: f.severity || "warning" }),
  },
  rag_doc: {
    label: "RAG Doc",
    fields: [
      { name: "title", label: "Title", placeholder: "e.g. PIX limits 2026" },
      { name: "source", label: "Source", placeholder: "e.g. BCB Manual" },
      { name: "content", label: "Content", type: "textarea", placeholder: "Document body the retriever will index…" },
    ],
    required: ["title", "content"],
    summary: (f) => `Add RAG doc "${f.title}"`,
    payload: (f) => ({ title: f.title?.trim(), source: f.source?.trim() || "", content: f.content?.trim() || "" }),
  },
};

// Reverse of each spec.payload(): turn a stored change payload back into the
// form's string fields, so "Edit" pre-fills the form from an existing change.
// The ledger stays append-only — editing produces a NEW proposal, never mutates
// the recorded one (that would void its config_hash / tamper-evidence).
function fieldsFromPayload(kind: string, payload: Record<string, unknown> | undefined): Fields {
  const p = payload || {};
  const s = (v: unknown): string => (v === null || v === undefined ? "" : String(v));
  switch (kind) {
    case "agent":
      return { name: s(p.name), model: s(p.model), system_prompt: s(p.system_prompt) };
    case "intent":
      return { name: s(p.name), family: s(p.family), threshold: s(p.threshold), samples: Array.isArray(p.samples) ? (p.samples as unknown[]).join("\n") : s(p.samples) };
    case "dq_rule":
      return { name: s(p.name), condition: s(p.condition), threshold: s(p.threshold), severity: s(p.severity) };
    case "rag_doc":
      return { title: s(p.title), source: s(p.source), content: s(p.content) };
    default:
      return {};
  }
}

// Canonical JSON that matches the backend's json.dumps(sort_keys, separators=(",",":")),
// so the client-side preview hash equals the config_hash the ledger will store
// (these kinds have no secret fields, so there is no masking divergence).
function canonical(obj: unknown): string {
  if (obj === null || typeof obj !== "object") return JSON.stringify(obj);
  if (Array.isArray(obj)) return "[" + obj.map(canonical).join(",") + "]";
  const o = obj as Record<string, unknown>;
  return "{" + Object.keys(o).sort().map((k) => JSON.stringify(k) + ":" + canonical(o[k])).join(",") + "}";
}

async function sha256Hex(text: string): Promise<string | null> {
  try {
    const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
  } catch {
    return null; // crypto.subtle unavailable (non-secure context) — skip the preview hash
  }
}

export default function GovernedChangesPanel() {
  const { operator } = useAppContext();
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<keyof typeof KIND_SPECS>("agent");
  const [fields, setFields] = useState<Fields>({});
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [previewHash, setPreviewHash] = useState<string | null>(null);
  const [editingFrom, setEditingFrom] = useState<number | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [visibleCount, setVisibleCount] = useState(12);
  const cardRef = useRef<HTMLDivElement>(null);

  const spec = KIND_SPECS[kind];
  const isValid = spec.required.every((r) => (fields[r] || "").trim());
  const builtPayload = useMemo(() => spec.payload(fields), [spec, fields]);
  const builtSummary = useMemo(() => spec.summary(fields), [spec, fields]);
  const canonicalPayload = useMemo(() => canonical(builtPayload), [builtPayload]);

  // Live config_hash preview — re-derives whenever the structured payload changes,
  // so the operator SEES the fingerprint move with the content (the whole point).
  useEffect(() => {
    let cancelled = false;
    if (!isValid) {
      setPreviewHash(null);
      return;
    }
    sha256Hex(canonicalPayload).then((h) => {
      if (!cancelled) setPreviewHash(h);
    });
    return () => {
      cancelled = true;
    };
  }, [canonicalPayload, isValid]);

  async function load() {
    try {
      const r = await fetch("/api/governance/changes", { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData(await r.json());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | undefined;
    const attempt = () => {
      fetch("/api/governance/changes", { cache: "no-store" })
        .then(async (r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then((j) => {
          if (cancelled) return;
          setData(j);
          setError(null);
          if (timer) clearInterval(timer);
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

  function setField(name: string, value: string) {
    setFields((f) => ({ ...f, [name]: value }));
  }
  function selectKind(k: keyof typeof KIND_SPECS) {
    setKind(k);
    setFields({}); // type-specific fields don't carry over between kinds
    setEditingFrom(null);
    setNote(null);
  }
  // Clone an existing change into the form so the operator can tweak + resubmit
  // without retyping. Produces a NEW change on submit (append-only ledger).
  function editFrom(c: Change) {
    if (!KIND_SPECS[c.kind]) return;
    setKind(c.kind as keyof typeof KIND_SPECS);
    setFields(fieldsFromPayload(c.kind, c.payload));
    setEditingFrom(c.id);
    setNote(null);
    cardRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  function clearEdit() {
    setFields({});
    setEditingFrom(null);
    setNote(null);
  }

  async function submit() {
    if (!isValid || busy) return;
    setBusy(true);
    setNote(null);
    try {
      const r = await fetch("/api/governance/changes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, summary: builtSummary.trim(), submitted_by: operator, payload: builtPayload }),
        cache: "no-store",
      });
      const j = await r.json().catch(() => null);
      if (!r.ok) {
        setNote(apiErrorText(j, r.status));
        return;
      }
      setFields({});
      setEditingFrom(null);
      await load();
      const msgs: string[] = [];
      if (j?.config_hash) msgs.push(`stored with config_hash ${String(j.config_hash).slice(0, 12)}…`);
      if (j?.duplicate_warning) msgs.push(j.duplicate_warning);
      setNote(msgs.join(" · ") || null);
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function decide(id: number, decision: "approve" | "reject") {
    setBusy(true);
    setNote(null);
    try {
      const r = await fetch(`/api/governance/changes/${id}/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, reviewer: operator }),
        cache: "no-store",
      });
      if (!r.ok) {
        const j = await r.json().catch(() => null);
        // segregation-of-duties etc. — surface the backend reason
        setNote(apiErrorText(j, r.status));
      } else {
        await load();
        setNote(decision === "approve"
          ? `✓ Change #${id} approved — a third operator must apply it.`
          : `✓ Change #${id} rejected.`);
      }
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  // Apply an approved change into the live system-of-record (now generalized backend-side
  // to agent/intent/dq_rule/rag_doc, not just provider/channel). Four-eyes: the applier
  // must differ from both submitter and reviewer — enforced by the backend, surfaced here.
  async function apply(id: number) {
    setBusy(true);
    setNote(null);
    try {
      const r = await fetch(`/api/governance/changes/${id}/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ applier: operator }),
        cache: "no-store",
      });
      if (!r.ok) {
        const j = await r.json().catch(() => null);
        setNote(apiErrorText(j, r.status));
      } else {
        await load();
        setNote(`✓ Change #${id} applied — now live.`);
      }
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  // Governed REMOVE of an applied object: propose an op:"remove" change for it; it takes
  // effect only after approve + apply (the backend apply deletes the active_configs row).
  async function removeObj(c: Change) {
    const p = c.payload ?? {};
    const objName = String((p.name as string) || (p.title as string) || "");
    if (!objName) {
      setNote("Cannot determine the object name to remove.");
      return;
    }
    setBusy(true);
    setNote(null);
    try {
      const r = await fetch("/api/governance/changes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: c.kind,
          summary: `Remove ${c.kind} "${objName}"`,
          submitted_by: operator,
          payload: { name: objName, op: "remove" },
        }),
        cache: "no-store",
      });
      if (!r.ok) {
        const j = await r.json().catch(() => null);
        setNote(apiErrorText(j, r.status));
      } else {
        await load();
        setNote(`Removal of "${objName}" proposed — approve + apply (3 distinct operators) to take effect.`);
      }
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (error && !data) {
    return (
      <div className="card card--wide">
        <h2>Governed Changes</h2>
        <div className="empty error" role="alert">backend unreachable ({error})</div>
      </div>
    );
  }

  const inputStyle: React.CSSProperties = {
    background: "var(--bc-bg)",
    border: "1px solid var(--bc-border)",
    borderRadius: 6,
    padding: "6px 8px",
    color: "var(--bc-text)",
    fontSize: 12,
    width: "100%",
    boxSizing: "border-box",
  };
  const labelStyle: React.CSSProperties = { fontSize: 10, color: "var(--bc-text-dim)", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 3, display: "block" };

  return (
    <div className="card card--wide" ref={cardRef}>
      <h2>
        Governed Changes
        <StateBadge feature="governed-changes" />
        <span className="card-subtitle">Every add / edit / remove needs a dated approval by a different person — segregation of duties (SR 11-7)</span>
      </h2>

      {editingFrom !== null && (
        <div style={{ fontSize: 11, color: "var(--bc-info-line)", marginBottom: 8, display: "flex", alignItems: "center", gap: 8 }}>
          ✎ Editing a copy of change #{editingFrom} — submitting creates a NEW change (the ledger is append-only).
          <button type="button" onClick={clearEdit} style={{ ...inputStyle, width: "auto", fontSize: 10, padding: "1px 6px", cursor: "pointer" }}>
            clear
          </button>
        </div>
      )}

      {/* Kind selector */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
        {Object.entries(KIND_SPECS).map(([k, s]) => (
          <button
            key={k}
            type="button"
            onClick={() => selectKind(k as keyof typeof KIND_SPECS)}
            style={{
              ...inputStyle,
              width: "auto",
              fontWeight: kind === k ? 700 : 400,
              borderColor: kind === k ? "var(--bc-info-line)" : "var(--bc-border)",
              color: kind === k ? "var(--bc-text)" : "var(--bc-text-dim)",
              cursor: "pointer",
            }}
          >
            {s.label}
          </button>
        ))}
      </div>

      {/* Type-specific fields — no longer one free-text box for everything */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
        {spec.fields.map((f) => {
          const full = f.type === "textarea";
          return (
            <div key={f.name} style={{ gridColumn: full ? "1 / -1" : undefined }}>
              <label style={labelStyle}>
                {f.label}
                {spec.required.includes(f.name) ? " *" : ""}
              </label>
              {f.type === "select" ? (
                <select aria-label={f.label} value={fields[f.name] ?? f.options?.[0] ?? ""} onChange={(e) => setField(f.name, e.target.value)} style={inputStyle}>
                  {f.options?.map((o) => (
                    <option key={o} value={o}>{o}</option>
                  ))}
                </select>
              ) : f.type === "textarea" ? (
                <textarea value={fields[f.name] ?? ""} onChange={(e) => setField(f.name, e.target.value)} placeholder={f.placeholder} rows={3} style={{ ...inputStyle, resize: "vertical" }} />
              ) : (
                <input
                  type={f.type === "number" ? "number" : "text"}
                  value={fields[f.name] ?? ""}
                  onChange={(e) => setField(f.name, e.target.value)}
                  placeholder={f.placeholder}
                  style={inputStyle}
                />
              )}
            </div>
          );
        })}
      </div>

      {/* Preview — what will actually be created, the derived summary, and the
          live config_hash so the tamper-evidence is visible BEFORE submitting. */}
      <div style={{ background: "#0b1220", border: "1px solid var(--bc-surface)", borderRadius: 6, padding: "8px 10px", marginBottom: 8 }}>
        <div style={labelStyle}>Preview — what gets recorded</div>
        <div style={{ fontSize: 12, color: "var(--bc-text)", marginBottom: 4 }}>
          <span style={{ color: "var(--bc-text-dim)" }}>summary:</span> {isValid ? builtSummary : <span style={{ color: "var(--bc-text-mute)" }}>fill the required fields…</span>}
        </div>
        <pre style={{ margin: 0, fontSize: 11, color: "var(--bc-text-dim)", fontFamily: "monospace", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          {JSON.stringify(builtPayload, null, 2)}
        </pre>
        <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 4, fontFamily: "monospace" }}>
          config_hash (SHA-256 of payload):{" "}
          <span style={{ color: previewHash ? "var(--bc-pass-line)" : "var(--bc-text-mute)" }}>
            {isValid ? (previewHash ?? "computing…") : "—"}
          </span>
        </div>
        <div style={{ fontSize: 10, color: "var(--bc-text-mute)", marginTop: 3 }}>
          This is a fingerprint that locks this approval to the exact change — if anyone alters it, auditors will see.
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <button
          type="button"
          onClick={submit}
          disabled={busy || !isValid}
          style={{ ...inputStyle, width: "auto", fontWeight: 600, cursor: busy || !isValid ? "default" : "pointer", borderColor: isValid ? "var(--bc-info-line)" : "var(--bc-border)" }}
        >
          Propose {spec.label.toLowerCase()} as {operator}
        </button>
        {!isValid && (
          <span style={{ fontSize: 11, color: "var(--bc-text-mute)" }}>
            Fill {spec.required.join(" + ")} to enable.
          </span>
        )}
      </div>
      {note && <div style={{ fontSize: 11, color: "var(--bc-flag-line)", marginBottom: 6 }}>{note}</div>}
      <div style={{ fontSize: 10, color: "var(--bc-text-mute)", marginBottom: 6 }}>
        What happens next: you propose it → a different operator approves → a third operator applies it.
      </div>

      {data && data.n > 0 && (
        <StatusMixBar
          byStatus={data.by_status}
          total={data.n}
          active={statusFilter}
          onPick={(s) => { setStatusFilter(s === statusFilter ? "" : s); setVisibleCount(12); }}
        />
      )}

      {/* Status filter — find the pending / approved ones among the applied. */}
      {data && data.n > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8, alignItems: "center" }}>
          {(["", "pending", "approved", "applied", "rejected"] as const).map((st) => {
            const count = st === "" ? data.n : (data.by_status?.[st] ?? 0);
            if (st !== "" && count === 0) return null;
            const on = statusFilter === st;
            return (
              <button
                key={st || "all"}
                type="button"
                onClick={() => { setStatusFilter(st); setVisibleCount(12); }}
                style={{
                  ...inputStyle, width: "auto", fontSize: 11, padding: "2px 10px", cursor: "pointer",
                  borderColor: on ? (STATUS_COLOR[st] || "var(--bc-accent)") : undefined,
                  color: on ? (STATUS_COLOR[st] || "var(--bc-text)") : "var(--bc-text-mute, var(--bc-text-dim))",
                  fontWeight: on ? 700 : 400,
                }}
              >
                {st === "" ? "all" : st} {count}
              </button>
            );
          })}
        </div>
      )}

      {/* list */}
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {(statusFilter ? (data?.changes || []).filter((c) => c.status === statusFilter) : (data?.changes || [])).slice(0, visibleCount).map((c) => (
          <div
            key={c.id}
            style={{ background: "var(--bc-bg)", border: "1px solid var(--bc-surface)", borderRadius: 6, padding: "6px 10px" }}
          >
            <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
              <span style={{ fontSize: 9, color: "var(--bc-text-dim)", textTransform: "uppercase" }}>{c.kind}</span>
              <span style={{ flex: 1, fontSize: 12, color: "var(--bc-text)" }}>{c.summary}</span>
              <span style={{ fontSize: 10, fontWeight: 700, color: STATUS_COLOR[c.status] || "var(--bc-text-dim)", textTransform: "uppercase" }}>
                {c.status}
              </span>
              {KIND_SPECS[c.kind] && (
                <button type="button" onClick={() => editFrom(c)} disabled={busy}
                  title="Pre-fill the form with this change's fields to tweak and propose a new version (the original stays — append-only ledger)."
                  style={{ ...inputStyle, width: "auto", fontSize: 11, padding: "2px 8px", color: "#93c5fd", cursor: busy ? "default" : "pointer" }}>
                  edit
                </button>
              )}
              {c.status === "pending" && (
                <span style={{ display: "flex", gap: 4 }}>
                  <button type="button" onClick={() => decide(c.id, "approve")}
                    disabled={busy || operator === c.submitted_by}
                    title={operator === c.submitted_by ? "You submitted this change — a different operator must review it (SR 11-7). Switch the operator at the top." : undefined}
                    style={{ ...inputStyle, width: "auto", fontSize: 11, padding: "2px 8px", color: "var(--bc-pass-line)", cursor: busy || operator === c.submitted_by ? "default" : "pointer" }}>
                    approve
                  </button>
                  <button type="button" onClick={() => decide(c.id, "reject")}
                    disabled={busy || operator === c.submitted_by}
                    title={operator === c.submitted_by ? "You submitted this change — a different operator must review it (SR 11-7). Switch the operator at the top." : undefined}
                    style={{ ...inputStyle, width: "auto", fontSize: 11, padding: "2px 8px", color: "var(--bc-block-line)", cursor: busy || operator === c.submitted_by ? "default" : "pointer" }}>
                    reject
                  </button>
                </span>
              )}
              {c.status === "approved" && (
                <button type="button" onClick={() => apply(c.id)}
                  disabled={busy || operator === c.submitted_by || operator === c.reviewer}
                  title={operator === c.submitted_by || operator === c.reviewer ? "Four-eyes: the applier must differ from BOTH the submitter and the reviewer (SR 11-7). Switch the operator at the top." : undefined}
                  style={{ ...inputStyle, width: "auto", fontSize: 11, padding: "2px 10px", color: "var(--bc-info-line)", cursor: busy || operator === c.submitted_by || operator === c.reviewer ? "default" : "pointer" }}>
                  apply
                </button>
              )}
              {c.status === "applied" && !/^Remove /.test(c.summary) && (
                <button type="button" onClick={() => removeObj(c)} disabled={busy}
                  title="Propose a governed removal of this object (approve + apply to delete it)."
                  style={{ ...inputStyle, width: "auto", fontSize: 11, padding: "2px 8px", color: "#f87171", cursor: busy ? "default" : "pointer" }}>
                  remove
                </button>
              )}
            </div>
            {c.status === "pending" && operator === c.submitted_by && (
              <div style={{ fontSize: 10, color: "var(--bc-flag-line)", marginTop: 3 }}>
                You proposed this — a different person must approve (bank rule). Switch the operator at the top.
              </div>
            )}
            {c.status === "approved" && (operator === c.submitted_by || operator === c.reviewer) && (
              <div style={{ fontSize: 10, color: "var(--bc-flag-line)", marginTop: 3 }}>
                You {operator === c.submitted_by ? "proposed" : "approved"} this — a third person must apply it (bank rule). Switch the operator at the top.
              </div>
            )}
            <div style={{ fontSize: 10, color: "var(--bc-text-mute)", marginTop: 2 }}>
              submitted by {c.submitted_by}
              {c.reviewer ? ` · ${c.status} by ${c.reviewer}` : ""}
            </div>
          </div>
        ))}
        {data && data.n === 0 && <div className="muted" style={{ fontSize: 12 }}>no changes yet — propose one above.</div>}
        {(() => {
          const filtered = statusFilter ? (data?.changes || []).filter((c) => c.status === statusFilter) : (data?.changes || []);
          if (statusFilter && filtered.length === 0) return <div className="muted" style={{ fontSize: 12 }}>no {statusFilter} changes.</div>;
          if (filtered.length > visibleCount) {
            return (
              <button type="button" onClick={() => setVisibleCount((v) => v + 12)}
                style={{ ...inputStyle, width: "auto", fontSize: 11, padding: "3px 10px", cursor: "pointer", alignSelf: "center", marginTop: 4 }}>
                Show {Math.min(12, filtered.length - visibleCount)} more ({filtered.length - visibleCount} older)
              </button>
            );
          }
          return null;
        })()}
      </div>

      <div style={{ fontSize: 11, color: "var(--bc-text-mute)", marginTop: 8 }}>
        Each change records a structured payload; its <strong>config_hash</strong> binds the approval to the
        exact content (SR 11-7 tamper-evidence). <strong>Edit</strong> clones a change into the form to tweak +
        re-propose — the original stays untouched (append-only). Persisted in SQLite. Demo operators — no real
        auth (phase v6). The reviewer must differ from the submitter (segregation of duties).
      </div>
    </div>
  );
}
