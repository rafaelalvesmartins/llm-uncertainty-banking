// Single source of truth for the UI's honesty layer (Bloco A1 + A5).
//
// Every dashboard panel declares here what it actually does and where its
// data comes from, classified as:
//   LIVE   — calls a backend endpoint that returns REAL runtime state.
//   MOCK   — calls a backend endpoint, but the data is canned / pre-seeded
//            (e.g. demo personas, demo RAG docs) rather than computed from a
//            real upstream system.
//   STATIC — pure informational UI, makes no backend call.
//
// `StateBadge` renders the badge + tooltip from this map (A1); `HowThisWorks`
// renders the Feature Map table and cross-checks each `endpoints` path against
// the live /openapi.json so the list can't silently drift (A5).
//
// `endpoints` use BACKEND paths (what /openapi.json exposes); the frontend
// reaches them through the matching /api/* proxy route.

export type FeatureState = "LIVE" | "MOCK" | "STATIC";

export interface Feature {
  /** Display name — matches the panel's <h2>. */
  name: string;
  state: FeatureState;
  /** Backend paths this panel calls, as "METHOD /path". */
  endpoints: string[];
  /** One phrase: what it does + where the data comes from. */
  what: string;
}

export const FEATURE_MAP = {
  "customer-query": {
    name: "Customer Query",
    state: "LIVE",
    endpoints: ["POST /query", "POST /query/stream"],
    what: "Sends the question through the real 12-stage pipeline and shows the guard's decision.",
  },
  "pipeline-trace": {
    name: "Pipeline Trace",
    state: "LIVE",
    endpoints: ["POST /query"],
    what: "Shows the 12 stages of the last query; click a stage to see what it does, its relative latency, and confidence.",
  },
  "demo-controls": {
    name: "Demo Controls",
    state: "LIVE",
    endpoints: ["GET /settings", "PUT /settings"],
    what: "Adjusts the guard threshold and toggles the cache at runtime; the effect shows on the next query.",
  },
  "bridge-metrics": {
    name: "Bridge Metrics",
    state: "LIVE",
    endpoints: ["GET /metrics", "GET /metrics/timeseries"],
    what: "Aggregates totals, decision mix, confidence and latency across every query this session; the timeseries feeds the live decision-trend chart.",
  },
  "sessions": {
    name: "Sessions by Customer",
    state: "LIVE",
    endpoints: ["GET /sessions"],
    what: "Groups the audit trail by customer/conversation — pick a customer and see the whole session (queries, intents, decisions, cost, PII). Operate like a bank, not loose log lines.",
  },
  "audit-trail": {
    name: "Recent Audit Trail",
    state: "LIVE",
    endpoints: [
      "GET /audit",
      "GET /audit/verify",
      "POST /audit/tamper-test",
      "GET /audit/replay/{seq}",
      "GET /audit/explain/{seq}",
      "GET /explain/{audit_index}",
      "DELETE /audit",
    ],
    what: "Live window of the tamper-evident hash-chain; verify/tamper/replay/explain/rotate operate on the in-memory store.",
  },
  "registered-agents": {
    name: "Registered Agents",
    state: "LIVE",
    endpoints: ["GET /agents"],
    what: "Lists the agents actually registered on the platform (chatbot / smart_payments / call_center).",
  },
  "semantic-cache": {
    name: "Semantic Cache",
    state: "LIVE",
    endpoints: ["GET /cache", "DELETE /cache"],
    what: "Real SemanticCache statistics (hits/misses); matches by normalized key, no embeddings in the demo.",
  },
  "customer-memory": {
    name: "Customer Memory",
    state: "MOCK",
    endpoints: ["GET /customers", "GET /customers/{id}"],
    what: "11 pre-seeded personas served by /customers; the memory store itself updates at runtime.",
  },
  "rag-corpus": {
    name: "RAG Corpus",
    state: "MOCK",
    endpoints: ["GET /docs/corpus"],
    what: "5 pre-loaded documents; the real TF-IDF retrieval runs over them on every query.",
  },
  "data-quality": {
    name: "Data Quality (DQ)",
    state: "LIVE",
    endpoints: ["GET /dq-dg"],
    what: "Real DQ-rule counters (blocks/warnings) accumulated this session.",
  },
  "data-governance": {
    name: "Data Governance (DG)",
    state: "LIVE",
    endpoints: ["GET /dq-dg"],
    what: "Real PII-masking (LGPD) counters accumulated this session.",
  },
  "intent-catalog": {
    name: "Intent Catalog",
    state: "LIVE",
    endpoints: ["GET /intents"],
    what: "The classifier's real catalog of 24 intents, with per-family counts this session.",
  },
  "drift-detection": {
    name: "Drift Detection",
    state: "LIVE",
    endpoints: ["GET /drift", "POST /drift/baseline", "POST /drift/auto-rebaseline"],
    what: "Real TV-distance between the baseline and the current window; the baseline auto-captures at query #50, manually, or auto-rebaselines every N.",
  },
  "ops-dashboard": {
    name: "Ops Dashboard",
    state: "LIVE",
    endpoints: ["GET /stats", "GET /stages/budgets", "GET /queue/depth", "GET /audit/export"],
    what: "Real watchdog (uptime/RPS/errors), per-stage latency budgets, and audit export.",
  },
  "auth": {
    name: "Authentication (v6 Phase 1)",
    state: "LIVE",
    endpoints: ["POST /auth/token", "GET /auth/jwks"],
    what: "Real EdDSA-JWT auth, ADDITIVE and gated by BRIDGE_AUTH (off by default = demo intact). When on, governance derives submitter/reviewer from the verified token — segregation of duties stops being defensible by mere strings. No dedicated panel yet (login UX is a later phase).",
  },
  "governed-changes": {
    name: "Governed Changes",
    state: "LIVE",
    endpoints: ["GET /governance/changes", "POST /governance/changes", "POST /governance/changes/{id}/decision", "POST /governance/changes/{id}/apply", "GET /governance/active-configs"],
    what: "Governed change workflow (add an agent/intent/DQ rule/RAG doc/channel/provider) behind dated approval with segregation of duties (reviewer ≠ submitter, SR 11-7) AND governed execution: the 'apply' step writes the active config (system-of-record) with a replay guard, config_hash (TOCTOU) and SoD on apply, without exposing secrets. PERSISTED in SQLite (survives restart). Demo operators — no real auth (v6 phase).",
  },
  "evidence-package": {
    name: "Evidence Package",
    state: "LIVE",
    endpoints: ["GET /evidence/package", "POST /evidence/verify", "GET /evidence/oscal"],
    what: "Assembles the archivable model-risk record (Model Card + calibration + crosswalk + SR 11-7), with a sha256 hash and an Ed25519 SIGNATURE over (hash | timestamp); exportable and verifiable (altering any byte fails verification). A non-repudiable supervisory evidence artifact.",
  },
  "integrations": {
    name: "Integrations",
    state: "LIVE",
    endpoints: ["GET /integrations"],
    what: "Inventory of LLM providers (FakeBackend, Ollama, OpenAI/Anthropic) with Ollama's real reachability (loaded models) and which backend is active. Switched via a server environment variable — never an API key in the UI (NeMo/Guardrails pattern).",
  },
  "playground": {
    name: "Playground",
    state: "LIVE",
    endpoints: ["POST /playground/compare"],
    what: "Runs the same query at several guard thresholds and shows how the decision (Pass/Flag/Re-ask/Escalate) flips, side by side. Side-effect-free; high-risk intents escalate at any threshold.",
  },
  "assistant": {
    name: "Ask AI",
    state: "LIVE",
    endpoints: ["POST /assistant/ask"],
    what: "Opt-in copilot that explains the panels and decisions in plain language using the REAL LLM (local Ollama). Degrades honestly when Ollama is unavailable — never fabricates an answer.",
  },
  "experiments": {
    name: "Experiments",
    state: "LIVE",
    endpoints: ["GET /datasets", "GET /datasets/{id}", "GET /experiments/run"],
    what: "Runs the battery of labeled cases (a versioned dataset) through the REAL classifier and scores predicted-vs-expected, with accuracy, failures and a reproducible hash. It's the SR 11-7 'effective challenge': re-run after changing the model and watch for regression.",
  },
  "vulnerability-scan": {
    name: "Vulnerability Scan",
    state: "LIVE",
    endpoints: ["GET /security/vulnerability-scan"],
    what: "Fixed battery of adversarial probes (injection, credential, PII, crisis, fraud) run against the REAL defenses (dq_input / data_governance / intent+guard) in defense-in-depth, with a content hash. Not an exhaustive pentest.",
  },
  "fleet-inventory": {
    name: "Fleet Inventory",
    state: "MOCK",
    endpoints: ["GET /fleet"],
    what: "Portfolio of agents (owner, risk, lifecycle, ECE, cost, review). Only the 'Bridge Banking AI' entry is this deployment (LIVE); the rest are seeded agents (MOCK) to illustrate governance at scale.",
  },
  "model-card": {
    name: "Model Card",
    state: "LIVE",
    endpoints: ["GET /model-card"],
    what: "Inventory / Model Card (SR 11-7 §IV): identity, intended use, components, controls and limitations, pinned by the real version/prompt/corpus fingerprints.",
  },
  "calibration": {
    name: "Calibration",
    state: "LIVE",
    endpoints: ["GET /calibration"],
    what: "Reliability diagram + real ECE/Brier/AUROC (lub.calibration) for the intent classifier over the catalog's labeled example queries.",
  },
  "challenge-nightly": {
    name: "Continuous Effective Challenge",
    state: "LIVE",
    endpoints: ["GET /challenge/nightly"],
    what: "Runs the SAME verdict rule as the scheduled `lub challenge-nightly` job (lub.challenge.nightly) over this deployment's labeled intent samples: measured ECE vs the bounded context's target, plus the challenge layer's own meta-calibration. Tri-state — PASS / FAIL / INCONCLUSIVE, where INCONCLUSIVE means the evidence was insufficient to judge and is NOT a pass. The demo classifier's confidence is a keyword heuristic, so a FAIL here is the gate working, not a defect hidden.",
  },
  "regulatory-coverage": {
    name: "Regulatory Coverage",
    state: "LIVE",
    endpoints: ["GET /compliance/frameworks"],
    what: "Surfaces the real compliance frameworks from lub's crosswalk (BCB 4.893, BCBS 239, EU AI Act, ISO 42001/23894, NIST AI RMF, SR 11-7) with their controls — multi-jurisdiction coverage.",
  },
  "sr-11-7": {
    name: "SR 11-7 Compliance",
    state: "LIVE",
    endpoints: ["GET /compliance/sr-11-7"],
    what: "SR 11-7 crosswalk derived from the running process's real version/prompt/corpus fingerprints.",
  },
  "feedback": {
    name: "Feedback (no panel)",
    state: "LIVE",
    endpoints: ["GET /feedback", "POST /feedback"],
    what: "Functional endpoint that collects customer feedback (helpful/not) and aggregates helpful_rate — still WITHOUT a dedicated UI control (callable only via API/proxy).",
  },
  "handoff": {
    name: "Human Handoff (no panel)",
    state: "LIVE",
    endpoints: ["GET /handoff", "POST /handoff"],
    what: "Functional endpoint that queues a handoff to a human agent and shows the queue — still WITHOUT a dedicated UI control (callable only via API/proxy).",
  },
  "ai-visibility": {
    name: "AI Visibility",
    state: "LIVE",
    endpoints: [
      "GET /visibility/config",
      "PUT /visibility/config",
      "POST /visibility/run",
      "POST /visibility/schedule",
      "GET /visibility/results",
      "GET /visibility/history",
    ],
    what: "Measures brands' share-of-voice; real guard + audit hash-chain over each collection + a time series in SQLite. Real adapters (OpenAI/Anthropic) activate only with an API key; the default is the offline fake.",
  },
  "ai-recommendations": {
    name: "AI Recommendations (B3)",
    state: "LIVE",
    endpoints: ["GET /visibility/recommendations"],
    what: "Prioritizes our own brand's visibility gaps by volume × (1 − SoV) × measurement confidence. A pure function over the last collection's data.",
  },
  "ai-content": {
    name: "AI Content (B4, human-gated)",
    state: "LIVE",
    endpoints: [
      "POST /visibility/content/draft",
      "GET /visibility/content",
      "POST /visibility/content/{draft_id}/approve",
    ],
    what: "Generates drafts gated by the uncertainty guard: Flag/Escalate are BLOCKED; only Pass queues for explicit human approval. Never auto-publishes; no real external channel.",
  },
} satisfies Record<string, Feature>;

export type FeatureId = keyof typeof FEATURE_MAP;

/** Ordered list for the Feature Map table (A5). */
export const FEATURE_IDS = Object.keys(FEATURE_MAP) as FeatureId[];

/** Normalize a path so "/a/{seq}" and "/a/{id}" compare equal. */
export function normalizePath(path: string): string {
  return path.replace(/\{[^}]+\}/g, "{}").replace(/\/+$/, "");
}

/** Strip the leading "METHOD " from an endpoint string. */
export function endpointPath(endpoint: string): string {
  return endpoint.replace(/^[A-Z]+\s+/, "");
}
