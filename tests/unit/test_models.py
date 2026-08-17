# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for Bridge REST API Pydantic models.

The models module is the schema contract at the Bridge boundary: every
request entering the 9-stage pipeline and every response leaving it must
round-trip through these schemas. Tests focus on validation rules,
defaults, enum membership, and the confidence/decision invariants that
downstream stages (UncertaintyGuard, AuditTrail) rely on.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from lub.connectors.bridge.api.models import (
    AgentInfo,
    AgentRegisterRequest,
    Channel,
    ComplianceResponse,
    Decision,
    ErrorResponse,
    HealthResponse,
    MetricsResponse,
    QueryRequest,
    QueryResponse,
)

# ---- Enum coverage ----


class TestChannelEnum:
    def test_known_values(self) -> None:
        assert Channel.APP.value == "app"
        assert Channel.WHATSAPP.value == "whatsapp"
        assert Channel.WEB.value == "web"
        assert Channel.CALL_CENTER.value == "call_center"

    def test_is_string_subclass(self) -> None:
        # StrEnum: comparable to plain strings, usable in dict keys
        assert Channel.APP == "app"
        assert {Channel.APP: 1}["app"] == 1

    def test_membership(self) -> None:
        assert "whatsapp" in {c.value for c in Channel}
        assert "telegram" not in {c.value for c in Channel}


class TestDecisionEnum:
    def test_known_values(self) -> None:
        assert Decision.PASSTHROUGH.value == "passthrough"
        assert Decision.FLAG.value == "flag"
        assert Decision.ABSTAIN.value == "abstain"
        assert Decision.ESCALATE.value == "escalate"

    def test_all_four_guard_outcomes_present(self) -> None:
        # UncertaintyGuard contract: must be able to emit all four
        assert len(list(Decision)) == 4


# ---- Request models ----


class TestQueryRequest:
    def test_minimal_payload_uses_defaults(self) -> None:
        req = QueryRequest(query="Qual o saldo da minha conta?")
        assert req.query == "Qual o saldo da minha conta?"
        assert req.channel == Channel.APP
        assert req.customer_id == ""
        assert req.session_id == ""
        assert req.language == "pt-BR"

    def test_full_payload(self) -> None:
        req = QueryRequest(
            query="Transferir R$ 100 para a Maria",
            channel=Channel.WHATSAPP,
            customer_id="CUST-001",
            session_id="SESS-abc",
            language="en-US",
        )
        assert req.channel == Channel.WHATSAPP
        assert req.customer_id == "CUST-001"
        assert req.language == "en-US"

    def test_empty_query_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            QueryRequest(query="")
        assert "query" in str(exc_info.value)

    def test_query_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError):
            QueryRequest(query="x" * 4097)

    def test_query_at_max_length_accepted(self) -> None:
        req = QueryRequest(query="x" * 4096)
        assert len(req.query) == 4096

    def test_invalid_channel_rejected(self) -> None:
        with pytest.raises(ValidationError):
            QueryRequest(query="oi", channel="telegram")  # type: ignore[arg-type]

    def test_channel_coerced_from_string(self) -> None:
        req = QueryRequest.model_validate({"query": "oi", "channel": "whatsapp"})
        assert req.channel == Channel.WHATSAPP

    def test_serialization_roundtrip(self) -> None:
        req = QueryRequest(query="saldo", channel=Channel.WEB, customer_id="C1")
        data = req.model_dump()
        assert data["query"] == "saldo"
        assert data["channel"] == "web"
        rebuilt = QueryRequest.model_validate(data)
        assert rebuilt == req

    def test_query_with_pii_accepted_at_schema_level(self) -> None:
        # PII handling is the guard/audit layer's job; schema must let it through.
        req = QueryRequest(query="meu CPF é 123.456.789-00, qual meu saldo?")
        assert "CPF" in req.query


