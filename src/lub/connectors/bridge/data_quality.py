# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Data Quality (DQ) for the Bridge platform.

Banking AI has two distinct DQ checkpoints:

* **Input DQ** — before the platform spends a token on the query, reject
  malformed, suspicious, or out-of-policy inputs (empty queries, queries
  that look like prompt injection attempts, payloads exceeding length
  limits, suspect character distributions).
* **Output DQ** — before the answer is released to the customer, score
  the response for likely-correct shape (length, presence of expected
  fields, refusal text, hallucinated currency amounts, etc.).

DQ does *not* replace :class:`~lub.guard.UncertaintyGuard`. The guard
asks "is the *model* confident in this answer?". DQ asks "regardless of
model confidence, is the *answer* structurally sane?". A high-confidence
hallucination of "PIX free for PJ up to R$1M" passes the guard but
fails the DQ check that no currency amount in the output exceeds the
PIX limit for the customer's tier.

Both checkpoints emit :class:`DQResult` objects that the platform
threads into its audit trail — so a BCB 4893 reviewer can answer
"what input DQ rules ran on this rejected query?" in one query.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import structlog

__all__ = [
    "DQResult",
    "DQRule",
    "DQSeverity",
    "DQViolation",
    "DataQualityChecker",
    "default_input_rules",
    "default_output_rules",
]

_LOG = structlog.get_logger("lub.bridge.data_quality")


class DQSeverity(StrEnum):
    """Severity of a DQ violation.

    ``BLOCK``: stop the pipeline (input rejected, output suppressed).
    ``WARN``: continue but flag in audit trail for review.
    ``INFO``: record only; no behavioral change.
    """

    BLOCK = "block"
    WARN = "warn"
    INFO = "info"


@dataclass(frozen=True)
class DQViolation:
    """One rule that fired against the data being checked.

    ``message`` is the internal/audit description (what compliance reads).
    ``customer_message`` is the user-facing string the BFF can show as the
    rejection reply — usually a calmer, regulation-aware sentence that
    tells the customer *why* and *what to do next*. When ``None`` (the
    pre-v10 default), callers fall back to a generic rejection string.
    """

    rule_id: str
    severity: DQSeverity
    message: str
    field: str | None = None
    customer_message: str | None = None


@dataclass(frozen=True)
class DQResult:
    """Aggregated outcome of a :class:`DataQualityChecker` run."""

    passed: bool
    violations: tuple[DQViolation, ...]
    rules_evaluated: int

    @property
    def blocking_violations(self) -> tuple[DQViolation, ...]:
        """Return only the BLOCK-severity violations from this DQ run.

        Bridge's pipeline calls this at stages 1 (input DQ) and 7-ish
        (output DQ before release) to decide whether to short-circuit:
        a non-empty tuple means the platform must reject the query or
        suppress the answer rather than forwarding it downstream.

        Returns:
            Tuple of :class:`DQViolation` entries whose severity is
            :attr:`DQSeverity.BLOCK`, in the order the rules fired.
            Empty tuple if no BLOCK rule triggered.
        """
        return tuple(v for v in self.violations if v.severity == DQSeverity.BLOCK)

    @property
    def warning_violations(self) -> tuple[DQViolation, ...]:
        """Return only the WARN-severity violations from this DQ run.

        Bridge does not stop the pipeline for warnings, but the audit
        trail step (stage 9, BCB 4893 logging) records them so a
        compliance reviewer can later trace soft signals — e.g. a query
        with unexpected control chars that nonetheless got an answer.

        Returns:
            Tuple of :class:`DQViolation` entries whose severity is
            :attr:`DQSeverity.WARN`, in the order the rules fired.
            Empty tuple if no WARN rule triggered.
        """
        return tuple(v for v in self.violations if v.severity == DQSeverity.WARN)


@dataclass
class DQRule:
    """One rule the checker may evaluate against incoming data.

    ``predicate(value, context) -> bool`` — returns True when the rule
    is **violated** (i.e. data is BAD). Returning False means OK.

    ``description`` is internal — the audit-log / compliance-review
    string. ``customer_message`` (round-10 addition) is the user-facing
    rejection reply. Production banking UX wants a per-rule sentence
    that names the relevant law (LGPD/COAF/BCB) and tells the customer
    what to do next — generic "[Rejected by input DQ]" was unhelpful
    for both UX and SR 11-7 explainability.
    """

    rule_id: str
    severity: DQSeverity
    description: str
    predicate: Any  # Callable[[Any, dict], bool]
    field: str | None = None
    customer_message: str | None = None


