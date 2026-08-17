# Bridge v6 — Production-Readiness Architecture (Merged Plan)

> Designed 2026-06-12 by a multi-agent design workflow (6 design agents + synthesis),
> grounded against the actual code on branch `product/bridge-platform`. Honest principle:
> never fake security; mark demo-grade clearly. Goal: first paying bank pilot.

**Key ground-truth correction the design surfaced:** `submitted_by` / `reviewer` arrive in
the **request body** (`SubmitRequest`/`DecisionRequest`), and the segregation-of-duties
check is a single string `==` (`governance_changes.py`). So today the SoD control is
**trust-the-caller** — defeatable by sending two different strings. Phase 1 fixes exactly
this by deriving both identities from a verified token.

## 1. Executive summary

Bridge today is an honest single-tenant demonstrator: real cryptographic primitives
(Ed25519 evidence signing, SHA-256 hash-chained audit) and real domain logic (uncertainty
guard, PII masking, SR 11-7 crosswalk), but with **trust-the-caller identity** — the
operator is a UI dropdown and the evidence key is generated per process. The road to a
paying pilot is **a trust-substrate program, not a feature program**: turn claimed identity
into verified identity, make per-tenant isolation systemic, and hand the signing key to
managed/HSM custody — without ever shipping mock auth dressed as real.

## 2. Target architecture

| Dimension | v5 (today) | v6 target (pilot) | v7+ (scale) |
|---|---|---|---|
| **Auth** | UI operator dropdown; `submitted_by`/`reviewer` are unverified body strings | Real credential → signed JWT (EdDSA); `Depends(verify_token)`; `sub` overrides body identity; RBAC analyst/validator/admin | OIDC/SSO, MFA, refresh rotation, PKCE |
| **Tenancy** | Implicit single tenant; global state | `tenant_id` from token via `ContextVar`; default `demo` when `BRIDGE_AUTH=off`; SQLite stores gain `tenant_id` + `WHERE` filter | DB-per-tenant / RLS if a bank demands physical isolation |
| **Persistence** | In-memory + 2 SQLite stores (audit hash-chain, change requests) | Keep SQLite (WAL); durable tables for users/sessions, settings-changelog, customer-memory; metrics/cache stay ephemeral | PostgreSQL + replica + PITR on HA need |
| **Security** | CORS `*` methods + credentials (localhost only); no TLS/headers; no auth | TLS at edge; tightened CORS; security headers; rate-limit per authed user; secrets from a manager | KMS/HSM signing key + RFC 3161 TSA; encryption-at-rest; external audit mirror |
| **Deploy** | `start-demo.sh`, uvicorn, local Ollama / FakeBackend | Containerized; runtime secret injection; CI gates; health + structured logs | Helm/GitOps, autoscale, Prometheus/Grafana SLOs, LLM pool |

## 3. Risk-ordered roadmap (by risk-if-shipped-without, not build order)

- **Phase 0 — Honest-config hardening (S).** Tighten CORS to env origins + explicit verbs (replace `["*"]`), security-headers middleware, move signing-key creation behind a `KeyManager` seam (still ephemeral, swappable), document `BRIDGE_AUTH=off`. Risk: trivial dev-flow breakage (keep localhost default).
- **Phase 1 — Real authentication, additive (S→M). ← smallest safe first slice.** `routers/auth.py`: `POST /auth/token` (credential → signed JWT), `verify_token` dependency, `GET /auth/jwks`. Wire governance endpoints to derive `submitted_by`/`reviewer` from `token.sub`. Gate behind `BRIDGE_AUTH` (off ⇒ demo/CI unchanged). Risk: token-handling/leak (reuse `cryptography`; log only `sub`; strip `Authorization`).
- **Phase 2 — RBAC + audit attribution (M).** Role claims; 403 on under-priv; audit stamps `authenticated_user`/`role`; SoD = approver `sub` ≠ submitter `sub`.
- **Phase 3 — Multi-tenant isolation (M→L).** `tenant_id` via `ContextVar`; `tenant_id` column on `audit_entries` + `change_requests` (backfill `demo`, recreate-table for `NOT NULL`); per-tenant in-memory accessors; `tenant_id` inside the signed evidence payload. Risk: a query missing `WHERE tenant_id=?` = cross-tenant leak (isolation tests + per-tenant hash-chain validation on migrate).
- **Phase 4 — Managed signing key + TSA (M, gated on bank KMS).** `KeyManager` against KMS/HSM (sign-only); versioned `key_id`; RFC 3161 timestamp. Makes evidence regulator-filable, not just process-verifiable.
- **Phase 5 — Durable persistence + retention (M).** Persist customer memory (LGPD Art. 20), settings-changelog, DQ/DG rollups; nightly retention (BCB 4.893 ~5yr); periodic disk-chain verify. Keep audit synchronous, batch the rest.
- **Phase 6 — Deploy/ops + SLOs (M).** Containerize, runtime secrets, CI gates, health/metrics, SLO dashboard. Containers + a single manifest is enough for one pilot (resist GitOps scope creep).

## 4. The smallest safe first slice (Phase 1)

Build an **additive** `/auth/token` + `verify_token` dependency, applied first only to the
two governance endpoints, leaving `BRIDGE_AUTH=off` (demo) fully working.

- `routers/auth.py`: `POST /auth/token` (credential → signed JWT with `sub`/`roles`/`exp`), `verify_token` dependency, `GET /auth/jwks`. Credentials compared with `secrets.compare_digest`.
- `governance_changes.py`: when authenticated, derive `submitted_by` (submit) and `reviewer` (decision) from `token.sub`, **ignoring** the body. The existing SoD `==` check then compares two *verified* subjects.
- Gate on `BRIDGE_AUTH`: `off` ⇒ `verify_token` yields no principal and the body fields are used (demo + CI keep passing); `on` ⇒ token required and identity is signature-bound.

**Why it's safe, not a liability:** real crypto (signed JWT, expiry enforced), not mock; the
demo path is explicitly labeled `off`; additive (no route contract removed — the 6 tabs keep
working); closes the single worst gap (defeatable SoD) honestly; small (the `cryptography`
dep is already imported; no DB migration; reversible; testable in isolation). It deliberately
does NOT yet remove the frontend operator dropdown, scope tenants, enforce `/query`, or add KMS.

## 5. What NOT to rush, and why

- **Multi-provider LLM failover** — largest effort, orthogonal to the moat; a pilot runs on the existing Ollama/FakeBackend seam. Defer to v7.
- **HSM/KMS + RFC 3161 TSA** — required for filable evidence but **blocked on the bank's KMS**; cannot be faked. Build the `KeyManager` seam now, wire real KMS when the bank provides it; until then label evidence exactly as the code does (process-verifiable, not externally time-bound).
- **Multi-tenant `NOT NULL` cutover** — SQLite can't `ALTER…MODIFY`; means recreate + backfill + per-tenant hash-chain re-validation. Its own phase with a dry-run + chain verify before/after — never bundled.
- **PostgreSQL migration** — unnecessary for a single-node pilot; SQLite-WAL meets BCB retention and the hash-chain is storage-agnostic. Trigger on real concurrency/HA need.
- **Forcing auth globally / removing the operator dropdown** — only after Phase 1's seam is proven and a login UX + role-aware UI exist; flipping `BRIDGE_AUTH` mandatory early bricks the dashboard and the prospect demo at once.