class TestAgentRegisterRequest:
    def test_minimal_valid(self) -> None:
        req = AgentRegisterRequest(name="chatbot", agent_type="chatbot")
        assert req.name == "chatbot"
        assert req.agent_type == "chatbot"
        assert req.config == {}

    def test_with_config(self) -> None:
        req = AgentRegisterRequest(
            name="payments",
            agent_type="smart_payments",
            config={"max_amount": 1000, "currency": "BRL"},
        )
        assert req.config["max_amount"] == 1000

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AgentRegisterRequest(name="", agent_type="chatbot")

    def test_name_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AgentRegisterRequest(name="x" * 101, agent_type="chatbot")

    def test_name_at_max_accepted(self) -> None:
        req = AgentRegisterRequest(name="x" * 100, agent_type="chatbot")
        assert len(req.name) == 100

    def test_missing_agent_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AgentRegisterRequest(name="bot")  # type: ignore[call-arg]


# ---- Response models ----


class TestQueryResponse:
    def test_minimal_valid(self) -> None:
        resp = QueryResponse(answer="Olá", confidence=0.9)
        assert resp.answer == "Olá"
        assert resp.confidence == 0.9
        assert resp.decision == Decision.PASSTHROUGH
        assert resp.intent == ""
        assert resp.agent_used == ""
        assert resp.escalated is False
        assert resp.latency_ms == 0.0
        assert resp.metadata == {}

    def test_high_confidence_passthrough(self) -> None:
        resp = QueryResponse(
            answer="Saldo: R$ 1.234,56",
            confidence=0.97,
            decision=Decision.PASSTHROUGH,
            intent="balance_inquiry",
            agent_used="chatbot",
        )
        assert resp.decision == Decision.PASSTHROUGH
        assert resp.escalated is False

    def test_low_confidence_escalate(self) -> None:
        resp = QueryResponse(
            answer="",
            confidence=0.18,
            decision=Decision.ESCALATE,
            escalated=True,
            intent="unknown",
            agent_used="call_center",
        )
        assert resp.decision == Decision.ESCALATE
        assert resp.escalated is True

    def test_mid_confidence_flag(self) -> None:
        resp = QueryResponse(
            answer="Acredito que o saldo é R$ 1.234,56",
            confidence=0.62,
            decision=Decision.FLAG,
        )
        assert resp.decision == Decision.FLAG

    def test_abstain_decision(self) -> None:
        resp = QueryResponse(answer="", confidence=0.0, decision=Decision.ABSTAIN)
        assert resp.decision == Decision.ABSTAIN

    @pytest.mark.parametrize("bad", [-0.01, -1.0, 1.01, 2.0, 100.0])
    def test_confidence_out_of_range_rejected(self, bad: float) -> None:
        with pytest.raises(ValidationError):
            QueryResponse(answer="x", confidence=bad)

    @pytest.mark.parametrize("good", [0.0, 0.5, 1.0])
    def test_confidence_boundaries(self, good: float) -> None:
        resp = QueryResponse(answer="x", confidence=good)
        assert resp.confidence == good

    def test_metadata_carries_pipeline_signals(self) -> None:
        resp = QueryResponse(
            answer="x",
            confidence=0.8,
            metadata={"tier": "frontier", "cache_hit": False, "rag_docs": 3},
        )
        assert resp.metadata["tier"] == "frontier"
        assert resp.metadata["cache_hit"] is False
        assert resp.metadata["rag_docs"] == 3

    def test_serialization_roundtrip(self) -> None:
        resp = QueryResponse(
            answer="ok",
            confidence=0.85,
            decision=Decision.PASSTHROUGH,
            intent="balance",
            agent_used="chatbot",
            latency_ms=212.5,
            metadata={"tier": "cheap"},
        )
        data = resp.model_dump()
        assert data["decision"] == "passthrough"
        assert QueryResponse.model_validate(data) == resp


