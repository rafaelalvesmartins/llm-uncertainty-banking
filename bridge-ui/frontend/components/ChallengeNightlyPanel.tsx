"use client";

import { useCallback, useEffect, useState } from "react";
import StateBadge from "@/components/StateBadge";

/**
 * Continuous Effective Challenge — the governance screen's verdict.
 *
 * SR 11-7 asks for ongoing monitoring and effective challenge, and until now
 * this console described both as processes. This panel makes them a number:
 * it calls the same verdict rule the scheduled `lub challenge-nightly` job
 * runs, over this deployment's own labeled samples.
 *
 * Tri-state on purpose. INCONCLUSIVE is not a pass — it means the evidence
 * was insufficient to judge, and collapsing it into PASS is exactly how a
 * governance check goes quietly fail-open.
 */

interface Verdict {
  status: "PASS" | "FAIL" | "INCONCLUSIVE";
  reason: string;
  context: string;
  method: string;
  measured_ece: number | null;
  target_ece: number;
  n_samples: number;
  min_samples: number;
  meta_ece: number;
  meta_observations: number;
  pending_claims: number;
  generated_at: string;
  evidence_source?: string;
}

const CONTEXTS = ["regulatory-qa", "investor-advisory", "retail-credit", "fraud-alerts"];

// Each status gets a distinct colour: INCONCLUSIVE must not read as either a
// pass or a breach, because "we could not measure" is its own evidence.
const TONE: Record<Verdict["status"], { line: string; label: string }> = {
  PASS: { line: "var(--bc-pass-line)", label: "Within target" },
  FAIL: { line: "var(--bc-block-line)", label: "Target breached" },
  INCONCLUSIVE: { line: "var(--bc-flag-line)", label: "Not enough evidence to judge" },
};

function fmt(v: number | null | undefined, digits = 4): string {
  return v === null || v === undefined || !Number.isFinite(v) ? "—" : v.toFixed(digits);
}

export default function ChallengeNightlyPanel() {
  const [ctx, setCtx] = useState<string>("regulatory-qa");
  const [data, setData] = useState<Verdict | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (context: string) => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`/api/challenge/nightly?context=${encodeURIComponent(context)}`, {
        cache: "no-store",
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body?.detail || body?.error || `HTTP ${r.status}`);
      setData(body as Verdict);
    } catch (e) {
      setError((e as Error).message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(ctx);
  }, [ctx, load]);

  const tone = data ? TONE[data.status] : null;

  return (
    <section className="bc-card" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, fontSize: 15 }}>
          Continuous Effective Challenge <StateBadge feature="challenge-nightly" />
        </h2>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
          <label htmlFor="cec-context" style={{ fontSize: 11, color: "var(--bc-text-dim)" }}>
            Judge against
          </label>
          <select
            id="cec-context"
            value={ctx}
            onChange={(e) => setCtx(e.target.value)}
            style={{ fontSize: 12, padding: "2px 6px" }}
          >
            {CONTEXTS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="bc-btn ghost"
            onClick={() => void load(ctx)}
            disabled={loading}
            style={{ fontSize: 12, padding: "2px 8px" }}
          >
            {loading ? "Running…" : "Re-run"}
          </button>
        </div>
      </div>

      <p style={{ fontSize: 12.5, color: "var(--bc-text-mute)", margin: 0, lineHeight: 1.55 }}>
        <strong style={{ color: "var(--bc-text)" }}>What this does:</strong>{" "}
        {
          "Re-checks whether this deployment's stated confidence still matches how often it is actually right, and says so in three ways: within target, target breached, or not enough evidence to judge. It is the same check the nightly job runs — the screen and the build cannot disagree about what passing means."
        }
      </p>

      {error && (
        <div role="alert" style={{ fontSize: 12, color: "var(--bc-block-line)" }}>
          Could not run the challenge: {error}
        </div>
      )}

      {data && tone && (
        <>
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: 10,
              padding: "10px 12px",
              borderLeft: `3px solid ${tone.line}`,
              background: "var(--bc-surface-2)",
              borderRadius: 6,
            }}
          >
            <strong style={{ fontSize: 18, color: tone.line }}>{data.status}</strong>
            <span style={{ fontSize: 12.5, color: "var(--bc-text-mute)" }}>{tone.label}</span>
            <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--bc-text-dim)" }}>
              {new Date(data.generated_at).toLocaleString()}
            </span>
          </div>

          <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
            <tbody>
              <tr>
                <td style={{ padding: "3px 0", color: "var(--bc-text-dim)" }}>
                  Measured calibration error (ECE)
                </td>
                <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                  {fmt(data.measured_ece)}
                </td>
              </tr>
              <tr>
                <td style={{ padding: "3px 0", color: "var(--bc-text-dim)" }}>
                  Target for <code>{data.context}</code>
                </td>
                <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                  {fmt(data.target_ece)}
                </td>
              </tr>
              <tr>
                <td style={{ padding: "3px 0", color: "var(--bc-text-dim)" }}>
                  Labelled answers behind the verdict
                </td>
                <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                  {data.n_samples} <span style={{ color: "var(--bc-text-dim)" }}>(min {data.min_samples})</span>
                </td>
              </tr>
              <tr>
                <td style={{ padding: "3px 0", color: "var(--bc-text-dim)" }}>
                  Challenge layer&apos;s own calibration error
                </td>
                <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                  {fmt(data.meta_ece)}{" "}
                  <span style={{ color: "var(--bc-text-dim)" }}>
                    over {data.meta_observations} matured claim(s)
                  </span>
                </td>
              </tr>
              <tr>
                <td style={{ padding: "3px 0", color: "var(--bc-text-dim)" }}>
                  Claims still ripening (horizon not elapsed)
                </td>
                <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                  {data.pending_claims}
                </td>
              </tr>
            </tbody>
          </table>

          <div style={{ fontSize: 11.5, color: "var(--bc-text-mute)", lineHeight: 1.5 }}>
            {data.reason}
          </div>

          {data.evidence_source && (
            <div style={{ fontSize: 11, color: "var(--bc-text-dim)" }}>
              Evidence: {data.evidence_source}. The demo classifier&apos;s confidence is a keyword
              heuristic, so a breach here is the gate working on a deliberately simple model — not a
              defect being hidden.
            </div>
          )}
        </>
      )}
    </section>
  );
}
