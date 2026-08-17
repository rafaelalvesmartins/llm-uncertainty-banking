# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""AI Visibility monitoring + intelligence (Bloco B).

Pipeline: monitoring prompts -> pluggable AI adapter -> entity mention
extraction -> the SAME uncertainty guard + tamper-evident audit hash-chain the
banking pipeline uses -> Share-of-Voice aggregation. On top of that:

* B1 (P3.7) pluggable REAL adapters (OpenAI/Anthropic) behind the same
  ``VisibilityAdapter`` interface as the fake one, called via stdlib urllib
  (no new pip deps, mirrors OllamaBackend). They register ONLY when their API
  key env var is present; otherwise the offline FakeVisibilityAdapter stays
  the default so the demo runs anywhere.
* B2 (P3.8) SQLite time-series persistence (audit-DB pattern; Postgres/
  Timescale is the documented production target) + an OPT-IN in-process
  scheduler (``VISIBILITY_SCHEDULE_EVERY_S``, 0 = off).
* B3 (P3.9) a recommendations engine: ranks the monitored brand's visibility
  gaps by volume x (1 - share_of_voice) x measurement confidence.
* B4 (P3.10) content drafts gated by the uncertainty guard: a draft inherits
  the confidence of the data it's built on; FLAG/ESCALATE drafts are BLOCKED
  from publication, only PASSTHROUGH drafts can be queued for EXPLICIT human
  approval. Nothing is ever auto-published and there is no real external
  distribution channel — "publish" = mark human-approved (enqueue).

