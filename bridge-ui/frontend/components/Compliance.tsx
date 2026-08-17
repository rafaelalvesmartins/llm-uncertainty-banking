"use client";

import { useEffect, useState } from "react";
import StateBadge from "@/components/StateBadge";
import GovernanceGlossary from "@/components/console/GovernanceGlossary";

interface Control {
  control_id: string;
  control_title: string;
  description: string;
}

interface MetricDetail {
  name: string;
  target?: number;
  comparator?: "<=" | ">=";
  observed?: number;
  source?: string;
  status: "pass" | "fail" | "pending" | "observed" | "synthetic";
}

interface Pillar {
  name: string;
  controls: Control[];
  metrics: string[];
  metric_details?: MetricDetail[];
}

interface Sr117Data {
  title: string;
  crosswalk_key: string;
  regime: string | null;
  pillars: Pillar[];
}

function formatValue(v?: number | string | null): string {
  if (v === undefined || v === null || v === "") return "—";
  // SR 11-7 endpoint can return strings (e.g. "pending" placeholders nested
  // under observed) or numbers; coerce defensively so the UI doesn't blow
  // up with "v.toFixed is not a function" on unexpected payload shapes.
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return String(v);
  return n.toFixed(n >= 1 ? 2 : 3);
}

// Readable labels for the raw backend metric keys (snake_case). Regulatory
// term names stay as-is; unknown keys fall back to a de-underscored form.
const METRIC_LABEL: Record<string, string> = {
  ece: "ECE",
  brier: "Brier",
  brier_score: "Brier",
  accuracy: "Accuracy",
  refusal_auroc: "Refusal AUROC",
  auroc: "AUROC",
  matthews_correlation: "Matthews correlation",
  miscalibration_area: "Miscalibration area",
  sharpness: "Sharpness",
  git_sha: "git SHA",
  dataset_hash: "Dataset hash",
  dataset_version: "Dataset version",
  missing_ratio: "Missing ratio",
  package_versions: "Package versions",
};
const prettyMetric = (n: string): string =>
  METRIC_LABEL[n] ?? n.replace(/_/g, " ");

// One-sentence plain meaning + which direction is "good", shown on hover so a
// non-technical reader can make sense of the otherwise-cryptic metric pills.
const METRIC_HELP: Record<string, string> = {
  ece: "ECE — how well the model knows its own confidence; lower is better.",
  brier: "Brier — overall accuracy of the model's probability guesses; lower is better.",
  brier_score: "Brier — overall accuracy of the model's probability guesses; lower is better.",
  accuracy: "Accuracy — share of answers the model got right; higher is better.",
  refusal_auroc: "Refusal AUROC — how well the model declines when it shouldn't answer; higher is better.",
  auroc: "AUROC — how well the model separates right from wrong answers; higher is better.",
  matthews_correlation: "Matthews correlation — a balanced score of correct vs. wrong, even with uneven data; higher is better.",
  miscalibration_area: "Miscalibration area — total gap between stated confidence and reality; lower is better.",
  sharpness: "Sharpness — how decisive (not wishy-washy) the model's confidence is; higher is better, as long as it stays accurate.",
};

function renderMetric(m: MetricDetail | string) {
  const detail: MetricDetail =
    typeof m === "string" ? { name: m, status: "pending" } : m;
  const cls = `metric-pill status-${detail.status}`;
  // B-NEW9 fix (v5 review): explicit "(demo)" suffix when status=synthetic
  // so the value can't be misread as a real eval. The purple dotted pill
  // already differs visually, but a literal text label closes the gap for
  // anyone reading the dashboard at a glance.
  const isSynthetic = detail.status === "synthetic";
  const baseValueLabel =
    detail.observed !== undefined
      ? `${formatValue(detail.observed)}${
          detail.target !== undefined
            ? ` ${detail.comparator || ""} ${formatValue(detail.target)}`
            : ""
        }`
      : detail.target !== undefined
        ? `target ${detail.comparator || ""} ${formatValue(detail.target)}`
        : "pending";
  const valueLabel = isSynthetic ? `${baseValueLabel} (demo)` : baseValueLabel;
  const help = METRIC_HELP[detail.name];
  const provenance = detail.source
    ? `source: ${detail.source}${isSynthetic ? " — not a real measurement" : ""}`
    : "no evaluation result connected yet";
  return (
    <span
      key={detail.name}
      className={cls}
      title={help ? `${help}\n${provenance}` : provenance}
    >
      <strong>{prettyMetric(detail.name)}</strong>
      <span className="metric-value">{valueLabel}</span>
    </span>
  );
}

export default function Compliance() {
  const [data, setData] = useState<Sr117Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | undefined;
    const attempt = () => {
      fetch("/api/compliance/sr-11-7", { cache: "no-store" })
        .then(async (r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          const json = await r.json();
          if (cancelled) return;
          setData(json);
          setError(null);
          if (timer) clearInterval(timer); // healed — stop polling
        })
        .catch((err: unknown) => {
          if (!cancelled) setError(err instanceof Error ? err.message : String(err));
        });
    };
    attempt();
    timer = setInterval(() => { if (!document.hidden) attempt(); }, 15000);
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, []);

  if (error) {
    return (
      <div className="card card--wide">
        <h2>SR 11-7 Compliance</h2>
        <div className="empty error" role="alert">backend unreachable ({error})</div>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="card card--wide">
        <h2>SR 11-7 Compliance</h2>
        <div className="empty">loading…</div>
      </div>
    );
  }

  return (
    <div className="card card--wide">
      <h2>
        SR 11-7 Compliance
        <StateBadge feature="sr-11-7" />
        <span className="card-subtitle" title={data.title}>
          Fed / OCC model risk management — {data.crosswalk_key}
        </span>
      </h2>
      <p className="card-subtitle" style={{ margin: "0 0 12px" }}>
        Shows the evidence this model produces toward the US supervisory guidance
        (SR 11-7) for governing, validating and monitoring models — the letter
        labels are lub&rsquo;s crosswalk convention, not verbatim citations. Hover any
        metric for a plain-language meaning.
      </p>
      <GovernanceGlossary terms={["SR 11-7", "Effective challenge"]} />
      <div className="pillar-grid" style={{ marginTop: 12 }}>
        {data.pillars.map((pillar) => (
          <div key={pillar.name} className="pillar-card">
            <div className="pillar-title">{pillar.name}</div>
            <div className="pillar-meta">
              {pillar.controls.length} control
              {pillar.controls.length === 1 ? "" : "s"} ·{" "}
              {pillar.metrics.length} metric
              {pillar.metrics.length === 1 ? "" : "s"}
            </div>

            <div className="control-list">
              {pillar.controls.map((c) => {
                const isOpen = expanded === c.control_id;
                return (
                  <div key={c.control_id}>
                    <button
                      type="button"
                      className="control-button"
                      onClick={() =>
                        setExpanded(isOpen ? null : c.control_id)
                      }
                      title={c.control_title}
                    >
                      {isOpen ? "▾" : "▸"} {c.control_id}
                    </button>
                    {isOpen && (
                      <div className="control-detail">
                        <strong>{c.control_title}</strong>
                        {c.description}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="metric-list">
              {(pillar.metric_details && pillar.metric_details.length > 0
                ? pillar.metric_details
                : pillar.metrics
              ).map(renderMetric)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