class TestHealthResponse:
    def test_defaults(self) -> None:
        h = HealthResponse()
        assert h.status == "ok"
        assert h.version == "0.1.0"
        assert h.agents_registered == 0
        assert h.uptime_seconds == 0.0
        assert isinstance(h.timestamp, datetime)

    def test_populated(self) -> None:
        h = HealthResponse(
            status="degraded",
            version="0.2.0",
            agents_registered=4,
            uptime_seconds=12345.6,
        )
        assert h.status == "degraded"
        assert h.agents_registered == 4


class TestAgentInfo:
    def test_defaults(self) -> None:
        info = AgentInfo(name="chatbot", agent_type="chatbot")
        assert info.status == "active"
        assert info.queries_handled == 0
        assert info.avg_confidence == 0.0
        assert info.escalation_rate == 0.0

    def test_populated(self) -> None:
        info = AgentInfo(
            name="payments",
            agent_type="smart_payments",
            status="active",
            queries_handled=42,
            avg_confidence=0.87,
            escalation_rate=0.05,
        )
        assert info.queries_handled == 42
        assert info.avg_confidence == pytest.approx(0.87)


class TestMetricsResponse:
    def test_defaults(self) -> None:
        m = MetricsResponse()
        assert m.total_queries == 0
        assert m.resolution_rate == 0.0
        assert m.escalation_rate == 0.0
        assert m.avg_confidence == 0.0
        assert m.avg_latency_ms == 0.0
        assert m.queries_by_channel == {}
        assert m.queries_by_intent == {}
        assert m.period_hours == 24

    def test_populated(self) -> None:
        m = MetricsResponse(
            total_queries=1000,
            resolution_rate=0.92,
            escalation_rate=0.08,
            avg_confidence=0.85,
            avg_latency_ms=320.5,
            queries_by_channel={"app": 700, "whatsapp": 300},
            queries_by_intent={"balance": 400, "transfer": 600},
            period_hours=48,
        )
        assert m.queries_by_channel["app"] == 700
        assert m.period_hours == 48


class TestComplianceResponse:
    def test_defaults(self) -> None:
        c = ComplianceResponse()
        assert c.bcb_4893_status == "compliant"
        assert c.bcbs_239_status == "compliant"
        assert c.sr_11_7_status == "compliant"
        assert c.audit_trail_complete is True
        assert c.violations == []
        assert isinstance(c.last_check, datetime)

    def test_with_violations(self) -> None:
        c = ComplianceResponse(
            bcb_4893_status="warning",
            audit_trail_complete=False,
            violations=[{"rule": "audit_gap", "severity": "low", "count": 2}],
        )
        assert c.bcb_4893_status == "warning"
        assert len(c.violations) == 1
        assert c.violations[0]["severity"] == "low"


class TestErrorResponse:
    def test_defaults(self) -> None:
        e = ErrorResponse(error="internal_error")
        assert e.error == "internal_error"
        assert e.detail == ""
        assert e.code == 500

    def test_custom_payload(self) -> None:
        e = ErrorResponse(error="not_found", detail="agent 'foo' missing", code=404)
        assert e.code == 404
        assert "foo" in e.detail


# ---- Fixtures and pipeline-shaped scenarios ----


@pytest.fixture
def low_confidence_response() -> QueryResponse:
    return QueryResponse(
        answer="",
        confidence=0.28,
        decision=Decision.ESCALATE,
        escalated=True,
        intent="unknown",
        agent_used="chatbot",
        latency_ms=850.0,
        session_id="SESS-low",
    )


@pytest.fixture
def high_confidence_response() -> QueryResponse:
    return QueryResponse(
        answer="Seu saldo é R$ 1.234,56",
        confidence=0.97,
        decision=Decision.PASSTHROUGH,
        intent="balance_inquiry",
        agent_used="chatbot",
        latency_ms=120.0,
        session_id="SESS-high",
        metadata={"cache_hit": True, "tier": "cheap", "rag_docs": 0},
    )