# ---------------------------------------------------------------------------
# Default input rules — sized for Brazilian PT-BR banking queries
# ---------------------------------------------------------------------------

_PROMPT_INJECTION_PATTERNS = re.compile(
    # English markers
    r"(\bignore (previous|above)\b"
    # N?-? : "ignore the/your/all instructions" slipped through (only previous|above
    # was covered) — a near-identical probe to the blocked "ignore previous
    # instructions" was reaching the confidence path instead of dq_block.
    r"|\bignore\s+(the|all|your|prior|previous|any|these|those|my)?\s*instructions?\b"
    r"|\bsystem prompt\b|\bforget (everything|all)\b"
    r"|\bact as\b|\bjailbreak\b|\bDAN mode\b|\bdeveloper mode\b|\bprompt:\b|<\|im_start\|>"
    # N8-3 v8 review: PT-BR injection markers. EN-only coverage left a
    # P0 gap for a BR-banking chat (an attacker asking in PT was free).
    r"|\bignore (as|a|o)? *instru[cç][oõ]es?"
    r"|\besque[cç]a (tudo|as instru[cç][oõ]es|o que (foi|disseram))"
    r"|\brevele (o )?(prompt|sistema|instru[cç][oõ]es)"
    r"|\bmodo desenvolvedor\b|\bmodo de desenvolvimento\b"
    r"|\baja como\b|\bfinja (ser|que)\b"
    r"|\bprompt (original|do sistema)\b"
    r"|\blibere (as )?restri[cç][oõ]es\b|\bsem restri[cç][oõ]es\b)",
    re.IGNORECASE,
)

# Classic SQL injection signatures. Customer chat NEVER has a legitimate
# reason to contain DROP/UNION/TRUNCATE/SQL comment markers. Catches the
# B2 bug in v1 review where `'; DROP TABLE customers; --` passed DQ.
_SQL_INJECTION_PATTERNS = re.compile(
    r"(\bDROP\s+TABLE\b|\bTRUNCATE\b|\bUNION\s+(ALL\s+)?SELECT\b"
    r"|\bDELETE\s+FROM\b|\bINSERT\s+INTO\b|\bUPDATE\s+\w+\s+SET\b"
    r"|--\s|;\s*--|/\*|\*/|\bxp_cmdshell\b|\bEXEC\s*\()",
    re.IGNORECASE,
)

# B-NEW7 (v5 review): HTML/JS injection. Customer-chat queries have no
# legitimate need for <script>, javascript: URIs, or HTML event handlers.
# Block at input DQ so the LLM never sees them, the audit never logs them,
# and the UI never accidentally renders them.
_HTML_INJECTION_PATTERNS = re.compile(
    r"(<\s*script\b|</\s*script\s*>|javascript\s*:|on(?:click|error|load"
    r"|mouseover|focus|blur)\s*=|<\s*iframe\b|<\s*img\b[^>]+\bsrc\s*=)",
    re.IGNORECASE,
)


def _too_short(value: str, _ctx: dict[str, Any]) -> bool:
    return not value or len(value.strip()) < 2


def _too_long(value: str, _ctx: dict[str, Any]) -> bool:
    return len(value or "") > 2000


def _prompt_injection(value: str, _ctx: dict[str, Any]) -> bool:
    return bool(_PROMPT_INJECTION_PATTERNS.search(value or ""))


def _sql_injection(value: str, _ctx: dict[str, Any]) -> bool:
    return bool(_SQL_INJECTION_PATTERNS.search(value or ""))


def _html_injection(value: str, _ctx: dict[str, Any]) -> bool:
    return bool(_HTML_INJECTION_PATTERNS.search(value or ""))


