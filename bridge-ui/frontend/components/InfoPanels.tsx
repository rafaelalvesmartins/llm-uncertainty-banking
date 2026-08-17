"use client";

import { useEffect, useState } from "react";
import StateBadge from "@/components/StateBadge";

interface Agent {
  name: string;
  status: string;
  intents: string[];
}

interface CacheStats {
  entries: number;
  max_entries: number;
  hits: number;
  misses: number;
  hit_rate: number;
  cost_saved_cents: number;
}

interface CustomerSummary {
  customer_id: string;
  blocks: string[];
  block_summaries: Record<string, string>;
}

interface DocSummary {
  id: string;
  source: string;
  text_preview: string;
}

interface DQDGStats {
  input_blocks: number;
  input_warns: number;
  output_blocks: number;
  output_warns: number;
  pii_masked_total: number;
  queries_with_pii: number;
  total_queries: number;
  pii_detection_rate: number;
  input_rules_active: number;
  output_rules_active: number;
}

interface CustomerDetail {
  customer_id: string;
  blocks: Record<
    string,
    { content: string; updated_at: number; update_count: number }
  >;
  rendered: string;
}

interface Props {
  refreshKey: number;
  // Which of the 6 cards to render, in order. Lets the dashboard place these
  // panels in different sections (e.g. DQ/DG under "Observability", Agents/RAG
  // under "Catalog") WITHOUT touching the shared fetch — the network logic is
  // unchanged; each mount just renders a subset. Defaults to all six.
  only?: CardKey[];
  // Which of the rendered cards should span the full grid width (card--wide).
  wide?: CardKey[];
}

type CardKey = "agents" | "cache" | "customers" | "rag" | "dq" | "dg";