State is module-local; ``server`` is used only for the guard, the runtime
threshold, and the audit chain via the lazy ``_server()`` accessor.
"""

from __future__ import annotations

import json as _json
import os as _os
import sqlite3 as _sqlite3
import threading as _threading
import time
import unicodedata
import urllib.error as _urllib_err
import urllib.request as _urllib_req
from pathlib import Path as _Path
from typing import TYPE_CHECKING, Any, Protocol

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

try:
    from backend.routers.auth import verify_token
except ImportError:
    from routers.auth import verify_token  # type: ignore[no-redef]

if TYPE_CHECKING:
    from types import ModuleType

router = APIRouter()


def _server() -> ModuleType:
    # Reuse whichever ``server`` module is already loaded so this router's
    # writes and the app's hot-path reads hit the SAME module globals. uvicorn
    # runs ``server:app`` and the tests ``import server`` — both register
    # ``"server"`` in sys.modules. Forcing ``from backend import server`` here
    # would create a divergent second module (runtime state would split).
    import sys
    mod = sys.modules.get("server") or sys.modules.get("backend.server")
    if mod is not None:
        return mod
    try:
        import server  # type: ignore[no-redef]
    except ImportError:
        from backend import server
    return server


# ---------------------------------------------------------------------------
# Monitoring config (in-memory; editable via PUT /visibility/config)
# ---------------------------------------------------------------------------

_MONITORING_QUERIES: list[dict[str, str]] = [
    {"id": "q1", "text": "Qual o melhor banco digital do Brasil?"},
    {"id": "q2", "text": "Quais bancos brasileiros tem melhor atendimento por IA?"},
    {"id": "q3", "text": "Onde abrir conta PJ com menor tarifa no Brasil?"},
]

_TARGET_ENTITIES: list[str] = ["Bradesco", "Nubank", "Itau", "Banco Inter", "C6 Bank"]

# The brand whose visibility the recommendations/content engines optimize for.
_OWN_BRAND: str = "Bradesco"

# Per-query monitoring volume weight (no real search-volume feed in the demo;
# a configurable hint, default 1.0 each). Used by the B3 ranking.
_QUERY_VOLUME: dict[str, float] = {}

# Results of the most recent collection run.
_LAST_RUN: dict[str, Any] | None = None

# B4 content drafts (in-memory).
_CONTENT_DRAFTS: list[dict[str, Any]] = []
_CONTENT_SEQ: int = 0


# ---------------------------------------------------------------------------
# Pluggable model adapters (B1)
# ---------------------------------------------------------------------------


class VisibilityAdapter(Protocol):
    """Common interface: prompt -> AI answer text + is_real flag."""

    name: str
    is_real: bool

    def answer(self, query_text: str) -> str: ...


class FakeVisibilityAdapter:
    """Deterministic, offline stand-in for a monitored AI model.

    Returns canned answers that mention the target entities in a fixed order,
    so the demo's metrics are reproducible without a network call.
    """

    name = "fake-ai:v1"
    is_real = False

    _CANNED: dict[str, str] = {
        "q1": (
            "Entre os melhores bancos digitais do Brasil, o Nubank costuma liderar "
            "em base de clientes, seguido pelo Banco Inter e pelo C6 Bank. O Itau "
            "tem forte presenca digital tambem."
        ),
        "q2": (
            "Em atendimento por IA, o Bradesco (BIA) e o Itau sao frequentemente "
            "citados, com o Nubank investindo em automacao de suporte."
        ),
        "q3": (
            "Para conta PJ com tarifas baixas, o Banco Inter e o C6 Bank sao "
            "opcoes populares; o Nubank PJ tambem cresce nesse segmento."
        ),
    }

    def answer(self, query_text: str) -> str:
        for q in _MONITORING_QUERIES:
            if q["text"] == query_text and q["id"] in self._CANNED:
                return self._CANNED[q["id"]]
        return (
            "Diversas instituicoes financeiras brasileiras competem nesse tema, "
            "incluindo Nubank, Itau e Bradesco."
        )


class _HTTPVisibilityAdapter:
    """Base for real provider adapters via stdlib urllib (no SDK dep).

    Mirrors the OllamaBackend pattern in server.py: a plain HTTP POST with a
    short timeout, graceful empty-string fallback on any transport/parse error
    so a flaky provider never crashes a collection run.
    """

    name = "real:override"
    is_real = True
    timeout_s = 20.0

    def _build_prompt(self, query_text: str) -> str:
        brands = ", ".join(_TARGET_ENTITIES)
        return (
            "Responda de forma concisa, em portugues. Pergunta de pesquisa de "
            f"mercado: '{query_text}'. Se mencionar instituicoes financeiras, "
            f"cite as relevantes (candidatas: {brands})."
        )

    def _post(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        data = _json.dumps(payload).encode("utf-8")
        req = _urllib_req.Request(url, data=data, headers=headers, method="POST")
        with _urllib_req.urlopen(req, timeout=self.timeout_s) as resp:
            return _json.loads(resp.read().decode("utf-8"))

    def answer(self, query_text: str) -> str:  # pragma: no cover - needs network+key
        raise NotImplementedError


class OpenAIVisibilityAdapter(_HTTPVisibilityAdapter):
    """OpenAI Chat Completions adapter. Active only if OPENAI_API_KEY is set."""

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        self.model = model
        self.name = f"openai:{model}"
        self._key = _os.environ.get("OPENAI_API_KEY", "")

    def answer(self, query_text: str) -> str:  # pragma: no cover - needs network+key
        if not self._key:
            return ""
        try:
            data = self._post(
                "https://api.openai.com/v1/chat/completions",
                {
                    "model": self.model,
                    "messages": [{"role": "user", "content": self._build_prompt(query_text)}],
                    "temperature": 0.3,
                },
                {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
            )
            return (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
        except (_urllib_err.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError):
            return ""


class AnthropicVisibilityAdapter(_HTTPVisibilityAdapter):
    """Anthropic Messages adapter. Active only if ANTHROPIC_API_KEY is set."""

    def __init__(self, model: str = "claude-haiku-4-5-20251001") -> None:
        self.model = model
        self.name = f"anthropic:{model}"
        self._key = _os.environ.get("ANTHROPIC_API_KEY", "")

    def answer(self, query_text: str) -> str:  # pragma: no cover - needs network+key
        if not self._key:
            return ""
        try:
            data = self._post(
                "https://api.anthropic.com/v1/messages",
                {
                    "model": self.model,
                    "max_tokens": 512,
                    "messages": [{"role": "user", "content": self._build_prompt(query_text)}],
                },
                {
                    "x-api-key": self._key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
            )
            blocks = data.get("content") or []
            return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        except (_urllib_err.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError):
            return ""


_ADAPTERS: dict[str, VisibilityAdapter] = {FakeVisibilityAdapter.name: FakeVisibilityAdapter()}
_ACTIVE_ADAPTER = FakeVisibilityAdapter.name


def _register_real_adapters() -> None:
    """Register provider adapters whose API key is present in the env. The fake
    adapter stays the default — real adapters are opt-in via key presence."""
    if _os.environ.get("OPENAI_API_KEY"):
        a = OpenAIVisibilityAdapter()
        _ADAPTERS[a.name] = a
    if _os.environ.get("ANTHROPIC_API_KEY"):
        a = AnthropicVisibilityAdapter()
        _ADAPTERS[a.name] = a


_register_real_adapters()


# ---------------------------------------------------------------------------
# SQLite time-series persistence (B2). Postgres/Timescale is the production
# target; SQLite mirrors the audit-DB pattern so the demo needs no infra.
# ---------------------------------------------------------------------------

_VIS_DB_PATH = _os.environ.get(
    "BRIDGE_VISIBILITY_DB",
    str(_Path(_os.environ.get("TMP", "/tmp")) / "bridge_visibility.db"),
)
_VIS_DB_LOCK = _threading.Lock()
_VIS_DB_CONN: _sqlite3.Connection | None = None


def _vis_db() -> _sqlite3.Connection:
    """Lazy SQLite connection for the visibility run history."""
    global _VIS_DB_CONN
    if _VIS_DB_CONN is None:
        conn = _sqlite3.connect(_VIS_DB_PATH, check_same_thread=False)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS visibility_runs ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, adapter TEXT, "
            "metrics_json TEXT)"
        )
        conn.commit()
        _VIS_DB_CONN = conn
    return _VIS_DB_CONN


def _persist_run(run: dict[str, Any]) -> None:
    """Append one run's metrics to the SQLite time series (best-effort)."""
    try:
        with _VIS_DB_LOCK:
            db = _vis_db()
            db.execute(
                "INSERT INTO visibility_runs (ts, adapter, metrics_json) VALUES (?,?,?)",
                (run["ts"], run["adapter"], _json.dumps(run["metrics"], default=str)),
            )
            db.commit()
    except Exception as e:  # noqa: BLE001 — persistence must never block a run
        print(f"[visibility] sqlite persist failed: {e}", flush=True)


