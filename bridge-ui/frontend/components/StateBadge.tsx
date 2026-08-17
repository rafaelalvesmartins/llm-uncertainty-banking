"use client";

import { FEATURE_MAP, FeatureId } from "@/lib/featureMap";

/**
 * Honesty badge (Bloco A1) rendered inside a panel's <h2>. Reads the panel's
 * state + description from the single-source-of-truth FEATURE_MAP so the
 * label can't drift from what the Feature Map (A5) shows. The native `title`
 * tooltip explains in one phrase what the feature does and where its data
 * comes from — matching the existing `title=`-based tooltips in the app.
 */
export default function StateBadge({ feature }: { feature: FeatureId }) {
  const f = FEATURE_MAP[feature];
  const tooltip = `${f.state} — ${f.what}\n\nEndpoints: ${f.endpoints.join(", ")}`;
  return (
    <span
      className={`state-badge ${f.state.toLowerCase()}`}
      title={tooltip}
      aria-label={`${f.state}: ${f.what}`}
    >
      {f.state}
    </span>
  );
}