# B-NEW-7/8 (v6 review): credential / secret leak. Customer chat NEVER has
# a legitimate reason to paste passwords, tokens, PINs, OTPs, API keys, JWTs,
# or private keys. Detect even loose "minha senha e X" phrasing so the input
# can be rejected before it lands in the audit trail in plaintext.
_CREDENTIAL_PATTERNS = re.compile(
    # Explicit secret markers + JWT/key shapes.
    r"(\b(senha|password|passwd|pwd|pin|otp|token|api[_-]?key|secret"
    r"|bearer|authorization)\b\s*[:=]?\s*\S"
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"  # JWT
    r"|-----BEGIN [A-Z ]*(PRIVATE|RSA|EC|OPENSSH) KEY-----"  # PEM private key
    r"|sk-[A-Za-z0-9]{20,}"  # OpenAI-style API key
    r"|AIza[A-Za-z0-9_-]{30,}"  # Google API key
    r"|AKIA[A-Z0-9]{16}"  # AWS access key id
    r")",
    re.IGNORECASE,
)


def _credential_leak(value: str, _ctx: dict[str, Any]) -> bool:
    return bool(_CREDENTIAL_PATTERNS.search(value or ""))


def _control_chars(value: str, _ctx: dict[str, Any]) -> bool:
    return any(ord(c) < 32 and c not in ("\n", "\t") for c in (value or ""))


def _excessive_special_chars(value: str, _ctx: dict[str, Any]) -> bool:
    if not value:
        return False
    special = sum(1 for c in value if not c.isalnum() and not c.isspace())
    return special / len(value) > 0.4


# ---------------------------------------------------------------------------
# v9 Part 2 — banking-specific compliance / security rules
# ---------------------------------------------------------------------------
# Each new rule BLOCKs the query (so the downstream pipeline returns
# ESCALATE) and prevents the LLM from ever seeing the dangerous content.
# Intent classification still happens elsewhere — these rules guarantee
# the *security* outcome (block + escalate) regardless of intent.
# R-INJECTION-PTBR from the SPRINT v9 spec is already covered above by
# _PROMPT_INJECTION_PATTERNS (the EN pattern was extended with PT-BR
# markers in N8-3 v8 review). The remaining 7 are added here.

# R-AGE — customer self-identifies as a minor (age < 18 in years).
_AGE_PATTERN = re.compile(r"\b(\d{1,2})\s*anos?\b", re.IGNORECASE)


def _minor_kyc(value: str, _ctx: dict[str, Any]) -> bool:
    for m in _AGE_PATTERN.finditer(value or ""):
        try:
            age = int(m.group(1))
            if 1 <= age < 18:
                return True
        except ValueError:
            continue
    return False


# R-AML-CASH — high-value cash operation paired with explicit "skip COAF"
# language. COAF (Lei 9.613) requires reporting cash operations >= R$30k;
# customers naming the threshold AND asking to bypass reporting is a hard
# escalate. Pure high-value amount without the bypass marker is handled
# upstream by intent_classifier "aml_review" — this is the explicit-intent
# variant.
_AML_CASH_PATTERN = re.compile(
    # round-10 self-flag: original pattern missed common phrasings the
    # validator hit. Widened verb list (transferir/enviar/mover/mandar),
    # value list (any number followed by mil/k/milhão, or 5+ raw digits),
    # and bypass list (não chamar atenção / sem aparecer / fora dos livros).
    r"(deposit[ao]r?|sacar|saque|movimentar?|transferir|transfer[êe]ncia"
    r"|enviar|mover|mandar|pass[ao]r?|passei|passou)"
    r".{0,60}(\d+\s*(?:mil|k|milh[ãa]o|milh[õo]es)|\d{4,}|"
    r"dinheiro\s*vivo|cash|esp[ée]cie|em\s*dinheiro)"
    r".{0,60}(sem\s*coaf|coaf\s*n[ãa]o|n[ãa]o\s*report|sem\s*report"
    r"|n[ãa]o\s*reportar|sem\s*reportar|driblar|escond|fugir\s*do"
    r"|sem\s*chamar\s*aten|sem\s*aparec|fora\s*dos\s*livros)",
    re.IGNORECASE,
)


def _aml_cash(value: str, _ctx: dict[str, Any]) -> bool:
    return bool(_AML_CASH_PATTERN.search(value or ""))


