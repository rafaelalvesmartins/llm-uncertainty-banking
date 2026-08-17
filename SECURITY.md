# Security Policy

> **Scope of this document.** This repository ships **two** things, and this
> policy covers both: (1) the **`lub` library** — a numpy + stdlib core for
> LLM/model-risk calibration, drift, and provenance evidence; and (2) the
> **`bridge-ui` demonstrator** — a FastAPI backend + Next.js dashboard that
> wraps the library into an operable governance console. The previous version of
> this file stated the project "does not run a server"; that is no longer true —
> `bridge-ui/backend` **is** a server, and its security posture is described in
> detail below.
>
> **Honesty note for evaluators (MRM / AI Governance).** This is a
> **pre-release, single-tenant demonstrator**, not a hosted product. It has
> **no** SOC 2 report, **no** independent penetration test, **no** SLA, **no**
> hosted SaaS offering, and **no** reference customer. Where a control is
> **planned but not built**, it is labelled **roadmap** and mapped to a phase in
> `bridge-ui/docs/PRODUCT_PLAN_V6.md`. Nothing below should be read as a claim
> that an unbuilt control exists. Do your diligence against the source — that is
> the point of an open-source evidence tool.

---

## 1. Supported versions

| Component | Version line | Support |
|---|---|---|
| `lub` library | `0.0.x` (pre-release) | Latest `main` only |
| `bridge-ui` backend/frontend | `0.2.0` (demonstrator) | Latest `main` on branch `product/bridge-platform` |

There is **no** long-term-support branch and **no** backported security fix
stream yet — the project is pre-1.0 and the public API/DB schema may change
between commits. Pin to a commit SHA for reproducibility; upgrade forward for
fixes.

---

## 2. Threat model (what this is, and what it defends)

### 2.1 Intended deployment

The demonstrator is designed to be run **single-tenant, on infrastructure the
operator controls** (a laptop, a VM, or an internal host behind the bank's own
network controls). The intended trust boundary is the operator's own perimeter:
TLS termination, network segmentation, identity federation, secret management,
and host hardening are **assumed to be provided by the deployer's environment**,
not by this repository. The backend does **not** ship a TLS listener and should
**not** be exposed directly to an untrusted network.

### 2.2 Assets

- **Audit trail** — the append-only, hash-chained record of every query decision
  (SQLite-persisted). Integrity is the primary asset.
- **Governed configuration** — change requests and applied policy overrides
  (SQLite), which alter runtime behaviour.
- **Evidence packages** — signed model-risk evidence exports.
- **Customer query text** — may contain PII; masked before it enters the audit
  trail.
- **Signing / auth keys** — ephemeral, in-process (see §3.4, §4.3).

### 2.3 In-scope threats (defended, to demonstrator grade)

- **Silent tampering of the audit record** → detected by the SHA-256 hash chain
  and the on-demand verifier (§3.3), including an at-rest edit of the SQLite file.
- **Trust-the-caller identity on governed changes** → closed **when
  `BRIDGE_AUTH=on`** by signature-bound identity + RBAC + segregation of duties
  (§3.2). **Left open, and explicitly flagged, when `BRIDGE_AUTH=off`** (the
  default) — see the honesty caveat in §3.2.
- **Unexpected data egress from an LLM call** → prevented by default via the
  demo-safe switch and local-only backends (§3.1).
- **PII leaking into the audit log** → mitigated by input masking before the
  audit append (§3.5).
- **Basic web hardening** → env-scoped CORS, baseline security headers, a
  per-caller rate limiter, and idempotency keys (§3.6).

### 2.4 Out-of-scope / NOT defended (know before you deploy)

- **Network transport security** — no TLS is shipped; terminate TLS at your edge.
- **Multi-tenant isolation** — the process is **single-tenant**; there is no
  `tenant_id` scoping on the stores yet (roadmap; `PRODUCT_PLAN_V6.md` Phase 3).
  Do **not** put two banks' data in one instance.
- **Externally verifiable timestamping** — evidence and audit entries are
  **process-verifiable, not externally time-bound** (§3.4). A KMS/HSM-held
  signing key and an RFC 3161 timestamp authority are **roadmap** (Phase 4),
  and **cannot be faked** — they are blocked on a real KMS/TSA the deployer
  provides.
- **Encryption at rest** — the SQLite stores are plaintext on disk; use
  filesystem/volume encryption you control.
- **A production identity store** — the demo credentials are hard-coded and
  **unhashed** (§3.2); this is not a user-management system.
- **Denial-of-service resilience at scale**, **supply-chain attestation of
  dependencies beyond pinning**, and **secrets management** — deployer
  responsibilities / roadmap.

