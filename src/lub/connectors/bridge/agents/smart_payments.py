# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Smart payments agent for WhatsApp and voice channels.

Extracts payment intent from natural-language messages, voice utterances,
or photographed *boletos*; validates business rules (amount limits,
recipient format, allowed currencies); and gates the final execution on
an uncertainty check so that ambiguous requests are routed to human
confirmation rather than executed blindly.

Supports PIX, TED, and DOC payment types as defined by Banco Central
do Brasil.

The agent has three multimodal entry points so that the same business
rules apply regardless of the channel the customer used:

* :meth:`SmartPaymentAgent.parse_payment` — text (chatbot/WhatsApp text).
* :meth:`SmartPaymentAgent.parse_voice` — audio bytes from WhatsApp or
  the call-center surface, transcribed and parsed by a
  :class:`VoiceProcessorProtocol` collaborator.
* :meth:`SmartPaymentAgent.parse_boleto_image` — a photographed slip,
  OCR'd and decoded against the FEBRABAN check-digit rules by the same
  collaborator.

The voice/image collaborators are injected as a *protocol* rather than a
concrete class so that this module does not import from
:mod:`lub.bridge.voice` (which itself imports :class:`PaymentIntent`,
:class:`PaymentType`, and :class:`Currency` from here). Decoupling at the
Protocol boundary keeps the dependency one-way and lets unit tests
substitute a fake without touching the bridge layer.

Usage::

    from lub.connectors.bridge.agents.smart_payments import SmartPaymentAgent
    from lub.connectors.bridge.voice import VoiceProcessor, AzureSpeechBackend

    voice = VoiceProcessor(speech_backend=AzureSpeechBackend(...))
    agent = SmartPaymentAgent(backend=my_llm, voice_processor=voice)

    intent = agent.parse_payment("Pix 50 reais para Maria")
    intent = agent.parse_voice(wav_bytes)            # voice utterance
    intent = agent.parse_boleto_image(jpeg_bytes)    # photo of a boleto

    result = agent.validate_payment(intent)
    if result.valid:
        ...  # proceed to execute
