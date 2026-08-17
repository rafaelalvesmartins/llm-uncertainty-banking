"use client";

import { useEffect, useState } from "react";
import ControlsPanel from "@/components/ControlsPanel";
import IntegrationsPanel from "@/components/IntegrationsPanel";
import InfoPanels from "@/components/InfoPanels";
import HowThisWorks from "@/components/HowThisWorks";
import Disclosure from "@/components/console/Disclosure";
import DecisionLegend from "@/components/console/DecisionLegend";
import { getHealth } from "@/components/console/api";
import type { Health } from "@/components/console/types";

/**
 * Configuração — thin console wrapper hosting the existing legacy panels.
 *
 * ControlsPanel and IntegrationsPanel self-fetch (no props). InfoPanels takes a
 * refreshKey (static 0 here). HowThisWorks needs the backend mode, so we fetch
 * /health once and feed it the real backend name + real/demo flag.
 */
export default function Configuracao() {
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    let active = true;
    getHealth()
      .then((h) => {
        if (active) setHealth(h);
      })
      .catch(() => {
        /* leave health null — HowThisWorks falls back to placeholders */
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <p style={{ fontSize: 12.5, color: "var(--bc-text-mute)", margin: 0, lineHeight: 1.55 }}>
        <strong style={{ color: "var(--bc-text)" }}>What this does:</strong>{" "}
        {"These are the system settings. Most panels are read-only; the controls below let you adjust how cautious the AI is and whether it reuses recent answers. The rest shows what is connected and what the AI reads to answer."}
      </p>
      <ul style={{ fontSize: 12.5, color: "var(--bc-text-mute)", margin: 0, paddingLeft: 18, lineHeight: 1.55 }}>
        <li>
          <strong style={{ color: "var(--bc-text)" }}>How cautious the AI is</strong>{" "}
          {"(the slider): lower = the AI answers more on its own; higher = more answers get reviewed, the customer is re-asked to clarify, or the question is sent to a human. Most setups sit around 0.60–0.70."}
        </li>
        <li>
          <strong style={{ color: "var(--bc-text)" }}>Reuse recent answers</strong>{" "}
          {"(the cache toggle): ON reuses the answer to an identical question, so it is faster and cheaper. OFF re-runs every question from scratch — safest when the underlying data changes often."}
        </li>
      </ul>
      <DecisionLegend title="The four outcomes the caution slider moves between" />
      <ControlsPanel />
      <Disclosure title="Advanced" hint="connections, knowledge, cache & what's real">
        <IntegrationsPanel />
        <InfoPanels refreshKey={0} />
        <HowThisWorks
          backendName={health?.backend ?? "—"}
          backendIsReal={health?.backend_is_real ?? false}
        />
      </Disclosure>
    </div>
  );
}
