"use client";

import { useEffect, useState } from "react";
import { useAppContext } from "@/components/AppContextProvider";
import StateBadge from "@/components/StateBadge";
import { apiErrorText } from "@/lib/apiError";

interface Stage {
  name: string;
  status: string;
  detail: string;
  confidence: number | null;
  duration_ms: number;
}

export interface QueryResult {
  query: string;
  answer: string;
  intent: string;
  confidence: number;
  decision: string;
  latency_ms: number;
  stages: Stage[];
  cache_hit?: boolean;
  cache_similarity?: number | null;
  tier?: string | null;
  cost_cents?: number | null;
  memory_blocks?: string[];
  citations?: string[];
  handoff_chain?: string[];
  agent_used?: string | null;
}

interface Props {
  onResult: (r: QueryResult) => void;
  // Tour driver: when the parent bumps `nonce`, this query runs through the
  // SAME submit path the user's button uses (no parallel data flow).
  autoQuery?: { text: string; nonce: number } | null;
  // Locks all controls (e.g. while the guided tour is running).
  disabled?: boolean;
}

const EXAMPLES = [
  "I want to see my account balance",
  "Pay 150 reais to João via PIX",
  "I want to apply for a personal loan",
  "Has my card bill arrived?",
  "I have a complaint about the service",
  "Hello",
];


