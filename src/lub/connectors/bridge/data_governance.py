# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Data Governance (DG) for the Bridge platform.

LLM-based banking AI has three governance concerns the existing
:class:`~lub.connectors.bridge.governance.AIGovernance` does NOT
address (those are about *AI* governance — model use, prompt safety):

* **PII detection + masking** — Brazilian PII (CPF, CNPJ, account
  numbers, phone, email) MUST NOT leak to third-party LLM providers
  (Azure OpenAI, Anthropic) without explicit consent. Per LGPD Art. 7
  and BCB 4893, you must minimize transferred personal data.
* **Data classification** — every piece of data entering the platform
  has a sensitivity tier (PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED)
  which drives downstream policy (cache eligibility, audit retention,
  LLM provider restriction).
* **Data lineage** — every transformation (mask, classify, route to
  LLM, store) is recorded so a regulator can answer "where did this
  customer's account number end up?".

This module is the *policy* layer; the Bridge platform threads its
results into the audit trail and the data-flow decisions (don't cache
RESTRICTED; don't send unmasked CPF to a US-hosted LLM, etc.).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum

import structlog

__all__ = [
    "DataClassification",
    "DataGovernor",
    "GovernanceResult",
    "LineageEntry",
    "PIIMatch",
    "PIIType",
]

_LOG = structlog.get_logger("lub.bridge.data_governance")


# ---------------------------------------------------------------------------
# Classification + PII enums
# ---------------------------------------------------------------------------


class DataClassification(StrEnum):
    """Brazilian banking sensitivity classification (BCB 4893 aligned).

    ``PUBLIC``: marketing copy, product pages, public rates.
    ``INTERNAL``: aggregate metrics, anonymized stats.
    ``CONFIDENTIAL``: customer-identifiable but not financial detail
        (name, generic preferences).
    ``RESTRICTED``: account balances, CPF, financial transactions —
        the most-protected tier. Triggers strictest controls.
    """

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class PIIType(StrEnum):
    """Brazilian PII categories that Bridge must detect + mask."""

    CPF = "cpf"
    CNPJ = "cnpj"
    PHONE = "phone"
    EMAIL = "email"
    ACCOUNT = "account"  # agencia + conta
    CARD = "card"  # 16-digit card number
    PIX_KEY = "pix_key"  # generic PIX key (could be CPF/email/random)
    # B-NEW-7 v6 review: credentials are not PII in the strict LGPD sense
    # but warrant the same masking discipline. A leaked password or token
    # in the audit log is a worse breach than a CPF in the same field.
    CREDENTIAL = "credential"


# ---------------------------------------------------------------------------
# Detection patterns
# ---------------------------------------------------------------------------

# CPF: 000.000.000-00 or 11 raw digits (handled carefully to avoid phone collision)
_PATTERN_CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")

# CNPJ: 00.000.000/0000-00
_PATTERN_CNPJ = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")

# Brazilian phone: (11) 99999-9999 or +55 11 99999-9999
_PATTERN_PHONE = re.compile(r"(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4}")

# Email
_PATTERN_EMAIL = re.compile(r"\b[\w.-]+@[\w.-]+\.\w{2,}\b")

# Bradesco-style account: agencia-d + conta-d (e.g. 1234-5 / 67890-1)
_PATTERN_ACCOUNT = re.compile(r"\b\d{4}-\d\b")

# Card (16-digit): 4111 1111 1111 1111 or contiguous
_PATTERN_CARD = re.compile(r"\b(?:\d{4}[\s-]?){4}\b")

# Credentials / secrets. Catches the same surface as the DQ rule but at the
# masking layer — if a credential somehow gets through DQ (e.g. partial
# marker, low-confidence match), DG still scrubs it before audit storage.
# Keyword-based credential mention. Greedy capture to end-of-sentence (up to
# 60 chars). Intentionally over-broad: when the user types "senha" we'd rather
# lose surrounding transactional context in the audit log than risk leaking
# the actual secret token. Under-masking here would persist plaintext
# credentials to disk.
_PATTERN_CREDENTIAL_KW = re.compile(
    # Gobble up to 80 non-newline chars after the keyword. We allow `.` inside
    # the captured range because secrets like JWTs and dotted tokens contain
    # dots; stopping at `.` would split the secret. CPF/card/email patterns
    # later in the same sentence still match independently against the
    # original text and get their own masks.
    r"\b(?:senha|password|passwd|pwd|pin|otp|token|api[_-]?key|secret"
    r"|bearer|authorization)\b[^\n]{0,80}",
    re.IGNORECASE,
)
# Token-blob signatures. Run independently of keyword detection so a JWT or
# OpenAI key embedded mid-sentence still gets caught when the keyword regex
# stops at the first `.`.
_PATTERN_CREDENTIAL_BLOB = re.compile(
    r"(eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    r"|-----BEGIN [A-Z0-9 ]*KEY-----[\s\S]+?-----END [A-Z0-9 ]*KEY-----"
    r"|sk-[A-Za-z0-9_-]{10,}"
    r"|AIza[A-Za-z0-9_-]{30,}"
    r"|AKIA[A-Z0-9]{16}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|ghp_[A-Za-z0-9]{30,})",
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PIIMatch:
    """A single PII fragment detected in text."""

    pii_type: PIIType
    start: int
    end: int
    value_hash: str
    """Hex hash of the original value — useful for re-identification by
    the customer's own ledger while preventing plaintext leak in logs."""


@dataclass(frozen=True)
class LineageEntry:
    """One transformation step in the data's journey through Bridge."""

    step: str
    timestamp_iso: str
    classification: DataClassification
    pii_count: int
    note: str = ""


@dataclass(frozen=True)
class GovernanceResult:
    """Outcome of a :meth:`DataGovernor.govern` call."""

    original: str
    masked: str
    classification: DataClassification
    matches: tuple[PIIMatch, ...]
    lineage: tuple[LineageEntry, ...]

    @property
    def has_pii(self) -> bool:
        return len(self.matches) > 0

    @property
    def safe_for_external_llm(self) -> bool:
        """True if the masked form can be sent to a third-party LLM."""
        return self.classification != DataClassification.RESTRICTED or not self.has_pii


# ---------------------------------------------------------------------------
# Governor
# ---------------------------------------------------------------------------


@dataclass
class DataGovernor:
    """Detect PII, classify, mask, and append to lineage.

    Stateless except for an in-memory lineage buffer per call. Callers
    threading lineage across a multi-step pipeline should pass the
    previous result's ``lineage`` tuple as ``prior_lineage`` to
    :meth:`govern`.
    """

    mask_token: str = "[REDACTED]"

    def detect(self, text: str) -> list[PIIMatch]:
        """Find every PII fragment in ``text``."""
        matches: list[PIIMatch] = []
        # Order matters: detect more-specific patterns first.
        # Credentials run FIRST so a JWT containing dots/digits doesn't get
        # mis-tagged as account or phone.
        for pii_type, pattern in (
            (PIIType.CREDENTIAL, _PATTERN_CREDENTIAL_BLOB),
            (PIIType.CREDENTIAL, _PATTERN_CREDENTIAL_KW),
            (PIIType.CPF, _PATTERN_CPF),
            (PIIType.CNPJ, _PATTERN_CNPJ),
            (PIIType.EMAIL, _PATTERN_EMAIL),
            (PIIType.CARD, _PATTERN_CARD),
            (PIIType.ACCOUNT, _PATTERN_ACCOUNT),
            (PIIType.PHONE, _PATTERN_PHONE),
        ):
            for regex_match in pattern.finditer(text):
                matches.append(
                    PIIMatch(
                        pii_type=pii_type,
                        start=regex_match.start(),
                        end=regex_match.end(),
                        value_hash=hashlib.blake2s(
                            regex_match.group(0).encode("utf-8"), digest_size=8
                        ).hexdigest(),
                    )
                )
        # Sort by position; resolve overlaps by keeping first match.
        matches.sort(key=lambda x: (x.start, -x.end))
        deduped: list[PIIMatch] = []
        last_end = -1
        for m in matches:
            if m.start >= last_end:
                deduped.append(m)
                last_end = m.end
        return deduped

    def classify(self, text: str, matches: list[PIIMatch]) -> DataClassification:
        """Pick the highest applicable sensitivity tier."""
        if any(
            m.pii_type
            in (
                PIIType.CPF,
                PIIType.CNPJ,
                PIIType.ACCOUNT,
                PIIType.CARD,
                PIIType.CREDENTIAL,  # secrets always restricted
            )
            for m in matches
        ):
            return DataClassification.RESTRICTED
        if any(m.pii_type in (PIIType.EMAIL, PIIType.PHONE) for m in matches):
            return DataClassification.CONFIDENTIAL
        # Heuristic: queries about financial state are INTERNAL even
        # without explicit PII (saldo, fatura, etc.).
        if re.search(r"\b(saldo|fatura|extrato|emprestimo|cartao)\b", text, re.IGNORECASE):
            return DataClassification.INTERNAL
        return DataClassification.PUBLIC

    def mask(self, text: str, matches: list[PIIMatch]) -> str:
        """Replace each PII match with the mask token."""
        if not matches:
            return text
        out: list[str] = []
        cursor = 0
        for m in matches:
            out.append(text[cursor : m.start])
            out.append(f"[{self.mask_token}:{m.pii_type.value}]")
            cursor = m.end
        out.append(text[cursor:])
        return "".join(out)

    def govern(
        self,
        text: str,
        *,
        step: str = "input",
        prior_lineage: tuple[LineageEntry, ...] = (),
        timestamp_iso: str | None = None,
    ) -> GovernanceResult:
        """Full pipeline: detect → classify → mask → append lineage."""
        from datetime import UTC, datetime

        ts = timestamp_iso or datetime.now(UTC).isoformat()
        matches = self.detect(text)
        classification = self.classify(text, matches)
        masked = self.mask(text, matches)
        new_entry = LineageEntry(
            step=step,
            timestamp_iso=ts,
            classification=classification,
            pii_count=len(matches),
            note=(f"masked {len(matches)} PII fragment(s)" if matches else "no PII detected"),
        )
        _LOG.info(
            "bridge.dg.governed",
            step=step,
            classification=classification.value,
            pii_count=len(matches),
            text_len=len(text),
        )
        return GovernanceResult(
            original=text,
            masked=masked,
            classification=classification,
            matches=tuple(matches),
            lineage=(*prior_lineage, new_entry),
        )
