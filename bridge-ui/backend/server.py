"""Bridge UI Backend — FastAPI BFF for the Next.js dashboard.

Wraps the existing :mod:`lub.connectors.bridge` platform with:
- A fake LLM backend (no API key required) so the demo runs offline.
- CORS enabled for the Next.js dev server (localhost:3000).
- A pipeline trace endpoint that returns every stage of the request
  flow so the UI can visualize: intent -> agent -> guard -> response.

Run with::

    cd bridge-ui/backend
    pip install -r requirements.txt
    uvicorn server:app --reload --port 8000
"""

from __future__ import annotations

import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Final, Literal

# Add lub source to path so we can import the Bridge platform
_LUB_SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(_LUB_SRC))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from lub.compliance.frameworks import sr_11_7
from lub.connectors.bridge.complexity import ComplexityRouter, ComplexityTier
from lub.connectors.bridge.customer_memory import CustomerMemory, InMemoryMemoryStore
from lub.connectors.bridge.data_governance import DataClassification, DataGovernor
from lub.connectors.bridge.data_quality import (
    DataQualityChecker,
    default_input_rules,
    default_output_rules,
)
from lub.connectors.bridge.handoffs import (
    run_with_handoffs,
)
from lub.connectors.bridge.memory import SemanticCache
from lub.connectors.bridge.rag import (
    Document,
    InMemoryDocumentStore,
    RAGPipeline,
    TFIDFRetriever,
)

# ---------------------------------------------------------------------------
# Fake LLM backend (no API key needed)
# ---------------------------------------------------------------------------

# Canned response templates now live in core/responses.py (decoupling step 6a) — a pure
# data leaf, re-exported so the agents + _answer (still here) and the backends module both
# use it without a circular import.
try:
    from core.responses import _RESPONSES  # noqa: F401
except ImportError:  # package-mode import (backend.server)
    from backend.core.responses import _RESPONSES  # noqa: F401


# LLM backends (FakeBackend / OllamaBackend + selection + Ollama circuit-breaker/queue)
# now live in backends.py (decoupling step 6b). They import _RESPONSES from core.responses
# (NOT from server) -> no circular import: server -> backends -> core.responses. The
# singleton _BACKEND = _select_backend() stays in server.py (below); _answer + the agent
# classes (still here) use _BACKEND / _LLM_ALLOWED_INTENTS via these re-exports. Plain
# re-exports — the rebound _OLLAMA queue/breaker scalars are internal (reached only via the
# re-exported functions), so no proxy is needed.
try:
    from backends import (  # noqa: F401
        FakeBackend,
        OllamaBackend,
        _select_backend,
        _LLM_ALLOWED_INTENTS,
        _OLLAMA_URL,
        _OLLAMA_MODEL,
        _OLLAMA_TIMEOUT_S,
        _OLLAMA_NUM_PREDICT,
        _OLLAMA_BREAKER_THRESHOLD,
        _OLLAMA_BREAKER_WINDOW_S,
        _OLLAMA_BREAKER_COOLDOWN_S,
        _OLLAMA_MAX_QUEUE,
        _OLLAMA_SEMAPHORE,
        _OLLAMA_QUEUE_LOCK,
        _ollama_breaker_open,
        _ollama_record_failure,
        _ollama_queue_enter,
        _ollama_queue_exit,
        _ollama_queue_depth,
    )
except ImportError:  # package-mode import (backend.server)
    from backend.backends import (  # noqa: F401
        FakeBackend,
        OllamaBackend,
        _select_backend,
        _LLM_ALLOWED_INTENTS,
        _OLLAMA_URL,
        _OLLAMA_MODEL,
        _OLLAMA_TIMEOUT_S,
        _OLLAMA_NUM_PREDICT,
        _OLLAMA_BREAKER_THRESHOLD,
        _OLLAMA_BREAKER_WINDOW_S,
        _OLLAMA_BREAKER_COOLDOWN_S,
        _OLLAMA_MAX_QUEUE,
        _OLLAMA_SEMAPHORE,
        _OLLAMA_QUEUE_LOCK,
        _ollama_breaker_open,
        _ollama_record_failure,
        _ollama_queue_enter,
        _ollama_queue_exit,
        _ollama_queue_depth,
    )
# Stdlib aliases server.py still needs directly (the audit/backends blocks that defined
# these moved out; server.py uses _os_for_backend for CORS/env config and the _json_*
# aliases in the SSE /query/stream handlers).
import os as _os_for_backend  # noqa: E402
import json as _json_audit  # noqa: E402  (SSE /query/stream handlers use this alias; the audit module owns its own copy)

# ---------------------------------------------------------------------------
# Intent classifier (lightweight keyword-based)
# ---------------------------------------------------------------------------

# Intent classifier + safety detectors now live in core/classifier.py (decoupling
# step 2). Re-exported here so the agent classes below (_CallCenterAgent /
# _ChatbotAgent) and the _server() surface (routers + tests) that reference these
# names via server.X keep resolving unchanged. Pure logic, no server state.
try:
    from core.classifier import (  # noqa: F401
        _kw_in,
        _INTENT_KEYWORDS,
        _FRAUD_MARKERS,
        _CRISIS_MARKERS,
        _SOCIAL_ENG_MARKERS,
        _ILLEGAL_MARKERS,
        _AGE_NUMBER_RE,
        _AML_STRUCTURING_MARKERS,
        _URGENCY_MARKERS,
        _FAMILY_EMERGENCY_MARKERS,
        _PHISHING_DOMAIN_PATTERN,
        _AML_VALUE_PATTERN,
        _URGENCY_WORDS,
        _FAMILY_WORDS,
        _TRANSFER_VERBS,
        _VALUE_AMOUNT,
        detect_urgency_manipulation,
        _THIRD_PARTY_MARKERS,
        _THIRD_PARTY_REL_REGEX,
        _MANIPULATION_MARKERS,
        _PRIV_ESCAL_MARKERS,
        _PROMPT_LEAK_MARKERS,
        _PROFANITY_MARKERS,
        _DISCRIMINATION_MARKERS,
        _NON_PT_MARKERS,
        classify_intent,
        _INTENT_CATALOG,
    )
except ImportError:  # package-mode import (backend.server)
    from backend.core.classifier import (  # noqa: F401
        _kw_in,
        _INTENT_KEYWORDS,
        _FRAUD_MARKERS,
        _CRISIS_MARKERS,
        _SOCIAL_ENG_MARKERS,
        _ILLEGAL_MARKERS,
        _AGE_NUMBER_RE,
        _AML_STRUCTURING_MARKERS,
        _URGENCY_MARKERS,
        _FAMILY_EMERGENCY_MARKERS,
        _PHISHING_DOMAIN_PATTERN,
        _AML_VALUE_PATTERN,
        _URGENCY_WORDS,
        _FAMILY_WORDS,
        _TRANSFER_VERBS,
        _VALUE_AMOUNT,
        detect_urgency_manipulation,
        _THIRD_PARTY_MARKERS,
        _THIRD_PARTY_REL_REGEX,
        _MANIPULATION_MARKERS,
        _PRIV_ESCAL_MARKERS,
        _PROMPT_LEAK_MARKERS,
        _PROFANITY_MARKERS,
        _DISCRIMINATION_MARKERS,
        _NON_PT_MARKERS,
        classify_intent,
        _INTENT_CATALOG,
    )


# ---------------------------------------------------------------------------
# Guard simulation
# ---------------------------------------------------------------------------


# Guard decision logic now lives in core/guard.py (decoupling step 1). Re-exported
# here so the _server() surface — routers (playground/security/governance) and the
# query pipeline + tests that call apply_guard / _extract_risk_level — keeps working
# unchanged. Pure functions, no server state; behaviour identical.
try:
    from core.guard import _extract_risk_level, apply_guard
except ImportError:  # package-mode import (backend.server)
    from backend.core.guard import _extract_risk_level, apply_guard


# Safe body served whenever the guard withholds the substantive answer (REASK,
# and any non-releasing decision re-derived on a cache hit). Module-level so the
# fresh path and the cache-hit short-circuit share ONE source and cannot drift —
# this is the fix for the cache-hit confidentiality leak: a cached PASSTHROUGH
# answer must never reach the client under a re-derived REASK/ESCALATE label.
_REASK_SAFE_ANSWER: Final[str] = (
    "I don't have enough confidence to answer this safely.\n\n"
    "— I can help better if you tell me which area you'd like to handle: "
    "balance/statement, transfer/PIX, card, loan, or a complaint."
)


# ---------------------------------------------------------------------------
# In-memory metrics
# ---------------------------------------------------------------------------


# Runtime observability state (metrics / per-stage latency / drift baseline) now lives
# in state/runtime.py (decoupling step 5). Mostly in-place-mutated or never-reassigned
# -> plain re-exports; the drift scalars are setattr'd by routers/drift.py + rebound by
# _maybe_capture_baseline, so they are PROXIED live to state.runtime by the module-
# attribute proxy at end of file. _CACHE + _RUNTIME_* controls stay in server.py with
# the /query pipeline. (_PROXIED_ATTRS is defined HERE — the earliest shim — and reused
# by the audit shim below.)
_PROXIED_ATTRS: dict[str, object] = {}
try:
    from state.runtime import (  # noqa: F401  (stable: in-place / non-reassigned)
        _percentiles,
        _STAGE_LATENCIES,
        _STAGE_LATENCY_WINDOW,
        _STAGE_BUDGETS_MS,
        _record_stage_latency,
        Metrics,
        _METRICS,
        _DRIFT_BASELINE_AT_QUERIES,
        _snapshot_for_baseline,
        _maybe_capture_baseline,
    )
    from state import runtime as _runtime_state_mod
except ImportError:  # package-mode import (backend.server)
    from backend.state.runtime import (  # noqa: F401
        _percentiles,
        _STAGE_LATENCIES,
        _STAGE_LATENCY_WINDOW,
        _STAGE_BUDGETS_MS,
        _record_stage_latency,
        Metrics,
        _METRICS,
        _DRIFT_BASELINE_AT_QUERIES,
        _snapshot_for_baseline,
        _maybe_capture_baseline,
    )
    from backend.state import runtime as _runtime_state_mod
for _runtime_proxied_name in ('_DRIFT_BASELINE', '_DRIFT_LAST_AUTO_REBASELINE_AT_QUERY', '_DRIFT_AUTO_REBASELINE_EVERY',):
    _PROXIED_ATTRS[_runtime_proxied_name] = _runtime_state_mod
# v8 — pick real LLM (Ollama) if reachable; fall back to FakeBackend.
# Set BRIDGE_USE_REAL_LLM=off to force the fake (CI / no-network).
# Set BRIDGE_USE_REAL_LLM=required to hard-fail when Ollama / model missing.
_BACKEND = _select_backend()


def _flatten_memory(snap: dict[str, Any] | None) -> str:
    """Compact memory snapshot to a string the LLM prompt can consume."""
    if not snap:
        return ""
    parts: list[str] = []
    for name, block in snap.items():
        content = getattr(block, "content", "") or ""
        if content:
            parts.append(f"{name}: {content}")
    return "\n".join(parts)


def _answer(intent: str, query: str, context: dict[str, Any] | None = None) -> str:
    """Pick the answer for an intent: canned for safety, LLM for normal.

    Centralizes the safety/LLM split so every agent uses the same policy.
    Safety intents (crisis, social_engineering, illegal_activity, aml_review,
    card_fraud, non_pt) STAY canned regardless of backend — we never let the
    LLM improvise on safety-critical messaging. Everything else routes
    through _BACKEND.respond which may be FakeBackend or OllamaBackend.
    """
    if intent in _LLM_ALLOWED_INTENTS:
        memory = ""
        if context and "memory_snapshot" in context:
            memory = _flatten_memory(context["memory_snapshot"])
        return _BACKEND.respond(intent, query=query, memory=memory)
    return _RESPONSES.get(intent, _RESPONSES["general"])


# Tamper-evident audit trail (hash chain + SQLite) now lives in state/audit.py
# (decoupling step 3). It is STATEFUL: _audit_append rebinds _AUDIT_SEQ /
# _AUDIT_LAST_HASH / _AUDIT_DB, routers read the chain head via server._AUDIT_SEQ,
# and the chain tests set server._AUDIT_SEQ + monkeypatch server._audit_db. So the
# shared deque/lock and non-rebound functions are plain re-exports; the rebound /
# monkeypatched names are PROXIED live to state.audit by the module-attribute proxy
# installed at end of file (server.X always hits the sub-module's live globals).
# Behaviour + BCB-4893 chain semantics identical.
try:
    from state.audit import (  # noqa: F401  (stable: shared object / non-rebound fns)
        _AUDIT,
        _AUDIT_LOCK,
        _audit_append,
        _audit_chain_break,
        _audit_restore_from_db,
    )
    from state import audit as _audit_state_mod
