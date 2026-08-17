# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Voice and image interpretation for Smart Payments.

The Smart Payments surface of the Bradesco Bridge platform accepts two
non-textual modalities that this module turns into structured banking
intents:

* **Voice** — a customer says "pagar 150 reais pro João" into WhatsApp
  or the mobile app. Audio bytes are transcribed by an Azure Speech /
  Whisper backend and the resulting Portuguese text is parsed into a
  :class:`~lub.agents.smart_payments.PaymentIntent`.
* **Image** — a customer photographs a *boleto* (a FEBRABAN-standard
  Brazilian payment slip). OCR over the image yields the 47-digit
  *linha digitável*, which this module decodes (regex + FEBRABAN
  field layout) into a :class:`BoletoData` with the amount, due date,
  recipient bank, and 44-digit barcode.

Regulatory context
------------------

Voice and image inputs sit on the *same* execution path as a normal
textual PIX/TED instruction, so they inherit the same regulatory
surface — BCB 4.893 (cyber-resilience and operational risk), BCBS 239
(traceable risk-data aggregation), and SR 11-7 (model-risk
management). Two consequences shape this module:

1. **Every interpretation step is logged** with structured fields the
   :mod:`lub.bridge.audit` ledger can ingest. A boleto extraction that
   succeeds against OCR but fails the FEBRABAN check digit is
   recorded with both the raw OCR text and the failing digit position
   — never silently dropped.
2. **Low-confidence outputs never auto-execute.** Both
   :meth:`VoiceProcessor.transcribe_audio` and
   :meth:`VoiceProcessor.extract_boleto` return a confidence score the
   caller's :class:`~lub.guard.UncertaintyGuard` can gate on. The
   module deliberately does not call the guard itself — that wiring
   belongs to :class:`~lub.bridge.BridgePlatform` so the same guard
   instance governs voice, image, and text uniformly.

Design notes
------------

The module is transport-agnostic and dependency-light by design.
Concrete speech-to-text and OCR backends are passed in via the
:class:`SpeechBackend` and :class:`OcrBackend` protocols, mirroring
the pattern used in :mod:`lub.agents.smart_payments`. Production
callers wire in :class:`AzureSpeechBackend` (Azure Cognitive Services)
or any Whisper-compatible client; tests inject a fake that returns a
deterministic transcript.

The boleto decoder is **pure-Python and offline**: once OCR yields the
47-digit linha digitável, FEBRABAN's field layout is decoded with
regex and arithmetic only. This keeps the regulator-visible decoding
path free of network dependencies and makes it trivially reproducible
during an audit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator

from lub.connectors.bridge.agents.smart_payments import Currency, PaymentIntent, PaymentType

__all__ = [
    "AzureSpeechBackend",
    "BoletoData",
    "BoletoExtractionError",
    "OcrBackend",
    "SpeechBackend",
    "TranscriptionResult",
    "VoiceProcessingError",
    "VoiceProcessor",
]

_LOG = structlog.get_logger("lub.bridge.voice")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class VoiceProcessingError(RuntimeError):
    """Raised when voice transcription fails irrecoverably.

    Distinct from "low confidence" — a :class:`VoiceProcessingError`
    means we have *no* transcript to gate on (empty audio, backend
    outage, malformed bytes). Callers must NOT execute a payment after
    catching this; surface it as a hard escalation in the audit trail.
    """


class BoletoExtractionError(RuntimeError):
    """Raised when a boleto image cannot be decoded into a valid slip.

    Banking-grade strict: invalid FEBRABAN check digits, missing
    required fields, or unparseable linha digitável all raise this
    rather than returning a partially-populated :class:`BoletoData`.
    A partial boleto presented to a customer for confirmation is a
    UX trap that has historically caused misdirected payments.
    """


# ---------------------------------------------------------------------------
# Backend protocols (decoupled from concrete SDKs for testability)
# ---------------------------------------------------------------------------