# ---------------------------------------------------------------------------
# Extraction + measurement
# ---------------------------------------------------------------------------


def _fold(text: str) -> str:
    """Lowercase + strip diacritics so 'Itaú' matches 'Itau'."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c)
    )


def _extract_mentions(answer: str) -> list[dict[str, Any]]:
    """Per target entity: mentioned?, first-occurrence char index, and rank
    (1 = appears first). Sentiment is left ``neutral`` — a real adapter would
    run sentiment; faking it would overclaim, so we don't."""
    folded = _fold(answer)
    found: list[tuple[int, str]] = []
    for entity in _TARGET_ENTITIES:
        idx = folded.find(_fold(entity))
        if idx >= 0:
            found.append((idx, entity))
    found.sort()
    rank_by_entity = {entity: i + 1 for i, (_, entity) in enumerate(found)}
    out: list[dict[str, Any]] = []
    for entity in _TARGET_ENTITIES:
        mentioned = entity in rank_by_entity
        out.append(
            {
                "entity": entity,
                "mentioned": mentioned,
                "position": rank_by_entity.get(entity),
                "sentiment": "neutral",
            }
        )
    return out


def _measurement_confidence(mentions: list[dict[str, Any]]) -> float:
    """Confidence in THIS visibility measurement (not in the answer's truth).

    Heuristic for the demo: a clear answer that mentions several distinct
    entities is an unambiguous reading (high confidence); an answer that
    mentions none is a low-confidence signal (the guard will FLAG/ESCALATE,
    prompting human review of whether the brand is truly absent).
    """
    n = sum(1 for m in mentions if m["mentioned"])
    if n == 0:
        return 0.45
    return min(0.75 + 0.06 * n, 0.97)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ConfigUpdate(BaseModel):
    queries: list[str] | None = Field(default=None, description="Monitoring prompt texts")
    entities: list[str] | None = Field(default=None, description="Target entity names")
    own_brand: str | None = Field(default=None, description="Brand to optimize visibility for")
    active_adapter: str | None = Field(default=None, description="Which registered adapter to use")
    query_volumes: dict[str, float] | None = Field(
        default=None, description="Per-query-id monitoring volume weight (default 1.0)"
    )


class DraftRequest(BaseModel):
    query_id: str = Field(..., description="Monitoring query the content targets")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/visibility/config")
