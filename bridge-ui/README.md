# Bridge UI — Next.js + FastAPI

Operable governance console that wraps the `lub` library into a demo a bank's
model-risk (MRM) function could use: a customer query flowing through the guard
(PASS / RE-ASK / ESCALATE when the model isn't sure), a hash-chained audit trail
with a live tamper-detection proof, and a signed, downloadable SR 11-7 evidence
package.

Scope and honest limits: [`docs/DEMO_SCOPE.md`](docs/DEMO_SCOPE.md). Security
posture (this demonstrator **is** a server): [`../SECURITY.md`](../SECURITY.md).

## Run

One command — offline by default (deterministic `FakeBackend`, no real LLM, no
real data):

```bash
./bridge-ui/start-demo.sh
```

It cleans stale processes, starts the backend on `:8000` and the frontend on
`:3002`, and prints:

```
Demo:    http://localhost:3002      ← the console
Backend: http://localhost:8000/health
Swagger: http://localhost:8000/docs ← full, live endpoint reference
```

To run against a real LLM (Ollama): `./bridge-ui/start-real.sh`.

Populate the console with realistic traffic (optional, idempotent):

```bash
python bridge-ui/scripts/seed-demo.py   # after the demo reports ready
```

### Manual start (fallback)

```bash
# backend
cd bridge-ui/backend && pip install -r requirements.txt && uvicorn server:app --port 8000
# frontend (in another shell)
cd bridge-ui/frontend && npm install && npm run dev -- -p 3002
```

Prefer `start-demo.sh` — it avoids the `--reload` foot-gun (a reload firing
mid-request on an unrelated file write makes the header show green "BFF online"
for a few seconds while queries fail).

## Backend selection (env)

Backend choice is environment-driven; the defaults keep the demo deterministic.
Full precedence and security notes are in [`../SECURITY.md`](../SECURITY.md) §3.

| Variable | Default | Effect |
|----------|---------|--------|
| `BRIDGE_DEMO_SAFE` | `on` | Master switch — forces `FakeBackend` and blocks real bindings. Must be `off` before any real-LLM knob is read. `start-real.sh` sets this off. |
| `BRIDGE_USE_REAL_LLM` | `auto` | Only consulted when `BRIDGE_DEMO_SAFE=off`: `auto` probes Ollama and falls back to fake; `required` fails hard if Ollama/model absent; `off` forces fake. |
| `BRIDGE_AUTH` | `off` | When `on`, state-changing endpoints require a bearer token (the demo UI has no login yet — see SECURITY.md). |

See [`.env.example`](.env.example) for the full annotated list.

## What the console shows (`/`)

`/` serves the multi-view governance console (a Next.js rewrite; the older
single-page dashboard is retained at `/legacy` for e2e tests). The rail groups
views as **Operate → Govern → Monitor → Setup**:

- **Dashboard** — the golden-path guide (Ask → Decide → See → Prove) with a
  one-click live sample, decision mix, and customer-flow funnel.
- **Flow** — a single query traced through every pipeline stage with timings,
  ending in the guard decision + plain-language explanation.
- **Audit** — the hash-chained, tamper-evident trail; "Verify chain", "Verify
  from disk", and a live "Prove tamper detection" proof; per-row "explain".
- **Governance** — SR 11-7 crosswalk, the signed evidence package (+ 2-page
  printable leave-behind at `/evidence-report`), and the propose → approve →
  apply governed-change ledger (two-person control).
- **Policies / Connections / Observability / Config** — channel firewall rules,
  governed vendor connections, drift + ops metrics, and guard configuration.

## Pipeline stages (what the Flow trace renders)

```
0a. dq_input           ← rejects prompt injection / empty / too-long BEFORE token spend
0b. data_governance    ← detects PII, classifies, masks
1.  semantic_cache     ← short-circuits on hit
2.  complexity_router  ← picks LLM tier
3.  customer_memory    ← loads persona/preferences blocks
4.  rag_retrieval      ← grounds in regulatory docs with citations
5.  intent_classifier  ← banking intent
6.  agent              ← chatbot/smart_payments/call_center (with handoffs)
6b. dq_output          ← blocks hallucinated amounts over threshold
7.  uncertainty_guard  ← PASSTHROUGH / FLAG / REASK / ESCALATE
8.  cache_store        ← saves for future near-matches
9.  audit_trail        ← hash-chained log (BCB 4893)
```

## Endpoints

The full, always-current endpoint reference is the live Swagger UI at
`http://localhost:8000/docs` (the backend ships far more than the original demo
table listed — `/auth`, `/evidence`, `/audit/verify`, `/audit/tamper-test`,
governed-changes, drift, visibility, and more). Every route the frontend uses is
proxied under `frontend/app/api/*`.

## Documentation

All design and validation docs live in [`docs/`](docs/README.md) — start with
[`docs/DEMO_SCOPE.md`](docs/DEMO_SCOPE.md) for what the demo does and does not do.