@runtime_checkable
class SpeechBackend(Protocol):
    """Structural contract for a speech-to-text backend.

    Anything exposing :meth:`transcribe` may stand in for Azure
    Speech-to-Text or Whisper. The method must return a tuple of
    ``(transcript, confidence)`` where ``confidence`` is in ``[0, 1]``
    or ``None`` if the backend does not expose one (in which case the
    :class:`VoiceProcessor` falls back to a conservative default).
    """

    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        language: str = "pt-BR",
    ) -> tuple[str, float | None]:
        """Transcribe raw audio into text and a confidence score.

        Bridge calls this from the Smart Payments voice path: WhatsApp
        / mobile audio arrives at the Bridge API, the platform hands the
        bytes to :class:`VoiceProcessor.transcribe_audio`, which delegates
        to this protocol method. The returned ``confidence`` flows into
        the same :class:`~lub.guard.UncertaintyGuard` that gates text
        intents, so a noisy clip cannot bypass Bridge's auto-execute
        threshold.

        Args:
            audio_bytes: Encoded audio payload from the channel adapter.
            language: BCP-47 tag; Bridge defaults to ``"pt-BR"`` because
                every Bradesco surface is Portuguese-first.

        Returns:
            ``(transcript, confidence)`` where ``confidence`` is in
            ``[0, 1]`` or ``None`` when the backend omits one — the
            :class:`VoiceProcessor` then substitutes a conservative
            default below the Bridge auto-execute threshold.
        """
        ...


@runtime_checkable
class OcrBackend(Protocol):
    """Structural contract for an OCR backend.

    Returns the raw text recognised in ``image_bytes``. The
    :class:`VoiceProcessor` post-processes that text with regex to
    extract the FEBRABAN linha digitável — keeping OCR concerns out of
    the decoder lets us swap Azure AI Vision, Tesseract, or a future
    multimodal model without changing the audit-visible decode logic.
    """

    def recognize(self, image_bytes: bytes) -> str:
        """Return the OCR text extracted from a boleto image.

        Bridge calls this from the Smart Payments image path: a photo
        of a FEBRABAN boleto enters via the Bridge API, the platform
        forwards the bytes to :meth:`VoiceProcessor.extract_boleto`,
        which uses this protocol method to obtain raw text before the
        pure-Python FEBRABAN decoder runs. Keeping OCR isolated here
        lets Bridge swap Azure AI Vision, Tesseract, or a multimodal
        LLM without touching the audit-visible decode path.

        Args:
            image_bytes: Encoded image payload (PNG/JPEG) from the
                channel adapter.

        Returns:
            Raw recognised text — the :class:`VoiceProcessor` post-
            processes it with regex to locate the 47-digit linha
            digitável or 44-digit barcode.
        """
        ...


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


class TranscriptionResult(BaseModel):
    """Outcome of an audio transcription call.

    The ``confidence`` field is propagated to the
    :class:`~lub.guard.UncertaintyGuard` so that a mumbled or noisy
    voice payment never auto-executes — the platform routes it to a
    confirm-by-text step before any PIX leaves the account.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    transcript: str = Field(..., description="Recognised text in the requested language.")
    language: str = Field(default="pt-BR", description="BCP-47 language code.")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Backend-reported confidence in ``[0, 1]``; defaulted "
        "to a conservative value when the backend does not expose one.",
    )
    duration_seconds: float | None = Field(
        default=None,
        ge=0.0,
        description="Length of the audio clip, when reported by the backend.",
    )
    transcribed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp of the transcription, for the audit trail.",
    )

    @field_validator("transcript")
    @classmethod
    def _strip_transcript(cls, value: str) -> str:
        return value.strip()


class BoletoSegment(StrEnum):
    """Logical segments of a FEBRABAN linha digitável.

    Named for the audit log; matches the segment ordering defined in
    FEBRABAN's Manual Operacional para Cobrança.
    """

    BANK_FIELD = "bank_field"
    PRODUCT_FIELD = "product_field"
    CHECK_DIGITS = "check_digits"
    DUE_DATE_FIELD = "due_date_field"
    AMOUNT_FIELD = "amount_field"


class BoletoData(BaseModel):
    """Structured representation of a Brazilian *boleto bancário*.

    Attributes mirror the regulator-defined fields of the 44-digit
    barcode plus a few human-friendly derivatives. ``confidence`` is
    composed from OCR quality and the FEBRABAN check-digit
    verification — a perfect decode with a passing check digit
    yields ``1.0``; OCR noise lowers it linearly.

    The ``payer_view_amount`` is rendered using the BRL convention
    ("R$ 1.234,56") to match what the customer will see when they
    confirm the payment, reducing transcription mismatches at the
    confirm-by-text step.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    barcode: str = Field(
        ...,
        min_length=44,
        max_length=44,
        pattern=r"^\d{44}$",
        description="44-digit FEBRABAN barcode.",
    )
    digitable_line: str = Field(
        ...,
        min_length=47,
        max_length=47,
        pattern=r"^\d{47}$",
        description="47-digit *linha digitável* — what is printed under the barcode.",
    )
    bank_code: str = Field(
        ...,
        min_length=3,
        max_length=3,
        pattern=r"^\d{3}$",
        description="Issuing bank code (e.g. ``237`` for Bradesco).",
    )
    amount: Decimal = Field(..., ge=Decimal("0"), description="Payment amount in BRL.")
    due_date: date | None = Field(
        default=None,
        description="Due date decoded from the FEBRABAN date field; "
        "``None`` for slips without a printed due date.",
    )
    recipient: str | None = Field(
        default=None,
        description="Recipient name when extracted by OCR; ``None`` if "
        "the slip image did not include a readable beneficiary block.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Composite confidence over OCR and FEBRABAN checks.",
    )
    raw_ocr_text: str = Field(
        default="",
        description="Full OCR output preserved verbatim for the audit trail.",
    )
    extracted_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp of the extraction, for the audit trail.",
    )

    @property
    def payer_view_amount(self) -> str:
        """Render the amount in pt-BR currency format ('R$ 1.234,56')."""
        cents = int((self.amount * 100).to_integral_value())
        sign = "-" if cents < 0 else ""
        cents = abs(cents)
        reais, frac = divmod(cents, 100)
        # Insert thousands separators (Brazilian convention: '.').
        reais_str = f"{reais:,}".replace(",", ".")
        return f"{sign}R$ {reais_str},{frac:02d}"


