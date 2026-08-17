# Bridge — Product Plan (model-risk governance platform)

**Branch:** `product/bridge-platform` (the `main` branch + tag `petition-exhibit-2026-07-01`
stay frozen as the NIW exhibit — never break them here). **Started:** 2026-06-11.

## Decisions (made on the user's delegation)
- **Isolation:** build on this branch; `main` is the frozen petition exhibit.
- **Real LLM:** Ollama local (llama3.1:8b) — `BRIDGE_USE_REAL_LLM=on`; zero cost, no API key.
  Providers (OpenAI/Anthropic/Azure) come later as adapters.
- **v1:** Datasets & Experiments — operationalize SR 11-7 "effective challenge" in the UI.

## The moat (do not dilute)
Bridge is **not** "another guardrails/observability tool" (NeMo/Guardrails/Phoenix/
Langfuse own that). Its defensible core is the **SR 11-7 / NIST-mapped per-response
evidence layer** — the regulator-filable record a second-line validator files. Every
feature must reinforce that, not chase feature-parity.

## Phased roadmap (one sellable slice at a time)
| Phase | Feature | Why it sells | Needs real LLM? |
|---|---|---|---|
| **v1** | **Datasets & Experiments** | A bank's MRM team runs the validation battery on every change and files the pass/fail report — effective challenge, operationalized | No (works on fake/Ollama) |
| v2 | Navigable trace (click a stage → role/latency/decision) — **DONE** | Per-decision auditability | No |
| v3 | Integrations inventory + live Ollama reachability — **DONE** | Validates the bank's *actual* model, not a fake | Yes |
| v4 | Playground — threshold sweep, side-by-side decisions — **DONE** | Fast tuning; closes the iterate loop | No |
| v5 | Ask AI (Ollama copilot, honest degradation) — **DONE** | Lowers the skill barrier | Yes |
| v6 | Auth / multi-tenant / persistence — **infra phase (not faked)** | SaaS foundation | — |

> **v6 note:** real auth + multi-tenancy is production infrastructure (sessions, data
> isolation, security), not a demonstrable UI slice. A mock login/tenant would be
> theater that violates the honesty layer, so it is **deferred to a proper infra
> effort** rather than faked. The v1–v5 product shell is complete and verified.

Each phase: backend + test + UI with the honesty layer (LIVE/MOCK/STATIC) + CHANGELOG.

## v1 spec — Datasets & Experiments (this slice)
- **Dataset** = the labelled intent battery already in `_INTENT_CATALOG` (24 intents ×
  samples) — a real, versioned (content-hashed) labelled set.
- **Experiment run** = classify every case through the live classifier + guard, score
  predicted-vs-expected, return accuracy + per-intent breakdown + the failures + a
  sha256 content hash + timestamp (reproducible, file-able — same evidence discipline
  as the model-risk package).
- **UI:** new **"Avaliação"** tab + an Experiments panel (run button, accuracy, failures
  table, hash). Re-run on demand; a dropped accuracy after a change = a caught regression.
- Endpoints: `GET /datasets`, `GET /datasets/{id}`, `GET /experiments/run`.