except ImportError:  # package-mode import (backend.server)
    from backend.state.audit import (  # noqa: F401
        _AUDIT,
        _AUDIT_LOCK,
        _audit_append,
        _audit_chain_break,
        _audit_restore_from_db,
    )
    from backend.state import audit as _audit_state_mod
for _audit_proxied_name in ('_AUDIT_SEQ', '_AUDIT_LAST_HASH', '_AUDIT_DB', '_audit_db',):
    _PROXIED_ATTRS[_audit_proxied_name] = _audit_state_mod


# v7 — customer-feedback store for /feedback. Bounded for demo memory hygiene.
_FEEDBACK: deque[dict[str, Any]] = deque(maxlen=500)
_COMPLEXITY = ComplexityRouter()
_CACHE = SemanticCache(similarity_threshold=0.85, max_entries=200, max_age_seconds=300.0)

# v16 A2 — runtime-tunable demo controls (exposed via the /settings router so
# the UI can show the pipeline REACT). Lowering the guard threshold shifts the
# PASSTHROUGH/FLAG/REASK/ESCALATE mix on the next /query for ordinary intents;
# safety/fraud intents still hard-override to ESCALATE regardless. Toggling the
# cache off makes every query re-run the full pipeline. Defaults preserve the
# prior behavior (0.7 threshold, cache on).
_RUNTIME_GUARD_THRESHOLD: float = 0.7
_RUNTIME_CACHE_ENABLED: bool = True
GUARD_THRESHOLD_MIN: Final[float] = 0.1
GUARD_THRESHOLD_MAX: Final[float] = 0.95
GUARD_THRESHOLD_DEFAULT: Final[float] = 0.7

# --- Governed intent overlay (Theme A: applied 'intent' changes take effect) ---
# An approved + applied governed 'intent' change is written to the active_configs
# system-of-record (domain='intent'). The /query path consults this overlay so the
# change actually ALTERS BEHAVIOUR: a new intent becomes classifiable via its sample
# utterances, and any intent gets a governed decision / threshold override. TTL-cached
# so the hot path never hits SQLite per request; an apply takes effect within the TTL.
# The overlay NEVER weakens a protected safety/fraud escalation (see _is_protected_intent).
_GOV_INTENT_CACHE: dict[str, Any] | None = None
_GOV_INTENT_TS: float = 0.0
_GOV_INTENT_TTL: float = 3.0
_PROTECTED_INTENTS: Final[frozenset[str]] = frozenset({
    "crisis", "social_engineering", "illegal_activity", "aml_review", "aml_suspect",
    "third_party_data", "account_manipulation", "privilege_escalation", "discrimination",
    "phishing", "urgency_scam", "age_minor", "complaint_escalated", "prompt_leak",
    "card_fraud", "non_pt",
})


def _is_protected_intent(intent: str) -> bool:
    """A safety/fraud intent the guard force-escalates — a governed overlay must never
    weaken it (the safety floor stays above operator policy)."""
    return intent in _PROTECTED_INTENTS or "_fraud" in intent


def _governed_intent_policies() -> dict[str, Any]:
    """Applied governed intent policies (name -> config) from the active_configs
    system-of-record, TTL-cached. Resolved via the ALREADY-LOADED governance module
    (mirrors the channel-policy lookup) so the read hits the same store the router
    writes — never a divergent second instance."""
    global _GOV_INTENT_CACHE, _GOV_INTENT_TS
    now = time.time()
    if _GOV_INTENT_CACHE is not None and (now - _GOV_INTENT_TS) < _GOV_INTENT_TTL:
        return _GOV_INTENT_CACHE
    import sys as _sys
    _gc = _sys.modules.get("routers.governance_changes") or _sys.modules.get(
        "backend.routers.governance_changes"
    )
    policies: dict[str, Any] = {}
    if _gc is not None:
        try:
            policies = _gc.active_intent_policies()
        except Exception:  # noqa: BLE001 — overlay is best-effort; never break /query
            policies = {}
    _GOV_INTENT_CACHE = policies
    _GOV_INTENT_TS = now
    return policies


def _gov_tokens(text: str) -> set[str]:
    """Significant (>=4 char) alphanumeric word tokens — no regex dependency."""
    out: set[str] = set()
    for raw in (text or "").lower().split():
        w = "".join(ch for ch in raw if ch.isalnum())
        if len(w) >= 4:
            out.add(w)
    return out


def _match_governed_intent(query: str) -> str | None:
    """Return a governed intent whose sample utterances match the query (all significant
    words of some sample present), else None. Lets a NEW applied intent be classified."""
    q = _gov_tokens(query)
    if not q:
        return None
    for name, cfg in _governed_intent_policies().items():
        for sample in cfg.get("samples") or []:
            words = _gov_tokens(str(sample))
            if words and words <= q:
                return name
    return None


_CUSTOMER_MEMORY = CustomerMemory(store=InMemoryMemoryStore())
_DQ_INPUT = DataQualityChecker(rules=default_input_rules())
_DQ_OUTPUT = DataQualityChecker(rules=default_output_rules())
_GOVERNOR = DataGovernor()
_DQ_DG_STATS: dict[str, int] = {
    "input_blocks": 0,
    "input_warns": 0,
    "output_blocks": 0,
    "output_warns": 0,
    "pii_masked_total": 0,
    "queries_with_pii": 0,
}

# ---------------------------------------------------------------------------
# Rate limiter (item 7 of post-v1-review hardening)
# ---------------------------------------------------------------------------
# Token-bucket per customer_id. Wires the existing lub.connectors.bridge
# RateLimiter into the BFF. Cheap defaults sized for a demo; tune for prod.
# v10 B-NEW-17 — demo limit too aggressive (10 in 30s tripped reviewer's
# adversarial sweep). Bump burst to 30 + 180/min so a normal exploration
# session is unbounded but actual abuse still trips. Real production
# deployments override via env vars.
import os as _os_rl  # noqa: E402

from lub.connectors.bridge.rate_limiter import RateLimitConfig, RateLimiter  # noqa: E402

_RATE_LIMITER = RateLimiter(
    config=RateLimitConfig(
        requests_per_minute=int(_os_rl.environ.get("BRIDGE_RPM", "180")),
        burst_size=int(_os_rl.environ.get("BRIDGE_BURST", "30")),
    ),
)

# ---------------------------------------------------------------------------
# Idempotency cache (item 8 of post-v1-review hardening)
# ---------------------------------------------------------------------------
# Maps (customer_id, channel, idempotency_key) -> (response_dict, expiry_epoch).
# Retried requests within the TTL get the cached response so a network
# retry never produces a duplicate side effect (critical for /query that
# would, in production, kick off a transaction).
_IDEMPOTENCY_TTL_SECONDS: Final = 60.0
_IDEMPOTENCY_CACHE: dict[tuple[str, str, str], tuple[dict[str, Any], float]] = {}


def _idempotency_lookup(customer_id: str, channel: str, key: str | None) -> dict[str, Any] | None:
    if not key:
        return None
    now = time.time()
    cached = _IDEMPOTENCY_CACHE.get((customer_id, channel, key))
    if cached is None:
        return None
    payload, expiry = cached
    if now > expiry:
        # pop() instead of del: two concurrent requests with the same expired
        # key would both pass the check and the second del would KeyError.
        _IDEMPOTENCY_CACHE.pop((customer_id, channel, key), None)
        return None
    return payload


def _idempotency_store(customer_id: str, channel: str, key: str | None, payload: dict[str, Any]) -> None:
    if not key:
        return
    _IDEMPOTENCY_CACHE[(customer_id, channel, key)] = (
        payload,
        time.time() + _IDEMPOTENCY_TTL_SECONDS,
    )


def _channel_firewall_blocks(channel: str, intent: str) -> bool:
    """True if `intent` is NOT on the channel's governed allow-list (so it must be
    ESCALATEd). Empty / no allow-list → never blocks. Called on BOTH the fresh and the
    cache-hit paths so the semantic cache (and idempotent replay) can't bypass the
    per-channel firewall. Resolves governance via the already-loaded module (mirrors
    _server()) to avoid the two-instance trap."""
    import sys as _sys
    _gc_mod = _sys.modules.get("routers.governance_changes") or _sys.modules.get("backend.routers.governance_changes")
    _pol = _gc_mod.active_channel_policy(channel) if _gc_mod is not None else None
    _allow = _pol.get("allowed_intents") if isinstance(_pol, dict) else None
    return isinstance(_allow, list) and bool(_allow) and intent not in _allow


# Seed RAG corpus with banking docs (in real life, ingested from BCB / internal wiki).
_DOC_STORE = InMemoryDocumentStore()
_DOC_STORE.add(
    Document(
        id="pix-001",
        text=(
            "PIX e o sistema de pagamentos instantaneos do Banco Central do Brasil. Funciona 24 horas por dia, 7 dias por semana. Para PF nao ha tarifa. Para PJ a partir de janeiro 2024 podem ser cobradas tarifas conforme contrato. "
            "PIX is the instant payment system of the Central Bank of Brazil. It works 24 hours a day, 7 days a week. There is no fee for individuals (PF); businesses (PJ) may be charged fees per contract from January 2024."
        ),
        source="BCB PIX Manual 2024",
    )
)
_DOC_STORE.add(
    Document(
        id="ted-001",
        text=(
            "TED (Transferencia Eletronica Disponivel) opera em dias uteis das 6h30 as 17h. Liquidacao no mesmo dia. Tarifa varia por banco. No Bradesco e R$ 9,90 para PF. "
            "TED (Electronic Funds Transfer) operates on business days from 6:30 to 17:00. Same-day settlement. The fee varies by bank. At Bradesco it is R$ 9.90 for individuals (PF)."
        ),
        source="Bradesco TED Manual",
    )
)
_DOC_STORE.add(
    Document(
        id="iof-001",
        text=(
            "IOF nao incide sobre transferencias PIX entre contas brasileiras. Operacoes de cambio tem IOF de 1,1% conforme decreto 6.306. Cartao de credito internacional tem IOF de 6,38%. "
            "IOF does not apply to PIX transfers between Brazilian accounts. FX transactions carry a 1.1% IOF per Decree 6,306. International credit cards carry a 6.38% IOF."
        ),
        source="Receita Federal Decree 6,306",
    )
)
_DOC_STORE.add(
    Document(
        id="saldo-001",
        text=(
            "Para consultar saldo, o cliente pode acessar o app, internet banking, ATM ou pelo telefone 4002-0022. Em caso de divergencia, contatar o gerente. "
            "To check the balance, the customer can use the app, internet banking, an ATM, or call 4002-0022. In case of a discrepancy, contact the manager."
        ),
        source="Bradesco Service Manual",
    )
)
_DOC_STORE.add(
    Document(
        id="emprestimo-001",
        text=(
            "Emprestimo pessoal Bradesco tem taxas a partir de 1,99% ao mes para clientes com bom relacionamento. Limite ate 60 meses. Sujeito a analise de credito. "
            "Bradesco personal loans have rates from 1.99% per month for customers in good standing. Up to 60 months. Subject to credit analysis."
        ),
        source="Bradesco Personal Loan Manual",
    )
)
_RAG = RAGPipeline(retriever=TFIDFRetriever(store=_DOC_STORE), top_k=2, min_score=0.05)

# Seed one demo customer to show the memory feature.
_CUSTOMER_MEMORY.update_block(
    "demo-customer",
    "persona",
    "Individual (PF), conservative profile, Bradesco customer for 8 years.",
)
_CUSTOMER_MEMORY.update_block(
    "demo-customer",
    "preferences",
    "Prefers TED for large amounts, PIX for small ones. Card statement always on the 5th.",
)