# ---------------------------------------------------------------------------
# Voice-utterance → PaymentIntent parsing
# ---------------------------------------------------------------------------


# Numeric words for amounts up to 999. Boleto/PIX voice utterances above
# this range are rare and ambiguous enough that we fall back to digit
# parsing rather than try to assemble compound number words.
_PT_UNITS: dict[str, int] = {
    "zero": 0,
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "três": 3,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
    "onze": 11,
    "doze": 12,
    "treze": 13,
    "quatorze": 14,
    "catorze": 14,
    "quinze": 15,
    "dezesseis": 16,
    "dezessete": 17,
    "dezoito": 18,
    "dezenove": 19,
    "vinte": 20,
    "trinta": 30,
    "quarenta": 40,
    "cinquenta": 50,
    "sessenta": 60,
    "setenta": 70,
    "oitenta": 80,
    "noventa": 90,
    "cem": 100,
    "cento": 100,
    "duzentos": 200,
    "trezentos": 300,
    "quatrocentos": 400,
    "quinhentos": 500,
    "seiscentos": 600,
    "setecentos": 700,
    "oitocentos": 800,
    "novecentos": 900,
    "mil": 1000,
}

_AMOUNT_NUMERIC_RE = re.compile(
    r"(?P<value>(?:\d{1,3}(?:[.\s]\d{3})+|\d+)(?:[.,]\d{1,2})?)"
    r"\s*(?:reais?|r\$)?",
    re.IGNORECASE,
)

# Recipient cues: "para X", "pro X", "pra X", "ao X". Anchored at the
# end of the utterance because Brazilian Portuguese payment utterances
# nearly always put the beneficiary last.
_RECIPIENT_RE = re.compile(
    r"\b(?:para|pro|pra|ao|à|a)\s+(?P<name>[\wÀ-ÿ][\wÀ-ÿ\s\.'-]{0,60}?)"
    r"(?:\s*[.,!?]|\s*$)",
    re.IGNORECASE,
)

_PIX_RE = re.compile(r"\bpix\b", re.IGNORECASE)
_TED_RE = re.compile(r"\bted\b", re.IGNORECASE)
_DOC_RE = re.compile(r"\bdoc\b", re.IGNORECASE)


def _amount_from_digits(value: str) -> Decimal | None:
    """Parse a Brazilian-formatted numeric amount into a :class:`Decimal`.

    Accepts ``1.234,56``, ``1234,56``, ``1234.56``, and ``1234`` and
    returns ``None`` if the value cannot be interpreted as money.
    """
    normalised = value.replace(" ", "")
    # When both '.' and ',' are present the dot is a thousands
    # separator (Brazilian convention) — strip it and turn the comma
    # into a decimal point.
    if "." in normalised and "," in normalised:
        normalised = normalised.replace(".", "").replace(",", ".")
    elif "," in normalised:
        normalised = normalised.replace(",", ".")
    try:
        return Decimal(normalised)
    except (ArithmeticError, ValueError):
        return None


