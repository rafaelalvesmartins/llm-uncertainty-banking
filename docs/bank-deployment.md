# Deploying `lub` / Bridge Inside a Bank — Procurement & InfoSec Guide

> **What this page is.** A straight, InfoSec-facing description of how a bank or
> insurer can stand up `llm-uncertainty-banking` (`lub`) and its **Bridge**
> console **inside its own VPC**, what runs with **zero network egress**, what
> each optional cloud adapter transmits if you turn it on, and — bluntly — what
> is **built vs. what is roadmap**. It follows the same scope-honesty convention
> as [`docs/sr-11-7.md`](sr-11-7.md): claim only what the code does, and name the
> gaps.
>
> **Read this first (posture in one paragraph).** `lub` is an Apache-2.0
> open-source library plus a **single-tenant, self-hosted** demonstrator console
> (Bridge). You run it on your own infrastructure; there is **no hosted SaaS, no
> multi-tenant service, and no vendor-operated endpoint** in this repository. The
> calibration/evidence core is **pure `numpy` + Python stdlib** and runs
> **air-gapped**. The Bridge console defaults to a deterministic offline backend
> with **no outbound calls**. Everything below distinguishes what is real today
> from what is a documented seam or roadmap item — because a bank does diligence,
> and over-claiming here would be both a procurement failure and a
> misrepresentation.

---

## 0. Honest scope banner (do not skip)

The following are **NOT true today** and are stated so you don't have to ask:

- **No SOC 2 report** (Type I or II). None has been performed or is in progress.
- **No independent penetration test** on record. None commissioned.
- **No SLA, no support contract, no legal entity, no hosted service.** This is an
  open-source project (Apache-2.0), maintained by an individual author.
- **No reference customer / no production bank deployment** to cite.
- **No SSO/OIDC, no KMS/HSM integration, no multi-tenant isolation** shipped.
  These are **bring-your-own seams** (SSO/KMS) or **roadmap** (tenancy),
  described in §3–§4. They are deliberately built as swappable interfaces so you
  can front them with *your* IdP and *your* KMS — but the integrations themselves
  are not done.

What **is** real and verifiable in the code today: air-gap-runnable evidence
core (numpy+stdlib), deterministic offline backend, local-LLM (Ollama) option,
EdDSA-signed evidence + SHA-256 hash-chained audit trail on SQLite, a real (but
**demo-grade**) EdDSA-JWT auth path that is **off by default**, env-driven CORS,
and baseline security headers.

---

## 1. Air-gapped / VPC deployment topology

### 1.1 What runs with ZERO network egress

The following configuration makes **no outbound network calls** and is suitable
for an air-gapped VPC subnet or an isolated validation enclave:

```
┌──────────────────────────── Your VPC (no egress) ────────────────────────────┐
│                                                                               │
│   Analyst / MRM browser ──TLS──▶ [ Your reverse proxy / IdP ]                 │
│                                        │  (you provide: TLS, OIDC, WAF)        │
│                                        ▼                                       │
│                          ┌─────────────────────────────┐                      │
│                          │  Bridge frontend (Next.js)   │  BFF proxy only      │
│                          └──────────────┬──────────────┘                      │
│                                         ▼ (in-VPC HTTP)                        │
│                          ┌─────────────────────────────┐                      │
│                          │  Bridge backend (FastAPI)    │                      │
│                          │  - FakeBackend (deterministic, canned) ← default    │
│                          │  - lub core: numpy + stdlib (no torch/sklearn)      │
│                          │  - Ed25519 evidence signing (ephemeral key)         │
│                          │  - SHA-256 hash-chained audit                       │
│                          └───────┬───────────────┬──────┘                      │
│                                  ▼               ▼                             │
│                     ┌────────────────┐   ┌───────────────────────────┐        │
│                     │ SQLite (WAL)   │   │ (optional, in-VPC only)    │        │
│                     │ audit chain,   │   │ Ollama @ localhost:11434   │        │
│                     │ change reqs,   │   │ local open-weights LLM     │        │
│                     │ visibility     │   │ (no internet needed once   │        │
│                     └────────────────┘   │  the model is pulled)      │        │
│                                          └───────────────────────────┘        │
│                                                                               │
│   NO connection leaves this box: no telemetry, no license call-home,          │
│   no cloud LLM, no analytics.                                                 │
└───────────────────────────────────────────────────────────────────────────────┘
```