# R-SMURFING — fractioning / structuring transactions to stay under
# reporting thresholds.
_SMURFING_PATTERN = re.compile(
    # round-10 self-flag: original pattern missed "fazer varios PIX de 9k
    # para nao chamar atencao". Added count-modifier verbs (varios, multiplos,
    # fazer N de) and softened the bypass anchor.
    r"(quebrar|fracionar|dividir|partir|v[áa]rios|v[áa]rias|multiplos|m[úu]ltiplas"
    r"|fazer\s+v[áa]rios|fazer\s+v[áa]rias|fazer\s+\d+|"
    r"diversos|diversas|in[úu]meros|in[úu]meras)"
    r".{0,80}(pix|transfer[êe]ncia|transfer[êe]ncias|saque|saques|dep[óo]sito"
    r"|dep[óo]sitos|opera[çc][ãa]o|opera[çc][õo]es|pagamento|pagamentos)"
    r".{0,80}(n[ãa]o\s*chamar|n[ãa]o\s*acionar|coaf|reportar|denunc"
    r"|n[ãa]o\s*reportar|sem\s*reportar|sem\s*chamar|sem\s*aparec"
    r"|para\s*n[ãa]o)",
    re.IGNORECASE,
)


def _smurfing(value: str, _ctx: dict[str, Any]) -> bool:
    return bool(_SMURFING_PATTERN.search(value or ""))


# R-LARANJA — explicit mention of money-mule / nominee patterns.
_LARANJA_PATTERN = re.compile(
    r"(conta\s+laranja"
    r"|testa[\s-]*de[\s-]*ferro"
    r"|laranja\s+para\s+(receber|sacar|movimentar)"
    r"|usar\s+(conta|cpf|cnpj)\s+de\s+terceiro)",
    re.IGNORECASE,
)


def _laranja(value: str, _ctx: dict[str, Any]) -> bool:
    return bool(_LARANJA_PATTERN.search(value or ""))


# R-SOCIAL-ENG-URGENCIA — "golpe do parente em apuro": urgency + relative
# in distress. The classic Brazilian PIX scam pretext.
_SOCIAL_ENG_URGENCY = re.compile(
    r"(urgente|agora|imediato|r[áa]pido|emerg[êe]ncia)"
    r".{0,60}(filho|filha|m[ãa]e|pai|parente|familiar|sobrinho|av[óo])"
    r".{0,60}(sequestr|internad|hospital|acidente|preso|UTI|delegacia)",
    re.IGNORECASE,
)


def _social_eng_urgency(value: str, _ctx: dict[str, Any]) -> bool:
    return bool(_SOCIAL_ENG_URGENCY.search(value or ""))


# R-PHISHING-DOMAIN — known-bank brand name appearing in a URL with a
# suspicious TLD (free / cheap / commonly abused domains).
_PHISHING_DOMAIN = re.compile(
    r"(bradesco|ita[uú]|santander|nubank|caixa|banco\s*do\s*brasil"
    r"|inter|bb|original|safra|pan|next|c6)"
    r"[\w-]*"
    r"\.(tk|ml|ga|cf|xyz|top|click|link|live|fit|monster|bond|country|loan)",
    re.IGNORECASE,
)


def _phishing_domain(value: str, _ctx: dict[str, Any]) -> bool:
    return bool(_PHISHING_DOMAIN.search(value or ""))


# R-CROSS-CUSTOMER — query mentions an identifier (customer_id, CPF, CNPJ,
# bank-style cliente/cust/cli/customer-N) that doesn't match the session
# customer. Hardened 2026-05-18 after v11 found the original single regex
# (`customer_id=X` only) leaked saldo in 3/4 phrasings:
#   "saldo de demo-customer-99"         → matched no pattern → PASSTHROUGH
#   "saldo do CPF 12345678901"           → matched no pattern → FLAG/balance
#   "dados do cliente CLI-002"           → matched no pattern → REASK/general
#   "saldo do cliente demo-customer-99"  → ALREADY worked via another path
# Multi-pattern detector now covers all four. Comparison is normalized
# (lowercase + strip non-alphanumeric) so "demo-customer-99" ≠ session
# "demo-customer" but "Demo-Customer" == session "demo-customer".
# ctx must supply session "customer_id"; absent context = abstain (don't
# block legitimate queries that happen to mention IDs in unrelated text).
_THIRD_PARTY_ID_PATTERNS: list[re.Pattern[str]] = [
    # Explicit `customer_id=X` / `customer-id: X` syntax (original v9 rule).
    re.compile(
        r"customer[_-]?id\s*[:=]?\s*['\"]?([A-Za-z0-9_-]{3,64})['\"]?",
        re.IGNORECASE,
    ),
    # Bank-style customer-ID tokens with required prefix + digits. Requires
    # the digits so a plain "cliente" word doesn't trigger.
    re.compile(
        r"\b((?:demo[-_]customer|cliente|customer|cust|cli)[-_]\d{1,8})\b",
        re.IGNORECASE,
    ),
    # CPF formatted: 000.000.000-00
    re.compile(r"\b(\d{3}\.\d{3}\.\d{3}-\d{2})\b"),
    # CPF raw: exactly 11 contiguous digits, word-bounded so 12-digit
    # account numbers don't accidentally match.
    re.compile(r"\b(\d{11})\b"),
    # CNPJ formatted: 00.000.000/0000-00
    re.compile(r"\b(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\b"),
    # CNPJ raw: exactly 14 contiguous digits, word-bounded.
    re.compile(r"\b(\d{14})\b"),
]