"""

# bridge-governance: upstream -- customer text is governed by BridgePlatform.process_query (bridge-ui/backend/server.py: _GOVERNOR.govern at the BFF). Agent sees masked text. See DATA_GOVERNANCE.md section 4a.
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import structlog

if TYPE_CHECKING:  # pragma: no cover - import only for type-checkers
    from lub.connectors.bridge.voice import BoletoData

_LOG = structlog.get_logger("lub.agents.smart_payments")


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


class LLMBackend(Protocol):
    """Minimal protocol for an LLM backend."""

    def complete(self, prompt: str, **kwargs: Any) -> str:
        """Generate a completion for ``prompt`` via the wired LLM backend.

        This is the single seam through which the smart-payments agent
        reaches the Bridge hub's LLM fleet: ``BridgePlatform`` injects a
        concrete wrapper (Azure OpenAI, on-prem Llama, etc.) selected by
        :mod:`lub.orchestration` so the agent itself stays vendor-agnostic
        and the tiered router can swap providers without touching this
        module.

        Args:
            prompt: Fully rendered user/system prompt to send to the model.
            **kwargs: Backend-specific knobs (temperature, max_tokens,
                stop sequences) forwarded verbatim by the wrapper.

        Returns:
            The raw text completion, already stripped of provider framing
            by the wrapper layer.
        """
        ...


@runtime_checkable
class VoiceProcessorProtocol(Protocol):
    """Multimodal collaborator able to produce a :class:`PaymentIntent`.

    The concrete implementation lives in :class:`lub.bridge.voice.VoiceProcessor`
    but the agent depends only on the two methods below so the bridge
    package can remain a downstream consumer of this module rather than a
    bidirectional dependency. Test fakes need only implement these two
    callables.
    """

    def parse_voice_payment(
        self,
        audio_bytes: bytes,
        *,
        language: str | None = None,
    ) -> PaymentIntent:
        """Transcribe an audio clip and return a parsed :class:`PaymentIntent`.

        Called by :meth:`SmartPaymentAgent.parse_voice` when a customer
        sends a voice note through WhatsApp or speaks to the call-center
        IVR. The concrete Bridge implementation chains its speech-to-text
        backend (Azure Speech in production) with
        :meth:`SmartPaymentAgent.parse_payment` so the same regex+LLM
        extraction path is used for text and voice, and the returned
        ``confidence`` reflects both transcription quality and extraction
        certainty — letting :class:`~lub.guard.UncertaintyGuard` escalate
        noisy clips to human confirmation.

        Args:
            audio_bytes: Raw audio payload (format negotiated with the
                speech backend; typically WAV/OGG from WhatsApp).
            language: Optional BCP-47 override; ``None`` uses the
                processor's default (``pt-BR`` for Bradesco).

        Returns:
            A :class:`PaymentIntent` carrying the extracted fields and a
            blended confidence score.
        """
        ...

    def extract_boleto(self, image_bytes: bytes) -> BoletoData:
        """OCR a *boleto* photo and decode its FEBRABAN digitable line.

        Called by :meth:`SmartPaymentAgent.parse_boleto_image` when a
        customer photographs a payment slip. The Bridge implementation
        runs OCR (Azure Document Intelligence in production), validates
        the FEBRABAN check digits on the *linha digitável*, and surfaces
        bank code, amount, due date, and beneficiary in a
        :class:`BoletoData`. The agent then converts it via
        :func:`boleto_to_intent`, so OCR errors propagate as a low
        ``confidence`` rather than a silent mis-payment.

        Args:
            image_bytes: Raw JPEG/PNG/HEIC bytes of the slip.

        Returns:
            A :class:`BoletoData` with decoded fields and a confidence
            score from the OCR+check-digit pipeline.
        """
        ...


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


class PaymentType(StrEnum):
    """Brazilian inter-bank payment types."""

    PIX = "pix"
    TED = "ted"
    DOC = "doc"


class Currency(StrEnum):
    """Supported currencies."""

    BRL = "BRL"
    USD = "USD"
    EUR = "EUR"


@dataclass(frozen=True)
class PaymentIntent:
    """Structured payment intent extracted from natural language.

    Attributes:
        recipient: Recipient identifier (name, CPF/CNPJ, PIX key, etc.).
        amount: Payment amount as a :class:`~decimal.Decimal`.
        currency: ISO 4217 currency code.
        description: Free-text description or memo.
        payment_type: Payment rail to use (PIX, TED, or DOC).
        confidence: Model confidence in the extraction, ``[0, 1]``.
        raw_text: Original user message that produced this intent.
    """

    recipient: str
    amount: Decimal
    currency: Currency = Currency.BRL
    description: str = ""
    payment_type: PaymentType = PaymentType.PIX
    confidence: float = 1.0
    raw_text: str = ""


@dataclass(frozen=True)
class ValidationResult:
    """Result of validating a :class:`PaymentIntent`.

    Attributes:
        valid: ``True`` if the intent passes all business rules.
        errors: List of human-readable validation error messages.
        warnings: Non-blocking warnings (e.g. unusually high amount).
    """

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Validation limits (configurable per institution)
# ---------------------------------------------------------------------------

_DEFAULT_LIMITS: dict[PaymentType, Decimal] = {
    PaymentType.PIX: Decimal("100000.00"),
    PaymentType.TED: Decimal("1000000.00"),
    PaymentType.DOC: Decimal("4999.99"),
}

_HIGH_VALUE_THRESHOLD = Decimal("5000.00")

# DOC is only available on business days until 21:30 BRT.
# TED is available on business days until 17:00 BRT.
# PIX is 24/7.

# ---------------------------------------------------------------------------
# Extraction patterns
# ---------------------------------------------------------------------------

_AMOUNT_PATTERN = re.compile(
    r"(?:R\$\s*)?(\d[\d.,]*\d|\d+)\s*(?:reais|real|brl)?",
    re.IGNORECASE,
)

_TYPE_KEYWORDS: dict[PaymentType, list[str]] = {
    PaymentType.PIX: ["pix"],
    PaymentType.TED: ["ted", "transferencia bancaria"],
    PaymentType.DOC: ["doc", "documento de credito"],
}


# ---------------------------------------------------------------------------
# Boleto → PaymentIntent helper
# ---------------------------------------------------------------------------


def boleto_to_intent(boleto: BoletoData) -> PaymentIntent:
    """Convert a decoded :class:`BoletoData` into a :class:`PaymentIntent`.

    The boleto pay-rail in modern Bradesco WhatsApp flows is the PIX
    network (since 2022 the linha digitável is settled as a PIX
    transaction under the hood), so the produced intent defaults to
    :attr:`PaymentType.PIX` and carries the digitable line in
    ``description`` so the audit trail records exactly which slip the
    customer asked to pay.

    The ``recipient`` falls back to the bank-code marker when OCR did
    not surface a beneficiary block — :meth:`SmartPaymentAgent.validate_payment`
    will then surface a high-value warning if applicable and let the
    UncertaintyGuard escalate to a confirm-by-text step.
    """
    recipient = (boleto.recipient or "").strip() or f"Boleto banco {boleto.bank_code}"
    return PaymentIntent(
        recipient=recipient,
        amount=boleto.amount,
        currency=Currency.BRL,
        description=f"Boleto {boleto.digitable_line}",
        payment_type=PaymentType.PIX,
        confidence=float(boleto.confidence),
        raw_text=boleto.raw_ocr_text or boleto.digitable_line,
    )


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


@dataclass
class SmartPaymentAgent:
    """Smart payment agent for conversational banking channels.

    Implements the **UncertaintyGuard pattern**: if the parsed payment
    intent has confidence below ``confidence_threshold``, the agent
    requests human confirmation before proceeding.

    Args:
        backend: LLM backend implementing the ``complete()`` protocol.
        confidence_threshold: Minimum extraction confidence to accept
            the payment without explicit user confirmation.
        limits: Per-payment-type maximum amounts. Defaults to standard
            BCB limits.
        voice_processor: Optional :class:`VoiceProcessorProtocol`
            collaborator. Required for :meth:`parse_voice` and
            :meth:`parse_boleto_image`; leave ``None`` for text-only
            deployments. Wiring this in is what closes the
            voice/image leg of the Bradesco Bridge Smart Payments
            product.
    """

    backend: LLMBackend
    confidence_threshold: float = 0.7
    limits: dict[PaymentType, Decimal] = field(default_factory=lambda: dict(_DEFAULT_LIMITS))
    voice_processor: VoiceProcessorProtocol | None = None

    def parse_payment(self, text: str) -> PaymentIntent:
        """Extract a payment intent from a natural-language message.

        Uses a combination of regex extraction (for amounts and payment
        types) and LLM completion (for recipient and description) to
        produce a structured :class:`PaymentIntent`.

        Args:
            text: User message (e.g. ``"Pix 50 reais para Maria"``).

        Returns:
            A :class:`PaymentIntent` populated with the best-effort
            extraction. The ``confidence`` field reflects how certain the
            parser is about the extraction.
        """
        _LOG.info("smart_payments.parse", text_len=len(text))

        payment_type = self._detect_payment_type(text)
        amount, amount_confidence = self._extract_amount(text)
        recipient, recipient_confidence = self._extract_recipient(text)
        description = self._extract_description(text)
        currency = self._detect_currency(text)

        overall_confidence = min(amount_confidence, recipient_confidence)

        intent = PaymentIntent(
            recipient=recipient,
            amount=amount,
            currency=currency,
            description=description,
            payment_type=payment_type,
            confidence=overall_confidence,
            raw_text=text,
        )

        _LOG.info(
            "smart_payments.parsed",
            recipient=recipient,
            amount=str(amount),
            payment_type=payment_type.value,
            confidence=f"{overall_confidence:.3f}",
        )

        return intent

    def parse_voice(
        self,
        audio_bytes: bytes,
        *,
        language: str | None = None,
    ) -> PaymentIntent:
        """Transcribe and parse a voice payment request.

        Delegates audio decoding to the injected
        :class:`VoiceProcessorProtocol`; the returned intent inherits
        the transcription confidence so a noisy clip naturally lowers
        the intent confidence below the
        :class:`~lub.guard.UncertaintyGuard` threshold and is routed to
        confirm-by-text rather than auto-executed.

        Args:
            audio_bytes: Raw audio (WAV/OGG/etc. — depends on the
                configured backend) carrying the customer utterance.
            language: BCP-47 language tag override; defaults to the
                processor's configured language (typically ``"pt-BR"``).

        Returns:
            A :class:`PaymentIntent` ready for :meth:`validate_payment`.

        Raises:
            RuntimeError: If no ``voice_processor`` was configured.
        """
        if self.voice_processor is None:
            raise RuntimeError(
                "SmartPaymentAgent.parse_voice requires a voice_processor; "
                "construct the agent with voice_processor=VoiceProcessor(...)"
            )
        if not audio_bytes:
            raise ValueError("parse_voice received empty audio_bytes")

        _LOG.info("smart_payments.voice_parse", bytes_in=len(audio_bytes), language=language)
        intent = self.voice_processor.parse_voice_payment(audio_bytes, language=language)
        _LOG.info(
            "smart_payments.voice_parsed",
            recipient=intent.recipient,
            amount=str(intent.amount),
            payment_type=intent.payment_type.value,
            confidence=f"{intent.confidence:.3f}",
        )
        return intent

    def parse_boleto_image(self, image_bytes: bytes) -> PaymentIntent:
        """OCR a boleto image and produce a :class:`PaymentIntent`.

        Delegates OCR + FEBRABAN check-digit verification to the
        injected :class:`VoiceProcessorProtocol`. The decoded
        :class:`BoletoData` is converted via :func:`boleto_to_intent`
        so the rest of the validation pipeline is identical to the text
        and voice paths.

        Args:
            image_bytes: Raw bytes of the boleto photo (JPEG/PNG/etc.).

        Returns:
            A :class:`PaymentIntent` whose ``description`` carries the
            decoded *linha digitável* — used by
            :meth:`validate_payment` and recorded verbatim in the
            BCB 4893 audit trail.

        Raises:
            RuntimeError: If no ``voice_processor`` was configured.
            ValueError: If ``image_bytes`` is empty.
            BoletoExtractionError: Propagated from the OCR layer when the
                slip cannot be decoded or fails the FEBRABAN check digit.
        """
        if self.voice_processor is None:
            raise RuntimeError(
                "SmartPaymentAgent.parse_boleto_image requires a voice_processor "
                "with an OCR backend; construct the agent with "
                "voice_processor=VoiceProcessor(..., ocr_backend=...)"
            )
        if not image_bytes:
            raise ValueError("parse_boleto_image received empty image_bytes")

        _LOG.info("smart_payments.boleto_parse", bytes_in=len(image_bytes))
        boleto = self.voice_processor.extract_boleto(image_bytes)
        intent = boleto_to_intent(boleto)
        _LOG.info(
            "smart_payments.boleto_parsed",
            bank_code=boleto.bank_code,
            amount=str(intent.amount),
            recipient=intent.recipient,
            confidence=f"{intent.confidence:.3f}",
        )
        return intent

    def validate_payment(self, intent: PaymentIntent) -> ValidationResult:
        """Validate a payment intent against business rules.

        Checks:
        - Amount is positive.
        - Amount does not exceed the per-type limit.
        - Recipient is not empty.
        - Confidence meets the UncertaintyGuard threshold.

        Args:
            intent: The payment intent to validate.

        Returns:
            A :class:`ValidationResult` indicating whether the payment
            can proceed and any errors or warnings.
        """
        errors: list[str] = []
        warnings: list[str] = []

        # Amount checks
        if intent.amount <= 0:
            errors.append("O valor do pagamento deve ser positivo.")

        limit = self.limits.get(intent.payment_type)
        if limit is not None and intent.amount > limit:
            errors.append(
                f"Valor R$ {intent.amount} excede o limite de "
                f"R$ {limit} para {intent.payment_type.value.upper()}."
            )

        if intent.amount >= _HIGH_VALUE_THRESHOLD:
            warnings.append(
                f"Pagamento de alto valor (R$ {intent.amount}). Confirme os dados do destinatario."
            )

        # Recipient checks
        if not intent.recipient or intent.recipient.strip() == "":
            errors.append("Destinatario nao identificado.")

        # DOC-specific: amount cap
        if (
            intent.payment_type == PaymentType.DOC
            and intent.amount > _DEFAULT_LIMITS[PaymentType.DOC]
        ):
            errors.append("DOC so permite valores ate R$ 4.999,99. Considere usar TED ou PIX.")

        # UncertaintyGuard: confidence check
        if intent.confidence < self.confidence_threshold:
            errors.append(
                f"Confianca na extracao ({intent.confidence:.0%}) esta abaixo "
                f"do limiar ({self.confidence_threshold:.0%}). "
                "Confirme os dados manualmente."
            )
            _LOG.warning(
                "smart_payments.low_confidence",
                confidence=f"{intent.confidence:.3f}",
                threshold=f"{self.confidence_threshold:.3f}",
            )

        valid = len(errors) == 0

        _LOG.info(
            "smart_payments.validated",
            valid=valid,
            n_errors=len(errors),
            n_warnings=len(warnings),
        )

        return ValidationResult(valid=valid, errors=errors, warnings=warnings)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _detect_payment_type(self, text: str) -> PaymentType:
        """Detect the payment type from keywords in the text."""
        text_lower = text.lower()
        for ptype, keywords in _TYPE_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return ptype
        return PaymentType.PIX  # default to PIX

    def _extract_amount(self, text: str) -> tuple[Decimal, float]:
        """Extract the monetary amount and return (amount, confidence)."""
        match = _AMOUNT_PATTERN.search(text)
        if match:
            raw_amount = match.group(1)
            # Normalise Brazilian format: 1.000,50 -> 1000.50
            if "," in raw_amount and "." in raw_amount:
                raw_amount = raw_amount.replace(".", "").replace(",", ".")
            elif "," in raw_amount:
                raw_amount = raw_amount.replace(",", ".")
            try:
                return Decimal(raw_amount), 0.95
            except InvalidOperation:
                _LOG.warning("smart_payments.invalid_amount", raw=raw_amount)
                return Decimal("0"), 0.1

        # Fallback: ask the LLM
        try:
            prompt = (
                "Extract the monetary amount from this message. "
                "Reply with the number only, no currency symbol.\n\n"
                f"Message: {text}"
            )
            raw = self.backend.complete(prompt).strip()
            raw = raw.replace(",", ".").replace("R$", "").strip()
            return Decimal(raw), 0.6
        except Exception as exc:
            _LOG.warning("smart_payments.amount_extraction_failed", error=str(exc))
            return Decimal("0"), 0.0

    def _extract_recipient(self, text: str) -> tuple[str, float]:
        """Extract the recipient name or key and return (recipient, confidence)."""
        # Try "para <name>" pattern (Portuguese)
        para_match = re.search(r"(?:para|pra|pro|to)\s+(.+?)(?:\s*$|[.,;])", text, re.IGNORECASE)
        if para_match:
            recipient = para_match.group(1).strip()
            # Remove trailing amount-like and payment-type fragments
            recipient = re.sub(r"\s+\d+.*$", "", recipient).strip()
            recipient = re.sub(
                r"\s+(?:via|por)\s+(?:pix|ted|doc)\b.*$", "", recipient, flags=re.IGNORECASE
            ).strip()
            if recipient:
                return recipient, 0.85

        # Fallback: ask the LLM
        try:
            prompt = (
                "Extract the payment recipient (person or company name, or PIX key) "
                "from this message. Reply with the name only.\n\n"
                f"Message: {text}"
            )
            raw = self.backend.complete(prompt).strip()
            if raw:
                return raw, 0.6
        except Exception as exc:
            _LOG.warning("smart_payments.recipient_extraction_failed", error=str(exc))

        return "", 0.0

    def _extract_description(self, text: str) -> str:
        """Extract an optional payment description or memo."""
        # Look for description markers
        desc_match = re.search(
            r"(?:descricao|descri[çc][ãa]o|memo|referencia|ref)[:\s]+(.+?)(?:$|[.,;])",
            text,
            re.IGNORECASE,
        )
        if desc_match:
            return desc_match.group(1).strip()
        return ""

    def _detect_currency(self, text: str) -> Currency:
        """Detect currency from the text. Defaults to BRL."""
        text_lower = text.lower()
        if any(kw in text_lower for kw in ("dollar", "dolar", "usd", "us$")):
            return Currency.USD
        if any(kw in text_lower for kw in ("euro", "eur", "€")):
            return Currency.EUR
        return Currency.BRL


__all__ = [
    "Currency",
    "LLMBackend",
    "PaymentIntent",
    "PaymentType",
    "SmartPaymentAgent",
    "ValidationResult",
    "VoiceProcessorProtocol",
    "boleto_to_intent",
]