**How zero-egress is enforced in code (verifiable):**

| Control | Mechanism | Default |
|---|---|---|
| Force deterministic offline backend | `BRIDGE_DEMO_SAFE=on` → `_select_backend()` returns `FakeBackend` and refuses any real/send-capable binding | **ON** (`backends.py`) |
| Never probe/dial a real LLM | `BRIDGE_USE_REAL_LLM=off` → always `FakeBackend`, no HTTP attempt | opt-in; `auto` only probes **localhost** Ollama |
| Local LLM stays local | Ollama backend calls `OLLAMA_URL` (default `http://localhost:11434`) only | in-VPC by construction |
| No cloud keys ⇒ no cloud adapters | OpenAI/Anthropic visibility adapters register **only when their env key is set**; otherwise the offline `FakeVisibilityAdapter` is used | keys **unset** by default |
| Evidence/calibration math | `lub.calibration`, `lub.evidence` are **numpy + stdlib only** (no torch, no sklearn, no network) | always |
| Persistence | Local **SQLite** file(s) (WAL) — audit hash-chain, change requests, visibility history | local file |

> To run the analytical core with **no server at all**, use `lub` as a library /
> CLI (`lub benchmark`, `lub report`) against the `dummy` backend — see the
> Tier-1 guide's executable dummy-backend example
> ([`docs/deployment/tier-1-systemically-important.md`](deployment/tier-1-systemically-important.md)).
> This is the fully hermetic, air-gap path an MRM engineer can validate before
> pointing anything at a model.

### 1.2 What each OPTIONAL cloud backend transmits (opt-in, off by default)

Turning on a cloud LLM is **your choice and your data-egress decision**. When
enabled, here is what leaves your VPC:

| Backend | Enabled by | What is transmitted off-VPC | Data-residency note |
|---|---|---|---|
| `FakeBackend` (default) | — | **Nothing.** Canned responses. | Stays in VPC. |
| Ollama (local) | `BRIDGE_DEMO_SAFE=off` + reachable local Ollama | **Nothing off-VPC** (localhost HTTP to your own Ollama). One-time model pull happens out-of-band, before air-gapping. | Stays in VPC. |
| OpenAI adapter | `OPENAI_API_KEY` set (+ demo-safe off) | Prompt/query text + parameters to OpenAI's API endpoint | Egresses to OpenAI; subject to OpenAI's terms/residency. |
| Anthropic adapter | `ANTHROPIC_API_KEY` set (+ demo-safe off) | Prompt/query text + parameters to Anthropic's API endpoint | Egresses to Anthropic; subject to Anthropic's terms/residency. |
| HF / vLLM (library-side) | configured in `lub` pipeline | HF: model weights pulled from Hub unless pre-cached; vLLM: stays in-VPC if you host the server | vLLM in-VPC; HF Hub pull is out-of-band. |