def get_config() -> dict[str, Any]:
    """Current monitoring config, adapters, and remaining gaps."""
    real_adapters = [n for n, a in _ADAPTERS.items() if getattr(a, "is_real", False)]
    gaps = []
    if not real_adapters:
        gaps.append(
            "No real model adapter active — set OPENAI_API_KEY / "
            "ANTHROPIC_API_KEY to register one (the offline FakeVisibilityAdapter is the default)."
        )
    if _SCHEDULE_EVERY_S <= 0:
        gaps.append("Scheduler off — collection is manual (enable it in the UI, or via VISIBILITY_SCHEDULE_EVERY_S).")
    gaps.append("SQLite persistence (demo); Postgres/Timescale is the production target.")
    gaps.append(
        "Content distribution = human approval queue only; no real external "
        "channel (blog/social/CMS) is connected, and nothing is published automatically."
    )
    return {
        "queries": _MONITORING_QUERIES,
        "entities": _TARGET_ENTITIES,
        "own_brand": _OWN_BRAND,
        "active_adapter": _ACTIVE_ADAPTER,
        "available_adapters": list(_ADAPTERS),
        "real_adapters": real_adapters,
        "query_volumes": {q["id"]: _QUERY_VOLUME.get(q["id"], 1.0) for q in _MONITORING_QUERIES},
        "schedule_every_s": _SCHEDULE_EVERY_S,
        "schedule_every_minutes": round(_SCHEDULE_EVERY_S / 60.0, 2),
        "gaps": gaps,
    }


@router.put("/visibility/config")
def put_config(
    update: ConfigUpdate,
    principal: dict[str, Any] | None = Depends(verify_token),
) -> dict[str, Any]:
    """Update monitoring config (queries, entities, own_brand, adapter, volumes)."""
    global _MONITORING_QUERIES, _TARGET_ENTITIES, _OWN_BRAND, _ACTIVE_ADAPTER
    if update.queries is not None:
        _MONITORING_QUERIES = [
            {"id": f"q{i + 1}", "text": t.strip()} for i, t in enumerate(update.queries) if t.strip()
        ]
    if update.entities is not None:
        _TARGET_ENTITIES = [e.strip() for e in update.entities if e.strip()]
    if update.own_brand is not None:
        _OWN_BRAND = update.own_brand.strip()
    if update.active_adapter is not None:
        if update.active_adapter not in _ADAPTERS:
            raise HTTPException(
                status_code=422,
                detail=f"unknown adapter {update.active_adapter!r}; available: {list(_ADAPTERS)}",
            )
        _ACTIVE_ADAPTER = update.active_adapter
    if update.query_volumes is not None:
        _QUERY_VOLUME.update({k: float(v) for k, v in update.query_volumes.items()})
    return get_config()


def _collect() -> dict[str, Any]:
    """Run every monitoring prompt through the active adapter once, instrument
    each collection (guard + audit chain), aggregate, persist, and return."""
    global _LAST_RUN
    s = _server()
    adapter = _ADAPTERS[_ACTIVE_ADAPTER]
    threshold = getattr(s, "_RUNTIME_GUARD_THRESHOLD", 0.7)
    collected: list[dict[str, Any]] = []
    run_ts = time.time()

    for q in _MONITORING_QUERIES:
        answer = adapter.answer(q["text"]) or ""
        mentions = _extract_mentions(answer)
        confidence = _measurement_confidence(mentions)
        decision, reason = s.apply_guard(confidence, threshold=threshold, intent="visibility")
        audit_entry = s._audit_append(
            {
                "ts": run_ts,
                # A SYNTHETIC monitoring probe, not a customer's query. Without this key the
                # explainer framed it as an LGPD Art. 20 "automated decision" about a data
                # subject (there is none — customer_id is the engine itself), and /dq-dg +
                # /sessions counted these probes as real customer traffic.
                "event": "visibility.probe",
                "query": f"[visibility] {q['text']}",
                "intent": "visibility_collection",
                "confidence": round(confidence, 3),
                "decision": decision,
                "answer": answer,
                "customer_id": "visibility-engine",
                "channel": "visibility",
                "from_cache": False,
                "tier": "monitoring",
                "cost_cents": 0.0,
                "query_was_masked": False,
                "pii_count": 0,
            }
        )
        collected.append(
            {
                "query_id": q["id"],
                "query": q["text"],
                "model": adapter.name,
                "is_real_model": getattr(adapter, "is_real", False),
                "answer": answer,
                "mentions": mentions,
                "confidence": round(confidence, 3),
                "decision": decision,
                "decision_reason": reason,
                "audit_seq": audit_entry["seq"],
                "audit_hash": audit_entry["hash"],
            }
        )

    _LAST_RUN = {
        "ts": run_ts,
        "adapter": adapter.name,
        "queries_run": len(collected),
        "results": collected,
        "metrics": _aggregate(collected),
    }
    _persist_run(_LAST_RUN)
    return _LAST_RUN


