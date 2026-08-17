# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for ``lub.connectors.bridge.data_governance``."""

from __future__ import annotations

from lub.connectors.bridge.data_governance import (
    DataClassification,
    DataGovernor,
    PIIType,
)


class TestPIIDetection:
    def setup_method(self) -> None:
        self.gov = DataGovernor()

    def test_detects_cpf(self) -> None:
        matches = self.gov.detect("Meu CPF e 123.456.789-10")
        assert any(m.pii_type == PIIType.CPF for m in matches)

    def test_detects_cnpj(self) -> None:
        matches = self.gov.detect("CNPJ da empresa 12.345.678/0001-90")
        assert any(m.pii_type == PIIType.CNPJ for m in matches)

    def test_detects_email(self) -> None:
        matches = self.gov.detect("Email cliente@bradesco.com.br")
        assert any(m.pii_type == PIIType.EMAIL for m in matches)

    def test_detects_account(self) -> None:
        matches = self.gov.detect("Minha conta 1234-5")
        assert any(m.pii_type == PIIType.ACCOUNT for m in matches)

    def test_detects_card(self) -> None:
        matches = self.gov.detect("Cartao 4111 1111 1111 1111 vencido")
        assert any(m.pii_type == PIIType.CARD for m in matches)

    def test_no_pii_in_clean_text(self) -> None:
        matches = self.gov.detect("Qual meu saldo?")
        # Saldo question alone has no PII
        assert len(matches) == 0

    def test_value_hash_not_plaintext(self) -> None:
        matches = self.gov.detect("CPF 123.456.789-10")
        assert all(len(m.value_hash) == 16 for m in matches)  # 8 bytes hex
        assert all("123.456" not in m.value_hash for m in matches)


class TestClassification:
    def setup_method(self) -> None:
        self.gov = DataGovernor()

    def test_cpf_marks_restricted(self) -> None:
        r = self.gov.govern("Meu CPF e 123.456.789-10")
        assert r.classification == DataClassification.RESTRICTED

    def test_account_marks_restricted(self) -> None:
        r = self.gov.govern("conta 5555-5")
        assert r.classification == DataClassification.RESTRICTED

    def test_email_marks_confidential(self) -> None:
        r = self.gov.govern("Email teste@email.com")
        assert r.classification == DataClassification.CONFIDENTIAL

    def test_financial_keyword_marks_internal(self) -> None:
        r = self.gov.govern("Quero ver meu saldo")
        assert r.classification == DataClassification.INTERNAL

    def test_generic_text_is_public(self) -> None:
        r = self.gov.govern("ola, tudo bem?")
        assert r.classification == DataClassification.PUBLIC


class TestMasking:
    def setup_method(self) -> None:
        self.gov = DataGovernor()

    def test_cpf_masked(self) -> None:
        r = self.gov.govern("CPF 123.456.789-10")
        assert "123.456.789-10" not in r.masked
        assert "REDACTED" in r.masked and "cpf" in r.masked

    def test_multiple_pii_all_masked(self) -> None:
        r = self.gov.govern(
            "CPF 123.456.789-10 email teste@email.com conta 1234-5"
        )
        assert "123.456.789-10" not in r.masked
        assert "teste@email.com" not in r.masked
        assert "1234-5" not in r.masked
        assert r.masked.count("REDACTED") == 3

    def test_no_pii_returns_original(self) -> None:
        r = self.gov.govern("ola")
        assert r.masked == "ola"

    def test_original_preserved_in_result(self) -> None:
        r = self.gov.govern("CPF 123.456.789-10")
        assert "123.456.789-10" in r.original


class TestSafeForExternalLLM:
    def setup_method(self) -> None:
        self.gov = DataGovernor()

    def test_public_always_safe(self) -> None:
        r = self.gov.govern("ola")
        assert r.safe_for_external_llm is True

    def test_internal_safe(self) -> None:
        r = self.gov.govern("Qual meu saldo?")
        assert r.safe_for_external_llm is True

    def test_restricted_with_pii_unsafe(self) -> None:
        r = self.gov.govern("CPF 123.456.789-10")
        assert r.safe_for_external_llm is False