@pytest.fixture
def whatsapp_query() -> QueryRequest:
    return QueryRequest(
        query="qual meu saldo?",
        channel=Channel.WHATSAPP,
        customer_id="CUST-9",
        session_id="SESS-high",
    )


class TestPipelineScenarios:
    """Schemas must support the Bridge 9-stage pipeline contracts."""

    def test_cache_hit_signaled_in_metadata(
        self, high_confidence_response: QueryResponse
    ) -> None:
        # Stage 1 SemanticCache hit -> low latency + cache_hit=True
        assert high_confidence_response.metadata["cache_hit"] is True
        assert high_confidence_response.latency_ms < 200

    def test_complexity_tier_signaled_in_metadata(
        self, high_confidence_response: QueryResponse
    ) -> None:
        # Stage 2 ComplexityRouter records chosen tier
        assert high_confidence_response.metadata["tier"] in {"cheap", "mid", "frontier"}

    def test_rag_doc_count_signaled(
        self, high_confidence_response: QueryResponse
    ) -> None:
        # Stage 4 RAG retrieval records doc count for audit
        assert "rag_docs" in high_confidence_response.metadata

    def test_intent_propagates_to_response(
        self, high_confidence_response: QueryResponse
    ) -> None:
        # Stage 5 IntentClassifier output surfaces on response
        assert high_confidence_response.intent == "balance_inquiry"

    def test_guard_escalation_path(self, low_confidence_response: QueryResponse) -> None:
        # Stage 7 UncertaintyGuard -> ESCALATE; answer suppressed
        assert low_confidence_response.escalated is True
        assert low_confidence_response.decision == Decision.ESCALATE
        assert low_confidence_response.answer == ""

    def test_session_continuity_request_to_response(
        self, whatsapp_query: QueryRequest, high_confidence_response: QueryResponse
    ) -> None:
        assert whatsapp_query.session_id == high_confidence_response.session_id

    def test_channel_aggregates_into_metrics(
        self, whatsapp_query: QueryRequest
    ) -> None:
        metrics = MetricsResponse(
            total_queries=1,
            queries_by_channel={whatsapp_query.channel.value: 1},
        )
        assert metrics.queries_by_channel["whatsapp"] == 1

    def test_escalation_appears_in_metrics(
        self, low_confidence_response: QueryResponse
    ) -> None:
        metrics = MetricsResponse(
            total_queries=10,
            escalation_rate=0.1 if low_confidence_response.escalated else 0.0,
        )
        assert metrics.escalation_rate == pytest.approx(0.1)


# ---- Edge cases / defensive behavior ----


class TestEdgeCases:
    def test_query_whitespace_only_passes_min_length(self) -> None:
        # Pydantic min_length counts whitespace as content; semantic stripping
        # is the agent layer's job, not the schema's.
        req = QueryRequest(query="   ")
        assert req.query == "   "

    def test_negative_latency_accepted_by_schema(self) -> None:
        # Schema doesn't constrain latency sign; callers may use -1 as sentinel.
        resp = QueryResponse(answer="x", confidence=0.5, latency_ms=-1.0)
        assert resp.latency_ms == -1.0

    def test_unknown_field_ignored_by_default(self) -> None:
        # Pydantic v2 default: extra fields are ignored, not raised.
        req = QueryRequest.model_validate(
            {"query": "oi", "unknown_field": "value"}
        )
        assert req.query == "oi"

    def test_response_with_empty_answer_and_high_confidence(self) -> None:
        # Allowed by schema; the guard layer decides whether this is coherent.
        resp = QueryResponse(answer="", confidence=0.99)
        assert resp.confidence == 0.99
        assert resp.answer == ""

    def test_agent_register_config_accepts_nested_structures(self) -> None:
        req = AgentRegisterRequest(
            name="rag",
            agent_type="custom",
            config={"retriever": {"k": 5, "scorer": "tfidf"}, "tools": ["calc"]},
        )
        assert req.config["retriever"]["k"] == 5
        assert "calc" in req.config["tools"]