---

## 3. Security posture of the `bridge-ui` server

Everything in this section is **implemented in the current code**. File
references are given so you can verify each claim directly.

### 3.1 No data egress with local backends (default)

The backend selects an LLM backend at startup with a **demo-safe master switch
that defaults ON** (`BRIDGE_DEMO_SAFE=on`). When on, it forces the deterministic
in-process `FakeBackend` — **no network call leaves the host**, and the governed
apply-executor refuses any real/send-capable binding
(`bridge-ui/backend/backends.py`, `is_demo_safe` / `_select_backend`).

When the operator opts into a real model, the default real backend is a **local
Ollama** endpoint (`http://localhost:11434`), so inference still stays on the
operator's host. There is **no** built-in call to any third-party hosted LLM
API. Combined with the library's **numpy + stdlib core**, the calibration /
evidence path is **air-gap runnable** — an auditor can re-run the numbers with
no outbound connectivity.

### 3.2 Authentication gate (`BRIDGE_AUTH`, default OFF) — real crypto, additive

Authentication is **real EdDSA (Ed25519) JWT**, not mock, and is **additive and
gated** (`bridge-ui/backend/routers/auth.py`):

- `POST /auth/token` exchanges credentials for an Ed25519-signed JWT
  (`sub` / `roles` / `iat` / `exp`, 1-hour TTL). Credentials are compared with
  `secrets.compare_digest`.
- `GET /auth/jwks` publishes the public key + auth status so a verifier can
  check tokens out of band.
- `verify_token` is a FastAPI dependency wired onto the three **governed-change**
  endpoints (`submit` / `decision` / `apply` in `routers/governance_changes.py`).
- When `BRIDGE_AUTH=on`: identity is **signature-bound** — `submitted_by` /
  `reviewer` / `applier` are derived from `token.sub`, the request-body strings
  are **ignored**, RBAC requires a `validator`/`admin` role to decide or apply,
  and segregation of duties compares two **verified** subjects.

> **Honesty caveat — the default is OFF.** With `BRIDGE_AUTH=off` (the shipped
> default, so the demo and CI run unauthenticated), the segregation-of-duties
> check compares **unverified request-body strings** — it is **defeatable by
> sending two different names** and is therefore **not** a cryptographically
> enforced control. The code says so at runtime: the API response carries
> `sod_enforced: false` and an explicit `sod_warning` telling the operator to
> set `BRIDGE_AUTH=on`. Treat an `off` deployment as a demo, not as an
> access-controlled system.
>
> **Not built (roadmap):** production/hashed user store, OIDC/SSO, MFA, refresh
> rotation, per-tenant scoping, and enforcing auth on `/query` and the rest of
> the surface (`PRODUCT_PLAN_V6.md` Phases 2–3).

### 3.3 Tamper-evident audit hash-chain

Every query decision is appended to an audit trail that is **hash-chained and
persisted** (`bridge-ui/backend/state/audit.py`):

- Each entry stores `(seq, prev_hash, hash)` where
  `hash = sha256(prev_hash || canonical_json_of_payload)`, so a verifier can
  replay the chain and detect any silent in-place edit.
- The chain is **persisted to SQLite (WAL mode)** so it survives a backend
  restart; on boot the full persisted chain is re-validated before it is
  trusted, and a chain found broken is **quarantined** (renamed) rather than
  silently continued.
- `GET /audit/verify?source=memory` re-hashes the live in-memory window;
  `GET /audit/verify?source=disk` re-validates **every persisted row**, catching
  an **at-rest / out-of-band edit** of `audit_entries` that the memory window
  alone cannot see (`bridge-ui/backend/routers/audit.py`).
- `POST /audit/tamper-test` demonstrates detection (mutates one entry, shows the
  verifier failing, then restores it).

> **Scope limit.** This is **integrity-evidence within the running system and
> its own SQLite store** — it proves *no entry was altered after it was
> written*. It does **not** prove *when* an entry was written to an external
> party (see §3.4), and it is not a substitute for a WORM / cold-storage archive
> under the deployer's retention control.

### 3.4 Evidence signing — process-verifiable, NOT externally time-bound

Model-risk evidence packages are signed with **Ed25519 over
`(content_sha256 | generated_at)`** and travel with the public key, so any
verifier can re-check them and detect a flipped byte
(`bridge-ui/backend/routers/evidence.py`, `/evidence/verify`).