def _normalize_id(s: str) -> str:
    """Lowercase + strip non-alphanumeric for stable equality compare."""
    return "".join(c for c in s.lower() if c.isalnum())


# v13 P0-5 self-reference fix: pattern catches "meu CPF é X" / "minha conta
# é X" / "sou X" so a customer authenticating with their own CPF in chat
# doesn't trip cross-customer. Captures the CPF/CNPJ in group 2; the value
# is added to the accepted-self set for this query only. Production should
# also pass `customer_cpf` / `customer_cnpj` in ctx so the comparison is
# canonical and not heuristic — this regex is the demo-mode fallback.
_SELF_IDENT_PATTERN = re.compile(
    r"\b(meu|minha|sou|eu\s+sou|m[eé])\b"
    r"(?:\s+\w+){0,3}\s*"
    r"(\d{3}\.?\d{3}\.?\d{3}-?\d{2}|\d{11}"
    r"|\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}|\d{14})",
    re.IGNORECASE,
)


def _cross_customer(value: str, ctx: dict[str, Any]) -> bool:
    """Block if query references an identifier that doesn't match the session.

    Session identity from ctx: ``customer_id`` is required; optional
    ``customer_cpf`` / ``customer_cnpj`` make the comparison canonical
    (recommended in production). v13 P0-5 added a self-reference
    heuristic — "meu CPF é X" adds X to the accepted-self set for this
    query only, so a customer self-identifying isn't blocked when ctx
    doesn't carry their CPF.
    """
    ctx = ctx or {}
    own_id = _normalize_id(str(ctx.get("customer_id") or ""))
    own_cpf = _normalize_id(str(ctx.get("customer_cpf") or ""))
    own_cnpj = _normalize_id(str(ctx.get("customer_cnpj") or ""))
    own_set = {x for x in (own_id, own_cpf, own_cnpj) if x}
    if not own_set:
        return False
    # Add any CPF/CNPJ adjacent to a self-identification marker to the
    # accepted set for this query. Heuristic; production should populate
    # ctx.customer_cpf directly from the authenticated profile.
    for m in _SELF_IDENT_PATTERN.finditer(value or ""):
        own_set.add(_normalize_id(m.group(2)))
    for pat in _THIRD_PARTY_ID_PATTERNS:
        for m in pat.finditer(value or ""):
            cand = _normalize_id(m.group(1))
            if cand and cand not in own_set:
                return True
    return False