**Rule of thumb:** *No cloud key set + `BRIDGE_DEMO_SAFE=on` (or `Ollama`) =
nothing leaves your VPC.* Cloud adapters are **opt-in switches**, never on by
default, and never accept a key pasted into the browser — keys are **server-side
env only** (see `routers/integrations.py`: "no credential ever touches the
browser").

---

## 2. One-page data-flow description

**All data stays in your VPC by default. Cloud adapters are opt-in and off.**

1. **Ingress.** A user request reaches the Bridge frontend through **your** edge
   (reverse proxy / load balancer / IdP). TLS termination, WAF, and
   authentication at the edge are **your responsibility** — the app does not
   terminate TLS itself.
2. **BFF proxy.** The Next.js frontend forwards to the FastAPI backend over
   in-VPC HTTP (`BRIDGE_API_URL`, default `http://localhost:8000`). No
   third-party call.
3. **Guarded pipeline.** The backend runs the request through the uncertainty
   guard, PII masking, and intent classification. Safety-critical intents are
   **always** served from canned responses — the LLM is never allowed to
   improvise on them, regardless of backend.
4. **Model call.** By default this hits `FakeBackend` (no network). If you opted
   into Ollama, it hits your **local** Ollama. If — and only if — you set a cloud
   key and disabled demo-safe, the configured cloud adapter transmits the prompt
   to that provider. This is the **only** path that egresses data, and it is
   off by default.
5. **Evidence + audit.** Each governed decision is recorded in a **SHA-256
   hash-chained** audit trail and, where applicable, signed with **Ed25519**.
   Persistence is **local SQLite (WAL)** by default. The chain is **replayable
   and tamper-evident** (`GET /audit/verify`).
6. **Egress.** **None** unless (4) uses a cloud adapter. No telemetry, no
   license check, no analytics call-home exists in the code.

**Data-at-rest:** local SQLite file(s) on your volume. Disk encryption is
**your infrastructure's job** (e.g. LUKS / cloud-provider EBS encryption).
Application-level encryption-at-rest is **roadmap**, not shipped.

**Customer memory / PII:** PII masking runs in-pipeline; customer-memory
persistence and retention (e.g. LGPD Art. 20 erasure, BCB ~5-yr retention) are
**partially built** (audit chain persists; durable customer-memory + automated
retention are roadmap, see §4).

---

## 3. Hardening checklist (before any non-demo use)

Everything below is a **customer-side configuration** step. The app ships with
safe **demo** defaults, not hardened **production** defaults — you must do these.

- [ ] **Turn on auth.** Set `BRIDGE_AUTH=on`. Understand its limits (§4): the
      built-in JWT path is **demo-grade** — ephemeral per-process signing key and
      **hardcoded demo users with no password hashing**. Do **not** use the
      built-in `_USERS` in production.
- [ ] **Front with your IdP.** Put the app behind your **reverse proxy / OIDC /
      SSO** (e.g. an OIDC-aware gateway, oauth2-proxy, or your API gateway).
      Enforce MFA and session policy **at the edge**. Treat the app's own auth as
      a fallback, not the perimeter. (SSO is a **bring-your-own seam** — not
      built in.)
- [ ] **Terminate TLS at the edge.** The app does **not** serve HTTPS itself.
      Put TLS on your reverse proxy / load balancer. Enable HSTS there.
- [ ] **Lock down CORS.** Set `BRIDGE_CORS_ORIGINS` to your exact frontend
      origin(s). The default list is **localhost dev ports** — replace it.
- [ ] **Bring your own KMS for the signing key.** The evidence/JWT signing key is
      an **ephemeral per-process** key behind a `KeyManager` seam. Wiring it to
      **your KMS/HSM** (sign-only, versioned `key_id`) is **roadmap (v6 Phase 4)**
      and is *blocked on you providing the KMS*. Until then, treat signatures as
      **process-verifiable, not externally time-bound** (no RFC 3161 timestamp).
- [ ] **Replace demo credentials.** Remove the hardcoded `_USERS`; wire a real
      identity store (or rely entirely on edge OIDC). The `.env.example` flags
      this explicitly: *"These MUST be replaced before any real deployment."*
- [ ] **Rate-limit per authenticated user.** Configure `BRIDGE_RPM` / `BRIDGE_BURST`;
      add gateway-level rate limiting for defense in depth.
- [ ] **Set persistence paths + backups.** Point `BRIDGE_AUDIT_DB`,
      `BRIDGE_CHANGES_DB`, `BRIDGE_VISIBILITY_DB` at an encrypted, backed-up
      volume. Confirm `GET /audit/verify?source=disk` returns `chain_valid: true`
      after restore drills.
- [ ] **Keep cloud LLMs off unless approved.** Leave `BRIDGE_DEMO_SAFE=on` (or use
      Ollama) until a data-egress review approves a specific cloud provider. Never
      set `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` in an environment that must stay
      air-gapped.
- [ ] **Verify security headers.** The app sets baseline headers
      (`X-Content-Type-Options`, `X-Frame-Options: DENY`, …); add CSP and any
      others at the edge per your standard.
- [ ] **Pin the supply chain.** Build from a pinned commit/tag; run your own SCA
      (there is no vendor-provided SBOM attestation yet).

---

## 4. Deployment-readiness matrix (real vs. planned)

Legend: **Built** = present and exercised in the code/tests · **Seam** =
swappable interface exists, integration is yours to provide · **Roadmap** =
designed, not implemented · **Not present** = does not exist.

| Capability | Status | Honest detail |
|---|---|---|
| Air-gapped / zero-egress core | **Built** | `numpy`+stdlib; `FakeBackend`/`dummy` default; no telemetry or call-home. |
| Local-LLM option (in-VPC) | **Built** | Ollama at localhost; circuit-breaker + queue; safety intents stay canned. |
| Deterministic, reproducible evidence | **Built** | Seed + dataset hash; OSCAL Assessment Results; Ed25519 signing; SHA-256 hash-chained audit on SQLite (WAL). |
| Authentication | **Built but demo-grade** | Real EdDSA-JWT (`/auth/token`, `verify_token`), **off by default** (`BRIDGE_AUTH=off`). **Ephemeral per-process key; hardcoded demo users; no password hashing.** Not a production identity store. |
| SSO / OIDC / SAML | **Seam (not built)** | Bring-your-own: front with your IdP via reverse-proxy/OIDC. No SSO code in-repo. |
| RBAC | **Partial / roadmap** | Role claims (`analyst`/`validator`/`admin`) exist in the demo token; full RBAC enforcement + audit attribution is v6 Phase 2. |
| Segregation of duties (maker/checker) | **Built (logic) / hardening in progress** | Propose→approve→apply with approver ≠ submitter. Today identity can arrive in the request body (**trust-the-caller**) unless `BRIDGE_AUTH=on` binds it to a verified `token.sub` (v6 Phase 1). |
| Multi-tenancy / tenant isolation | **Roadmap** | **Single-tenant only** today; per-tenant `tenant_id` + `WHERE` filtering + per-tenant hash-chain is v6 Phase 3. Do **not** assume isolation between orgs. |
| High availability / horizontal scale | **Single-node** | App is **not stateless** today; SQLite + in-process state. Redis/Postgres adapters exist as **reference/flag-gated** wiring (`scale/`, `SCALE_WIRING.md`) but the pilot path is **single node**. |
| Persistence (durable) | **Partial** | Audit chain + change requests persist to SQLite. Durable users/sessions, customer-memory, retention jobs = roadmap (v6 Phase 5). |
| KMS / HSM signing + RFC 3161 timestamp | **Seam / roadmap** | `KeyManager` seam present; key is **ephemeral**. Managed-key + TSA = v6 Phase 4, **blocked on your KMS**. Evidence today is process-verifiable, not externally time-bound. |
| Encryption in transit (TLS) | **Customer-provided** | App does not terminate TLS; do it at your edge. |
| Encryption at rest | **Customer-provided** | Use disk/volume encryption. App-level at-rest encryption = roadmap. |
| SOC 2 | **None** | Not performed, not in progress. |
| Independent penetration test | **None** | Not commissioned. |
| SLA / support / legal entity / hosted SaaS | **None** | Apache-2.0 OSS, self-hosted, individual author. |
| SBOM / signed release attestation | **Not present** | Run your own SCA; pin to a commit/tag. |
| Reference customer | **None** | No production bank deployment to cite. |

---

## 5. CAIQ-lite / TPRM answer table

A condensed third-party-risk questionnaire, answered for the **self-hosted,
default (offline)** deployment. Where an answer depends on your configuration,
it says so. This is **not** a completed CAIQ v4 workbook and is **not** an
attestation — it is an honest quick-reference to accelerate your own assessment.

| # | Domain | Question | Answer (self-hosted, default config) |
|---|---|---|---|
| 1 | Hosting model | Is this SaaS or self-hosted? | **Self-hosted only.** No vendor-operated service exists. You run it in your VPC. |
| 2 | Subprocessors | List subprocessors handling customer data. | **None** in the default (offline) deployment — nothing leaves your VPC. If *you* enable a cloud LLM (OpenAI/Anthropic), that provider becomes **your** subprocessor under **your** contract; it is opt-in and off by default. |
| 3 | Data residency | Where is customer data stored/processed? | **Entirely within your VPC** (local SQLite + local/optional in-VPC LLM). Residency is wherever you host. |
| 4 | Data egress / telemetry | Does the product phone home? | **No.** No telemetry, analytics, or license call-home in the code. Egress only via an opt-in cloud LLM adapter you enable. |
| 5 | Encryption in transit | Is traffic encrypted? | **Customer-provided.** Terminate TLS at your edge (app does not serve HTTPS). Internal hop is in-VPC HTTP. |
| 6 | Encryption at rest | Is data encrypted at rest? | **Customer-provided** (disk/volume encryption). App-level at-rest encryption is roadmap. |
| 7 | Authentication | How do users authenticate? | Built-in EdDSA-JWT is **demo-grade and off by default**; **front with your IdP/OIDC** for production. SSO is a bring-your-own seam. |
| 8 | Authorization | Is access role-based? | Partial: demo role claims exist; full RBAC enforcement is roadmap. Enforce authorization at your gateway meanwhile. |
| 9 | Multi-tenancy | Is data isolated between tenants? | **Single-tenant only.** No cross-tenant isolation today. Deploy one instance per org/environment. |
| 10 | Audit logging | Is there a tamper-evident audit trail? | **Yes** — SHA-256 hash-chained, append-only, replayable/verifiable (`/audit/verify`), persisted to SQLite (WAL). |
| 11 | Cryptographic evidence | Are decisions signed? | **Yes**, Ed25519 — but with an **ephemeral per-process key** (no KMS/HSM, no RFC 3161 timestamp yet). Treat as **process-verifiable, not externally time-bound**. |
| 12 | Key management | How are keys managed? | Ephemeral in-process behind a `KeyManager` seam; **bring your own KMS/HSM** (roadmap wiring). No secret is hardcoded except the flagged demo credentials, which you must remove. |
| 13 | Secrets handling | How are secrets provided? | Server-side **env vars** / your secret manager. Cloud LLM keys never touch the browser. Demo user passwords are hardcoded and **must be replaced**. |
| 14 | Availability / HA | What is the availability posture? | **Single-node, no HA, no SLA.** Redis/Postgres scale-out is reference-only; not the supported pilot topology. |
| 15 | Backup / DR | Backup and recovery? | **Customer-owned** — back up the SQLite volume; validate the chain after restore. No managed backup. |
| 16 | Vulnerability mgmt / pen-test | Independent security testing? | **None on record.** No SOC 2, no pen-test. Run your own review; the source is open (Apache-2.0) for inspection. |
| 17 | SBOM / supply chain | Is an SBOM/attestation provided? | **Not provided.** Pin to a commit/tag and run your own SCA. Core deps are minimal (numpy + stdlib for the analytical core). |
| 18 | Data deletion / retention | Deletion and retention controls? | Audit retention is disk-bound; automated retention + customer-memory erasure (LGPD Art. 20) are **roadmap**. |
| 19 | Licensing / exit | License and exit/portability? | **Apache-2.0.** No license fee; no lock-in. You hold the source, the SQLite data, and the OSCAL evidence — full portability. |
| 20 | Incident response | Is there a vendor IR process/contract? | **No vendor IR / SLA.** Security issues via the repo's `SECURITY.md`; you own operational IR for your deployment. |

---

## 6. Recommended first deployment (safe default)

For a first, defensible pilot inside a bank:

1. **Single VPC subnet, no egress.** `BRIDGE_DEMO_SAFE=on` (or Ollama in-VPC),
   no cloud keys, SQLite on an encrypted volume.
2. **Your edge in front.** Reverse proxy terminating TLS + OIDC/SSO + rate limit;
   set `BRIDGE_CORS_ORIGINS` to the real origin.
3. **Auth on, edge-enforced.** `BRIDGE_AUTH=on` for the maker/checker binding, but
   treat the **edge IdP as the real authenticator** and remove demo users.
4. **Validate hermetically first.** Run the `dummy`-backend `lub benchmark` /
   `lub report` path (numpy+stdlib, no network) to satisfy MRM wiring review
   before any model is connected — per the Tier-1/2/3 deployment guides.
5. **Treat evidence as process-verifiable.** Until you wire your KMS + a TSA, cite
   the signed, hash-chained evidence as *reproducible internal evidence*, not as
   an externally timestamped, non-repudiable artifact.

---

*Companion docs: [`docs/sr-11-7.md`](sr-11-7.md) (SR 11-7 scope limits),
[`docs/deployment/`](deployment/) (Tier 1/2/3 patterns),
`bridge-ui/docs/PRODUCT_PLAN_V6.md` (the trust-substrate roadmap this matrix
tracks), `bridge-ui/docs/SCALE_WIRING.md` (the — reference-only — HA scale-out
procedure). Regulatory citations in the tier guides are marked "verify against
primary source"; this document makes no new regulatory-deadline claims.*