export default function InfoPanels({ refreshKey, only, wide }: Props) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [cacheStats, setCacheStats] = useState<CacheStats | null>(null);
  const [cacheErr, setCacheErr] = useState<string | null>(null);
  const [customers, setCustomers] = useState<CustomerSummary[]>([]);
  const [docs, setDocs] = useState<DocSummary[]>([]);
  const [dqdg, setDqdg] = useState<DQDGStats | null>(null);
  const [expandedCustomer, setExpandedCustomer] = useState<CustomerDetail | null>(null);
  // Tracks whether the first poll completed (regardless of outcome) so
  // panels can distinguish "still loading" from "tried, backend unreachable".
  // Fix for v2-review bug: three panels (cache, dq, dg) were stuck on
  // "loading..." after a 502 because they couldn't tell those states apart.
  const [polled, setPolled] = useState(false);
  const [backendDown, setBackendDown] = useState(false);

  async function expandCustomer(id: string) {
    if (expandedCustomer?.customer_id === id) {
      setExpandedCustomer(null);
      return;
    }
    const r = await fetch(`/api/customers/${encodeURIComponent(id)}`, {
      cache: "no-store",
    });
    if (r.ok) {
      setExpandedCustomer(await r.json());
    }
  }

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const [a, c, cu, d, dq] = await Promise.all([
          fetch("/api/agents", { cache: "no-store" }).then((r) => r.json()),
          fetch("/api/cache", { cache: "no-store" }).then((r) => r.json()),
          fetch("/api/customers", { cache: "no-store" }).then((r) => r.json()),
          fetch("/api/corpus", { cache: "no-store" }).then((r) => r.json()),
          fetch("/api/dq-dg", { cache: "no-store" }).then((r) => r.json()),
        ]);
        if (cancelled) return;
        setAgents(a.agents || []);
        setCacheStats(c.error ? null : c);
        setCustomers(cu.customers || []);
        setDocs(d.documents || []);
        setDqdg(dq.error ? null : dq);
        // Backend is reachable iff at least one endpoint returned a
        // non-error payload. Single .error doesn't necessarily mean
        // outage (could be just one endpoint with a bug).
        const anyOk = !a.error || !c.error || !cu.error || !d.error || !dq.error;
        setBackendDown(!anyOk);
      } catch {
        if (!cancelled) setBackendDown(true);
      } finally {
        if (!cancelled) setPolled(true);
      }
    };
    tick();
    const interval = setInterval(() => { if (!document.hidden) tick(); }, 15000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [refreshKey]);

  const clearCache = async () => {
    setCacheErr(null);
    const del = await fetch("/api/cache", { method: "DELETE" }).catch(() => null);
    if (!del || !del.ok) {
      // Don't no-op silently (backend down / BRIDGE_AUTH on) — say so.
      setCacheErr(del ? `clear failed (HTTP ${del.status})` : "clear failed — backend unreachable");
      return;
    }
    // Re-fetch immediately so the numbers update without waiting for the 15s poll.
    const c = await fetch("/api/cache", { cache: "no-store" })
      .then((r) => r.json())
      .catch(() => ({ error: true }));
    setCacheStats(c.error ? null : c);
  };

  // Unified empty-state copy: every panel gives the same recovery hint when
  // the backend is unreachable, instead of mixed "loading..." / "no X loaded"
  // messages that confuse a dev about whether the system is broken or empty.
  const emptyState = (subject: string) => {
    if (backendDown) {
      return (
        <div className="empty">
          Service temporarily unavailable. Please try again in a moment.
        </div>
      );
    }
    if (!polled) {
      return <div className="empty">loading {subject}...</div>;
    }
    return <div className="empty">{subject} unavailable</div>;
  };

  const cardCls = (k: CardKey) => `card${wide?.includes(k) ? " card--wide" : ""}`;

  // Display-only PT labels; the raw keys stay as CSS classes / data keys.
  const STATUS_LABEL: Record<string, string> = {
    active: "active",
    standby: "on standby",
  };
  const BLOCK_LABEL: Record<string, string> = {
    persona: "Persona",
    preferences: "Preferences",
    risk_profile: "Risk profile",
  };

  const cards: Record<CardKey, JSX.Element> = {
    agents: (
      <div className={cardCls("agents")} key="agents">
        <h2>Registered Agents<StateBadge feature="registered-agents" /></h2>
        <div className="agent-list">
          {agents.length === 0 ? (
            emptyState("agents")
          ) : (
            agents.map((a) => (
              <div key={a.name} className={`agent-row ${a.status}`}>
                <div className="agent-meta">
                  <strong>{a.name}</strong>
                  <span className={`agent-status ${a.status}`}>{STATUS_LABEL[a.status] ?? a.status}</span>
                </div>
                <div className="agent-intents">
                  {a.intents.length === 0 ? (
                    <span className="muted">no intents linked</span>
                  ) : (
                    a.intents.map((i) => (
                      <span key={i} className="intent-pill">
                        {i}
                      </span>
                    ))
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    ),
    cache: (
      <div className={cardCls("cache")} key="cache">
        <h2>
          Similarity Cache
          <StateBadge feature="semantic-cache" />
          {cacheStats && cacheStats.entries > 0 && (
            <button
              type="button"
              className="link-btn"
              onClick={clearCache}
              title="Discard all cached entries"
            >
              clear
            </button>
          )}
          {cacheErr && (
            <span role="alert" style={{ fontSize: 11, color: "var(--bc-block-line, #ef4444)", marginLeft: 8 }}>{cacheErr}</span>
          )}
        </h2>
        {!cacheStats ? (
          emptyState("cache stats")
        ) : (
          <div className="cache-stats">
            <div className="cache-row">
              <span className="muted">Entries</span>
              <strong>
                {cacheStats.entries} / {cacheStats.max_entries}
              </strong>
            </div>
            <div className="cache-row">
              <span className="muted">Hit rate</span>
              <strong className={cacheStats.hit_rate > 0.5 ? "ok" : ""}>
                {(cacheStats.hit_rate * 100).toFixed(0)}% ({cacheStats.hits}/
                {cacheStats.hits + cacheStats.misses})
              </strong>
            </div>
            <div className="cache-row">
              <span className="muted">Cost saved</span>
              <strong className={cacheStats.cost_saved_cents > 0 ? "ok" : ""}>
                {cacheStats.cost_saved_cents.toFixed(2)}¢
              </strong>
            </div>
          </div>
        )}
      </div>
    ),
    customers: (
      <div className={cardCls("customers")} key="customers">
        <h2>Customer Memory ({customers.length})<StateBadge feature="customer-memory" /></h2>
        {customers.length === 0 ? (
          emptyState("customer profiles")
        ) : (
          <div className="customer-list">
            {customers.map((c) => {
              const isExpanded = expandedCustomer?.customer_id === c.customer_id;
              return (
                <div key={c.customer_id} className="customer-row">
                  <button
                    type="button"
                    className="customer-id-btn"
                    onClick={() => expandCustomer(c.customer_id)}
                  >
                    <span className="customer-id">{c.customer_id}</span>
                    <span className="muted">{isExpanded ? "▾" : "▸"}</span>
                  </button>
                  {isExpanded && expandedCustomer ? (
                    <div className="customer-detail">
                      {Object.entries(expandedCustomer.blocks).map(
                        ([name, block]) => (
                          <div key={name} className="customer-block-full">
                            <div className="block-name">
                              {BLOCK_LABEL[name] ?? name} · updated {block.update_count}x
                            </div>
                            <div className="block-content-full">
                              {block.content}
                            </div>
                          </div>
                        ),
                      )}
                    </div>
                  ) : (
                    c.blocks.map((b) => (
                      <div key={b} className="customer-block">
                        <span className="block-name">{BLOCK_LABEL[b] ?? b}:</span>
                        <span className="block-content">
                          {c.block_summaries[b]}
                        </span>
                      </div>
                    ))
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    ),
    rag: (
      <div className={cardCls("rag")} key="rag">
        <h2>Knowledge base ({docs.length} docs)<StateBadge feature="rag-corpus" /></h2>
        {docs.length === 0 ? (
          emptyState("RAG documents")
        ) : (
          <div className="doc-list">
            {docs.map((d) => (
              <div key={d.id} className="doc-row">
                <div className="doc-meta">
                  <span className="doc-source">📄 {d.source}</span>
                  <span className="doc-id muted">{d.id}</span>
                </div>
                <div className="doc-preview">{d.text_preview}...</div>
              </div>
            ))}
          </div>
        )}
      </div>
    ),
    dq: (
      <div className={cardCls("dq")} key="dq">
        <h2>Data quality checks<StateBadge feature="data-quality" /></h2>
        {!dqdg ? (
          emptyState("DQ/DG stats")
        ) : (
          <div className="cache-stats">
            <div className="cache-row">
              <span className="muted">Active input rules</span>
              <strong>{dqdg.input_rules_active}</strong>
            </div>
            <div className="cache-row">
              <span className="muted">Active output rules</span>
              <strong>{dqdg.output_rules_active}</strong>
            </div>
            <div className="cache-row">
              <span className="muted">Input blocks (rejected)</span>
              <strong className={dqdg.input_blocks > 0 ? "warn" : "ok"}>
                {dqdg.input_blocks}
              </strong>
            </div>
            <div className="cache-row">
              <span className="muted">Output blocks (suppressed)</span>
              <strong className={dqdg.output_blocks > 0 ? "warn" : "ok"}>
                {dqdg.output_blocks}
              </strong>
            </div>
            <div className="cache-row">
              <span className="muted">Total warnings</span>
              <strong>{dqdg.input_warns + dqdg.output_warns}</strong>
            </div>
          </div>
        )}
      </div>
    ),
    dg: (
      <div className={cardCls("dg")} key="dg">
        <h2>Privacy &amp; data protection<StateBadge feature="data-governance" /></h2>
        {!dqdg ? (
          emptyState("DQ/DG stats")
        ) : (
          <div className="cache-stats">
            <div className="cache-row">
              <span className="muted">PII detection rate</span>
              <strong className={dqdg.pii_detection_rate > 0 ? "warn" : "muted"}>
                {(dqdg.pii_detection_rate * 100).toFixed(0)}%
              </strong>
            </div>
            <div className="cache-row">
              <span className="muted">Queries with PII</span>
              <strong>
                {dqdg.queries_with_pii} / {dqdg.total_queries}
              </strong>
            </div>
            <div className="cache-row">
              <span className="muted">PII fragments masked</span>
              <strong className="ok">{dqdg.pii_masked_total}</strong>
            </div>
            <div className="cache-row" style={{ flexDirection: "column", alignItems: "flex-start" }}>
              <span className="muted" style={{ marginBottom: 4 }}>
                LGPD Compliance
              </span>
              <span style={{ fontSize: 11, color: "var(--bc-text-dim)" }}>
                CPF/CNPJ/account/card masked before the LLM call. The
                classification drives cache + audit retention per{" "}
                <abbr
                  title="BCB Resolution No. 4,893 — requires a tamper-evident audit trail for financial systems."
                  style={{ textDecoration: "underline dotted", cursor: "help" }}
                >
                  BCB 4893
                </abbr>
                .
              </span>
            </div>
          </div>
        )}
      </div>
    ),
  };

  const order: CardKey[] = only ?? ["agents", "cache", "customers", "rag", "dq", "dg"];
  return <>{order.map((k) => cards[k])}</>;
}