export default function QueryPanel({ onResult, autoQuery, disabled }: Props) {
  const [query, setQuery] = useState("");
  const [channel, setChannel] = useState("whatsapp");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [abortController, setAbortController] = useState<AbortController | null>(null);
  // v14 P2 — persona switcher. Reads /api/customers and lets the operator
  // pick which pre-seeded profile (PF / PJ / PEP / menor / idoso / ...) the
  // query is attributed to, so the same query routes differently depending
  // on the customer-memory context the agent loads. Defaults to "demo" so
  // a fresh session still works without selecting anything.
  // v15 — the active client is global (top context bar) instead of a local
  // dropdown, so selecting a client drives every panel, not just this one.
  const { client: customerId, customers } = useAppContext();
  // v14 P3 — SSE streaming opt-in. When on, /query/stream is used and the
  // user sees heartbeats + progressive stage reveal instead of a 45s
  // blank "Processing…" button.
  const [streamMode, setStreamMode] = useState(true);
  const [streamProgress, setStreamProgress] = useState<{
    elapsed_s?: number;
    stage_name?: string;
    last_event?: string;
  } | null>(null);


  // B-NEW-20 (round 10): hard timeout + AbortController + finally so the
  // "Processing..." button always clears even if Ollama hangs / BFF 502s.
  // Default 90s matches BFF route maxDuration; Ollama p95 today is ~45s.
  const TIMEOUT_MS = 90_000;

  async function submit(text: string) {
    if (!text.trim()) return;
    setLoading(true);
    setError(null);
    setElapsedMs(0);
    setStreamProgress(null);
    const start = Date.now();
    const ticker = setInterval(() => setElapsedMs(Date.now() - start), 250);

    const ctrl = new AbortController();
    setAbortController(ctrl);
    const timeoutId = setTimeout(() => ctrl.abort("timeout"), TIMEOUT_MS);
    const body = JSON.stringify({ query: text, channel, customer_id: customerId });
    const endpoint = streamMode ? "/api/query/stream" : "/api/query";

    try {
      const r = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
        signal: ctrl.signal,
      });
      if (!r.ok) {
        // Covers both modes now: a stream-mode HTTP error (e.g. the proxy's
        // 502 when the backend is down) used to fall through and be read as
        // SSE, surfacing the generic "Stream ended without a done event".
        const data = await r.json().catch(() => null);
        setError(apiErrorText(data, r.status));
        return;
      }
      if (!streamMode) {
        const data = await r.json().catch(() => ({ error: "non-JSON response" }));
        onResult(data);
        setQuery("");
        return;
      }
      // SSE path — read the response stream and dispatch by event type.
      if (!r.body) {
        setError("Streaming response had no body");
        return;
      }
      // Local flag: the closure-captured `error` is stale inside submit(), so a
      // setError() fired mid-stream would not be seen by the post-loop check.
      let streamError = false;
      const reader = r.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finalResult: unknown = null;
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // SSE events are separated by blank lines (\n\n).
        let idx;
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
          const chunk = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          let eventName = "message";
          let dataLine = "";
          for (const line of chunk.split("\n")) {
            if (line.startsWith("event:")) eventName = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLine += line.slice(5).trim();
          }
          if (!dataLine) continue;
          let parsed: any;
          try {
            parsed = JSON.parse(dataLine);
          } catch {
            continue;
          }
          if (eventName === "heartbeat") {
            setStreamProgress({ elapsed_s: parsed.elapsed_s, last_event: "heartbeat" });
          } else if (eventName === "stage") {
            setStreamProgress({ stage_name: parsed.name, last_event: "stage" });
          } else if (eventName === "done") {
            finalResult = parsed;
          } else if (eventName === "error") {
            setError(`Pipeline error ${parsed.status_code}: ${apiErrorText(parsed, parsed.status_code)}`);
            streamError = true;
          }
        }
      }
      if (finalResult) {
        onResult(finalResult as QueryResult);
        setQuery("");
      } else if (!streamError) {
        setError("Stream ended without a done event");
      }
    } catch (e) {
      const err = e as Error;
      // B-NEW-21: distinguish (a) timeout abort (BFF too slow → show actionable
      // hint), (b) user-cancelled abort (silent — user knows they clicked),
      // (c) any other DOMException with empty name/message (network glitch,
      // Next 14 HMR teardown) — was producing "undefined: undefined" red text.
      if (err.name === "AbortError") {
        const reason = (ctrl.signal as AbortSignal & { reason?: unknown }).reason;
        if (reason === "user-cancelled") {
          // User clicked Cancel — they don't need an error message.
          return;
        }
        setError(
          `Timeout: backend did not respond in ${TIMEOUT_MS / 1000}s. ` +
            `Ollama may be loading the model — try again in a few seconds.`,
        );
      } else {
        const name = err.name || "Error";
        const message = err.message || "request failed (no further detail)";
        setError(`${name}: ${message}`);
      }
    } finally {
      clearTimeout(timeoutId);
      clearInterval(ticker);
      setLoading(false);
      setAbortController(null);
      setStreamProgress(null);
    }
  }

  function cancel() {
    abortController?.abort("user-cancelled");
  }

  // Tour driver: parent bumps autoQuery.nonce → run that query via the real
  // submit path. nonce (not text) is the trigger so repeating the same query
  // (the cache-hit step) still fires.
  useEffect(() => {
    if (autoQuery) submit(autoQuery.text);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoQuery?.nonce]);

  const locked = loading || !!disabled;

  return (
    <div className="card">
      <h2>Customer Query<StateBadge feature="customer-query" /></h2>
      <form
        className="query-form"
        onSubmit={(e) => {
          e.preventDefault();
          submit(query);
        }}
      >
        <textarea
          placeholder="Type a customer message..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          disabled={locked}
          // Opt out of Grammarly et al.: extensions that inject overlay nodes
          // into the field break React hydration and can cover the Send button.
          data-gramm="false"
          data-gramm_editor="false"
          data-enable-grammarly="false"
        />
        <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
          <select
            aria-label="channel"
            value={channel}
            onChange={(e) => setChannel(e.target.value)}
            disabled={locked}
          >
            <option value="whatsapp">WhatsApp</option>
            <option value="app">Mobile App</option>
            <option value="web">Web Chat</option>
            <option value="call_center">Call Center</option>
          </select>
          <button type="submit" disabled={locked || !query.trim()}>
            {loading
              ? `Processing… ${Math.floor(elapsedMs / 1000)}s / ~${TIMEOUT_MS / 1000}s`
              : "Send"}
          </button>
          {loading && (
            <button
              type="button"
              onClick={cancel}
              style={{ marginLeft: 8, background: "#7f1d1d", color: "#fecaca" }}
            >
              Cancel
            </button>
          )}
        </div>
        {customerId !== "demo" && (
          <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 2 }}>
            persona:{" "}
            <strong style={{ color: "#e2e8f0" }}>{customerId}</strong>{" "}
            {(() => {
              const c = customers.find((x) => x.customer_id === customerId);
              if (!c) return null;
              const persona = c.block_summaries?.persona;
              return persona ? <em>· {persona.slice(0, 80)}</em> : null;
            })()}
          </div>
        )}
        <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 4 }}>
          <label
            style={{ fontSize: 11, color: "#94a3b8", display: "flex", alignItems: "center", gap: 4, cursor: "pointer" }}
            title="Streaming SSE: heartbeats while the pipeline runs, then progressively reveals stages"
          >
            <input
              type="checkbox"
              checked={streamMode}
              onChange={(e) => setStreamMode(e.target.checked)}
              disabled={locked}
            />
            streaming mode
          </label>
          {loading && streamMode && streamProgress && (
            <span style={{ fontSize: 11, color: "#fbbf24" }}>
              {streamProgress.last_event === "stage" && streamProgress.stage_name
                ? `▸ ${streamProgress.stage_name}`
                : streamProgress.elapsed_s !== undefined
                ? `♥ alive @ ${streamProgress.elapsed_s}s`
                : null}
            </span>
          )}
        </div>
        <div className="examples">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => submit(ex)}
              disabled={locked}
            >
              {ex}
            </button>
          ))}
        </div>
        {error && (
          <div style={{ color: "#f87171", fontSize: 13 }}>{error}</div>
        )}
      </form>
    </div>
  );
}