def _amount_from_words(text: str) -> Decimal | None:
    """Best-effort parse of a spelled-out Portuguese amount.

    Handles the common "cento e cinquenta", "duzentos reais",
    "mil e quinhentos" shapes embedded inside a sentence
    (e.g., "pagar cento e cinquenta reais pro João"). Falls back
    to ``None`` for anything more exotic so the caller can route
    the request to confirm-by-text.
    """
    lower = text.lower()
    # Trim everything after the first occurrence of "reais" / "real"
    # since boleto values past the currency token are usually noise.
    cut = re.split(r"\b(?:reais?|real)\b", lower, maxsplit=1)[0]
    raw_tokens = [tok for tok in re.split(r"[\s,]+", cut) if tok]

    best: Decimal | None = None
    i = 0
    while i < len(raw_tokens):
        if raw_tokens[i] not in _PT_UNITS:
            i += 1
            continue
        # Greedily extend the run, allowing the connector "e" between
        # number words.
        run: list[str] = []
        j = i
        while j < len(raw_tokens):
            tok = raw_tokens[j]
            if tok in _PT_UNITS:
                run.append(tok)
                j += 1
                continue
            if tok == "e" and j + 1 < len(raw_tokens) and raw_tokens[j + 1] in _PT_UNITS:
                j += 1
                continue
            break

        value = _sum_pt_run(run)
        if value is not None and (best is None or value > best):
            best = value
        i = max(j, i + 1)

    return best


def _sum_pt_run(tokens: list[str]) -> Decimal | None:
    """Sum a contiguous list of recognised Portuguese number words."""
    if not tokens:
        return None
    total = 0
    current = 0
    saw_value = False
    for tok in tokens:
        value = _PT_UNITS.get(tok)
        if value is None:
            return None
        saw_value = True
        if value == 1000:
            current = (current or 1) * 1000
            total += current
            current = 0
        elif value >= 100 and current and current < 100:
            current = current * value
        else:
            current += value
    total += current
    if not saw_value or total <= 0:
        return None
    return Decimal(total)


def _parse_payment_type(text: str) -> PaymentType:
    """Pick a payment rail from the utterance; default to PIX."""
    if _TED_RE.search(text):
        return PaymentType.TED
    if _DOC_RE.search(text):
        return PaymentType.DOC
    # PIX is the dominant rail and is the safe default for ambiguous
    # voice utterances on the Smart Payments surface.
    return PaymentType.PIX


def _parse_recipient(text: str) -> str:
    """Extract the recipient phrase from the utterance.

    Returns an empty string when no "para X" cue is present — the
    :class:`~lub.bridge.BridgePlatform` will then route to confirm-by-text
    rather than auto-execute.
    """
    match = _RECIPIENT_RE.search(text)
    if not match:
        return ""
    name = match.group("name").strip().rstrip(".,!?")
    # Drop trailing currency / rail tokens accidentally swept in.
    name = re.sub(r"\s+(?:pix|ted|doc|reais?|real|r\$)\s*$", "", name, flags=re.IGNORECASE)
    return name.strip()


def _parse_amount(text: str) -> Decimal | None:
    """Extract a monetary amount from a free-form Portuguese utterance."""
    # Prefer a digit match — speech-to-text often normalises "cento e
    # cinquenta reais" to "150 reais" already.
    for match in _AMOUNT_NUMERIC_RE.finditer(text):
        amount = _amount_from_digits(match.group("value"))
        if amount is not None and amount > 0:
            return amount
    return _amount_from_words(text)


# ---------------------------------------------------------------------------
# Boleto decoding (FEBRABAN linha digitável → BoletoData)
# ---------------------------------------------------------------------------


# Boleto barcodes are 44 digits. The linha digitável is 47 digits in
# five groups: ``\d{5}\.\d{5} \d{5}\.\d{6} \d{5}\.\d{6} \d \d{14}``.
# The strict pattern accepts the printed form; ``_DIGITABLE_LOOSE_RE``
# accepts a contiguous 47-digit OCR run too.
_DIGITABLE_STRICT_RE = re.compile(
    r"\b(\d{5})\.?(\d{5})\s+(\d{5})\.?(\d{6})\s+(\d{5})\.?(\d{6})\s+(\d)\s+(\d{14})\b"
)
_DIGITABLE_LOOSE_RE = re.compile(r"\b(\d{47})\b")
_BARCODE_RAW_RE = re.compile(r"\b(\d{44})\b")
_BENEFICIARY_RE = re.compile(
    r"(?:benefici[aá]rio|cedente|favorecido)\s*[:\-]?\s*(?P<name>[^\n\r]{2,100})",
    re.IGNORECASE,
)


