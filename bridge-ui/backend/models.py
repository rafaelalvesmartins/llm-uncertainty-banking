# Copyright 2026 Rafael Martins Alves — Apache-2.0
"""API-contract DTOs (decoupling step 7).

The /query request + response schemas and the channel / customer-id validators, extracted
VERBATIM from server.py. Pure pydantic — no server coupling. server.py re-exports them so the
route handlers, routers and tests that reference server.QueryRequest / server._CUSTOMER_ID_PATTERN
keep working unchanged.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, Field

_AllowedChannel = Literal["whatsapp", "app", "web", "call_center"]


_CUSTOMER_ID_PATTERN = r"^[A-Za-z0-9._-]{1,64}$"


class QueryRequest(BaseModel):
    # `text` is accepted as an alias for `query` so the test-plan v1 schema
    # (which used `text`) keeps working after the v2 rename. N2 fix from
    # the post-fix review — deprecation without breaking existing callers.
    # G6 v7 fix: min_length on the post-strip form is checked downstream by
    # dq_input (_too_short), but reject obviously-empty payloads at the
    # schema level too so the pipeline doesn't spin up for "   \n\t  ".
    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        validation_alias=AliasChoices("query", "text"),
        serialization_alias="query",
        pattern=r"\S",  # at least one non-whitespace char
    )
    # B-NEW5 v4/v5 fix (2026-05-17): channel and customer_id were previously
    # defaulted, which let clients POST without them and get a silent
    # "whatsapp"/"demo-customer". Now required — missing → HTTP 422.
    channel: _AllowedChannel = Field(
        ..., description="Customer channel (required since 2026-05-17)"
    )
    # G7 v7 fix (2026-05-17): customer_id must match a conservative
    # identifier regex so XSS / HTML injection / unicode tricks don't
    # land in audit/log lines. Generous enough to accept UUIDs, slugs,
    # numeric IDs, and underscores/dots/hyphens — no spaces, no angle
    # brackets, no quotes, ASCII-only.
    customer_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Customer ID (required since 2026-05-17; regex-validated v7)",
        pattern=_CUSTOMER_ID_PATTERN,
    )
    idempotency_key: str | None = Field(
        default=None,
        description="Optional client-supplied unique key. Requests with the same "
        "key within 60s return the cached prior response (idempotent retry).",
    )

    model_config = {"populate_by_name": True}


class PipelineStage(BaseModel):
    name: str
    status: str
    detail: str
    confidence: float | None = None
    duration_ms: float


class QueryResponse(BaseModel):
    query: str
    answer: str
    intent: str
    confidence: float
    decision: str
    latency_ms: float
    stages: list[PipelineStage]
    # Structured highlights — populated when the corresponding stage ran.
    cache_hit: bool = False
    cache_similarity: float | None = None
    tier: str | None = None  # SIMPLE / MEDIUM / COMPLEX
    cost_cents: float | None = None
    memory_blocks: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    handoff_chain: list[str] = Field(default_factory=list)
    agent_used: str | None = None
    # Hash-chain sequence of THIS decision's audit entry, so the caller can point at the
    # immutable record of the decision it just received — the hook for the LGPD Art. 20
    # right to an explanation of an automated decision (GET /audit/explain/{seq}).
    # In practice always set on a decision path (_audit_append stamps the seq before it
    # touches SQLite, and the disk write is the only best-effort part). Optional so the
    # contract stays honest if a future sink can't assign one; the UI hides the link then.
    audit_seq: int | None = None


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------


__all__ = [
    'QueryRequest',
    'PipelineStage',
    'QueryResponse',
    '_AllowedChannel',
    '_CUSTOMER_ID_PATTERN',
]