# v13 P0-4 mass disclosure: query asks to enumerate / dump / export a
# collective banking dataset (clientes, contas, saldos, CPFs, dados).
# Catches at DQ before the LLM is invoked — saves ~30s per query and
# prevents the LLM from "helpfully" describing schemas. Two paths:
#   (a) verb + "todos|todas" + collective noun
#   (b) strong-action verb (dump/exportar/extrair) + database/sistema
# LGPD Art. 7 prohibits broad disclosure without explicit consent.
_MASS_DISCLOSURE_VERBS = (
    r"listar?|liste|listagem|dump(?:ar)?|exportar?|extrair?|baixar|"
    r"recuperar|me\s+passe|me\s+d[eê]|forne(?:cer|ça)"
)
_MASS_DISCLOSURE_TARGETS = (
    r"clientes?|contas?|saldos?|cpfs?|cnpjs?|dados?|usu[áa]rios?|"
    r"titulares?|registros?|tabelas?|database|banco\s+de\s+dados"
)
_MASS_DISCLOSURE_PATTERN = re.compile(
    # Path (a): action + (todos|todas) + collective
    r"\b(?:" + _MASS_DISCLOSURE_VERBS + r")\b"
    r"(?:\s+\w+){0,5}\s*"
    r"\b(?:todos|todas|all)\b"
    r"(?:\s+\w+){0,3}\s*"
    r"\b(?:" + _MASS_DISCLOSURE_TARGETS + r")\b"
    r"|"
    # Path (b): strong-action verb directly on database/sistema
    r"\b(?:dump(?:ar)?|exportar?|extrair?)\b"
    r"(?:\s+\w+){0,3}\s*"
    r"\b(?:database|banco\s+de\s+dados|sistema|tabelas?|clientes?|contas?|saldos?)\b",
    re.IGNORECASE,
)


def _mass_disclosure(value: str, _ctx: dict[str, Any]) -> bool:
    return bool(_MASS_DISCLOSURE_PATTERN.search(value or ""))


