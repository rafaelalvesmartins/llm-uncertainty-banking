// Shared data contracts for the /console redesign.
//
// These mirror the backend response shapes (backend/models.py + routers) so
// every console view binds to the same field names. They are console-local
// copies (not imported from the legacy panels) to keep the console
// self-contained and let the 6 view-builder agents share one source of truth.

export type Decision = "PASSTHROUGH" | "FLAG" | "REASK" | "ESCALATE";

/** A single pipeline stage in a /query response. */
export interface Stage {
  name: string;
  status: string; // "OK" | "BLOCKED" | "WARNING" | "HIT" | ...
  detail: string;
  confidence?: number | null;
  duration_ms: number;
}

/** POST /query response. */
export interface QueryResult {
  query: string;
  answer: string;
  intent: string;
  confidence: number; // 0..1
  decision: Decision | string;
  latency_ms: number;
  stages: Stage[];
  cache_hit?: boolean;
  cache_similarity?: number | null;
  tier?: string | null; // "SIMPLE" | "MEDIUM" | "COMPLEX"
  cost_cents?: number | null;
  memory_blocks?: string[];
  citations?: string[];
  handoff_chain?: string[];
  agent_used?: string | null;
  /** Hash-chain seq of THIS decision's audit entry — the handle for GET /audit/explain/{seq}
   *  (LGPD Art. 20: the right to an explanation of an automated decision). Null only if the
   *  audit sink failed, in which case the UI hides the explain affordance rather than guess. */
  audit_seq?: number | null;
}

export type Channel = "whatsapp" | "app" | "web" | "call_center";

/** POST /query request body. customer_id must match ^[A-Za-z0-9._-]{1,64}$. */
export interface QueryRequest {
  query: string;
  channel: Channel;
  customer_id: string;
  idempotency_key?: string | null;
}

/** One LLM provider/backend in GET /integrations. */
export interface Provider {
  id: string;
  name: string;
  kind: string;
  status: string; // active | available | reachable | unreachable | not_configured
  live?: boolean;
  reachable?: boolean;
  models?: string[];
  configured_model?: string | null;
  model_loaded?: boolean | null;
  endpoint?: string;
  note?: string;
}

/** GET /integrations response. */
export interface Integrations {
  active_backend: string;
  n_providers: number;
  n_available: number;
  providers: Provider[];
  switch_note: string;
  checked_at: string;
}

/** GET /health snapshot. */
export interface Health {
  status?: string;
  backend?: string;
  backend_is_real?: boolean;
  /** Air-gapped profile in force (LUB_LOCAL_ONLY) — enforced by the library. */
  local_only?: boolean;
}

// /metrics and /audit shapes are permissive on purpose — the Metricas and
// Auditoria views read them defensively and may declare a tighter local
// interface after inspecting the live endpoint / legacy panel.
export type Metrics = Record<string, unknown>;
export type AuditEntry = Record<string, unknown>;

/** Map a guard decision to its semantic color family (used by views). */
export function decisionTone(d: string): "pass" | "flag" | "reask" | "block" {
  const k = (d || "").toUpperCase();
  if (k === "PASSTHROUGH") return "pass";
  if (k === "FLAG") return "flag";
  if (k === "REASK") return "reask";
  // Governance lifecycle events (a change proposed / approved / rejected / applied) are NOT
  // customer escalations — painting them red would make a healthy four-eyes approval look
  // like an incident on the dashboard feed.
  if (k === "APPLIED" || k === "APPROVED") return "pass";
  if (k === "PENDING") return "flag"; // awaiting a second person
  if (k === "REJECTED") return "reask"; // a reviewer turned it down — deliberate, not an alarm
  return "block"; // ESCALATE + anything unknown → strongest signal
}

/** Client-facing plain label for a guard decision token — the single source of
 *  truth so screens stop showing the raw "PASSTHROUGH/FLAG/REASK/ESCALATE" codes.
 *  Unknown values fall back to the raw token so nothing is silently hidden. */
export const DECISION_LABEL: Record<string, string> = {
  PASSTHROUGH: "Pass",
  FLAG: "Flag",
  REASK: "Re-ask",
  ESCALATE: "Escalate",
  // Governed-change lifecycle steps (they share the audit trail with guard decisions).
  APPLIED: "Config applied",
  PENDING: "Change proposed",
  APPROVED: "Change approved",
  REJECTED: "Change rejected",
};
export function decisionLabel(d: string): string {
  return DECISION_LABEL[(d || "").toUpperCase()] ?? d;
}

/** A few intents don't read well under the generic title-case rule (acronyms,
 *  language codes). Override just those; everything else falls through. */
const INTENT_LABELS: Record<string, string> = {
  pix: "PIX",
  aml_suspect: "AML suspect",
  aml_review: "AML review",
  non_pt: "Other language",
  third_party_data: "Third-party data",
  age_minor: "Underage account",
};

/** snake_case intent → human-readable ("balance_inquiry" → "Balance inquiry"). */
export function humanizeIntent(intent: string): string {
  if (!intent) return intent;
  const override = INTENT_LABELS[intent.toLowerCase()];
  if (override) return override;
  const s = intent.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}
