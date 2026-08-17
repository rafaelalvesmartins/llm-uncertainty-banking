// Shared fetch helpers for the /console views.
//
// Follows the house data-fetching convention: raw fetch() to the /api/* BFF
// proxy with `cache: "no-store"`, throwing Error(`HTTP <status>`) on failure so
// views can render a consistent error state. No SWR/react-query (matches the
// legacy panels).

import { apiErrorText } from "@/lib/apiError";
import type { Health, Metrics, QueryRequest, QueryResult } from "./types";

/** GET any /api/* path and parse JSON, throwing on non-2xx. */
export async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(path, { cache: "no-store" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (await r.json()) as T;
}

export const getHealth = () => getJSON<Health>("/api/health");
export const getMetrics = () => getJSON<Metrics>("/api/metrics");

/** POST /query — surfaces the backend's error on validation/runtime failures.
 *  Accepts an AbortSignal so the caller can cancel or time out a slow real-LLM
 *  request (an Ollama generation can take 15–30s). */
export async function postQuery(body: QueryRequest, signal?: AbortSignal): Promise<QueryResult> {
  const r = await fetch("/api/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
    signal,
  });
  if (!r.ok) {
    // Pydantic 422 returns `detail` as an array — apiErrorText flattens it to a
    // readable message instead of the old "HTTP 422: [object Object]".
    const errBody = await r.json().catch(() => null);
    throw new Error(apiErrorText(errBody, r.status));
  }
  return (await r.json()) as QueryResult;
}