# v10 P3 — Pre-seed a heterogeneous customer fleet so reviewers can drive
# realistic flows without having to populate memory by hand. Each profile
# represents a regulatory edge case the Bridge platform must cope with:
# PF (standard retail), PJ (corporate), PEP (politically-exposed person —
# extra AML scrutiny), menor (under-18, LGPD Art. 14 needs guardian),
# idoso (senior — Estatuto do Idoso adds anti-fraud obligations),
# nao-residente (FX + cross-border KYC), pre-arranged scam victim flag,
# small-business owner with PJ+PF mix, recent fraud-recovery customer
# (flagged by FIU), and a low-literacy customer (channel = WhatsApp,
# response simplification expected).
_SEED_CUSTOMERS: list[dict[str, dict[str, str]]] = [
    {
        "id": {"v": "C001-PF-padrao"},
        "persona": {"v": "Individual (PF), 34, salaried (CLT), no record. Checking account since 2019."},
        "preferences": {"v": "Preferred channel: app. Accepts PIX. Declines credit offers by SMS."},
        "risk": {"v": "Good internal score (720). No COAF alerts in the last 24 months."},
    },
    {
        "id": {"v": "C002-PJ-mei"},
        "persona": {"v": "Business (PJ), MEI (CNAE 6201-5), average revenue R$ 18k/month. Sole holder (spouse not a partner)."},
        "preferences": {"v": "Channel: app + internet banking. Uses Pix Cobrança for billing."},
        "risk": {"v": "Low. CNAE consistent with revenue. No cash transactions above R$ 10k."},
    },
    {
        "id": {"v": "C003-PEP"},
        "persona": {"v": "Politically Exposed Person (PEP): sitting city councilman. Mandatory enhanced AML treatment."},
        "preferences": {"v": "Channel: in-branch. Declines WhatsApp service for security."},
        "risk": {"v": "HIGH (AML). Every transaction above R$ 5k requires manual review + COAF. PEP_ESCALATE active."},
    },
    {
        "id": {"v": "C004-menor"},
        "persona": {"v": "Minor (16), joint savings account with a guardian (father's CPF linked)."},
        "preferences": {"v": "Channel: supervised app. Credit blocked. Daily PIX limit R$ 200."},
        "risk": {"v": "LGPD Art. 14 — every transaction escalates to the guardian. No credit products offered."},
    },
    {
        "id": {"v": "C005-idoso"},
        "persona": {"v": "Senior, 78, INSS retiree, lives alone. Estatuto do Idoso (Law 10.741) applies."},
        "preferences": {"v": "Channel: branch phone. Declines payroll loans on inbound calls (recurrent scam victim)."},
        "risk": {"v": "MEDIUM-HIGH. Fits the fake-employee scam victim pattern. Enhanced anti-fraud."},
    },
    {
        "id": {"v": "C006-nao-residente"},
        "persona": {"v": "Non-resident individual (PF, temporary visa). CDE account (resident abroad). FATCA + CRS KYC applies."},
        "preferences": {"v": "Channel: internet banking. Frequent FX transactions via the corporate platform."},
        "risk": {"v": "BCB Resolution 277 — remittance limits + mandatory reporting. Cross-border review on every transfer > USD 10k equiv."},
    },
    {
        "id": {"v": "C007-vitima-golpe"},
        "persona": {"v": "Individual (PF), confirmed PIX scam victim on 2026-02-14 (R$ 3,200 unrecovered). Protection flag active."},
        "preferences": {"v": "Channel: branch. Every new PIX key requires 2FA confirmation + an anti-fraud call."},
        "risk": {"v": "HIGH. Flag victim_recurrent — any transfer > R$ 500 triggers extra verification + a 30min delay."},
    },
    {
        "id": {"v": "C008-PJ-grande"},
        "persona": {"v": "Business (PJ), average revenue R$ 2.4M/month, retail (CNAE 4789-0). 12 individual partners. Primary operating account."},
        "preferences": {"v": "Channel: dedicated manager + business internet banking. Uses Bradesco payroll for 87 employees."},
        "risk": {"v": "MEDIUM (size). Tax consistency verified. No alerts. KYC renewal due 2026-08-15."},
    },
    {
        "id": {"v": "C009-recente-fraude"},
        "persona": {"v": "New customer (opened account 2026-04-22). Account flagged by intelligence (network shared with mule CPFs under COAF investigation 2025/4421)."},
        "preferences": {"v": "Channel: app. Accepts PIX. NEW: declared income source 'crypto investor' (unverified)."},
        "risk": {"v": "VERY HIGH. Automatic 48h hold on every deposit > R$ 1k. Daily AML sweep. FIU recommendation: do not offer credit until 2026-10-22."},
    },
    {
        "id": {"v": "C010-baixa-letramento"},
        "persona": {"v": "Individual (PF), 62, incomplete primary education. Requested payroll-loan cancellation 3x in 2026 (always via WhatsApp)."},
        "preferences": {"v": "Channel: WhatsApp only. Replies must be simple (max 2 sentences), no banking jargon. Confirm understanding before any transaction."},
        "risk": {"v": "MEDIUM. Vulnerability pattern. Channel-specific UI: simplifies the reply to Flesch>70."},
    },
]
for _seed in _SEED_CUSTOMERS:
    _cid = _seed["id"]["v"]
    _CUSTOMER_MEMORY.update_block(_cid, "persona", _seed["persona"]["v"])
    _CUSTOMER_MEMORY.update_block(_cid, "preferences", _seed["preferences"]["v"])
    _CUSTOMER_MEMORY.update_block(_cid, "risk_profile", _seed["risk"]["v"])

# Cost per query by tier (cents). Used to show savings in the UI.
_TIER_COST = {
    ComplexityTier.SIMPLE: 0.05,  # cheap fast model (Haiku-class)
    ComplexityTier.MEDIUM: 0.30,  # mid-tier (Sonnet-class)
    ComplexityTier.COMPLEX: 1.50,  # frontier (Opus-class)
}


# ---------------------------------------------------------------------------
# Handoff-aware agents (Swarm-style)
# ---------------------------------------------------------------------------


class _SmartPaymentsAgent:
    """Final agent for payment intents."""

    name = "smart_payments"

    def handle(self, query: str, context: dict[str, Any]) -> str:
        """Answer a payments-domain turn via the active backend.

        v7 G3 — memory snapshot (context['memory_snapshot']) is flattened
        into the LLM prompt by _answer(), so personalization happens via
        the model when running on a real backend, or via the canned
        templates when running on FakeBackend.
        """
        intent = "pix" if "pix" in query.lower() else "transfer"
        return _answer(intent, query, context)


class _CallCenterAgent:
    """Final agent for complaints / human escalation."""

    name = "call_center"

    def handle(self, query: str, context: dict[str, Any]) -> str:
        """Acknowledge a complaint and stage it for human follow-up.

        Bridge hub connection: terminal agent at Stage 6 for complaint
        flows; pairs with the UncertaintyGuard's ESCALATE branch so the
        Bridge hub can route the customer to a human operator while still
        producing a courteous interim response.

        Card-fraud markers in the query route to the antifraud-specific
        response (preventive block + transfer to 24h antifraud desk) rather
        than the generic complaint acknowledgement — a "cartao clonado"
        report must never be answered with the fatura template (regression
        guard for the B1 bug in the v1 review).
        """
        # Fold accents the SAME way classify_intent does (NFKD, drop combining
        # marks) so the unaccented markers also match accented input. Without
        # this the agent missed e.g. "compra que não reconheço" / accented
        # safety phrases and fell through to the generic complaint reply even
        # though classify_intent had already routed the turn here.
        import unicodedata as _ud
        q = "".join(
            c for c in _ud.normalize("NFKD", query.lower()) if not _ud.combining(c)
        )
        # v7 — safety classifiers checked in priority order so the right
        # canned response lands even though the agent doesn't receive
        # the intent label directly (run_with_handoffs forwards query only).
        if any(m in q for m in _CRISIS_MARKERS):
            return _RESPONSES["crisis"]
        if any(m in q for m in _SOCIAL_ENG_MARKERS):
            return _RESPONSES["social_engineering"]
        if _PHISHING_DOMAIN_PATTERN.search(q):
            return _RESPONSES["phishing"]
        if any(u in q for u in _URGENCY_MARKERS) and any(f in q for f in _FAMILY_EMERGENCY_MARKERS):
            return _RESPONSES["urgency_scam"]
        if any(m in q for m in _AML_STRUCTURING_MARKERS):
            return _RESPONSES["aml_suspect"]
        if any(m in q for m in _ILLEGAL_MARKERS):
            return _RESPONSES["illegal_activity"]
        if _AML_VALUE_PATTERN.search(q):
            return _RESPONSES["aml_review"]
        age_match = _AGE_NUMBER_RE.search(q)
        if age_match:
            age_str = age_match.group(1)
            try:
                if age_str and 5 <= int(age_str) < 18:
                    return _RESPONSES["age_minor"]
            except ValueError:
                pass
            if not age_str:  # "menor de idade" literal
                return _RESPONSES["age_minor"]
        # round-7 — same priority as classify_intent: prompt-leak > privilege >
        # manipulation > third-party > discrimination, then fraud, then complaint
        # default. prompt-leak goes first because its markers are highly
        # specific (no false-positive overlap with the others).
        if any(m in q for m in _PROMPT_LEAK_MARKERS):
            return _RESPONSES["prompt_leak"]
        if any(m in q for m in _PRIV_ESCAL_MARKERS):
            return _RESPONSES["privilege_escalation"]
        if any(m in q for m in _MANIPULATION_MARKERS):
            return _RESPONSES["account_manipulation"]
        if any(m in q for m in _THIRD_PARTY_MARKERS) or _THIRD_PARTY_REL_REGEX.search(q):
            return _RESPONSES["third_party_data"]
        if any(m in q for m in _DISCRIMINATION_MARKERS):
            return _RESPONSES["discrimination"]
        if any(m in q for m in _PROFANITY_MARKERS):
            return _RESPONSES["complaint_escalated"]
        if any(m in q for m in _FRAUD_MARKERS):
            return _RESPONSES["card_fraud"]
        # complaint is in _LLM_ALLOWED_INTENTS so it can be personalized
        # via the LLM when one is loaded.
        return _answer("complaint", query, context)


class _ChatbotAgent:
    """First agent for general queries; hands off when intent shifts."""

    name = "chatbot"

    def handle(self, query: str, context: dict[str, Any]) -> Any:
        """Answer a general query OR hand off to a specialist agent.

        Bridge hub connection: front-line agent at Stage 6 of the Bridge
        pipeline. Implements the Swarm-style handoff contract — returning
        another agent instance triggers ``run_with_handoffs`` to continue
        the turn with that specialist, letting the Bridge hub chain
        chatbot -> smart_payments / call_center mid-conversation.

        Args:
            query: Customer message text.
            context: Shared handoff context; populated with a
                ``handoff_reason`` when this agent decides to delegate.

        Returns:
            Either a string reply (terminal answer) or a specialist agent
            instance for the handoff runner to invoke next.
        """
        q = query.lower()
        # v7 G5 — non-PT detection BEFORE PT keyword match so "What is my
        # balance?" doesn't get routed to the balance template just because
        # the word "balance" appears.
        if any(m in q for m in _NON_PT_MARKERS):
            return _RESPONSES["non_pt"]
        # Mid-conversation intent shift: hand off to specialist. The keyword
        # sets come from _INTENT_KEYWORDS so PT + EN stay in sync with
        # classify_intent (otherwise an English "I want to see my balance"
        # classified as `balance` would fall through to the general template).
        if any(_kw_in(kw, q) for kw in (*_INTENT_KEYWORDS["pix"], *_INTENT_KEYWORDS["transfer"])):
            context["handoff_reason"] = "detected payment intent in chatbot turn"
            return _SmartPaymentsAgent()
        if any(_kw_in(kw, q) for kw in _INTENT_KEYWORDS["complaint"]):
            context["handoff_reason"] = "detected complaint, escalating to call_center"
            return _CallCenterAgent()
        # v8 — delegate to the active backend (LLM or Fake). _answer() handles
        # the safety/LLM split + memory flattening + model call.
        if any(_kw_in(kw, q) for kw in _INTENT_KEYWORDS["balance"]):
            return _answer("balance", query, context)
        if any(_kw_in(kw, q) for kw in _INTENT_KEYWORDS["card"]):
            return _answer("card", query, context)
        if any(_kw_in(kw, q) for kw in _INTENT_KEYWORDS["loan"]):
            return _answer("loan", query, context)
        return _answer("general", query, context)


def _select_initial_agent(intent: str) -> Any:
    """Choose the agent that takes the FIRST turn. Handoffs may shift it."""
    if intent in ("transfer", "pix"):
        return _SmartPaymentsAgent()
    # v7 — safety intents go straight to call_center (which knows the
    # canned crisis/social-engineering/illegal/aml responses).
    if intent in (
        "complaint",
        "card_fraud",
        "crisis",
        "social_engineering",
        "illegal_activity",
        "aml_review",
        "third_party_data",
        "account_manipulation",
        "privilege_escalation",
        "discrimination",
        "phishing",
        "urgency_scam",
        "aml_suspect",
        "age_minor",
        "complaint_escalated",
        "prompt_leak",
    ):
        return _CallCenterAgent()
    return _ChatbotAgent()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


# API-contract DTOs (QueryRequest / QueryResponse / PipelineStage + the channel /
# customer-id validators) now live in models.py (decoupling step 7). Pure pydantic,
# re-exported so the /query + /query/stream handlers, routers and tests that reference
# them via server.X keep working. _CUSTOMER_ID_PATTERN is re-exported too (used by other
# validators below).
try:
    from models import QueryRequest, PipelineStage, QueryResponse, _AllowedChannel, _CUSTOMER_ID_PATTERN  # noqa: F401
except ImportError:  # package-mode import (backend.server)
    from backend.models import QueryRequest, PipelineStage, QueryResponse, _AllowedChannel, _CUSTOMER_ID_PATTERN  # noqa: F401

