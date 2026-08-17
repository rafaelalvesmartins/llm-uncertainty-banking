"use client";

import { useCallback, useEffect, useState } from "react";
import StateBadge from "@/components/StateBadge";
import { apiErrorText } from "@/lib/apiError";
import { useAppContext } from "@/components/AppContextProvider";

interface Settings {
  guard_threshold: number;
  guard_threshold_default: number;
  guard_threshold_min: number;
  guard_threshold_max: number;
  cache_enabled: boolean;
  backend: string;
  backend_is_real: boolean;
  backend_mutable: boolean;
}

/**
 * Bloco A2 — real runtime controls. Unlike the old static InfoPanels, these
 * write to the backend (/settings) and the effect is visible on the very next
 * query: lowering the guard threshold shifts the PASSTHROUGH/FLAG/REASK/
 * ESCALATE mix shown in Bridge Metrics; toggling the cache off makes repeat
 * queries re-run the whole pipeline (watch Pipeline Trace stage 1).
 *
 * The backend selector is shown read-only (STATIC) — the LLM backend is fixed
 * at startup, so we don't pretend a runtime swap that doesn't exist.
 */
export default function ControlsPanel() {
  const { operator } = useAppContext();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [pendingThreshold, setPendingThreshold] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/settings", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then((s: Settings) => setSettings(s))
      .catch(() => setError("backend unreachable"));
  }, []);

  const apply = useCallback(
    async (update: Partial<Pick<Settings, "guard_threshold" | "cache_enabled">>) => {
      setSaving(true);
      setError(null);
      setSavedMsg(null);
      try {
        const r = await fetch("/api/settings", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          // Attribute the change so it lands on the audit hash-chain with an operator.
          body: JSON.stringify({ ...update, operator }),
        });
        const data = await r.json();
        if (!r.ok) {
          setError(apiErrorText(data, r.status));
          setPendingThreshold(null); // revert thumb to server reality + re-enable the 15s poll
          return;
        }
        setSettings(data);
        setPendingThreshold(null);
        setSavedMsg(
          update.guard_threshold !== undefined
            ? `✓ threshold set to ${Number(data.guard_threshold).toFixed(2)} — applies to the next query`
            : update.cache_enabled !== undefined
            ? `✓ cache ${data.cache_enabled ? "on" : "off"}`
            : "✓ saved",
        );
      } catch (e) {
        setError((e as Error).message);
        setPendingThreshold(null);
      } finally {
        setSaving(false);
      }
    },
    [operator],
  );

  // Persist a moved threshold reliably — a beat after the last change — instead of
  // only on mouse/touch release (which missed keyboard and felt flaky).
  useEffect(() => {
    if (pendingThreshold === null || !settings || pendingThreshold.toFixed(2) === settings.guard_threshold.toFixed(2)) return;
    const t = setTimeout(() => apply({ guard_threshold: pendingThreshold }), 300);
    return () => clearTimeout(t);
  }, [pendingThreshold, settings, apply]);

  // Auto-refresh so the panel reflects out-of-band changes (raw API / another
  // operator) without a manual reload — symmetry with the Policies view. Skip
  // while the user is mid-edit (saving, or a pending slider value) so a poll
  // never clobbers in-progress input.
  useEffect(() => {
    const id = setInterval(() => {
      if (document.hidden || saving || pendingThreshold !== null) return;
      fetch("/api/settings", { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
        .then((s: Settings) => setSettings(s))
        .catch(() => {
          /* keep the last good settings on a transient poll failure */
        });
    }, 15000);
    return () => clearInterval(id);
  }, [saving, pendingThreshold]);

  if (error && !settings) {
    return (
      <div className="card">
        <h2>
          Runtime controls
          <StateBadge feature="demo-controls" />
        </h2>
        <div className="empty">Backend unreachable ({error}).</div>
      </div>
    );
  }
  if (!settings) {
    return (
      <div className="card">
        <h2>
          Runtime controls
          <StateBadge feature="demo-controls" />
        </h2>
        <div className="empty">loading controls...</div>
      </div>
    );
  }

  const shownThreshold = pendingThreshold ?? settings.guard_threshold;
  const isDirty = pendingThreshold !== null && pendingThreshold.toFixed(2) !== settings.guard_threshold.toFixed(2);

  return (
    <div className="card">
      <h2>
        Runtime controls
        <StateBadge feature="demo-controls" />
      </h2>

      <div className="control-row">
        <div className="control-label">
          <span className="state-badge live">LIVE</span>
          <strong title="Minimum confidence for the model to answer on its own; below this it flags, re-asks, or escalates. (a.k.a. the uncertainty guard threshold)">
            How cautious the AI is
          </strong>
          <span className="muted control-hint">
            lower → the AI answers more on its own · higher → it asks to clarify or escalates more
          </span>
        </div>
        <div className="control-input">
          <input
            type="range"
            min={settings.guard_threshold_min}
            max={settings.guard_threshold_max}
            step={0.05}
            value={shownThreshold}
            onChange={(e) => setPendingThreshold(parseFloat(e.target.value))}
            aria-label="guard threshold"
          />
          <span className={`control-value ${isDirty ? "dirty" : ""}`}>
            {shownThreshold.toFixed(2)}
            {shownThreshold.toFixed(2) === settings.guard_threshold_default.toFixed(2) && " (default)"}
          </span>
          <span className="muted control-hint">
            lower = the AI answers more on its own · higher = more get reviewed / re-asked / sent to a human (~0.60–0.70 typical) · also adjustable in Policies → Advanced
          </span>
        </div>
      </div>

      <div className="control-row">
        <div className="control-label">
          <span className="state-badge live">LIVE</span>
          <strong>Similarity cache</strong>
          <span className="muted control-hint">
            off → every query re-runs the full pipeline (see Pipeline Trace · stage 1)
          </span>
        </div>
        <div className="control-input">
          <button
            type="button"
            className={`toggle ${settings.cache_enabled ? "on" : "off"}`}
            onClick={() => {
              // Capture + clear the dirty threshold BEFORE applying so the slider's
              // debounce timer is cancelled (its effect re-runs on the null change)
              // — otherwise the bundled write here + the timer fire two PUTs.
              const upd = {
                cache_enabled: !settings.cache_enabled,
                ...(isDirty ? { guard_threshold: pendingThreshold! } : {}),
              };
              if (isDirty) setPendingThreshold(null);
              apply(upd);
            }}
            disabled={saving}
            aria-pressed={settings.cache_enabled}
          >
            {settings.cache_enabled ? "ON" : "OFF"}
          </button>
          <span className="muted control-hint">
            ON reuses the answer to identical questions (faster, cheaper) · OFF re-runs every query (safest when data changes often)
          </span>
        </div>
      </div>

      <div className="control-row">
        <div className="control-label">
          <span className="state-badge static">STATIC</span>
          <strong>LLM backend</strong>
          <span className="muted control-hint">
            set at startup — not swappable at runtime in this demo
          </span>
        </div>
        <div className="control-input">
          <code>{settings.backend}</code>
          <span className="muted" style={{ marginLeft: 8 }}>
            {settings.backend_is_real ? "(real model)" : "(canned)"}
          </span>
        </div>
      </div>

      {error && <div className="warn" style={{ marginTop: 8, fontSize: 12 }}>⚠ {error}</div>}
      {saving && <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>applying…</div>}
      {!saving && savedMsg && <div role="status" style={{ marginTop: 8, fontSize: 12, color: "var(--bc-pass-line, #22c55e)" }}>{savedMsg}</div>}
    </div>
  );
}