def default_input_rules() -> list[DQRule]:
    """Return the default input DQ rules for Bridge banking queries."""
    return [
        DQRule(
            "INPUT_EMPTY",
            DQSeverity.BLOCK,
            "Query is empty or too short to process",
            _too_short,
            field="query",
            customer_message=(
                "Nao recebi sua mensagem. Pode escrever o que voce precisa? "
                "Posso ajudar com saldo, transferencia, cartao ou outras "
                "operacoes da sua conta."
            ),
        ),
        DQRule(
            "INPUT_TOO_LONG",
            DQSeverity.BLOCK,
            "Query exceeds 2000 chars (likely abuse or bad UX)",
            _too_long,
            field="query",
            customer_message=(
                "Sua mensagem ficou muito longa (acima de 2000 caracteres). "
                "Pode resumir em uma ou duas frases o que precisa?"
            ),
        ),
        DQRule(
            "INPUT_PROMPT_INJECTION",
            DQSeverity.BLOCK,
            "Query contains known prompt-injection patterns",
            _prompt_injection,
            field="query",
            customer_message=(
                "Detectei padroes na sua mensagem que tentam alterar meu "
                "comportamento. Posso ajudar com saldo, transferencia, "
                "cartao ou outras operacoes regulares da sua conta."
            ),
        ),
        DQRule(
            "INPUT_SQL_INJECTION",
            DQSeverity.BLOCK,
            "Query contains classic SQL injection signatures (DROP/UNION/--/;)",
            _sql_injection,
            field="query",
            customer_message=(
                "Sua mensagem contem comandos tecnicos (SQL) que nao posso "
                "processar. Reformule em linguagem natural, por favor."
            ),
        ),
        DQRule(
            "INPUT_HTML_INJECTION",
            DQSeverity.BLOCK,
            "Query contains HTML/JS injection patterns "
            "(<script>, javascript:, on*= handlers, <iframe>, <img src=)",
            _html_injection,
            field="query",
            customer_message=(
                "Sua mensagem contem codigo HTML ou JavaScript. Reformule "
                "em texto simples, sem tags ou comandos."
            ),
        ),
        DQRule(
            "INPUT_CREDENTIAL_LEAK",
            DQSeverity.BLOCK,
            "Query contains credential-like patterns (senha/password/pin/otp/"
            "token/api_key/secret/bearer/JWT/private key) — customers must "
            "never paste secrets into chat",
            _credential_leak,
            field="query",
            customer_message=(
                "Por seguranca, NUNCA digite senha, PIN, token, codigo SMS "
                "ou qualquer credencial neste chat. O Bradesco jamais pede "
                "esses dados por aqui. Reformule sua pergunta sem incluir "
                "credenciais e troque a senha vazada agora pelo app."
            ),
        ),
        DQRule(
            "INPUT_CONTROL_CHARS",
            DQSeverity.WARN,
            "Query has unexpected control characters",
            _control_chars,
            field="query",
        ),
        DQRule(
            "INPUT_HIGH_SPECIAL_CHARS",
            DQSeverity.WARN,
            "Query is >40% special chars (suspect)",
            _excessive_special_chars,
            field="query",
        ),
        # v9 Part 2 — 7 banking-specific compliance rules (BLOCK → ESCALATE).
        DQRule(
            "INPUT_MINOR_KYC",
            DQSeverity.BLOCK,
            "Query indicates customer may be under 18 — requires legal guardian per BACEN KYC rules",
            _minor_kyc,
            field="query",
            customer_message=(
                "Para abertura ou movimentacao de conta de menor de idade, "
                "e necessaria a presenca de um responsavel legal (BACEN "
                "Resolucao 4.753 + CC Art. 5). Compareca a uma agencia "
                "com seu responsavel. Vou transferir voce para um atendente "
                "humano que pode orientar."
            ),
        ),
        DQRule(
            "INPUT_AML_CASH_BYPASS",
            DQSeverity.BLOCK,
            "Query asks to move high-value cash while bypassing COAF reporting (Lei 9.613)",
            _aml_cash,
            field="query",
            customer_message=(
                "Movimentacoes em especie acima de R$ 30.000 sao reportadas "
                "ao COAF (Lei 9.613/1998 + Circular BACEN 3.978). Nao posso "
                "ajudar a contornar esse reporte. Vou registrar este pedido "
                "e transferir para o time de prevencao a lavagem de dinheiro."
            ),
        ),
        DQRule(
            "INPUT_STRUCTURING",
            DQSeverity.BLOCK,
            "Query asks to fraction transactions to avoid reporting thresholds (smurfing)",
            _smurfing,
            field="query",
            customer_message=(
                "Fracionar valores em transacoes menores para evitar reportes "
                "ao COAF e crime (Lei 9.613/1998 Art. 1, smurfing). Vou "
                "registrar este pedido e transferir para compliance."
            ),
        ),
        DQRule(
            "INPUT_MONEY_MULE",
            DQSeverity.BLOCK,
            "Query explicitly references money-mule / nominee patterns (conta laranja, testa-de-ferro)",
            _laranja,
            field="query",
            customer_message=(
                "Operar conta em nome de terceiros (conta laranja, testa-de-"
                "ferro) e crime previsto na Lei 9.613/1998 e na Lei 12.850/"
                "2013. Nao posso prosseguir. Vou registrar este pedido e "
                "encaminhar para o time de prevencao a fraude."
            ),
        ),
        DQRule(
            "INPUT_SOCIAL_ENG_URGENCY",
            DQSeverity.BLOCK,
            "Query matches social-engineering pattern (urgency + relative in distress — classic PIX scam pretext)",
            _social_eng_urgency,
            field="query",
            customer_message=(
                "Detectei sinais classicos do 'golpe do parente em apuro' "
                "(urgencia + valor + emocao). ANTES de qualquer transferencia: "
                "(1) desligue, (2) ligue voce mesmo para o parente usando um "
                "numero ja salvo na sua agenda, (3) confirme em pessoa se "
                "possivel. O Bradesco nunca pede transferencia urgente por "
                "chat. Vou transferir para um atendente que pode validar."
            ),
        ),
        DQRule(
            "INPUT_PHISHING_DOMAIN",
            DQSeverity.BLOCK,
            "Query contains a URL with bank brand on a suspicious / commonly abused TLD",
            _phishing_domain,
            field="query",
            customer_message=(
                "O link na sua mensagem tem aparencia de banco mas usa um "
                "dominio comumente abusado para phishing. O Bradesco usa "
                "APENAS o dominio bradesco.com.br. NAO clique no link. Vou "
                "transferir para o time antifraude."
            ),
        ),
        DQRule(
            "INPUT_CROSS_CUSTOMER",
            DQSeverity.BLOCK,
            "Query references a customer_id that does not match the session customer (spoof attempt)",
            _cross_customer,
            field="query",
            customer_message=(
                "Voce so pode consultar dados da propria conta. Acesso a "
                "dados de outro CPF/CNPJ sem autorizacao explicita do "
                "titular viola a LGPD (Art. 7). Se voce e procurador ou "
                "representante legal, traga a documentacao a uma agencia. "
                "Vou transferir para um atendente que pode validar autorizacao."
            ),
        ),
        DQRule(
            "INPUT_MASS_DISCLOSURE",
            DQSeverity.BLOCK,
            "Query asks to enumerate or export multiple customers' data (mass disclosure / data exfiltration)",
            _mass_disclosure,
            field="query",
            customer_message=(
                "Nao posso fornecer listas em massa de clientes, contas, "
                "saldos ou CPFs do banco. A LGPD (Art. 7) exige base legal "
                "especifica para tratamento de dados de multiplos titulares; "
                "uma solicitacao de um cliente individual nao atende esse "
                "requisito. Para auditoria, compliance ou subpoena, esse "
                "pedido precisa passar pelo canal juridico do banco."
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# Default output rules — catch hallucinated amounts, refusals, etc.
# ---------------------------------------------------------------------------

_CURRENCY_AMOUNT = re.compile(r"R\$\s*([\d.,]+)")

# Reasonable per-query maximum amount a Bridge answer might quote.
# Higher amounts are suspect — flag for compliance review.
_HIGH_AMOUNT_THRESHOLD = 1_000_000  # R$ 1M

_REFUSAL_MARKERS = re.compile(
    r"\b(nao posso|nao tenho acesso|nao sei|sorry, i can't|i don'?t know)\b",
    re.IGNORECASE,
)


def _output_empty(value: str, _ctx: dict[str, Any]) -> bool:
    return not value or not value.strip()


def _output_too_short(value: str, _ctx: dict[str, Any]) -> bool:
    return len((value or "").strip()) < 5


def _output_hallucinated_amount(value: str, _ctx: dict[str, Any]) -> bool:
    for match in _CURRENCY_AMOUNT.finditer(value or ""):
        amt_text = match.group(1).replace(".", "").replace(",", ".")
        try:
            if float(amt_text) > _HIGH_AMOUNT_THRESHOLD:
                return True
        except ValueError:
            continue
    return False


def _output_refusal_pattern(value: str, _ctx: dict[str, Any]) -> bool:
    return bool(_REFUSAL_MARKERS.search(value or ""))


def default_output_rules() -> list[DQRule]:
    """Return the default output DQ rules for Bridge banking answers."""
    return [
        DQRule(
            "OUTPUT_EMPTY",
            DQSeverity.BLOCK,
            "Response is empty",
            _output_empty,
            field="answer",
        ),
        DQRule(
            "OUTPUT_TOO_SHORT",
            DQSeverity.WARN,
            "Response is suspiciously short (< 5 chars)",
            _output_too_short,
            field="answer",
        ),
        DQRule(
            "OUTPUT_HALLUCINATED_AMOUNT",
            DQSeverity.BLOCK,
            f"Response quotes an amount over R$ {_HIGH_AMOUNT_THRESHOLD:,} (likely hallucination)",
            _output_hallucinated_amount,
            field="answer",
        ),
        DQRule(
            "OUTPUT_REFUSAL",
            DQSeverity.INFO,
            "Response is a refusal — record for retraining signal",
            _output_refusal_pattern,
            field="answer",
        ),
    ]


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------


@dataclass
class DataQualityChecker:
    """Runs a configurable rule set against a value + context.

    Construct with the right rule set for each checkpoint::

        input_checker = DataQualityChecker(rules=default_input_rules())
        output_checker = DataQualityChecker(rules=default_output_rules())
    """

    rules: list[DQRule] = field(default_factory=list)

    def check(self, value: Any, context: dict[str, Any] | None = None) -> DQResult:
        """Evaluate all rules. ``passed`` is False iff any BLOCK fired."""
        ctx = context or {}
        violations: list[DQViolation] = []
        for rule in self.rules:
            try:
                if rule.predicate(value, ctx):
                    violations.append(
                        DQViolation(
                            rule_id=rule.rule_id,
                            severity=rule.severity,
                            message=rule.description,
                            field=rule.field,
                            customer_message=rule.customer_message,
                        )
                    )
            except Exception as exc:
                _LOG.warning(
                    "bridge.dq.rule_error",
                    rule_id=rule.rule_id,
                    error=str(exc),
                )

        passed = not any(v.severity == DQSeverity.BLOCK for v in violations)
        result = DQResult(
            passed=passed,
            violations=tuple(violations),
            rules_evaluated=len(self.rules),
        )
        _LOG.info(
            "bridge.dq.checked",
            passed=passed,
            blocking=len(result.blocking_violations),
            warnings=len(result.warning_violations),
            rules=len(self.rules),
        )
        return result