> **The honest limit, stated the same way the code states it:** the signing key
> is an **ephemeral, per-process demo key**. The signature proves *content
> integrity* and *non-repudiation for whoever holds that process's private key*
> — it is **process-verifiable, but NOT externally time-bound**. Making the
> evidence **regulator-filable** requires a **managed/HSM-held signing key** and
> an **RFC 3161 timestamp from an external Timestamp Authority**. Both are
> **roadmap** (`PRODUCT_PLAN_V6.md` Phase 4), **gated on a KMS/TSA the bank
> provides**, and **cannot be faked**. The same caveat applies to the auth
> signing key in §3.2.

### 3.5 PII handling

Customer query text is passed through a data governor that **masks PII before
the audit append** (`_record_short_circuit` and the main `/query` path in
`server.py`), and the audit entry records `query_was_masked` / `pii_count`
rather than raw PII. Explanations are served under an LGPD Art. 20 framing. The
stores are **not** encrypted at rest by this software (§2.4).

### 3.6 Baseline web hardening

- **CORS** is env-scoped (`BRIDGE_CORS_ORIGINS`) with explicit methods/headers —
  not a blanket `*` — defaulting to localhost dev ports (`server.py`).
- **Security headers** (`X-Content-Type-Options: nosniff`, `X-Frame-Options:
  DENY`, `Referrer-Policy: no-referrer`) are set on every response.
- **Rate limiting** is per `customer_id` + channel (token bucket), and
  **idempotency keys** de-duplicate retried requests within a TTL.
- **`/docs`, `/redoc`, `/openapi.json`** are intentionally exposed for auditor
  inspection; disable them at your edge if you do not want them public.

---

## 4. Security posture of the `lub` library

### 4.1 Attack surface

The library is a set of pure-computation modules (calibration, drift, conformal
coverage, an append-only ledger, OSCAL/crosswalk reporting) over **numpy +
Python stdlib**. Standalone, it **does not open a network socket** and processes
only the data the caller passes to it.

### 4.2 Security-relevant areas

- **Deserialization** of benchmark data, cached results, and any TOML/JSON
  config the caller supplies — treat inputs as untrusted.
- **Third-party dependency vulnerabilities** — mitigated by pinning; there is
  **no** independent supply-chain attestation (roadmap).
- **The `lub.ledger`** — a durable, replayable audit log. It is **not**
  tamper-evident on its own: it has no hash chain or `verify()` API, and a
  direct SQL `UPDATE` to a recorded outcome is not detected. Tamper-evidence is
  provided by the **Bridge audit hash-chain** (`bridge-ui` `state/audit.py`:
  SHA-256 `prev_hash` links + boot-time chain validation), which carries the
  same *process-verifiable, not externally time-bound* limit as §3.4.

### 4.3 Keys

Any signing performed by the library or demonstrator uses **ephemeral,
in-process keys** unless the deployer wires in managed custody. No private key
is exported or written to disk by this software.

---

## 5. Reporting a vulnerability (coordinated disclosure)

**Please do NOT open a public GitHub issue for a security vulnerability.**

Report privately via **GitHub Security Advisories** on the repository, or contact
the maintainer directly (see the repository's `README` / commit authorship for
the current contact). PGP is not yet offered.

Please include:

- A description of the issue and its impact.
- Steps to reproduce (a proof-of-concept is ideal).
- The affected version or commit SHA.
- Any known mitigations or workarounds.

### 5.1 Coordinated-disclosure process & response targets

These are **good-faith targets for a solo, pre-release, open-source project** —
they are **not a contractual SLA** and there is no legal entity or paid support
behind them:

| Stage | Target |
|---|---|
| Acknowledgement of your report | within **7 calendar days** |
| Initial triage / severity assessment | within **14 calendar days** |
| Fix or documented mitigation for high-severity issues | **best effort**, coordinated with you |
| Public disclosure | **coordinated** — by mutual agreement, or **90 days** after acknowledgement, whichever comes first |

We support **coordinated disclosure**: we ask that you give us a reasonable
window to remediate before public disclosure, and in return we will credit you
(unless you prefer to remain anonymous) and keep you informed of progress. We
will not pursue legal action against good-faith security research conducted
within this policy. There is **no bug-bounty program** and **no monetary
reward** at this time.

---

## 6. What we will not claim

For the avoidance of doubt, and because over-claiming to a regulated buyer is
worse than under-claiming: this project does **not** currently have, and this
document does **not** assert, any of the following — a SOC 2 (or ISO 27001)
report, an independent third-party penetration test, a hosted/managed SaaS,
a service-level agreement, a legal entity, encryption at rest, multi-tenant
isolation, externally anchored timestamps, or a production identity store. Each
of these is either a **deployer responsibility** or a **roadmap item** tracked in
`bridge-ui/docs/PRODUCT_PLAN_V6.md`.
