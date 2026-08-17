# Pluggable Provider Architecture

> **Date:** 2026-06-15 · **Goal:** make the bridge's external dependencies —
> LLM backends, infra/storage, cloud targets, integrations — **plug-and-play**.
> Register, enable, disable, or swap a provider through config, with **zero changes
> to the core pipeline**. The same way you pick AWS vs GCP vs Azure, or OpenAI vs
> Anthropic vs Ollama.
>
> **Why now:** the bones already exist — `backends.py` has a backend abstraction +
> `_select_backend()`, the `scale/` adapters are swappable behind flags, and the
> Integrations panel + `+ Nova` already enumerate providers with health. This plan
> formalizes that into one consistent plugin model instead of three ad-hoc ones.

---

## 1. Provider taxonomy (the layers you can swap)

| Layer | Examples (providers) | Today |
|---|---|---|
| **LLM backend** | FakeBackend, Ollama, OpenAI, Anthropic, vLLM/TGI, Bedrock/Vertex/Azure OpenAI | `backends.py` + `_select_backend()` (hardcoded list) |
| **Infra / scale** | cache (Redis · in-memory · Memcached), audit store (Postgres · SQLite · DynamoDB), metrics (Prometheus · OTLP), rate-limit store | `scale/` adapters behind flags |
| **Cloud** (a bundle of infra) | **AWS** (RDS+ElastiCache+Bedrock) · **GCP** (CloudSQL+Memorystore+Vertex) · **Azure** (AzureDB+Cache+AzureOpenAI) | reference `docker-compose.scale.yml` only |
| **Integration** | RAG sources, compliance frameworks, data connectors | `lub.connectors.bridge.*` + Integrations panel |

A **cloud provider** is just a preset that selects a set of infra providers — so "use AWS"
= `audit=rds, cache=elasticache, llm=bedrock` under one name.

---

## 2. The core pattern (one model for all layers)

Four pieces, identical per layer:

1. **Protocol** — the contract a provider implements. One per layer:
   `LLMBackend`, `CacheStore`, `AuditStore`, `MetricsSink`, `Integration`.
   (Python `typing.Protocol`; the layering contract in `import-linter` already allows this.)

2. **Registry** — `name -> factory`. Populated from three sources, in order:
   - **built-in** providers, registered at import (e.g. `@register("ollama")`);
   - **plugins** — third-party providers shipped as pip packages, discovered via
     entry-points (the way pytest/flake8 plugins work) → *add a provider by `pip install`*;
   - **config** — which providers are enabled + their settings.

3. **Capability descriptor** — each provider declares: required env/secrets, optional
   deps, and a `health()` check. This feeds the honesty layer (`live` / `demo` /
   `not_configured`) and the Conexões status dots — no hardcoding.

4. **Selection** — config picks the active provider per layer:
   `BRIDGE_BACKEND=ollama`, `BRIDGE_CACHE=redis`, `BRIDGE_CLOUD=aws`. Unset → safe default
   (FakeBackend / in-memory). **Add** = register + enable in config. **Remove** = disable
   in config (or uninstall the plugin). Core never changes.

```python
# shape (illustrative)
class LLMBackend(Protocol):
    name: str
    def health(self) -> ProviderHealth: ...
    def generate(self, req: Request) -> Response: ...

@register_backend("openai")
def _make_openai(cfg: ProviderConfig) -> LLMBackend: ...   # only built if BRIDGE_BACKEND=openai + key present

# selection (replaces the hardcoded _select_backend)
backend = backend_registry.resolve(os.getenv("BRIDGE_BACKEND", "fake"))
```

---

## 3. Mapping to the existing code (what changes, surgically)

| Existing | Becomes |
|---|---|
| `backends.py` `_select_backend()` + FakeBackend/OllamaBackend | a `backend_registry` + `LLMBackend` protocol; the two existing backends register themselves |
| `scale/cache_redis.py`, `audit_postgres.py`, … (flag-gated `get_cache(fallback)`) | `CacheStore` / `AuditStore` protocols + registries; the flag becomes the selector |
| `/api/integrations` + Conexões panel (status active/reachable/not_configured) | reads the registries' `health()` — already the right shape |
| `+ Nova` (today a teaser) | a real form: pick provider type → enter endpoint/secret → writes config → registry picks it up |
| Ollama circuit breaker (`_OLLAMA_BREAKER_LOCK`) | generalized: a breaker **per provider** in the registry |

**Nothing in the pipeline changes** — every provider still flows through `data_governance`
(masking), the `uncertainty_guard`, and the audit chain. Providers can't bypass the safety layers.

---

## 4. Phased plan (each phase verifiable; gate = the named test)

| Phase | What | Gate |
|---|---|---|
| **1. Backend registry** | Extract `LLMBackend` protocol + registry; refactor `_select_backend()` to `registry.resolve()`. FakeBackend/Ollama self-register. | `pytest` (backend-selection tests) + `import-linter` |
| **2. Prove add/remove** | Add OpenAI + Anthropic backends via the registry, behind flags (no key → `not_configured`, honest). Remove = disable. | the new providers appear in `/api/integrations` with correct status |
| **3. Infra providers** | Formalize the `scale/` adapters into `CacheStore`/`AuditStore`/`MetricsSink` protocols + registries; the flag becomes the selector. | `pytest scale/` + cross-store parity (audit) |
| **4. Cloud bundles** | `BRIDGE_CLOUD={aws,gcp,azure}` = a preset selecting infra providers; reference deploy config per cloud (compose/terraform stub). | `docker-compose.<cloud>.yml` validates; load-test smoke |
| **5. Plugins + UI** | Entry-point discovery (3rd-party provider via `pip install`); wire `+ Nova` to register a provider instance from the UI. | e2e: add a provider in the console, see it in Conexões |

Order matters: **Phase 1 first** (it's the cleanest extraction and the template for the rest).

---

## 5. Cross-cutting (the banking constraints — don't skip)

- **Secrets:** provider credentials come from a secret manager / KMS, never hardcoded
  (ties to the open P0 in the consolidated analysis). The registry reads from the secret
  source, not from code.
- **Safety is non-bypassable:** a new backend still goes through masking + guard + audit.
  A provider is a *source*, not an escape hatch.
- **Health + breaker per provider:** generalize the existing Ollama breaker so any provider
  that fails trips its own breaker (no single bad provider takes the bridge down).
- **Honesty:** a provider with missing config renders `not_configured` (the layer already
  does this) — never shown as live.

---

## 6. Why this is the right "add/remove like a cloud"

- It replaces three ad-hoc mechanisms (hardcoded backends, flag-gated scale adapters,
  the static integrations list) with **one** registry+protocol+config model.
- "Add a provider" becomes: register (or `pip install` a plugin) + one config line.
  "Remove" becomes: disable in config. **No core edits, ever.**
- The cloud bundles (AWS/GCP/Azure) make Track D (scale) concrete: pick a cloud, get its
  managed Postgres/Redis/LLM-serving as providers.
- It makes `+ Nova` honest *and* functional — the feature the UI already promises.

### One-line summary
Turn the hardcoded backends, the flag-gated scale adapters, and the static integrations into
**one provider plugin system** — protocol + registry + config + health — so LLM backends,
infra, whole clouds (AWS/GCP/Azure), and third-party integrations are add/remove by config,
never by touching the core, with safety (masking/guard/audit) always in the path.