@router.post("/visibility/run")
def run_collection(
    principal: dict[str, Any] | None = Depends(verify_token),
) -> dict[str, Any]:
    """Manually trigger one collection pass (also runnable by the scheduler)."""
    return _collect()


@router.get("/visibility/results")
def get_results() -> dict[str, Any]:
    """Return the most recent collection run, or an empty shell if none yet."""
    if _LAST_RUN is None:
        return {
            "ts": None,
            "adapter": _ACTIVE_ADAPTER,
            "queries_run": 0,
            "results": [],
            "metrics": {"entities": [], "total_mentions": 0, "queries": 0},
            "note": "No collection run yet — POST /visibility/run.",
        }
    return _LAST_RUN


@router.get("/visibility/history")
def get_history(limit: int = 50) -> dict[str, Any]:
    """Time series of past runs (SQLite) — per-run Share-of-Voice per entity."""
    try:
        with _VIS_DB_LOCK:
            db = _vis_db()
            rows = db.execute(
                "SELECT ts, adapter, metrics_json FROM visibility_runs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    except Exception as e:  # noqa: BLE001
        print(f"[visibility] history query failed: {e!r}", flush=True)
        return {"runs": [], "count": 0, "error": "internal error"}
    runs = []
    for ts, adapter, metrics_json in reversed(rows):
        try:
            metrics = _json.loads(metrics_json)
        except ValueError:
            metrics = {}
        runs.append(
            {
                "ts": ts,
                "adapter": adapter,
                "share_of_voice": {
                    e["entity"]: e["share_of_voice"] for e in metrics.get("entities", [])
                },
            }
        )
    return {"runs": runs, "count": len(runs), "store": "sqlite"}


@router.get("/visibility/recommendations")
def get_recommendations() -> dict[str, Any]:
    """B3 — rank the own-brand's visibility gaps by volume x gap x confidence.

    For each monitored query, the gap is how far the own brand is from full
    Share-of-Voice in that answer (absent = gap 1.0; mentioned but not first =
    partial). Score = volume x gap x measurement-confidence, so a high-volume
    query where the brand is absent AND the reading is confident ranks first.
    """
    if _LAST_RUN is None:
        return {"own_brand": _OWN_BRAND, "recommendations": [], "note": "Run a collection first."}
    recs = []
    for r in _LAST_RUN["results"]:
        own = next((m for m in r["mentions"] if m["entity"] == _OWN_BRAND), None)
        if own is None:
            continue
        if not own["mentioned"]:
            gap, state = 1.0, "absent"
        elif own["position"] == 1:
            gap, state = 0.0, "leader (position 1)"
        else:
            # mentioned but not first — partial gap shrinking with rank.
            gap, state = round(1.0 - 1.0 / own["position"], 3), f"mentioned (position {own['position']})"
        volume = _QUERY_VOLUME.get(r["query_id"], 1.0)
        score = round(volume * gap * r["confidence"], 4)
        if gap > 0:
            recs.append(
                {
                    "query_id": r["query_id"],
                    "query": r["query"],
                    "own_brand_state": state,
                    "gap": gap,
                    "volume_weight": volume,
                    "confidence": r["confidence"],
                    "score": score,
                    "evidence": (r["answer"] or "")[:160],
                    "action": (
                        f"Produce content (FAQ/article) positioning {_OWN_BRAND} for "
                        f"'{r['query']}' — target PR/SEO/GEO in the sources cited by the AI."
                    ),
                }
            )
    recs.sort(key=lambda x: x["score"], reverse=True)
    return {
        "own_brand": _OWN_BRAND,
        "recommendations": recs,
        "note": "Prioritization = volume × gap (1 − own SoV) × measurement confidence.",
    }


def _generate_draft_text(rec_query: str) -> str:
    """Produce a draft for a gap query. Uses the active adapter if it can
    generate (real), else a deterministic template (fake/offline)."""
    adapter = _ADAPTERS[_ACTIVE_ADAPTER]
    if getattr(adapter, "is_real", False):
        text = adapter.answer(
            f"Write an FAQ paragraph, in English, positioning {_OWN_BRAND} "
            f"as the answer to: '{rec_query}'. Be factual and concise."
        )
        if text:
            return text
    return (
        f"{_OWN_BRAND}: for the question '{rec_query}', we highlight digital "
        f"service, competitive fees, and AI support. [draft generated for "
        f"human review — not published]"
    )


@router.post("/visibility/content/draft")
def create_draft(
    req: DraftRequest,
    principal: dict[str, Any] | None = Depends(verify_token),
) -> dict[str, Any]:
    """B4 — generate a content draft for a gap query and GATE it with the guard.

    The draft inherits the measurement confidence of its source query, runs
    through the SAME uncertainty guard, and is BLOCKED from publication unless
    the decision is PASSTHROUGH. FLAG/ESCALATE drafts can never be approved —
    they require the data/quality to improve first. Nothing is auto-published.
    """
    global _CONTENT_SEQ
    if _LAST_RUN is None:
        raise HTTPException(status_code=409, detail="Run a collection first (POST /visibility/run).")
    source = next((r for r in _LAST_RUN["results"] if r["query_id"] == req.query_id), None)
    if source is None:
        raise HTTPException(status_code=404, detail=f"query_id {req.query_id!r} not in last run.")
    s = _server()
    threshold = getattr(s, "_RUNTIME_GUARD_THRESHOLD", 0.7)
    confidence = source["confidence"]
    decision, reason = s.apply_guard(confidence, threshold=threshold, intent="content")
    text = _generate_draft_text(source["query"])
    publishable = decision == "PASSTHROUGH"
    _CONTENT_SEQ += 1
    draft = {
        "id": _CONTENT_SEQ,
        "query_id": req.query_id,
        "query": source["query"],
        "text": text,
        "confidence": confidence,
        "decision": decision,
        "decision_reason": reason,
        "status": "pending_approval" if publishable else "blocked",
        "publishable": publishable,
        "approved_by": None,
        "created_ts": time.time(),
    }
    _CONTENT_DRAFTS.append(draft)
    return draft


@router.get("/visibility/content")
def list_content() -> dict[str, Any]:
    """List all content drafts and their gate status."""
    return {
        "drafts": _CONTENT_DRAFTS,
        "total": len(_CONTENT_DRAFTS),
        "pending_approval": sum(1 for d in _CONTENT_DRAFTS if d["status"] == "pending_approval"),
        "blocked": sum(1 for d in _CONTENT_DRAFTS if d["status"] == "blocked"),
        "approved": sum(1 for d in _CONTENT_DRAFTS if d["status"] == "approved"),
    }


@router.post("/visibility/content/{draft_id}/approve")
def approve_draft(
    draft_id: int,
    approver: str = "human-operator",
    principal: dict[str, Any] | None = Depends(verify_token),
) -> dict[str, Any]:
    """EXPLICIT human approval. Only PASSTHROUGH drafts can be approved;
    FLAG/ESCALATE (blocked) drafts are refused. Approval marks the draft
    human-approved (enqueued) — it does NOT publish to any external channel."""
    approver = principal["sub"] if principal else approver
    draft = next((d for d in _CONTENT_DRAFTS if d["id"] == draft_id), None)
    if draft is None:
        raise HTTPException(status_code=404, detail=f"draft {draft_id} not found.")
    if draft["status"] == "blocked":
        raise HTTPException(
            status_code=409,
            detail=(
                f"draft {draft_id} is BLOCKED (guard decision {draft['decision']}); "
                f"FLAG/ESCALATE content can never be approved/published."
            ),
        )
    draft["status"] = "approved"
    draft["approved_by"] = approver
    draft["approved_ts"] = time.time()
    return {
        "status": "approved",
        "draft_id": draft_id,
        "note": (
            "Human-approved and enqueued. No external publication occurred — the "
            "demo has no real distribution channel wired."
        ),
        "draft": draft,
    }


def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Share-of-Voice, presence%, and average position per target entity."""
    total_queries = len(results)
    total_mentions = 0
    per_entity: dict[str, dict[str, Any]] = {
        e: {"entity": e, "mentions": 0, "positions": []} for e in _TARGET_ENTITIES
    }
    for r in results:
        for m in r["mentions"]:
            if m["mentioned"]:
                total_mentions += 1
                bucket = per_entity.setdefault(
                    m["entity"], {"entity": m["entity"], "mentions": 0, "positions": []}
                )
                bucket["mentions"] += 1
                if m["position"] is not None:
                    bucket["positions"].append(m["position"])
    entities_out = []
    for e in _TARGET_ENTITIES:
        b = per_entity[e]
        positions = b["positions"]
        entities_out.append(
            {
                "entity": e,
                "mentions": b["mentions"],
                "presence_pct": round(b["mentions"] / total_queries, 3) if total_queries else 0.0,
                "share_of_voice": round(b["mentions"] / total_mentions, 3) if total_mentions else 0.0,
                "avg_position": round(sum(positions) / len(positions), 2) if positions else None,
            }
        )
    entities_out.sort(key=lambda x: x["share_of_voice"], reverse=True)
    return {
        "entities": entities_out,
        "total_mentions": total_mentions,
        "queries": total_queries,
    }


# ---------------------------------------------------------------------------
# Opt-in scheduler (B2). Off by default; a daemon thread runs collections every
# N seconds when VISIBILITY_SCHEDULE_EVERY_S > 0.
# ---------------------------------------------------------------------------

_SCHEDULER_STARTED = False
# Runtime-mutable interval in seconds (0 = off). Seeded from the env so existing
# VISIBILITY_SCHEDULE_EVERY_S deployments keep working, but now also settable at
# runtime via POST /visibility/schedule — no restart, configurable from the UI.
try:
    _SCHEDULE_EVERY_S: float = float(_os.environ.get("VISIBILITY_SCHEDULE_EVERY_S", "0") or 0)
except ValueError:
    _SCHEDULE_EVERY_S = 0.0


def _scheduler_loop() -> None:  # pragma: no cover - timing-dependent background loop
    while True:
        every = _SCHEDULE_EVERY_S
        if every and every > 0:
            time.sleep(every)
            if _SCHEDULE_EVERY_S and _SCHEDULE_EVERY_S > 0:  # may have been disabled mid-sleep
                try:
                    _collect()
                except Exception as e:  # noqa: BLE001
                    print(f"[visibility] scheduled collection failed: {e}", flush=True)
        else:
            time.sleep(2.0)  # idle while off, so enabling takes effect within ~2s


def _ensure_scheduler() -> None:
    global _SCHEDULER_STARTED
    if _SCHEDULER_STARTED:
        return
    _SCHEDULER_STARTED = True
    _threading.Thread(target=_scheduler_loop, daemon=True, name="visibility-scheduler").start()


def _set_schedule_seconds(seconds: float) -> float:
    """Set the runtime schedule (0 = off) and start the daemon if needed."""
    global _SCHEDULE_EVERY_S
    _SCHEDULE_EVERY_S = max(0.0, seconds)
    if _SCHEDULE_EVERY_S > 0:
        _ensure_scheduler()
    return _SCHEDULE_EVERY_S


class ScheduleUpdate(BaseModel):
    every_minutes: float = Field(ge=0, le=1440, description="Collection interval in minutes; 0 = off")


@router.post("/visibility/schedule")
def set_schedule(
    update: ScheduleUpdate,
    principal: dict[str, Any] | None = Depends(verify_token),
) -> dict[str, Any]:
    """Enable/disable scheduled collection at runtime (no restart). 0 = off; a
    positive value is clamped to a 15s floor so the demo can't self-DoS."""
    secs = 0.0 if update.every_minutes <= 0 else max(15.0, update.every_minutes * 60.0)
    every = _set_schedule_seconds(secs)
    return {
        "schedule_every_s": every,
        "schedule_every_minutes": round(every / 60.0, 2),
        "enabled": every > 0,
    }


# Start the daemon at import if the env pre-enabled it (it idles when off).
if _SCHEDULE_EVERY_S > 0:
    _ensure_scheduler()


__all__ = ["router"]
