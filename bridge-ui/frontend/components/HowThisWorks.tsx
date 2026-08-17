"use client";

import { useEffect, useState } from "react";
import {
  FEATURE_IDS,
  FEATURE_MAP,
  endpointPath,
  normalizePath,
} from "@/lib/featureMap";

interface Props {
  backendName: string;
  backendIsReal: boolean;
}

// Infra/diagnostic paths intentionally excluded from the Feature Map (not
// user-facing features). The reverse cross-check below ignores these; anything
// else live in /openapi.json but absent from FEATURE_MAP is flagged.
const INFRA_ALLOWLIST = new Set(["/health", "/version", "/metrics/prometheus"].map(normalizePath));

/**
 * Bloco A1 header ("O que é real / How this works") + Bloco A5 Feature Map.
 *
 * Collapsed by default to one honest line. Expanded, it shows the backend
 * mode (fake/ollama, from /health via props), a LIVE/MOCK/STATIC legend, and
 * a table of every panel with its state, endpoints, and one-phrase purpose.
 *
 * Each endpoint is cross-checked against the live /openapi.json: ✓ = the
 * server exposes that path, ✗ = declared here but missing upstream (the map
 * drifted). This keeps the Feature Map honest instead of a hand-maintained
 * list that rots.
 */
export default function HowThisWorks({ backendName, backendIsReal }: Props) {
  const [open, setOpen] = useState(false);
  const [openapiPaths, setOpenapiPaths] = useState<Set<string> | null>(null);
  const [openapiRawPaths, setOpenapiRawPaths] = useState<string[] | null>(null);
  const [openapiError, setOpenapiError] = useState(false);

  useEffect(() => {
    if (!open || openapiPaths || openapiError) return;
    fetch("/api/openapi", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then((spec) => {
        const paths = spec?.paths ? Object.keys(spec.paths) : [];
        setOpenapiPaths(new Set(paths.map(normalizePath)));
        setOpenapiRawPaths(paths);
      })
      .catch(() => setOpenapiError(true));
  }, [open, openapiPaths, openapiError]);

  const checkEndpoint = (endpoint: string): boolean | null => {
    if (!openapiPaths) return null; // unknown (not loaded / errored)
    return openapiPaths.has(normalizePath(endpointPath(endpoint)));
  };

  // Reverse cross-check (A5): every path the server exposes should be in the
  // Feature Map or the infra allowlist — otherwise it silently escapes the
  // honesty layer. This catches NEW endpoints the forward ✓/✗ check can't.
  const declaredPaths = new Set(
    FEATURE_IDS.flatMap((id) =>
      FEATURE_MAP[id].endpoints.map((e) => normalizePath(endpointPath(e))),
    ),
  );
  const uncoveredPaths = (openapiRawPaths ?? []).filter(
    (p) => !declaredPaths.has(normalizePath(p)) && !INFRA_ALLOWLIST.has(normalizePath(p)),
  );

  const liveCount = FEATURE_IDS.filter((id) => FEATURE_MAP[id].state === "LIVE").length;
  const mockCount = FEATURE_IDS.filter((id) => FEATURE_MAP[id].state === "MOCK").length;

  return (
    <div className="how-it-works">
      <button
        type="button"
        className="how-toggle"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className="how-toggle-caret">{open ? "▾" : "▸"}</span>
        <strong>What is real in this demo?</strong>
        <span className="muted">
          backend <code>{backendName}</code>
          {backendIsReal ? " (LLM real)" : " (canned)"} · {liveCount} LIVE · {mockCount} MOCK
        </span>
      </button>

      {open && (
        <div className="how-body">
          <p className="how-intro">
            The backend is running in{" "}
            <strong>{backendIsReal ? "ollama (real LLM)" : "fake (canned responses)"}</strong>{" "}
            mode. Each panel below declares what it does and where its data comes from. Production
            gaps are documented in <code>DEMO_SCOPE.md</code>.
          </p>

          <p className="how-legend-why muted">
            Each panel shows whether it pulls live data (LIVE), uses demo data (MOCK), or is just
            informational (STATIC) — so you know which controls are real vs demo.
          </p>

          <div className="how-legend">
            <span className="state-badge live">LIVE</span> calls the backend and shows real state ·
            <span className="state-badge mock">MOCK</span> real endpoint, pre-seeded data ·
            <span className="state-badge static">STATIC</span> informational only, no call
          </div>

          <div className="how-openapi-note muted">
            {openapiError
              ? "⚠ /openapi.json unavailable — could not validate endpoints (backend offline?)."
              : openapiPaths
                ? "✓ = endpoint confirmed in server /openapi.json · ✗ = declared here but missing (map out of date)."
                : "loading… /openapi.json to validate endpoints…"}
          </div>

          {openapiRawPaths && uncoveredPaths.length > 0 && (
            <div className="how-openapi-note warn">
              ⚠ {uncoveredPaths.length} endpoint(s) on the server missing from the Feature Map
              (outside the infra allowlist):{" "}
              {uncoveredPaths.map((p, i) => (
                <span key={p}>
                  {i > 0 ? " · " : ""}
                  <code>{p}</code>
                </span>
              ))}
            </div>
          )}

          <table className="feature-map">
            <thead>
              <tr>
                <th>Feature</th>
                <th>State</th>
                <th>Endpoints</th>
                <th>What it does / data source</th>
              </tr>
            </thead>
            <tbody>
              {FEATURE_IDS.map((id) => {
                const f = FEATURE_MAP[id];
                return (
                  <tr key={id}>
                    <td>{f.name}</td>
                    <td>
                      <span className={`state-badge ${f.state.toLowerCase()}`}>{f.state}</span>
                    </td>
                    <td className="feature-map-endpoints">
                      {f.endpoints.map((e) => {
                        const ok = checkEndpoint(e);
                        return (
                          <div key={e} className="feature-map-endpoint">
                            <span
                              className={
                                ok === null ? "muted" : ok ? "ok" : "warn"
                              }
                              title={
                                ok === null
                                  ? "validation pending"
                                  : ok
                                    ? "confirmed in /openapi.json"
                                    : "missing from /openapi.json — map out of date"
                              }
                            >
                              {ok === null ? "·" : ok ? "✓" : "✗"}
                            </span>{" "}
                            <code>{e}</code>
                          </div>
                        );
                      })}
                    </td>
                    <td className="muted">{f.what}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          <p className="how-footer muted">
            Details and limitations per feature (production gaps):{" "}
            <code>bridge-ui/DEMO_SCOPE.md</code> in the repository.
          </p>
        </div>
      )}
    </div>
  );
}
