# Bridge — load test

A k6 load test for the `/query` pipeline, used to find the single-node ceiling
today and to gate each step of the scale work (see
`docs/ENGINEERING_HARDENING_PLAN.md` → Track D).

## Run

```bash
# 1. start the backend (single node, fake backend — the current demo)
cd ../backend && BRIDGE_USE_REAL_LLM=off uvicorn server:app --port 8000

# 2. in another shell, run the ramp
k6 run -e BASE_URL=http://localhost:8000 query_load.js
```

Install k6: <https://k6.io/docs/get-started/installation/>.

## Ramp → daily volume

| Stage rate | ≈ daily volume | Note |
|---|---|---|
| 12 rps  | ~1M/day average | should be comfortable |
| 50 rps  | ~1M/day peak    | single worker still ok-ish (fake backend) |
| 116 rps | ~10M/day average | audit-lock + SQLite write contention shows here |
| 460 rps | ~10M/day peak   | single node saturates — **this is the point** |

## How to read it

- **`query_latency_ms` p95/p99** vs the thresholds (`p95<800ms`, `p99<1500ms`):
  where they blow past the target is your single-node limit.
- **`query_throttled_429`**: with a real LLM (Ollama, semaphore=1, queue≤10)
  this climbs fast — that's the LLM tier being the throughput cap, not a bug.
- **`http_req_failed`**: true errors (5xx / connection) vs. expected 429s.

## What fixes the ceiling

Not tuning the cheap stages — they're sub-millisecond. The ceiling is:
1. the **LLM serving tier** (remove the `semaphore=1` cap; batching / managed API),
2. the **audit write** under a global lock (move to Postgres, per-tenant chain),
3. **single process / in-memory state** (make the app stateless → scale replicas).

Full plan + target topology: `docs/ENGINEERING_HARDENING_PLAN.md`, Track D.