app = FastAPI(
    title="Bridge UI BFF",
    version="0.2.0",
    description=(
        "Bridge banking AI demo — 12-stage pipeline orchestrator. "
        "DEMO MODE: FakeBackend, no auth, in-memory state."
    ),
    docs_url="/docs",  # N3 v2 fix: previously disabled, restored for SR 11-7 audit
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# v6 Phase 0 — config hardening. Origins are env-driven (BRIDGE_CORS_ORIGINS,
# comma-separated); methods/headers are explicit instead of "*" (which pairs
# badly with allow_credentials). Defaults cover the local dev ports.
_CORS_ORIGINS = [
    o.strip()
    for o in _os_for_backend.environ.get(
        "BRIDGE_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3002,http://127.0.0.1:3002",
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def _security_headers(request, call_next):  # type: ignore[no-untyped-def]
    """v6 Phase 0 — baseline security headers on every response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


# v15 — health watchdog stats. Tracks rolling request count + error count
# over the last 10 minutes so /stats can show ops a single-screen view of
# "is the BFF healthy right now?". Implemented as a single middleware so
# every endpoint (not just /query) feeds the counters.
_PROCESS_START_TS: Final[float] = time.time()
_WATCHDOG_REQUEST_TS: deque[float] = deque(maxlen=10_000)
_WATCHDOG_ERROR_TS: deque[float] = deque(maxlen=10_000)
_WATCHDOG_LAST_ERROR: dict[str, Any] | None = None


@app.middleware("http")
async def _watchdog_middleware(request, call_next):
    """Tick the watchdog counters on every HTTP call (success or error)."""
    global _WATCHDOG_LAST_ERROR
    now = time.time()
    _WATCHDOG_REQUEST_TS.append(now)
    try:
        response = await call_next(request)
    except Exception as exc:
        _WATCHDOG_ERROR_TS.append(now)
        # Full detail stays server-side; /stats is unauthenticated and the UI
        # renders last_error verbatim, so keep the client-visible message generic.
        print(
            f"[watchdog] {request.method} {getattr(request.url, 'path', '?')}: {exc!r}",
            flush=True,
        )
        _WATCHDOG_LAST_ERROR = {
            "ts": now,
            "path": getattr(request.url, "path", "?"),
            "method": request.method,
            "error_type": type(exc).__name__,
            "error_message": "unhandled exception",
        }
        raise
    if response.status_code >= 500:
        _WATCHDOG_ERROR_TS.append(now)
        _WATCHDOG_LAST_ERROR = {
            "ts": now,
            "path": getattr(request.url, "path", "?"),
            "method": request.method,
            "error_type": f"HTTP_{response.status_code}",
            "error_message": f"upstream returned {response.status_code}",
        }
    return response


# Static-ish version metadata for SR 11-7 "Ongoing Monitoring" requirement.
# Hashes derived once at startup so consumers (audit, compliance dashboard)
# can pin which artifact produced any given response. Exposed as
# module-level globals so the platform router can read them lazily.
import hashlib as _hashlib  # noqa: E402

_PROMPT_FINGERPRINT = _hashlib.blake2s(
    str(sorted(_RESPONSES.items())).encode("utf-8"), digest_size=8
).hexdigest()
_CORPUS_FINGERPRINT = _hashlib.blake2s(
    "|".join(sorted(d.id for d in _DOC_STORE.all())).encode("utf-8"), digest_size=8
).hexdigest()


# /health and /version now live in routers/platform.py — see app.include_router
# at the bottom of this file. The migration keeps server.py's module-level
# state intact (the router reads it lazily).


@app.post("/query/stream")
def query_stream(req: QueryRequest) -> StreamingResponse:
    """Server-Sent Events wrapper around /query — emits progress for the UI.

    Bridge hub connection: the long pole in /query is Stage 6 (LLM call,
    p95 ~45s when Ollama is loading). A synchronous POST means the UI
    sees nothing until the whole pipeline finishes. This endpoint runs
    the same pipeline in a background thread and:

      1. Emits ``event: heartbeat`` every 1s while the pipeline is alive,
         so the UI can render an "alive" pulse instead of a frozen spinner.
      2. After the pipeline returns, replays each ``PipelineStage`` as an
         ``event: stage`` with a small delay so the operator can SEE the
         12-stage breakdown visually.
      3. Emits ``event: done`` with the full ``QueryResponse`` payload.
      4. Emits ``event: error`` if the pipeline raised.

    Trade-off: this is "post-hoc streaming" — real per-stage streaming
    requires refactoring the 700-line ``query()`` body to accept a stage
    callback (a larger change). The current shape kills the perceived
    latency without that refactor.
    """
    import queue
    import threading

    event_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def run_pipeline() -> None:
        try:
            result = query(req)
            event_queue.put({"event": "result", "data": result.model_dump()})
        except HTTPException as e:
            event_queue.put({"event": "error", "data": {"status_code": e.status_code, "detail": e.detail}})
        except Exception as e:  # noqa: BLE001 — don't leak internals to the client
            print(f"[/query/stream] unexpected error: {e!r}", flush=True)
            event_queue.put({"event": "error", "data": {"status_code": 500, "detail": "internal error"}})
        finally:
            event_queue.put(None)  # sentinel

    worker = threading.Thread(target=run_pipeline, daemon=True)
    worker.start()

    def emit_terminal(msg: dict[str, Any]):
        """Translate the worker's terminal message into closing SSE events.

        A "result" message is replayed as a sequence of ``stage`` events
        followed by the ``done`` event the UI waits on; an "error" message
        is forwarded verbatim. Used by BOTH the heartbeat loop and the drain
        loop so the result is never emitted raw as ``event: result`` (which
        the frontend doesn't recognize, causing "Stream ended without a done
        event" — the pipeline can finish fast enough that the heartbeat loop
        consumes the result before the worker thread is observed dead).
        """
        data = msg["data"]
        if msg["event"] == "result":
            for stage in data.get("stages", []) or []:
                yield f"event: stage\ndata: {_json_audit.dumps(stage, default=str)}\n\n"
                time.sleep(0.04)  # readable pace, ~0.5s for 12 stages
            yield f"event: done\ndata: {_json_audit.dumps(data, default=str)}\n\n"
        else:
            yield f"event: {msg['event']}\ndata: {_json_audit.dumps(data, default=str)}\n\n"

    def event_gen():
        yield (
            f"event: start\ndata: "
            f"{_json_audit.dumps({'channel': req.channel, 'customer_id': req.customer_id})}\n\n"
        )
        start_ts = time.time()
        # Heartbeat loop while the pipeline thread runs. The worker enqueues
        # exactly one terminal message (result|error) then a None sentinel, so
        # the first non-None message is terminal — translate it and stop.
        while worker.is_alive():
            try:
                msg = event_queue.get(timeout=1.0)
                if msg is None:
                    break
                yield from emit_terminal(msg)
                break
            except queue.Empty:
                elapsed = round(time.time() - start_ts, 1)
                yield f"event: heartbeat\ndata: {{\"elapsed_s\":{elapsed}}}\n\n"
        worker.join()
        # Drain remaining messages (covers the case where the worker finished
        # before the heartbeat loop observed it alive).
        while True:
            try:
                msg = event_queue.get_nowait()
            except queue.Empty:
                break
            if msg is None:
                continue
            yield from emit_terminal(msg)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering if proxied
        },
    )


def _extract_amount(text: str) -> float | None:
    """Best-effort BRL amount from a query, for the value-proportional guard (#B1.2).

    Conservative on purpose: only numbers with a currency cue (R$, 'reais', or a
    'mil'/'milhão' multiplier) count, so an account/phone/order number in a transfer
    request doesn't masquerade as a value. Returns None when nothing clearly monetary
    is found, so the guard falls back to FLAG (review) instead of guessing.
    pt-BR notation: '.' thousands, ',' decimal (e.g. 1.500.000,50).
    """
    import re

    t = text.lower()

    def _to_float(raw: str) -> float | None:
        s = raw.strip().replace("r$", "").replace(" ", "")
        if "," in s:
            # pt-BR: '.' thousands, ',' decimal -> "1.500,50" = 1500.50
            s = s.replace(".", "").replace(",", ".")
        elif not re.fullmatch(r"\d+\.\d{1,2}", s):
            # no comma and not a lone decimal like "1.5": dots are thousands groups
            s = s.replace(".", "")
        try:
            v = float(s)
        except ValueError:
            return None
        # 0 / negative is anomalous input — return None so the guard FLAGs it
        # rather than treating it as a clean low-value release.
        return v if v > 0 else None

    # "5 mil", "1,5 milhão", "1.5 mil" (EN decimal), "2 milhões"
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(mil|milh[aã]o|milh[oõ]es)\b", t)
    if m:
        base = _to_float(m.group(1))
        if base is not None:
            return base * (1_000 if m.group(2) == "mil" else 1_000_000)

    best: float | None = None
    for pat in (r"r\$\s*(\d[\d.\s]*(?:,\d{1,2})?)", r"(\d[\d.\s]*(?:,\d{1,2})?)\s*reais?\b"):
        for raw in re.findall(pat, t):
            v = _to_float(raw)
            if v is not None and (best is None or v > best):
                best = v
    return best


def _answer_withheld_from_customer(decision: str, *, from_cache: bool) -> bool:
    """Did the pipeline hold the substantive answer BACK from the customer?

    This is a FACT about what was served, and only the pipeline knows it — it cannot be
    re-derived downstream from the decision token, because it differs per path:

    * fresh path — only ``REASK`` withholds (``_REASK_SAFE_ANSWER``); an ``ESCALATE``
      RELEASES the answer with a routed-to-a-human banner (see the final_answer block).
    * cache path — anything but PASSTHROUGH/FLAG withholds (the B3 confidentiality fix:
      a body produced under PASSTHROUGH must not be served under a re-derived REASK
      *or* ESCALATE).

    Recorded on the audit entry so the explanation surfaces state what actually happened
    instead of guessing (guessing is what made /audit/explain claim "the guard did not
    release an answer" about escalations the customer had in fact received).
    """
    if from_cache:
        return decision not in ("PASSTHROUGH", "FLAG")
    return decision == "REASK"


def _record_short_circuit(
    *,
    query_text: str,
    intent: str,
    decision: str,
    answer: str,
    confidence: float,
    latency_ms: float,
    customer_id: str,
    channel: str,
    stages: list[PipelineStage],
    tier: str,
    rationale: str = "",
) -> tuple[str, int | None]:
    """Record metrics + audit for a pre-pipeline short-circuit (rate-limit / DQ block).

    These guard rejections ``return`` before the main recording sites (the cache-hit
    and full-path blocks), so without this the highest-risk events — prompt-injection
    / abusive input blocked at ``dq_input`` and rate-limited callers — were returned as
    HTTP 200 ``decision="ESCALATE"`` yet never counted in ``/metrics`` (queries_total,
    decisions.ESCALATE, escalation_rate) nor written to the tamper-evident audit chain,
    leaving the events a governance console most needs to show (SR 11-7 / BCB 4.893)
    invisible. The query is masked before logging (LGPD Art. 46 / BCB 4.893 §6), matching
    the cache-hit and full-path audit entries. Volume is bounded (per-customer rate
    limit), so the extra audit write is negligible at demo scale.

    Returns the PII-masked query so the caller can echo it in the HTTP response
    without leaking clear-text PII (consistent with the masking applied to the
    audit entry and to the cache-hit / full-path responses), plus the audit-chain
    ``seq`` of the entry just written — a blocked/rate-limited call IS an adverse
    automated decision, so it must be explainable (LGPD Art. 20) like any other.
    """
    _METRICS.record(intent, confidence, decision, latency_ms)
    _maybe_capture_baseline()
    for _s in stages:
        _record_stage_latency(_s.name, _s.duration_ms)
    _gov = _GOVERNOR.govern(query_text, step="input")
    _entry = _audit_append(
        {
            "ts": time.time(),
            "query": _gov.masked,
            "query_was_masked": _gov.has_pii,
            "pii_count": len(_gov.matches),
            "intent": intent,
            "confidence": confidence,
            "decision": decision,
            "answer": answer,
            "customer_id": customer_id,
            "channel": channel,
            "from_cache": False,
            "tier": tier,
            "cost_cents": 0.0,
            # A short-circuit's "answer" IS the refusal message the customer received —
            # nothing substantive was held back.
            "answer_withheld": False,
            # The REAL reason this call was refused (which DQ rule fired / rate limit).
            # Without it the explanation would be derived from the decision token alone
            # and would state a wrong cause ("confidence too low") for a rule-based block.
            **({"rationale": rationale} if rationale else {}),
        }
    )
    return _gov.masked, _entry.get("seq")


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest) -> QueryResponse:
    """Run a customer query through the full Bridge 12-stage pipeline.

    Bridge hub connection: this is the primary entry point exposing the
    Bridge hub to the UI. It threads the request through SemanticCache ->
    ComplexityRouter -> CustomerMemory -> RAG -> IntentClassifier -> Agent
    -> UncertaintyGuard -> cache store -> AuditTrail, recording metrics
    and audit log entries along the way.

    Args:
        req: Validated query payload (text, channel, customer_id).

    Returns:
        Final answer plus a per-stage trace the dashboard renders as the
        Bridge pipeline timeline (intent, confidence, guard decision,
        latency, and each stage's status/detail).
    """
    start = time.perf_counter()
    stages: list[PipelineStage] = []

    # v9 P0-5: queue overload guard. If Ollama is saturated above the
    # threshold, reject early with 429 + Retry-After rather than queueing
    # the request behind a multi-minute backlog (Ollama serializes on 1 GPU).
    if _ollama_queue_depth() >= _OLLAMA_MAX_QUEUE:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Ollama queue full ({_OLLAMA_MAX_QUEUE} in flight). Try again in a few seconds."
            ),
            headers={"Retry-After": "10"},
        )

    # Stage -1: Idempotency check (before any work) — repeated retries
    # within 60s of the same (customer_id, idempotency_key) return the
    # cached prior response unchanged. Keeps transactional flows safe
    # against client/network retry storms.
    cached_idempotent = _idempotency_lookup(req.customer_id, req.channel, req.idempotency_key)
    if cached_idempotent is not None:
        return QueryResponse(**cached_idempotent)

    # Stage 0 (pre-pipeline): Rate limit per customer+channel
    if not _RATE_LIMITER.allow(req.customer_id, req.channel):
        latency_ms = (time.perf_counter() - start) * 1000
        stages.append(
            PipelineStage(
                name="rate_limit",
                status="error",
                detail="429 — rate limit exceeded (60/min, burst 10)",
                confidence=None,
                duration_ms=latency_ms,
            )
        )
        masked_query, audit_seq = _record_short_circuit(
            query_text=req.query,
            intent="rate_limited",
            decision="ESCALATE",
            answer="[Rate limit exceeded — please retry in a moment]",
            confidence=0.0,
            latency_ms=latency_ms,
            customer_id=req.customer_id,
            channel=req.channel,
            stages=stages,
            tier="rate_limited",
            rationale="Rate limit exceeded for this customer — request refused before the model ran.",
        )
        return QueryResponse(
            query=masked_query,
            answer="[Rate limit exceeded — please retry in a moment]",
            intent="rate_limited",
            confidence=0.0,
            decision="ESCALATE",
            latency_ms=latency_ms,
            stages=stages,
            audit_seq=audit_seq,
        )

    # Stage 0a: Input Data Quality (DQ)
    # v9 Part 2: pass session context so context-aware rules (R-CROSS-CUSTOMER)
    # can compare the in-query customer_id reference against the authenticated
    # session id. Context-free rules (regex-only) ignore the dict.
    s0a_start = time.perf_counter()
    dq_input = _DQ_INPUT.check(req.query, {"customer_id": req.customer_id})
    _DQ_DG_STATS["input_blocks"] += len(dq_input.blocking_violations)
    _DQ_DG_STATS["input_warns"] += len(dq_input.warning_violations)
    if not dq_input.passed:
        # Hard reject: don't burn a token on a blocked input.
        blockers = "; ".join(v.message for v in dq_input.blocking_violations)
        stages.append(
            PipelineStage(
                name="dq_input",
                status="error",
                detail=f"BLOCKED: {blockers}",
                confidence=None,
                duration_ms=(time.perf_counter() - s0a_start) * 1000,
            )
        )
        latency_ms = (time.perf_counter() - start) * 1000
        # round-10 — use the first blocking rule's customer_message when one
        # is set, so the customer gets a regulation-aware sentence instead of
        # a generic "rejected" string. Fall back to the legacy message when
        # the rule didn't define one (older rules + WARN-derived flows).
        rejection_msg = "[Rejected by input DQ — please rephrase]"
        for v in dq_input.blocking_violations:
            if v.customer_message:
                rejection_msg = v.customer_message
                break
        masked_query, audit_seq = _record_short_circuit(
            query_text=req.query,
            intent="rejected",
            decision="ESCALATE",
            answer=rejection_msg,
            confidence=0.0,
            latency_ms=latency_ms,
            customer_id=req.customer_id,
            channel=req.channel,
            stages=stages,
            tier="rejected",
            rationale=f"Blocked by input data-quality rule(s): {blockers}",
        )
        return QueryResponse(
            query=masked_query,
            answer=rejection_msg,
            intent="rejected",
            confidence=0.0,
            decision="ESCALATE",
            latency_ms=latency_ms,
            stages=stages,
            audit_seq=audit_seq,
        )
    stages.append(
        PipelineStage(
            name="dq_input",
            status="ok" if not dq_input.warning_violations else "warning",
            detail=f"OK ({dq_input.rules_evaluated} rules, {len(dq_input.warning_violations)} warnings)",
            confidence=None,
            duration_ms=(time.perf_counter() - s0a_start) * 1000,
        )
    )

    # v17 (#B1.2) — parse any transaction amount once, up front; the guard uses it
    # to size the decision on money-moving actions (both cache-hit and full path).
    _query_amount = _extract_amount(req.query)

    # Stage 0b: Data Governance (PII detect + mask + classify)
    s0b_start = time.perf_counter()
    gov_result = _GOVERNOR.govern(req.query, step="input")
    if gov_result.has_pii:
        _DQ_DG_STATS["queries_with_pii"] += 1
        _DQ_DG_STATS["pii_masked_total"] += len(gov_result.matches)
    pii_types = sorted({m.pii_type.value for m in gov_result.matches})
    stages.append(
        PipelineStage(
            name="data_governance",
            status="warning" if gov_result.has_pii else "ok",
            detail=(
                f"classification={gov_result.classification.value}, "
                f"PII masked: {len(gov_result.matches)} "
                f"({', '.join(pii_types) if pii_types else 'none'})"
            ),
            confidence=None,
            duration_ms=(time.perf_counter() - s0b_start) * 1000,
        )
    )

    # Stage 1: Semantic cache lookup ("elephant memory")
    # Bypass cache entirely for RESTRICTED-classified queries (CPF/CNPJ/
    # account/card present). Fix for N1 in v2 review: two different fraud
    # reports could otherwise collide in the masked-embedding space and
    # one customer would receive another customer's cached response.
    s1_start = time.perf_counter()
    # B-NEW8 fix (2026-05-17): action intents (pix/transfer) must NOT be
    # served from cache — idempotency is the customer's responsibility but
    # a cached "yes I'll PIX 150" reply on a future query would be a real
    # operational hazard. Cheap pre-classify by keyword at cache time.
    _ACTION_KEYWORDS = (*_INTENT_KEYWORDS["pix"], *_INTENT_KEYWORDS["transfer"])
    _is_action_query = any(_kw_in(kw, req.query.lower()) for kw in _ACTION_KEYWORDS)
    cache_bypass = (
        not _RUNTIME_CACHE_ENABLED  # A2: cache toggled off at runtime
        or gov_result.classification == DataClassification.RESTRICTED
        or gov_result.has_pii
        or _is_action_query
    )
    # Scope the cache by customer_id so one customer can NEVER be served
    # another's cached answer, even for an identical, non-RESTRICTED query
    # (e.g. "qual meu saldo?") whose personalized answer differs per customer.
    # Complements the RESTRICTED/PII bypass above (defense in depth).
    cached = None if cache_bypass else _CACHE.lookup(req.query, scope=req.customer_id)
    if cached is not None:
        stages.append(
            PipelineStage(
                name="semantic_cache",
                status="ok",
                detail=f"HIT: similar query cached {cached.age_seconds:.0f}s ago (sim={cached.similarity:.2f})",
                confidence=cached.original_confidence,
                duration_ms=(time.perf_counter() - s1_start) * 1000,
            )
        )
        # Short-circuit: cached answer skips intent/agent/LLM.
        # B1 fix: the runtime guard threshold (Controls slider) must still
        # govern the decision on a cache hit — otherwise raising the slider has
        # no effect on a repeated query (its headline interaction). Re-run the
        # guard with the cached intent/confidence; risk_level isn't available
        # here (customer memory loads later in the full path), so use 0.0.
        cache_decision, cache_reason = apply_guard(
            cached.original_confidence,
            threshold=_RUNTIME_GUARD_THRESHOLD,
            intent=cached.original_intent,
            amount=_query_amount,
        )
        # Per-channel firewall on the cache path too — a cache HIT must not serve an
        # off-list intent on a restricted channel (the fresh path enforces this after
        # its guard; without this the semantic cache would be a firewall bypass).
        if cache_decision != "ESCALATE" and _channel_firewall_blocks(req.channel, cached.original_intent):
            cache_decision = "ESCALATE"
        # Output DQ on the cache path too (defense in depth). Nothing blocked can ENTER the
        # cache any more (DQ now runs before the store), but a DQ rule is itself a governed
        # change — a rule added AFTER an answer was cached must still apply to it, or the
        # cache would let the old content outlive the new rule.
        cache_blocked_answer: str | None = None
        cache_dq = _DQ_OUTPUT.check(cached.answer)
        if not cache_dq.passed:
            cache_blocked_answer = cached.answer
            cache_decision = "ESCALATE"
            cache_reason = (
                "Blocked by output data-quality rule(s): "
                + "; ".join(v.message for v in cache_dq.blocking_violations)
            )
            _DQ_DG_STATS["output_blocks"] += len(cache_dq.blocking_violations)
        # B3 fix (confidentiality): the cached body was produced under PASSTHROUGH.
        # If the re-derived decision withholds the answer (REASK/ESCALATE), the
        # cached content must NOT be served — gate it exactly like the fresh path,
        # otherwise a balance leaks out under a "REASK" label.
        served_answer = (
            cached.answer if cache_decision in ("PASSTHROUGH", "FLAG") else _REASK_SAFE_ANSWER
        )
        latency_ms = (time.perf_counter() - start) * 1000
        _METRICS.record(
            cached.original_intent, cached.original_confidence, cache_decision, latency_ms
        )
        _maybe_capture_baseline()
        # v15: per-stage tracking on the cache-hit path too.
        for s in stages:
            _record_stage_latency(s.name, s.duration_ms)
        cache_entry = _audit_append(
            {
                "ts": time.time(),
                # B-NEW-1 fix (2026-05-17): persist MASKED query, not raw.
                # Raw query held CPF / card numbers / passport patterns that
                # the data_governance stage had already masked. Storing the
                # raw form in audit was an LGPD Art. 46 / BCB 4893 §6 leak.
                "query": gov_result.masked,
                "query_was_masked": gov_result.has_pii,
                "pii_count": len(gov_result.matches),
                "intent": cached.original_intent,
                "confidence": cached.original_confidence,
                "decision": cache_decision,
                # NOTE: unlike the fresh path this stores the SERVED answer (the cached body
                # is already gated by B3 above), so there is nothing substantive to leak here
                # — but the flag still records that the customer did not get the real answer.
                "answer": served_answer,
                "answer_withheld": _answer_withheld_from_customer(cache_decision, from_cache=True),
                # Same evidence rule as the fresh path: if a DQ rule blocked the cached body,
                # keep it for the reviewer (audit only) — never hand it back.
                **({"blocked_answer": cache_blocked_answer} if cache_blocked_answer else {}),
                "rationale": f"{cache_reason} [served from the semantic cache]",
                # v15-fix-p02: BCB 4.893 §6 audit requires per-titular trace.
                # Was missing in 9/9 entries across 3 rounds.
                "customer_id": req.customer_id,
                "channel": req.channel,
                "from_cache": True,
                "tier": "cached",
                "cost_cents": 0.0,
            }
        )
        return QueryResponse(
            query=gov_result.masked,
            answer=served_answer,
            intent=cached.original_intent,
            confidence=cached.original_confidence,
            decision=cache_decision,
            latency_ms=latency_ms,
            stages=stages,
            cache_hit=True,
            cache_similarity=cached.similarity,
            tier="cached",
            cost_cents=0.0,
            audit_seq=cache_entry.get("seq"),
        )
    stages.append(
        PipelineStage(
            name="semantic_cache",
            status="ok",
            detail="MISS: no similar query in cache, running the full pipeline",
            confidence=None,
            duration_ms=(time.perf_counter() - s1_start) * 1000,
        )
    )

    # Stage 2: Complexity routing (picks model tier)
    s2_start = time.perf_counter()
    complexity = _COMPLEXITY.score(req.query)
    cost_cents = _TIER_COST[complexity.tier]
    stages.append(
        PipelineStage(
            name="complexity_router",
            status="ok",
            detail=f"Tier: {complexity.tier.value.upper()} (score={complexity.raw_score:.1f}, est. cost ${cost_cents:.2f}c) — {complexity.rationale}",
            confidence=None,
            duration_ms=(time.perf_counter() - s2_start) * 1000,
        )
    )

    # Stage 3: Customer memory (Letta-style long-term recall)
    s3_start = time.perf_counter()
    memory_snapshot = _CUSTOMER_MEMORY.snapshot(req.customer_id)
    if memory_snapshot:
        memory_summary = ", ".join(memory_snapshot.keys())
        memory_detail = f"{len(memory_snapshot)} memory block(s) loaded: {memory_summary}"
    else:
        memory_detail = "No prior memory for this customer"
    stages.append(
        PipelineStage(
            name="customer_memory",
            status="ok",
            detail=memory_detail,
            confidence=None,
            duration_ms=(time.perf_counter() - s3_start) * 1000,
        )
    )

    # Stage 4: RAG retrieval (Haystack-style grounding)
    s4_start = time.perf_counter()
    rag_result = _RAG.run(req.query)
    if rag_result.has_grounding:
        rag_detail = (
            f"{len(rag_result.retrieved)} doc(s) retrieved, top score "
            f"{rag_result.retrieved[0].score:.2f}, sources: {', '.join(rag_result.citations)}"
        )
        rag_status = "ok"
    else:
        rag_detail = "No relevant document in the corpus (ungrounded answer)"
        rag_status = "warning"
    stages.append(
        PipelineStage(
            name="rag_retrieval",
            status=rag_status,
            detail=rag_detail,
            confidence=None,
            duration_ms=(time.perf_counter() - s4_start) * 1000,
        )
    )

    # Stage 5: Intent classification
    s3_start = time.perf_counter()
    intent, intent_conf = classify_intent(req.query)
    # Theme A: an applied governed intent whose samples match takes over classification,
    # UNLESS the static classifier already locked a protected safety/fraud intent
    # (never let operator policy override the safety floor).
    if not _is_protected_intent(intent):
        _gov_intent = _match_governed_intent(req.query)
        if _gov_intent is not None:
            intent, intent_conf = _gov_intent, max(intent_conf, 0.9)
    stages.append(
        PipelineStage(
            name="intent_classifier",
            status="ok",
            detail=f"Classified as '{intent}'",
            confidence=intent_conf,
            duration_ms=(time.perf_counter() - s3_start) * 1000,
        )
    )

    # Stage 4: Agent (chatbot/payments/call_center) WITH HANDOFFS
    # v7 G3 — thread customer_id + memory snapshot through the handoff
    # context so downstream agents can personalize the answer. Without
    # this, the memory panel rendered preferences but the agent ignored
    # them entirely.
    s4_start = time.perf_counter()
    initial_agent = _select_initial_agent(intent)
    handoff_context: dict[str, Any] = {
        "customer_id": req.customer_id,
        "memory_snapshot": memory_snapshot,
    }
    handoff_chain = run_with_handoffs(initial_agent, req.query, context=handoff_context, max_hops=3)
    answer = handoff_chain.final_answer
    if handoff_chain.hop_count > 0:
        path = " -> ".join([initial_agent.name] + [h.to_agent for h in handoff_chain.hops])
        agent_detail = f"HANDOFF chain: {path} ({handoff_chain.hop_count} hops, final: {handoff_chain.final_agent})"
    else:
        agent_detail = f"Single agent: {handoff_chain.final_agent} ({len(answer)} chars) using model {complexity.tier.value}"
    stages.append(
        PipelineStage(
            name=f"agent_{handoff_chain.final_agent}",
            status="ok",
            detail=agent_detail,
            confidence=intent_conf,
            duration_ms=(time.perf_counter() - s4_start) * 1000,
        )
    )

    # Stage 5: Uncertainty guard (intent passed so fraud → ESCALATE override;
    # v13-fix Phase 2 — risk_level pulled from customer memory so PEP /
    # victim_recurrent / minor get a stricter threshold than the baseline.)
    s5_start = time.perf_counter()
    _risk_block = (memory_snapshot or {}).get("risk_profile")
    _risk_text = getattr(_risk_block, "content", "") if _risk_block else ""
    _risk_level = _extract_risk_level(_risk_text)
    decision, reason = apply_guard(
        intent_conf, threshold=_RUNTIME_GUARD_THRESHOLD, intent=intent,
        risk_level=_risk_level, amount=_query_amount,
    )
    # Theme A: a governed intent policy can PIN a decision or TIGHTEN the threshold for
    # its intent (approved + applied change). Never weakens a protected escalation.
    if not _is_protected_intent(intent):
        _gov_pol = _governed_intent_policies().get(intent)
        if _gov_pol:
            _gov_dec = str(_gov_pol.get("default_decision") or "").upper()
            _gov_thr = _gov_pol.get("threshold")
            if _gov_dec in ("PASSTHROUGH", "FLAG", "REASK", "ESCALATE"):
                decision = _gov_dec
                reason = f"Governed intent policy for '{intent}' -> {_gov_dec} (approved + applied change)."
            elif isinstance(_gov_thr, (int, float)) and 0 < float(_gov_thr) <= 1:
                decision, reason = apply_guard(
                    intent_conf, threshold=float(_gov_thr), intent=intent,
                    risk_level=_risk_level, amount=_query_amount,
                )
                reason = f"{reason} [governed threshold {float(_gov_thr):.2f}]"
    # Per-channel firewall (governed channel_policy): a channel can carry an intent
    # allow-list; anything off-list is ESCALATEd (default-deny) regardless of
    # confidence — e.g. a public WhatsApp channel permitted only balance/pix.
    if decision != "ESCALATE" and _channel_firewall_blocks(req.channel, intent):
        decision = "ESCALATE"
        reason = (
            f"channel '{req.channel}' allow-list: intent '{intent}' not permitted "
            f"→ escalate (governed channel policy)"
        )
    stages.append(
        PipelineStage(
            name="uncertainty_guard",
            status="ok" if decision in ("PASSTHROUGH", "FLAG") else "warning",
            detail=f"{decision}: {reason}",
            confidence=intent_conf,
            duration_ms=(time.perf_counter() - s5_start) * 1000,
        )
    )
    # The guard's OWN reason (threshold / governed policy / channel firewall) is the true
    # rationale for this decision. It used to live only in the transient stage detail, so the
    # explanation surfaces fell back to a 4-item guess keyed on the decision token. Record it.
    # (An output-DQ block below overrides it with the rule that actually fired.)
    decision_rationale = reason

    # Stage 6a: Output Data Quality (DQ) — MUST run BEFORE the cache stores the answer.
    # It used to run AFTER, so an answer an output-DQ rule had refused to release was already
    # sitting in the semantic cache. The next near-duplicate query took the cache path (which
    # re-runs no model — and re-ran no DQ) and served the blocked content verbatim, auditing it
    # as released. The cache was an output-DQ BYPASS — the same class of hole the channel
    # firewall was already fixed for on the cache path. Now nothing enters the cache until DQ
    # has cleared it: a block flips `decision` to ESCALATE, which `cacheable` already excludes.
    s6b_start = time.perf_counter()
    blocked_answer: str | None = None  # set only when an output-DQ rule suppresses the answer
    dq_output = _DQ_OUTPUT.check(answer)
    _DQ_DG_STATS["output_blocks"] += len(dq_output.blocking_violations)
    _DQ_DG_STATS["output_warns"] += len(dq_output.warning_violations)
    if not dq_output.passed:
        blockers = "; ".join(v.message for v in dq_output.blocking_violations)
        stages.append(
            PipelineStage(
                name="dq_output",
                status="error",
                detail=f"BLOCKED: {blockers}",
                confidence=None,
                duration_ms=(time.perf_counter() - s6b_start) * 1000,
            )
        )
        # Suppress the answer, force escalation. The model's ORIGINAL output is kept for the
        # model-risk reviewer (a reviewer cannot review a block whose content was destroyed)
        # — on the audit entry only, never in the HTTP response. Without this the trail said
        # it retained the withheld answer while having overwritten it in place.
        blocked_answer = answer
        answer = "[Response blocked by output DQ — escalating to a human agent]"
        decision = "ESCALATE"
        # Record the RULE that fired, so the explanation states the real cause instead of
        # falling back to the decision-token map ("confidence too low" for a DQ block).
        decision_rationale = f"Blocked by output data-quality rule(s): {blockers}"
    else:
        stages.append(
            PipelineStage(
                name="dq_output",
                status="ok" if not dq_output.warning_violations else "warning",
                detail=f"OK ({dq_output.rules_evaluated} rules, {len(dq_output.warning_violations)} warnings)",
                confidence=None,
                duration_ms=(time.perf_counter() - s6b_start) * 1000,
            )
        )

    # Stage 6b: Cache the answer for future near-matches.
    # Bypass storage for RESTRICTED or fraud-flagged intents (N1 fix v2):
    # caching a per-customer answer would let it surface for another
    # customer with a semantically close question.
    s6_start = time.perf_counter()
    cacheable = (
        _RUNTIME_CACHE_ENABLED  # A2: cache toggled off at runtime
        # ...and only content output-DQ CLEARED above (a block set this to ESCALATE).
        and decision in ("PASSTHROUGH", "FLAG")
        and gov_result.classification != DataClassification.RESTRICTED
        and not intent.endswith("_fraud")
    )
    if cacheable:
        _CACHE.store(req.query, answer, intent=intent, confidence=intent_conf, scope=req.customer_id)
        cache_detail = f"Stored for future hits ({_CACHE.size}/{_CACHE.max_entries} entries)"
    elif not _RUNTIME_CACHE_ENABLED:
        cache_detail = "Skipped (semantic cache disabled via /settings)"
    elif gov_result.classification == DataClassification.RESTRICTED:
        cache_detail = "Skipped (RESTRICTED — per-customer data, not cacheable)"
    elif intent.endswith("_fraud"):
        cache_detail = "Skipped (fraud intent — must stay per-customer)"
    elif blocked_answer is not None:
        cache_detail = "Skipped (blocked by output DQ — must never be re-served from cache)"
    else:
        cache_detail = "Skipped (escalated/rejected — not cacheable)"
    stages.append(
        PipelineStage(
            name="cache_store",
            status="ok",
            detail=cache_detail,
            confidence=None,
            duration_ms=(time.perf_counter() - s6_start) * 1000,
        )
    )

    # Stage 7: Audit
    s7_start = time.perf_counter()
    audit_entry = _audit_append(
        {
            "ts": time.time(),
            # B-NEW-1 fix (2026-05-17): persist MASKED query, not raw.
            # See cached-path comment above for the LGPD/BCB rationale.
            "query": gov_result.masked,
            "query_was_masked": gov_result.has_pii,
            "pii_count": len(gov_result.matches),
            "intent": intent,
            "confidence": intent_conf,
            "decision": decision,
            # The SUBSTANTIVE answer is kept for the model-risk reviewer even when the
            # customer never saw it — but then the flag below says so, so no explanation
            # surface can hand it back as if it had been released.
            "answer": answer,
            "answer_withheld": _answer_withheld_from_customer(decision, from_cache=False),
            # The model output an output-DQ rule refused to release. Evidence for the reviewer;
            # the customer never saw it, so every read surface must treat it as withheld.
            **({"blocked_answer": blocked_answer} if blocked_answer else {}),
            "rationale": decision_rationale,
            # v15-fix-p02: BCB 4.893 §6 audit requires per-titular trace.
            "customer_id": req.customer_id,
            "channel": req.channel,
            "from_cache": False,
            "tier": complexity.tier.value,
            "cost_cents": cost_cents,
        }
    )
    stages.append(
        PipelineStage(
            name="audit_trail",
            status="ok",
            # THIS request's own seq (we hold the entry), not the global chain head: /query
            # runs in a threadpool, so a concurrent append could otherwise make the trace
            # show a seq that belongs to someone else's decision.
            detail=f"Recorded in the audit trail (entry #{len(_AUDIT)}, seq={audit_entry.get('seq')})",
            confidence=None,
            duration_ms=(time.perf_counter() - s7_start) * 1000,
        )
    )

    latency_ms = (time.perf_counter() - start) * 1000
    _METRICS.record(intent, intent_conf, decision, latency_ms)
    _maybe_capture_baseline()
    # v15: per-stage latency tracking for the /stages/budgets SLO endpoint.
    for s in stages:
        _record_stage_latency(s.name, s.duration_ms)

    # B-NEW2 + B-NEW6 fix (2026-05-17): preserve agent's substantive answer
    # and APPEND a routing banner instead of replacing it. The agent (e.g.
    # CallCenterAgent on card_fraud) often produces a domain-correct reply
    # that the user should see; the old logic threw it away in favour of
    # a generic placeholder. System-tagged answers (those wrapped in [...])
    # stay as-is to avoid double-tagging.
    _ESCALATE_BANNER = "\n\n— Case routed to a human agent for review."

    def _is_system_msg(s: str) -> bool:
        s = (s or "").strip()
        return s.startswith("[") and s.endswith("]")

    if decision in ("PASSTHROUGH", "FLAG"):
        final_answer = answer
    elif decision == "REASK":
        # REASK must NOT reveal the substantive answer (e.g. the balance) — the
        # guard isn't confident enough to release it. Hold the content back and
        # return only the ask-to-clarify (shared with the cache-hit path).
        final_answer = _REASK_SAFE_ANSWER
    else:  # ESCALATE
        if _is_system_msg(answer):
            final_answer = answer  # DQ-block or similar marker — leave as-is
        else:
            base = answer or "Case logged."
            final_answer = base + _ESCALATE_BANNER

    handoff_path = [initial_agent.name] + [h.to_agent for h in handoff_chain.hops]

    response = QueryResponse(
        query=gov_result.masked,
        answer=final_answer,
        intent=intent,
        confidence=intent_conf,
        decision=decision,
        latency_ms=latency_ms,
        stages=stages,
        cache_hit=False,
        tier=complexity.tier.value.upper(),
        cost_cents=cost_cents,
        memory_blocks=list(memory_snapshot.keys()) if memory_snapshot else [],
        citations=list(rag_result.citations) if rag_result.has_grounding else [],
        handoff_chain=handoff_path,
        agent_used=handoff_chain.final_agent,
        audit_seq=audit_entry.get("seq"),
    )

    # Save for idempotent retries.
    _idempotency_store(req.customer_id, req.channel, req.idempotency_key, response.model_dump())

    return response


# GET /metrics, /stats, /queue/depth moved to routers/metrics.py


# GET /agents moved to routers/discovery.py


# v10 P3 — intent catalog endpoint. Auditors/devs need a single source-of-
# truth describing every intent the classifier can emit, the agent that
# handles it, the guard verdict it ALWAYS produces (for safety intents),
# and an example query — so they can validate coverage without grepping
# the source. Counts are joined from the live Metrics so reviewers can see
# how often each intent has actually fired in this session.
# _INTENT_CATALOG now lives in core/classifier.py (decoupling step 2) and is
# re-exported above alongside classify_intent. /intents (routers/discovery.py),
# experiments and calibration consume it via the server surface unchanged.


# GET /intents moved to routers/discovery.py — uses _INTENT_CATALOG above



# v7 — customer feedback collection. Single POST that logs the customer's
# rating + optional comment against the audit entry index they're rating.
# Used by /api/feedback in the BFF and by the dashboard's per-row feedback
# buttons (out of scope for this demo, but the endpoint is ready).
class FeedbackRequest(BaseModel):
    audit_index: int = Field(..., ge=0, description="Audit entry being rated (0=newest).")
    helpful: bool = Field(..., description="Did the answer help the customer?")
    reason: str | None = Field(
        default=None, max_length=500, description="Optional free-text comment."
    )
    customer_id: str = Field(..., min_length=1, max_length=64, pattern=_CUSTOMER_ID_PATTERN)


@app.post("/feedback")
def feedback(req: FeedbackRequest) -> dict[str, Any]:
    """Log a customer-side rating against a prior audit entry.

    Bridge hub connection: closes the RLHF / model-improvement loop. The
    audit trail records what the model did; this endpoint records whether
    the customer found the outcome useful — the signal a real production
    system would use to retrain or to weight escalation thresholds.
    """
    # Validate the audit_index exists right now (it could fall outside the
    # bounded deque if the customer waited too long — surface that clearly).
    if req.audit_index >= len(_AUDIT):
        raise HTTPException(
            status_code=404,
            detail=(
                f"audit_index={req.audit_index} no longer in the audit window "
                f"(current size={len(_AUDIT)})"
            ),
        )
    record = {
        "ts": time.time(),
        "audit_index": req.audit_index,
        "helpful": req.helpful,
        "reason": req.reason,
        "customer_id": req.customer_id,
    }
    _FEEDBACK.append(record)
    return {
        "status": "recorded",
        "feedback_id": len(_FEEDBACK) - 1,
        "feedback_total": len(_FEEDBACK),
    }


@app.get("/feedback")
def feedback_list(limit: int = 20) -> dict[str, Any]:
    """List recent feedback (newest first)."""
    # Snapshot before iterating — a concurrent POST /feedback appending to the
    # live deque mid-iteration raises RuntimeError (same class as audit.py).
    snapshot = list(_FEEDBACK)
    items = list(reversed(snapshot))[:limit]
    helpful_count = sum(1 for f in snapshot if f.get("helpful"))
    total = len(snapshot)
    return {
        "entries": items,
        "total": total,
        "helpful_count": helpful_count,
        "helpful_rate": round(helpful_count / total, 3) if total else None,
    }


# v9 P1: human-handoff endpoint (closes the trio /feedback /explain /handoff
# that the v9 SPRINT issue called out). Marks an audit entry for human review
# and persists it for the dashboard's escalation queue (in-memory for demo).
_HANDOFFS: deque[dict[str, Any]] = deque(maxlen=500)


class HandoffRequest(BaseModel):
    audit_index: int = Field(..., ge=0, description="Audit entry to hand off (0=newest).")
    reason: str = Field(..., min_length=3, max_length=500, description="Why the human is needed.")
    channel: Literal["phone", "chat", "email", "branch"] = Field(
        ..., description="How the customer prefers to be reached."
    )
    customer_id: str = Field(..., min_length=1, max_length=64, pattern=_CUSTOMER_ID_PATTERN)


@app.post("/handoff")
def handoff(req: HandoffRequest) -> dict[str, Any]:
    """Mark an audit entry for human handoff. Persists to in-memory queue.

    Bridge hub connection: completes the LGPD / governance loop alongside
    /feedback (customer satisfaction) and /explain (decision rationale).
    Where /feedback says "the answer wasn't enough" and /explain says
    "here's why we did what we did", /handoff says "transfer this to a
    person now" with the customer-preferred channel.
    """
    if req.audit_index >= len(_AUDIT):
        raise HTTPException(
            status_code=404,
            detail=(
                f"audit_index={req.audit_index} no longer in the audit window "
                f"(current size={len(_AUDIT)})"
            ),
        )
    record = {
        "ts": time.time(),
        "audit_index": req.audit_index,
        "customer_id": req.customer_id,
        "reason": req.reason,
        "channel": req.channel,
        "status": "pending",
    }
    _HANDOFFS.append(record)
    return {
        "status": "queued",
        "handoff_id": len(_HANDOFFS) - 1,
        "queue_position": len(_HANDOFFS),
        "channel": req.channel,
    }


@app.get("/handoff")
def handoff_list(limit: int = 20) -> dict[str, Any]:
    """List recent handoff requests (newest first)."""
    # Snapshot before iterating — a concurrent POST /handoff appending to the
    # live deque mid-iteration raises RuntimeError (same class as audit.py).
    snapshot = list(_HANDOFFS)
    items = list(reversed(snapshot))[:limit]
    return {
        "entries": items,
        "total": len(snapshot),
        "pending": sum(1 for h in snapshot if h.get("status") == "pending"),
    }


# GET /cache, DELETE /cache moved to routers/metrics.py


# GET /customers, /customers/{id}, /docs/corpus, /dq-dg moved to routers/discovery.py


# DELETE /audit moved to routers/audit.py


def _load_latest_observed_metrics() -> dict[str, dict[str, Any]]:
    """Read the most-recent benchmark result JSON and pull metric values.

    Best-effort: returns a dict keyed by metric name with {value, source}.
    Missing files/metrics yield an empty dict and the downstream `_enrich_metric`
    falls back to status="pending". Kept demo-scoped (BFF layer) so the lub
    framework stays clean.
    """
    import json as _json
    import os as _os

    observed: dict[str, dict[str, Any]] = {}
    results_dir = _os.path.normpath(
        _os.path.join(_os.path.dirname(__file__), "..", "..", "benchmarks", "results")
    )
    try:
        json_files = [
            _os.path.join(results_dir, f) for f in _os.listdir(results_dir) if f.endswith(".json")
        ]
        if not json_files:
            return observed
        latest = max(json_files, key=_os.path.getmtime)
        with open(latest, encoding="utf-8") as fh:
            payload = _json.load(fh)
        # Skip Dummy/Fake backends — accuracy=0.0 from a sanity-test eval would
        # display as a misleading "fail" on the SR 11-7 panel. Calibration
        # metrics (ECE/Brier) are still informative on a dummy run, so we keep
        # them; outcome metrics (accuracy/auroc) only land if a real backend ran.
        backend_name = str(payload.get("backend", "")).lower()
        is_dummy = "dummy" in backend_name or "fake" in backend_name
        source = _os.path.basename(latest)
        calibration_keys = ("ece", "brier")
        outcome_keys = ("auroc", "accuracy")
        for key in calibration_keys:
            if payload.get(key) is not None:
                observed[key] = {"value": float(payload[key]), "source": source}
        if not is_dummy:
            for key in outcome_keys:
                if payload.get(key) is not None:
                    observed[key] = {"value": float(payload[key]), "source": source}
    except (OSError, _json.JSONDecodeError, ValueError):
        pass
    return observed


# Industry-typical targets per metric (supervisory guidance + lub.calibration
# thresholds). Drives the pass/fail/pending traffic-light in the dashboard.
_METRIC_TARGETS: Final[dict[str, dict[str, Any]]] = {
    "ece": {"target": 0.05, "comparator": "<="},
    "brier": {"target": 0.20, "comparator": "<="},
    "auroc": {"target": 0.80, "comparator": ">="},
    "refusal_auroc": {"target": 0.80, "comparator": ">="},
    "accuracy": {"target": 0.85, "comparator": ">="},
}

# Synthetic-demo metric values used to populate the SR 11-7 dashboard so
# reviewers can see the framework rendering pass/fail/synthetic states
# end-to-end. NOT real eval output — values picked to be plausible for a
# FakeBackend (constant-confidence reply, decent intent routing, modest
# refusal-AUROC). Replace these with real benchmark JSONs once a non-dummy
# backend has been benchmarked. Each synthetic value carries a clearly-
# labeled source so a reviewer cannot mistake it for a real measurement.
_DEMO_SYNTHETIC_METRICS: Final[dict[str, float]] = {
    "brier": 0.28,
    "accuracy": 0.78,
    "refusal_auroc": 0.76,
}
_DEMO_SYNTHETIC_SOURCE: Final[str] = "demo:synthetic_placeholder (no real eval)"

# Demo deployment uses FakeBackend; performance metrics in _METRIC_TARGETS
# uniformly show `synthetic` rather than mixing real pass/fail badges with
# placeholder badges (real benchmark values came from a different model,
# not this deployment). Runtime metadata (git_sha, dataset_hash, etc.) is
# unaffected. See B-NEW9 in bridge-ui/VALIDATION_HISTORY.md. Flip to False
# once a real backend ships and a benchmark of *that* backend is wired in.
_FORCE_SYNTHETIC_STATUS: Final[bool] = True


def _load_runtime_metadata_metrics() -> dict[str, dict[str, Any]]:
    """Fill the SR 11-7 Ongoing Monitoring pillar with real runtime facts.

    Pillar VI requires evidence that the model + dataset version are tracked
    over time. The 5 metrics it expects (git_sha, dataset_hash,
    dataset_version, missing_ratio, package_versions) aren't pass/fail —
    they're audit-trail facts. We collect them once at startup and stamp
    them with source="runtime" so the dashboard distinguishes them from
    pass/fail performance metrics.
    """
    import json as _json
    import os as _os
    import subprocess as _sp

    out: dict[str, dict[str, Any]] = {}

    # git_sha from `git rev-parse HEAD` of the bridge-ui parent repo.
    try:
        sha = _sp.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=_os.path.dirname(__file__),
            stderr=_sp.DEVNULL,
            text=True,
            timeout=2,
        ).strip()
        if sha:
            out["git_sha"] = {"value": sha, "source": "runtime: git rev-parse HEAD"}
    except (_sp.SubprocessError, FileNotFoundError, OSError):
        pass

    # dataset_* from the latest benchmark result JSON.
    results_dir = _os.path.normpath(
        _os.path.join(_os.path.dirname(__file__), "..", "..", "benchmarks", "results")
    )
    try:
        json_files = [
            _os.path.join(results_dir, f) for f in _os.listdir(results_dir) if f.endswith(".json")
        ]
        if json_files:
            latest = max(json_files, key=_os.path.getmtime)
            with open(latest, encoding="utf-8") as fh:
                payload = _json.load(fh)
            src = _os.path.basename(latest)
            if payload.get("dataset_hash"):
                # Short hash for display; full hash still in source field.
                full = str(payload["dataset_hash"])
                out["dataset_hash"] = {
                    "value": f"{full[:12]}…" if len(full) > 12 else full,
                    "source": f"runtime: {src}",
                }
            if payload.get("dataset"):
                out["dataset_version"] = {
                    "value": str(payload["dataset"]),
                    "source": f"runtime: {src}",
                }
            # missing_ratio: derived from the eval payload. Clean datasets
            # report 0.0; we use the eval's own `n` and `missing` if present,
            # else default to 0.0 (br_regulatory has no missing rows).
            missing = payload.get("missing", 0)
            n = payload.get("n", 1) or 1
            out["missing_ratio"] = {
                "value": round(float(missing) / float(n), 4),
                "source": f"runtime: {src} (computed)",
            }
    except (OSError, _json.JSONDecodeError, ValueError, ZeroDivisionError):
        pass

    # package_versions: count of pinned packages from the latest eval JSON.
    try:
        if "json_files" in dir() and json_files:  # type: ignore[possibly-undefined]
            with open(latest, encoding="utf-8") as fh:  # type: ignore[possibly-undefined]
                payload = _json.load(fh)
            pkgs = payload.get("package_versions") or {}
            if pkgs:
                out["package_versions"] = {
                    "value": f"{len(pkgs)} pinned",
                    "source": f"runtime: {_os.path.basename(latest)}",  # type: ignore[possibly-undefined]
                }
    except (OSError, _json.JSONDecodeError):
        pass

    return out


def _enrich_metric(name: str, observed: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Decorate a metric name with target + observed value + status.

    Status taxonomy (drives pill colour in the dashboard):
      - pass     : observed within target
      - fail     : observed outside target
      - synthetic: observed is a demo placeholder (source includes 'synthetic')
      - pending  : no observed value yet
    """
    entry: dict[str, Any] = {"name": name}
    target_info = _METRIC_TARGETS.get(name)
    if target_info:
        entry["target"] = target_info["target"]
        entry["comparator"] = target_info["comparator"]
    obs = observed.get(name)
    if obs is not None:
        entry["observed"] = obs["value"]
        entry["source"] = obs["source"]
        src_l = str(obs["source"]).lower()
        if "synthetic" in src_l:
            entry["status"] = "synthetic"
        elif target_info:
            # Benchmark placeholders stay "synthetic" under the demo flag, but a
            # value computed from THIS deployment at runtime (source "runtime:
            # ...", e.g. the live intent-classifier calibration) is real and is
            # graded pass/fail against its target.
            if _FORCE_SYNTHETIC_STATUS and not src_l.startswith("runtime"):
                entry["status"] = "synthetic"
            else:
                t = target_info["target"]
                if target_info["comparator"] == "<=":
                    entry["status"] = "pass" if obs["value"] <= t else "fail"
                elif target_info["comparator"] == ">=":
                    entry["status"] = "pass" if obs["value"] >= t else "fail"
                else:
                    entry["status"] = "observed"
        else:
            entry["status"] = "observed"
    else:
        entry["status"] = "pending"
    return entry


def _intent_calibration_samples() -> list[dict[str, Any]]:
    """Per-sample (query, expected, predicted, confidence, correct) for the intent
    classifier over the catalog's labelled example queries.

    Single source of truth for calibration: BOTH the /calibration panel and the
    SR 11-7 Outcome Analysis pillar derive their ECE/Brier/AUROC/accuracy from
    this, so the dashboard cites ONE set of numbers, not two.
    """
    out: list[dict[str, Any]] = []
    for entry in _INTENT_CATALOG:
        expected = entry["name"]
        for q in entry.get("samples", []):
            pred, conf = classify_intent(q)
            out.append(
                {
                    "query": q,
                    "expected": expected,
                    "predicted": pred,
                    "confidence": float(conf),
                    "correct": pred == expected,
                }
            )
    return out


def _load_live_calibration_metrics() -> dict[str, dict[str, Any]]:
    """Real calibration metrics of the intent classifier (this deployment).

    Returned in the ``observed`` shape (value + source) so they override the
    benchmark/synthetic placeholders for the SR 11-7 calibration metrics. The
    ``runtime:`` source marks them as real (graded pass/fail, not synthetic).
    """
    try:
        from lub.calibration.metrics import (
            brier_score,
            expected_calibration_error,
            refusal_auroc,
        )
    except Exception:  # pragma: no cover - lub always present in this repo
        return {}
    samples = _intent_calibration_samples()
    if not samples:
        return {}
    confs = [s["confidence"] for s in samples]
    correct = [1.0 if s["correct"] else 0.0 for s in samples]
    n = len(confs)
    src = (
        f"runtime: intent-classifier calibration — in-sample, {n} labeled catalog "
        f"samples (not a held-out test set)"
    )
    return {
        "ece": {"value": round(expected_calibration_error(confs, correct, n_bins=10), 4), "source": src},
        "brier": {"value": round(brier_score(confs, correct), 4), "source": src},
        "accuracy": {"value": round(sum(correct) / n, 4), "source": src},
        "refusal_auroc": {"value": round(refusal_auroc(confs, correct), 4), "source": src},
    }


def _build_sr_11_7_payload() -> dict[str, Any]:
    pillar_controls = sr_11_7.get_pillar_controls()
    pillar_metrics = sr_11_7.get_pillar_metrics()
    observed = _load_latest_observed_metrics()
    # Pad with synthetic-demo values for metrics not yet wired to a real eval.
    # Honesty preserved via source string + dedicated "synthetic" status colour.
    for key, val in _DEMO_SYNTHETIC_METRICS.items():
        if key not in observed:
            observed[key] = {"value": val, "source": _DEMO_SYNTHETIC_SOURCE}
    # Fold in Ongoing-Monitoring runtime metadata (v7 follow-up — fills the
    # 3rd SR 11-7 pillar with real audit-trail facts: git_sha, dataset_hash,
    # dataset_version, missing_ratio, package_versions).
    observed.update(_load_runtime_metadata_metrics())
    # Single source of truth: replace the benchmark/synthetic calibration
    # placeholders with the REAL intent-classifier calibration (same numbers the
    # /calibration panel shows), so the dashboard never displays two ECEs.
    observed.update(_load_live_calibration_metrics())
    return {
        "title": sr_11_7.TITLE,
        "crosswalk_key": sr_11_7.CROSSWALK_KEY,
        "regime": sr_11_7.REGIME,
        "pillars": [
            {
                "name": name,
                "controls": pillar_controls[name],
                "metrics": pillar_metrics[name],
                "metric_details": [_enrich_metric(m, observed) for m in pillar_metrics[name]],
            }
            for name in sr_11_7.PILLARS
        ],
    }


# Built once at startup -- SR 11-7 controls come from a TOML loaded at
# package import, so the response cannot drift between requests.
_SR_11_7_PAYLOAD: Final[dict[str, Any]] = _build_sr_11_7_payload()


# GET /compliance/sr-11-7 moved to routers/compliance.py


# ---------------------------------------------------------------------------
# Router registration — incremental split of this file into routers/*.
# Routers live in backend/routers/ and read this module's state lazily.
# ---------------------------------------------------------------------------
try:
    from backend.routers import audit as _audit_router
    from backend.routers import calibration as _calibration_router
    from backend.routers import challenge as _challenge_router
    from backend.routers import compliance as _compliance_router
    from backend.routers import discovery as _discovery_router
    from backend.routers import evidence as _evidence_router
    from backend.routers import fleet as _fleet_router
    from backend.routers import security as _security_router
    from backend.routers import experiments as _experiments_router
    from backend.routers import integrations as _integrations_router
    from backend.routers import playground as _playground_router
    from backend.routers import assistant as _assistant_router
    from backend.routers import sessions as _sessions_router
    from backend.routers import governance_changes as _changes_router
    from backend.routers import auth as _auth_router
    from backend.routers import model_card as _model_card_router
    from backend.routers import drift as _drift_router
    from backend.routers import metrics as _metrics_router
    from backend.routers import platform as _platform_router
    from backend.routers import settings as _settings_router
    from backend.routers import visibility as _visibility_router
except ImportError:
    # When server.py is imported as a top-level module (no ``backend``
    # package on the path), fall back to a sibling-relative import.
    from routers import audit as _audit_router  # type: ignore[no-redef]
    from routers import calibration as _calibration_router  # type: ignore[no-redef]
    from routers import challenge as _challenge_router  # type: ignore[no-redef]
    from routers import compliance as _compliance_router  # type: ignore[no-redef]
    from routers import discovery as _discovery_router  # type: ignore[no-redef]
    from routers import evidence as _evidence_router  # type: ignore[no-redef]
    from routers import fleet as _fleet_router  # type: ignore[no-redef]
    from routers import security as _security_router  # type: ignore[no-redef]
    from routers import experiments as _experiments_router  # type: ignore[no-redef]
    from routers import integrations as _integrations_router  # type: ignore[no-redef]
    from routers import playground as _playground_router  # type: ignore[no-redef]
    from routers import assistant as _assistant_router  # type: ignore[no-redef]
    from routers import sessions as _sessions_router  # type: ignore[no-redef]
    from routers import governance_changes as _changes_router  # type: ignore[no-redef]
    from routers import auth as _auth_router  # type: ignore[no-redef]
    from routers import model_card as _model_card_router  # type: ignore[no-redef]
    from routers import drift as _drift_router  # type: ignore[no-redef]
    from routers import metrics as _metrics_router  # type: ignore[no-redef]
    from routers import platform as _platform_router  # type: ignore[no-redef]
    from routers import settings as _settings_router  # type: ignore[no-redef]
    from routers import visibility as _visibility_router  # type: ignore[no-redef]

app.include_router(_platform_router.router)
app.include_router(_metrics_router.router)
app.include_router(_discovery_router.router)
app.include_router(_drift_router.router)
app.include_router(_compliance_router.router)
app.include_router(_model_card_router.router)
app.include_router(_calibration_router.router)
app.include_router(_challenge_router.router)
app.include_router(_fleet_router.router)
app.include_router(_evidence_router.router)
app.include_router(_security_router.router)
app.include_router(_experiments_router.router)
app.include_router(_integrations_router.router)
app.include_router(_playground_router.router)
app.include_router(_assistant_router.router)
app.include_router(_sessions_router.router)
app.include_router(_changes_router.router)
app.include_router(_auth_router.router)
app.include_router(_audit_router.router)
app.include_router(_settings_router.router)
app.include_router(_visibility_router.router)


# Optional Prometheus scrape endpoint (Track D / scale). Mounted ONLY when the
# scale deps (prometheus-client) are installed; in the single-node demo they are
# not, so this import fails and the endpoint is simply absent — the demo, tests
# and e2e are unaffected. When present it serves text-format metrics at
# /metrics/prometheus (distinct from the JSON ``GET /metrics`` dashboard, which
# stays mounted). Point deploy/prometheus.yml's metrics_path here. See
# SCALE_WIRING.md Step 3.
try:
    try:
        from backend.routers import observability as _observability_router
    except ImportError:
        from routers import observability as _observability_router  # type: ignore[no-redef]
    app.include_router(_observability_router.router)
except Exception:  # prometheus-client not installed (demo mode) — skip mounting
    pass


# ---------------------------------------------------------------------------
# Module-attribute proxy (decoupling step 3+). A few names whose canonical home
# is a state sub-module (state.audit; later state.runtime) are REBOUND by that
# module's mutators and/or monkeypatched by tests on THIS module. Re-exporting
# them by value would bind a stale copy. __getattr__ (fires only on a normal-
# lookup MISS, so registered names must be ABSENT from this module's __dict__)
# and __setattr__ delegate those names to the owning sub-module, keeping
# server.X and the sub-module's globals a single source of truth. Installed last
# so all normal module-level assignments above used plain dict storage.
# ---------------------------------------------------------------------------
import sys as _sys_proxy  # noqa: E402
import types as _types_proxy  # noqa: E402


class _ProxyingServerModule(_types_proxy.ModuleType):
    def __getattr__(self, name):  # only on miss; registered names absent from __dict__
        _owner = _PROXIED_ATTRS.get(name)
        if _owner is not None:
            return getattr(_owner, name)
        raise AttributeError(f"module {self.__name__!r} has no attribute {name!r}")

    def __setattr__(self, name, value):
        _owner = _PROXIED_ATTRS.get(name)
        if _owner is not None:
            setattr(_owner, name, value)
        else:
            super().__setattr__(name, value)


# Drift guard (architecture audit R3): every name registered for proxying MUST
# exist on its owning sub-module. Without this, a scalar added to state/audit.py
# or state/runtime.py but forgotten in the _PROXIED_ATTRS registration would fail
# silently — server.X would raise AttributeError only when first read at runtime.
# Asserting at import turns that into a loud, immediate failure.
for _pname, _powner in _PROXIED_ATTRS.items():
    assert hasattr(_powner, _pname), (
        f"proxied name {_pname!r} is registered in _PROXIED_ATTRS but is not defined on "
        f"{getattr(_powner, '__name__', _powner)!r} — fix the registration or the sub-module."
    )

_sys_proxy.modules[__name__].__class__ = _ProxyingServerModule
