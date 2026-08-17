"use client";

import { useEffect, useState, type ComponentType } from "react";
import ConsoleShell, { CONSOLE_VIEWS, ViewId } from "@/components/console/ConsoleShell";
import GlobalSearch from "@/components/console/GlobalSearch";
import GoldenPath from "@/components/console/GoldenPath";
import GuidedTour from "@/components/console/GuidedTour";
import Painel from "@/components/console/views/Painel";
import Fluxo from "@/components/console/views/Fluxo";
import Conexoes from "@/components/console/views/Conexoes";
import Politicas from "@/components/console/views/Politicas";
import Auditoria from "@/components/console/views/Auditoria";
import Observabilidade from "@/components/console/views/Observabilidade";
import Governanca from "@/components/console/views/Governanca";
import Configuracao from "@/components/console/views/Configuracao";
import { getHealth } from "@/components/console/api";
import type { Health } from "@/components/console/types";

const VIEWS: Record<ViewId, ComponentType> = {
  dashboard: Painel,
  flow: Fluxo,
  connections: Conexoes,
  policies: Politicas,
  audit: Auditoria,
  observability: Observabilidade,
  governance: Governanca,
  config: Configuracao,
};

// Resolve the URL hash to a view. `unmatched` carries the raw slug when the hash
// was non-empty but matched nothing — so the page can say so explicitly instead
// of silently snapping to the dashboard (which read as a broken deep-link).
function resolveHash(): { id: ViewId; unmatched: string | null } {
  if (typeof window === "undefined") return { id: "dashboard", unmatched: null };
  const h = window.location.hash.replace("#", "").toLowerCase();
  if (!h) return { id: "dashboard", unmatched: null };
  // Consolidated rail: Sessions is now Audit's "By customer" view; Metrics is the
  // Dashboard. Keep the old deep-links working by redirecting them.
  if (h === "sessions") {
    window.sessionStorage.setItem("bridge:auditView", "by-customer");
    return { id: "audit", unmatched: null };
  }
  if (h === "metrics") return { id: "dashboard", unmatched: null };
  if (CONSOLE_VIEWS.some((v) => v.id === h)) return { id: h as ViewId, unmatched: null };
  // Tolerate a label-derived abbreviation (e.g. "#observ" → "observability") via a
  // unique id prefix before treating the hash as unknown.
  const byPrefix = CONSOLE_VIEWS.filter((v) => v.id.startsWith(h));
  if (byPrefix.length === 1) return { id: byPrefix[0].id, unmatched: null };
  return { id: "dashboard", unmatched: h };
}

export default function ConsolePage() {
  const [active, setActive] = useState<ViewId>("dashboard");
  const [routeNotice, setRouteNotice] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthy, setHealthy] = useState<boolean | null>(null);

  useEffect(() => {
    const apply = () => {
      const { id, unmatched } = resolveHash();
      setActive(id);
      setRouteNotice(unmatched ? `Unknown section “#${unmatched}” — showing Dashboard.` : null);
    };
    apply();
    window.addEventListener("hashchange", apply);
    return () => window.removeEventListener("hashchange", apply);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const check = () =>
      getHealth()
        .then((h) => {
          if (!cancelled) {
            setHealth(h);
            setHealthy(true);
          }
        })
        .catch(() => {
          if (!cancelled) setHealthy(false);
        });
    check();
    const id = setInterval(() => { if (!document.hidden) check(); }, 15000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  function selectView(id: ViewId) {
    if (typeof window !== "undefined") window.location.hash = id;
    setActive(id);
    setRouteNotice(null);
  }

  const Active = VIEWS[active];
  return (
    <ConsoleShell
      active={active}
      onSelect={selectView}
      backendName={health?.backend ?? "fake"}
      backendIsReal={health?.backend_is_real === true}
      localOnly={health?.local_only === true}
      healthy={healthy}
    >
      <GlobalSearch />
      {active === "dashboard" && <GoldenPath />}
      {routeNotice && (
        <div
          role="status"
          style={{
            marginBottom: 16,
            padding: "8px 12px",
            display: "flex",
            alignItems: "center",
            gap: 10,
            fontSize: 13,
            color: "var(--bc-text)",
            background: "var(--bc-surface-2)",
            border: "1px solid var(--bc-flag-line)",
            borderRadius: 8,
          }}
        >
          <span style={{ flex: 1 }}>{routeNotice}</span>
          <button
            type="button"
            className="bc-btn ghost"
            onClick={() => setRouteNotice(null)}
            style={{ fontSize: 12, padding: "2px 8px" }}
          >
            Dismiss
          </button>
        </div>
      )}
      <Active />
      <GuidedTour />
    </ConsoleShell>
  );
}