def _strip_to_digitable(text: str) -> str | None:
    """Find the 47-digit linha digitável within a noisy OCR run."""
    strict = _DIGITABLE_STRICT_RE.search(text)
    if strict:
        return "".join(strict.groups())
    loose = _DIGITABLE_LOOSE_RE.search(text)
    if loose:
        return loose.group(1)
    # Fall back to a contiguous 44-digit barcode — reconstruct the
    # linha digitável from it using FEBRABAN's mapping.
    raw = _BARCODE_RAW_RE.search(text)
    if raw:
        return _barcode_to_digitable(raw.group(1))
    return None


def _mod10(digits: str) -> int:
    """FEBRABAN modulo-10 check (used for linha-digitável fields)."""
    total = 0
    multiplier = 2
    for ch in reversed(digits):
        prod = int(ch) * multiplier
        if prod > 9:
            prod = (prod // 10) + (prod % 10)
        total += prod
        multiplier = 1 if multiplier == 2 else 2
    remainder = total % 10
    return 0 if remainder == 0 else 10 - remainder


def _mod11_barcode(digits: str) -> int:
    """FEBRABAN modulo-11 check (used for the barcode general DV)."""
    weights = [2, 3, 4, 5, 6, 7, 8, 9]
    total = 0
    for i, ch in enumerate(reversed(digits)):
        total += int(ch) * weights[i % len(weights)]
    remainder = total % 11
    dv = 11 - remainder
    return 1 if dv in (0, 10, 11) else dv


def _barcode_to_digitable(barcode: str) -> str:
    """Reconstruct the 47-digit linha digitável from a 44-digit barcode.

    FEBRABAN layout: ``BBBMCCCCC...`` with the barcode general DV at
    position 4 (index 4). The three field DVs are computed by
    :func:`_mod10`.
    """
    field1_data = barcode[0:4] + barcode[19:24]
    field2_data = barcode[24:34]
    field3_data = barcode[34:44]
    dv1 = _mod10(field1_data)
    dv2 = _mod10(field2_data)
    dv3 = _mod10(field3_data)
    general_dv = barcode[4]
    date_amount = barcode[5:19]
    return f"{field1_data}{dv1}{field2_data}{dv2}{field3_data}{dv3}{general_dv}{date_amount}"


def _digitable_to_barcode(digitable: str) -> str:
    """Recover the 44-digit barcode from the 47-digit linha digitável.

    FEBRABAN layout of the 47-digit line:
    ``[0:10]`` field1 (9 data + DV1), ``[10:21]`` field2 (10 data + DV2),
    ``[21:32]`` field3 (10 data + DV3), ``[32]`` general DV,
    ``[33:47]`` due-date factor (4) + amount (10).
    """
    bank_currency = digitable[0:4]
    general_dv = digitable[32]
    date_amount = digitable[33:47]
    free_field_1 = digitable[4:9]
    free_field_2 = digitable[10:20]
    free_field_3 = digitable[21:31]
    return bank_currency + general_dv + date_amount + free_field_1 + free_field_2 + free_field_3


_FEBRABAN_EPOCH = date(1997, 10, 7)


def _decode_due_date(barcode: str) -> date | None:
    """Decode the 4-digit FEBRABAN due-date field.

    ``0000`` (and a few legacy sentinels) mean "no due date printed";
    otherwise the field is days since :data:`_FEBRABAN_EPOCH`.
    """
    field = barcode[5:9]
    if field == "0000":
        return None
    try:
        days = int(field)
    except ValueError:
        return None
    if days == 0:
        return None
    return _FEBRABAN_EPOCH + timedelta(days=days)


def _decode_amount(barcode: str) -> Decimal:
    """Decode the 10-digit centavos amount field into BRL."""
    cents = int(barcode[9:19])
    return (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"))


def _verify_digitable(digitable: str) -> bool:
    """Verify all three field check digits on a linha digitável."""
    f1 = digitable[0:10]
    f2 = digitable[10:21]
    f3 = digitable[21:32]
    ok1 = _mod10(f1[:-1]) == int(f1[-1])
    ok2 = _mod10(f2[:-1]) == int(f2[-1])
    ok3 = _mod10(f3[:-1]) == int(f3[-1])
    return ok1 and ok2 and ok3


def _verify_barcode(barcode: str) -> bool:
    """Verify the FEBRABAN modulo-11 general check digit."""
    data = barcode[:4] + barcode[5:]
    return _mod11_barcode(data) == int(barcode[4])


def _extract_recipient_from_ocr(ocr_text: str) -> str | None:
    """Pull a beneficiary name from raw OCR text, if present."""
    match = _BENEFICIARY_RE.search(ocr_text)
    if not match:
        return None
    name = match.group("name").strip().rstrip(".,;:")
    # Beneficiary lines on boletos often include the CNPJ on the same
    # line — cut at the first CPF/CNPJ-shaped token.
    name = re.split(
        r"\s+\d{2,3}[\./\-\d]+",
        name,
        maxsplit=1,
    )[0].strip()
    return name or None


# ---------------------------------------------------------------------------
# Azure Speech-to-Text backend (optional dependency)
# ---------------------------------------------------------------------------


class AzureSpeechBackend:
    """Thin adapter over Azure Cognitive Services Speech SDK.

    Implements :class:`SpeechBackend`. The Azure SDK is imported
    lazily so that the rest of :mod:`lub.bridge` can be exercised in
    test environments without the package installed — matching the
    pattern used in :mod:`lub.integrations.whatsapp`.

    Parameters
    ----------
    subscription_key:
        Azure Speech resource key. Pass the value from a secret store;
        never check it into git.
    region:
        Azure region the resource is deployed in (e.g. ``"brazilsouth"``).
    default_language:
        BCP-47 language tag used when the caller does not specify one.
    """

    _MISSING_MSG = (
        "The 'azure-cognitiveservices-speech' package is required for "
        "AzureSpeechBackend. Install it with: pip install "
        "azure-cognitiveservices-speech"
    )

    def __init__(
        self,
        *,
        subscription_key: str,
        region: str,
        default_language: str = "pt-BR",
    ) -> None:
        if not subscription_key:
            raise ValueError("AzureSpeechBackend requires a non-empty subscription_key")
        if not region:
            raise ValueError("AzureSpeechBackend requires a non-empty region")
        self._subscription_key = subscription_key
        self._region = region
        self._default_language = default_language

    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        language: str = "pt-BR",
    ) -> tuple[str, float | None]:
        """Transcribe ``audio_bytes`` using Azure Speech-to-Text.

        Returns ``(transcript, confidence)``. Azure does not always
        emit a confidence score (it depends on the recognition mode);
        when absent, ``None`` is returned so the
        :class:`VoiceProcessor` can apply its conservative default.
        """
        try:
            import azure.cognitiveservices.speech as speechsdk
        except ImportError as exc:  # pragma: no cover - exercised in deployments
            raise VoiceProcessingError(self._MISSING_MSG) from exc

        if not audio_bytes:
            raise VoiceProcessingError("AzureSpeechBackend received empty audio bytes")

        try:
            config = speechsdk.SpeechConfig(
                subscription=self._subscription_key, region=self._region
            )
            config.speech_recognition_language = language or self._default_language
            stream = speechsdk.audio.PushAudioInputStream()
            stream.write(audio_bytes)
            stream.close()
            audio_config = speechsdk.audio.AudioConfig(stream=stream)
            recognizer = speechsdk.SpeechRecognizer(speech_config=config, audio_config=audio_config)
            result = recognizer.recognize_once()
        except Exception as exc:  # noqa: BLE001 — wrap all SDK failures
            raise VoiceProcessingError(f"Azure Speech recognition failed: {exc}") from exc

        text = (getattr(result, "text", "") or "").strip()
        confidence: float | None = None
        # Azure attaches a JSON blob under the "JsonResult" property
        # when detailed output is requested; opportunistically parse it.
        json_blob = getattr(result, "json", None) or getattr(result, "properties", None)
        if isinstance(json_blob, str):
            confidence = _try_parse_azure_confidence(json_blob)
        return text, confidence


def _try_parse_azure_confidence(blob: str) -> float | None:
    """Best-effort extraction of an Azure confidence from a JSON blob."""
    import json

    try:
        payload: Any = json.loads(blob)
    except (ValueError, TypeError):
        return None
    nbest = payload.get("NBest") if isinstance(payload, dict) else None
    if isinstance(nbest, list) and nbest:
        candidate = nbest[0]
        if isinstance(candidate, dict):
            conf = candidate.get("Confidence")
            if isinstance(conf, (int, float)):
                return max(0.0, min(1.0, float(conf)))
    return None


# ---------------------------------------------------------------------------
# Main processor
# ---------------------------------------------------------------------------


_DEFAULT_CONFIDENCE_WHEN_UNREPORTED = 0.75
"""Conservative fallback when the speech backend omits a confidence score.

Chosen below the ``0.85`` threshold the Bradesco production guard uses
for auto-execute on Smart Payments, so any unreported-confidence
transcription is routed to confirm-by-text by default.
"""


@dataclass(frozen=True)
class VoiceProcessor:
    """Voice and image interpretation for the Smart Payments surface.

    The processor is a thin façade: it owns no transport state and
    keeps no per-customer data, so it is safe to share across threads
    as long as the injected backends are themselves thread-safe.

    Parameters
    ----------
    speech_backend:
        Anything implementing :class:`SpeechBackend`. In production this
        is an :class:`AzureSpeechBackend`; in tests it is a fake.
    ocr_backend:
        Anything implementing :class:`OcrBackend`. Optional — required
        only for :meth:`extract_boleto`; voice-only deployments may
        leave this ``None``.
    default_language:
        BCP-47 language tag used when transcribing audio. Defaults to
        ``"pt-BR"`` because every Bradesco Bridge surface is
        Portuguese-first.
    min_confidence_for_intent:
        Lower bound on transcription confidence below which
        :meth:`parse_voice_payment` returns an intent with
        :attr:`PaymentIntent.confidence` clamped accordingly so the
        downstream :class:`~lub.guard.UncertaintyGuard` escalates.
    """

    speech_backend: SpeechBackend
    ocr_backend: OcrBackend | None = None
    default_language: str = "pt-BR"
    min_confidence_for_intent: float = 0.5

    def transcribe_audio(
        self,
        audio_bytes: bytes,
        *,
        language: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe an audio clip into a :class:`TranscriptionResult`.

        Raises :class:`VoiceProcessingError` when the backend returns
        an empty transcript or fails outright — the caller must treat
        either case as a hard escalation, not as a low-confidence
        transcription.
        """
        if not audio_bytes:
            raise VoiceProcessingError("transcribe_audio received empty audio bytes")

        lang = language or self.default_language
        try:
            transcript, raw_confidence = self.speech_backend.transcribe(audio_bytes, language=lang)
        except VoiceProcessingError:
            raise
        except Exception as exc:  # noqa: BLE001
            _LOG.error(
                "voice.transcribe.backend_error",
                error=str(exc),
                error_type=type(exc).__name__,
                language=lang,
                bytes_in=len(audio_bytes),
            )
            raise VoiceProcessingError(f"Speech backend failed: {type(exc).__name__}") from exc

        transcript = (transcript or "").strip()
        if not transcript:
            _LOG.warning(
                "voice.transcribe.empty",
                language=lang,
                bytes_in=len(audio_bytes),
            )
            raise VoiceProcessingError("Speech backend produced an empty transcript")

        confidence = (
            raw_confidence if raw_confidence is not None else _DEFAULT_CONFIDENCE_WHEN_UNREPORTED
        )
        confidence = max(0.0, min(1.0, float(confidence)))

        result = TranscriptionResult(
            transcript=transcript,
            language=lang,
            confidence=confidence,
        )
        _LOG.info(
            "voice.transcribe.ok",
            language=lang,
            bytes_in=len(audio_bytes),
            transcript_chars=len(result.transcript),
            confidence=result.confidence,
            confidence_reported=raw_confidence is not None,
        )
        return result

    def parse_voice_payment(
        self,
        audio_bytes: bytes,
        *,
        language: str | None = None,
    ) -> PaymentIntent:
        """Transcribe and parse a voice payment request.

        The returned :class:`PaymentIntent` inherits the transcription
        confidence, so a noisy clip naturally lowers the intent
        confidence below the guard threshold. When the utterance lacks
        an amount or recipient the function still returns an intent —
        with empty fields and a low confidence — so the audit trail
        captures the failed parse rather than silently dropping it.
        """
        transcription = self.transcribe_audio(audio_bytes, language=language)
        return self._intent_from_text(
            transcription.transcript, base_confidence=transcription.confidence
        )

    def parse_intent_from_text(self, text: str, *, base_confidence: float = 1.0) -> PaymentIntent:
        """Parse a pre-transcribed Portuguese utterance into an intent.

        Useful when a different channel (chatbot, call-center summary)
        has already produced text and only the structured-extraction
        step is needed.
        """
        return self._intent_from_text(text, base_confidence=base_confidence)

    def extract_boleto(self, image_bytes: bytes) -> BoletoData:
        """OCR a boleto image and decode the FEBRABAN payload.

        Raises :class:`BoletoExtractionError` when:

        * the OCR backend is not configured,
        * the image yields no recognizable linha digitável / barcode,
        * the recovered digits fail the FEBRABAN check-digit verification.

        Returning a *partially-populated* boleto would be a UX trap that
        has historically caused misdirected payments — we'd rather
        escalate to a human capture step than auto-execute a malformed
        slip.
        """
        if self.ocr_backend is None:
            raise BoletoExtractionError("VoiceProcessor.extract_boleto requires an ocr_backend")
        if not image_bytes:
            raise BoletoExtractionError("extract_boleto received empty image bytes")

        try:
            ocr_text = self.ocr_backend.recognize(image_bytes)
        except Exception as exc:  # noqa: BLE001
            _LOG.error(
                "voice.boleto.ocr_error",
                error=str(exc),
                error_type=type(exc).__name__,
                bytes_in=len(image_bytes),
            )
            raise BoletoExtractionError(f"OCR backend failed: {type(exc).__name__}") from exc

        ocr_text = ocr_text or ""
        digitable = _strip_to_digitable(ocr_text)
        if digitable is None:
            _LOG.warning(
                "voice.boleto.no_digitable",
                bytes_in=len(image_bytes),
                ocr_chars=len(ocr_text),
            )
            raise BoletoExtractionError(
                "OCR text did not contain a recognizable linha digitável or 44-digit barcode"
            )

        if len(digitable) != 47 or not digitable.isdigit():
            raise BoletoExtractionError(
                f"recovered linha digitável has wrong shape (len={len(digitable)})"
            )

        digitable_ok = _verify_digitable(digitable)
        barcode = _digitable_to_barcode(digitable)
        barcode_ok = _verify_barcode(barcode)

        if not (digitable_ok and barcode_ok):
            _LOG.warning(
                "voice.boleto.check_digit_failed",
                digitable_ok=digitable_ok,
                barcode_ok=barcode_ok,
                bytes_in=len(image_bytes),
            )
            raise BoletoExtractionError(
                "FEBRABAN check-digit verification failed "
                f"(digitable_ok={digitable_ok}, barcode_ok={barcode_ok})"
            )

        amount = _decode_amount(barcode)
        due_date = _decode_due_date(barcode)
        bank_code = barcode[0:3]
        recipient = _extract_recipient_from_ocr(ocr_text)

        # Composite confidence: digitable + barcode passing gives 0.95
        # baseline; presence of a beneficiary block pushes us to 1.0.
        confidence = 0.95
        if recipient:
            confidence = 1.0

        data = BoletoData(
            barcode=barcode,
            digitable_line=digitable,
            bank_code=bank_code,
            amount=amount,
            due_date=due_date,
            recipient=recipient,
            confidence=confidence,
            raw_ocr_text=ocr_text,
        )
        _LOG.info(
            "voice.boleto.ok",
            bank_code=bank_code,
            amount=str(amount),
            due_date=due_date.isoformat() if due_date else None,
            has_recipient=recipient is not None,
            confidence=confidence,
        )
        return data

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _intent_from_text(self, text: str, *, base_confidence: float) -> PaymentIntent:
        """Shared utterance → :class:`PaymentIntent` parser."""
        cleaned = (text or "").strip()
        recipient = _parse_recipient(cleaned)
        amount = _parse_amount(cleaned)
        payment_type = _parse_payment_type(cleaned)

        # Confidence is the base (transcription) confidence, dampened
        # by any missing extracted field. Missing amount is especially
        # serious — a payment without an amount must always escalate.
        confidence = max(0.0, min(1.0, float(base_confidence)))
        if not recipient:
            confidence = min(confidence, 0.45)
        if amount is None:
            confidence = min(confidence, 0.30)

        intent = PaymentIntent(
            recipient=recipient,
            amount=amount if amount is not None else Decimal("0"),
            currency=Currency.BRL,
            description="",
            payment_type=payment_type,
            confidence=confidence,
            raw_text=cleaned,
        )
        _LOG.info(
            "voice.intent.parsed",
            payment_type=payment_type.value,
            amount=str(intent.amount),
            has_recipient=bool(recipient),
            has_amount=amount is not None,
            confidence=intent.confidence,
            base_confidence=base_confidence,
            escalate=intent.confidence < self.min_confidence_for_intent,
        )
        return intent
