// Bridge /query load test (k6).
//
// Run:   k6 run -e BASE_URL=http://localhost:8000 loadtest/query_load.js
// Install k6: https://k6.io/docs/get-started/installation/
//
// Capacity intuition (so the ramp maps to real daily volume):
//   1M req/day  ≈ 12 req/s average  (~50 rps at a 4x peak)
//   10M req/day ≈ 116 req/s average (~460 rps at a 4x peak)
//
// What this exercises depends on the backend:
//   - FakeBackend (BRIDGE_USE_REAL_LLM=off): probes the 12-stage pipeline +
//     the audit hash-chain write path (the `_AUDIT_LOCK` serialization point).
//     A single uvicorn worker will start saturating well before the 10M/day
//     peak — that's the point: it shows where the single-node ceiling is.
//   - Real LLM (Ollama, semaphore=1, queue<=10): expect HTTP 429 above ~10
//     in-flight; throughput is capped at roughly one inference at a time. This
//     demonstrates why the LLM serving tier (Track D §D.3) is the throughput
//     killer for millions/day.

import http from "k6/http";
import { check, sleep } from "k6";
import { Counter, Trend } from "k6/metrics";

const BASE = __ENV.BASE_URL || "http://localhost:8000";
const throttled = new Counter("query_throttled_429");
const e2e = new Trend("query_latency_ms", true);

export const options = {
  scenarios: {
    ramp: {
      executor: "ramping-arrival-rate",
      startRate: 5,
      timeUnit: "1s",
      preAllocatedVUs: 60,
      maxVUs: 600,
      stages: [
        { target: 12, duration: "1m" }, // ~1M/day average
        { target: 50, duration: "2m" }, // ~1M/day peak
        { target: 116, duration: "2m" }, // ~10M/day average
        { target: 460, duration: "2m" }, // ~10M/day peak (single node will saturate)
        { target: 0, duration: "30s" },
      ],
    },
  },
  // SLO targets — tune to your contract. Failing these flags the scale gap.
  thresholds: {
    http_req_failed: ["rate<0.01"], // <1% transport errors
    query_latency_ms: ["p(95)<800", "p(99)<1500"],
  },
};

const PROMPTS = [
  "Quero ver o saldo da minha conta",
  "Pagar 150 reais pro Joao via PIX",
  "Minha fatura do cartao chegou?",
  "quero simular um emprestimo pessoal",
];

export default function () {
  const payload = JSON.stringify({
    query: PROMPTS[Math.floor(Math.random() * PROMPTS.length)],
    channel: "app",
    // Distinct customer per VU so the per-customer cache scope (R1) is exercised
    // realistically rather than every request hitting one cache key.
    customer_id: `load-${__VU}`,
  });

  const res = http.post(`${BASE}/query`, payload, {
    headers: { "Content-Type": "application/json" },
    tags: { name: "POST /query" },
  });

  e2e.add(res.timings.duration);
  if (res.status === 429) throttled.add(1);

  check(res, {
    "200 or 429 (throttled, not error)": (r) => r.status === 200 || r.status === 429,
  });

  sleep(0.1);
}
