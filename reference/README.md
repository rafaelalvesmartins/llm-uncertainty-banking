# Reference Deployment

> **This directory is documentation, not shipped infrastructure.**
> It demonstrates how a financial institution would integrate `lub`
> into its existing stack, as described in Section 7 of the tech report.

## Architecture

```
                    ┌────────────────────────┐
                    │    docker-compose.yml   │
                    └────────┬───────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
         ┌────▼────┐   ┌────▼────┐   ┌────▼────┐
         │ gateway  │   │  db     │   │ monitor │
         │ FastAPI  │   │ Postgres│   │Prometheus│
         │ + lub    │   │         │   │+ Grafana │
         └─────────┘   └─────────┘   └─────────┘
```

- **gateway** — FastAPI service that imports `lub` as a library.
  This is the ~30 lines of integration code a bank would write.
- **db** — PostgreSQL for persisting `GuardResult` JSON.
  In production this would be the institution's existing database.
- **monitor** — Prometheus + Grafana for confidence/refusal metrics.
  In production this would be the institution's existing observability stack.

## Running

```bash
cd reference/
docker compose up --build
```

Then:

```bash
# Ask a question
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the minimum capital ratio under Basel III?"}'

# Health check
curl http://localhost:8000/health

# Prometheus metrics
curl http://localhost:9090/api/v1/query?query=lub_requests_total
```

## What this demonstrates

1. `lub` is imported as a Python library — no sidecar, no gRPC, no message queue.
2. Persistence, auth, and monitoring are the institution's responsibility.
3. The gateway is stateless — horizontal scaling is just more replicas.
4. `pip install --upgrade lub` updates scoring without touching the database.

## What this does NOT demonstrate

- Authentication (institution-specific IAM)
- TLS termination (institution's load balancer)
- Model hosting (institution's GPU cluster or API key management)
- Audit trail retention policy (institution's compliance team)

These are deliberately out of scope. See Section 7.3 of the tech report.
