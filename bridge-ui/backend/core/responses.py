# Copyright 2026 Rafael Martins Alves — Apache-2.0
"""Canned response templates (decoupling step 6a).

Pure immutable data — the safety/banking canned answers. Extracted VERBATIM from server.py
so BOTH server.py (the agents + _answer that stay there) and the backends module can import
it without a circular `import server`. server.py re-exports it; behaviour identical.

The customer-facing copy is in English for the bilingual demo; Brazilian regulatory
references (CVV 188, COAF, LGPD, BACEN, Bradesco channels, official domains) are kept
verbatim because they are proper nouns / real contact points.
"""

from __future__ import annotations

_RESPONSES = {
    "balance": "Your current balance is R$ 12,450.32 in your checking account.",
    "transfer": "To make a transfer, I need the amount, the recipient, and the type (PIX/TED/DOC).",
    "loan": "We offer personal loans from 1.99% per month. Would you like a simulation?",
    "complaint": "I'm sorry for the inconvenience. I'll log your complaint.",
    "card": "Your current bill is R$ 3,240.15. Would you like to pay it now?",
    "card_fraud": (
        "I detected a report of fraud/cloning on your card. "
        "I'm preemptively blocking it and transferring you to our 24h "
        "anti-fraud team. You won't be charged for the disputed transactions."
    ),
    "pix": "To send a PIX, please give me the recipient's key and the amount.",
    "account_help": (
        "To reset your password, use 'Forgot password' in the app or at bradesco.com.br, "
        "or call 4002-0022. For your security, Bradesco never asks for your full password "
        "or any code by phone, SMS, or WhatsApp."
    ),
    "general": "How can I help you today? I can check your balance or make transfers.",
    # v7 review G1 — crisis / mental-health signal. Bank-channel is often
    # the first place crisis appears ("last balance", "close account").
    "crisis": (
        "I sense that you're going through a very hard time. "
        "You don't have to face this alone — call the CVV at 188 "
        "(free, 24h) or visit cvv.org.br. I'm transferring you now "
        "to a person on our team. We're with you."
    ),
    # v7 review G2 — social-engineering proactive alert (fake-employee /
    # fake SMS support scam).
    "social_engineering": (
        "Warning: Bradesco will NEVER ask for an SMS code, password, or token "
        "by phone, WhatsApp, or email. If you received such a request, do NOT "
        "share the code and hang up. Confirm only through the official call "
        "center: 4002-0022 (capitals) or 0800-704-8383. I'm logging this "
        "report and transferring you to the anti-fraud team."
    ),
    # v8 review G2.b — urgency + family-emergency scam ("relative-in-trouble").
    "urgency_scam": (
        "STOP. This is the classic 'relative-in-trouble scam' pattern. "
        "NEVER transfer money in urgent situations without first calling the "
        "family member on a known number. Verify in person. "
        "Bradesco anti-fraud: 0800-704-8383. I'm logging the alert."
    ),
    # v8 review G2.c — phishing / look-alike domain.
    "phishing": (
        "Warning: domains like bradesco-X.tk/.ml/.ga/.cf/.xyz are NOT "
        "Bradesco's. The official domain is bradesco.com.br. Do NOT click the "
        "link, do NOT share any code. Use only the official app or "
        "bradesco.com.br. I'm logging this report with the anti-fraud team."
    ),
    # v8 review G1.b — minor / age gate.
    "age_minor": (
        "For customers under 18, opening an account requires a legal guardian "
        "and additional documentation (KYC). I can transfer you to an agent "
        "who handles that flow, or you can visit a branch with your guardian."
    ),
    # v8 review G1.c / G10.b — AML / cash structuring / smurfing / straw man.
    "aml_suspect": (
        "Transactions that try to avoid COAF reporting, split amounts, or use "
        "third parties to receive funds are blocked and reported. If your "
        "intent was legitimate, I can direct you to the compliance team to "
        "regularize it — bring documentation (source of funds, contract, invoice)."
    ),
    # v7 review G10 — illegal activity advisory. Refuse + redirect, never
    # provide guidance.
    "illegal_activity": (
        "I can't advise on that practice. If you have questions about "
        "taxation, I recommend consulting the Receita Federal (receita.fazenda.gov.br) "
        "or your accountant. If you'd like, I can help you with your balance, "
        "transfers, or other regular account operations."
    ),
    # v7 review G5 — query in another language. The demo handles PT and EN;
    # anything else gets a brief bilingual ask to rephrase.
    "non_pt": (
        "This service is currently available in Portuguese and English. "
        "Could you rephrase your question in one of those languages? "
        "(Este atendimento está disponível em português e inglês — "
        "reformule em português ou inglês.)"
    ),
    # AML / structured cash deposits — large-cash trigger (R$30k+ in
    # specie is a PCD signal; R$50k+ is COAF mandatory reporting).
    "aml_review": (
        "Cash transactions above R$ 30,000 require compliance review (PCD) "
        "before execution. I'll log this and route it to the anti-money-"
        "laundering team — you'll be contacted within 24 business hours with "
        "the required documentation."
    ),
    # round-7 — request for data about a third party. LGPD Art. 7 requires
    # explicit consent of the data subject for personal-data treatment.
    "third_party_data": (
        "I can't provide another person's account information. The LGPD "
        "(Art. 7) requires the data subject's explicit consent to process "
        "personal data. If you're an attorney-in-fact or legal representative, "
        "bring the documentation to a branch. I'll transfer you now to an "
        "agent who can validate the authorization."
    ),
    # B-NEW-13 (round 10) — urgency manipulation / social-engineering scam.
    # Pattern: pressure language + family emergency + transfer ask.
    # Anti-fraud guidance: never act on urgency; always verify out-of-band.
    "urgency_manipulation": (
        "I detected signs of unusual urgency in this request. For your safety, "
        "I'll connect you with a human agent to validate your identity and the "
        "transaction before proceeding. Scammers often use family-emergency "
        "stories to pressure transfers — NEVER share codes, passwords, or "
        "authorize transfers under pressure. If it's a real emergency, "
        "call 4002-0022 or go to a branch."
    ),
    # round-7 — attempt to manually alter balance/account state. Social-
    # engineering of the chatbot; route to security team.
    "account_manipulation": (
        "I detected an attempt to manually change a balance or account. Only "
        "regular operations (deposit, transfer, PIX) change a balance, and "
        "they require the account holder's authentication. I'll log this "
        "contact and transfer you to the security team."
    ),
    # round-7 — privilege-escalation attempt (sudo / admin / root). Customer-
    # facing chatbot has no admin surface; this is either an attack probe
    # or a confused internal user — both warrant logging + human review.
    "privilege_escalation": (
        "Administrative operations require specific credentials, separate from "
        "customer service. This channel has no administrative privileges. "
        "I'll log this contact and transfer you to an agent."
    ),
    # v10 P3 — prompt-leak / system-prompt exfiltration. Refuse, do not
    # echo any portion of the system prompt or instructions, and escalate.
    # Tone is neutral (no shaming) — the customer may be a curious dev
    # rather than an attacker, but the answer is the same either way.
    "prompt_leak": (
        "I can't share internal instructions, system configuration, or the "
        "content of my prompt. This channel is exclusively for banking "
        "service. I'll log this request and transfer you to an agent in case "
        "you have a legitimate question."
    ),
    # round-7 — discrimination question. Institutional response with
    # explicit legal basis. Escalate so a human attendant follows up
    # (compliance reporting + relationship recovery).
    "discrimination": (
        "Bradesco serves all customers without distinction of race, color, "
        "religion, gender, sexual orientation, or origin (Federal Constitution "
        "Art. 5 + Law 7.716/1989 + institutional policy). I'm transferring you "
        "to an agent for any further detail or to file a formal report."
    ),
    # round-10 P1 — strong profanity / "I want a manager" frustration. Do NOT
    # moralize about language; acknowledge frustration as legitimate, route
    # to human immediately, and surface the Ombudsman as the regulated
    # escalation path (BACEN Resolution 4.860).
    "complaint_escalated": (
        "I can see you're very frustrated, and that frustration is legitimate. "
        "I'll transfer you immediately to a human agent. If that doesn't "
        "resolve it, you have the right to file a formal complaint with the "
        "Bradesco Ombudsman (a channel regulated by BACEN, Resolution 4.860, "
        "with a response within 10 business days). I'm logging your request. "
        "Please hold a moment."
    ),
}


__all__ = ["_RESPONSES"]