class TestCredentialDetection:
    """Round-7 follow-up: credentials in the audit trail are worse than
    PII. These tests pin the regex behavior so future refactors don't
    regress credential masking."""

    def setup_method(self) -> None:
        self.gov = DataGovernor()

    def test_password_keyword_pt(self) -> None:
        r = self.gov.govern("minha senha e XYZ123 e quero saldo")
        assert any(m.pii_type == PIIType.CREDENTIAL for m in r.matches)
        assert "XYZ123" not in r.masked

    def test_password_keyword_en(self) -> None:
        r = self.gov.govern("my password is hunter2")
        assert any(m.pii_type == PIIType.CREDENTIAL for m in r.matches)
        assert "hunter2" not in r.masked

    def test_pin_keyword(self) -> None:
        r = self.gov.govern("meu pin do cartao e 4321")
        assert any(m.pii_type == PIIType.CREDENTIAL for m in r.matches)
        assert "4321" not in r.masked

    def test_otp_keyword(self) -> None:
        r = self.gov.govern("recebi o OTP 123456")
        assert any(m.pii_type == PIIType.CREDENTIAL for m in r.matches)
        assert "123456" not in r.masked

    def test_jwt_bare(self) -> None:
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOjEyMzR9.SflKxwRJSMeKKF2QT4f"
        r = self.gov.govern(jwt)
        assert any(m.pii_type == PIIType.CREDENTIAL for m in r.matches)
        assert jwt not in r.masked

    def test_jwt_inside_sentence(self) -> None:
        # Regression for the leak found in round 7: keyword "token" was
        # eating only up to the first dot, leaving subsequent JWT segments
        # visible.
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOjEyMzR9.SflKxwRJSMeKKF2QT4f"
        r = self.gov.govern(f"meu token e {jwt} por favor")
        assert any(m.pii_type == PIIType.CREDENTIAL for m in r.matches)
        # No segment of the JWT should survive in the masked output.
        for segment in jwt.split("."):
            assert segment not in r.masked

    def test_pem_private_key_bare(self) -> None:
        # The original regex required `[A-Z ]+` before PRIVATE, missing the
        # bare `BEGIN PRIVATE KEY` form.
        pem = "-----BEGIN PRIVATE KEY-----abcdef-----END PRIVATE KEY-----"
        r = self.gov.govern(pem)
        assert any(m.pii_type == PIIType.CREDENTIAL for m in r.matches)
        assert "abcdef" not in r.masked

    def test_pem_rsa_private_key(self) -> None:
        pem = "-----BEGIN RSA PRIVATE KEY-----xyz-----END RSA PRIVATE KEY-----"
        r = self.gov.govern(pem)
        assert any(m.pii_type == PIIType.CREDENTIAL for m in r.matches)

    def test_openai_sk_key_short(self) -> None:
        # Round-7 regression: the original {20,} length floor let the PHONE
        # regex steal the digits in shorter sk- keys, producing the falsely-
        # reassuring partial mask `sk-[[REDACTED]:phone]abcdef`.
        r = self.gov.govern("sk-1234567890abcdef")
        assert any(m.pii_type == PIIType.CREDENTIAL for m in r.matches)
        # Make sure phone didn't win.
        assert not any(m.pii_type == PIIType.PHONE for m in r.matches)
        assert "1234567890abcdef" not in r.masked

    def test_openai_sk_key_inline(self) -> None:
        r = self.gov.govern("minha api key sk-1234567890abcdef ok")
        assert any(m.pii_type == PIIType.CREDENTIAL for m in r.matches)
        assert "1234567890abcdef" not in r.masked

    def test_bearer_token(self) -> None:
        r = self.gov.govern("Bearer xyz123abc")
        assert any(m.pii_type == PIIType.CREDENTIAL for m in r.matches)
        assert "xyz123abc" not in r.masked

    def test_aws_akia_key(self) -> None:
        r = self.gov.govern("AKIAIOSFODNN7EXAMPLE")
        assert any(m.pii_type == PIIType.CREDENTIAL for m in r.matches)

    def test_github_pat(self) -> None:
        r = self.gov.govern("github_pat_aaaaaaaaaaaaaaaaaaaaaaaaaa")
        assert any(m.pii_type == PIIType.CREDENTIAL for m in r.matches)

    def test_credential_marks_restricted(self) -> None:
        # Credentials should classify the message as RESTRICTED so it never
        # leaves the BFF for an external LLM in plaintext.
        r = self.gov.govern("Bearer xyz123abc")
        assert r.classification == DataClassification.RESTRICTED
        assert r.safe_for_external_llm is False

    def test_innocent_banking_query_clean(self) -> None:
        # Negative tests — these must NOT trigger credential detection.
        for query in (
            "qual meu saldo de hoje",
            "Pagar 150 via PIX pro Joao",
            "Qual posicao do BCB sobre tributacao PIX para PJ?",
            "Quero ver meu extrato dos ultimos 30 dias",
        ):
            r = self.gov.govern(query)
            assert not any(
                m.pii_type == PIIType.CREDENTIAL for m in r.matches
            ), f"false positive credential on: {query}"


class TestLineage:
    def setup_method(self) -> None:
        self.gov = DataGovernor()

    def test_lineage_has_single_entry(self) -> None:
        r = self.gov.govern("test", step="input")
        assert len(r.lineage) == 1
        assert r.lineage[0].step == "input"

    def test_prior_lineage_chained(self) -> None:
        r1 = self.gov.govern("CPF 123.456.789-10", step="input")
        r2 = self.gov.govern(r1.masked, step="post_mask", prior_lineage=r1.lineage)
        assert len(r2.lineage) == 2
        assert [e.step for e in r2.lineage] == ["input", "post_mask"]

    def test_lineage_records_pii_count(self) -> None:
        r = self.gov.govern("CPF 123.456.789-10 e email a@b.com")
        assert r.lineage[0].pii_count == 2

    def test_lineage_records_classification(self) -> None:
        r = self.gov.govern("CPF 123.456.789-10")
        assert r.lineage[0].classification == DataClassification.RESTRICTED
