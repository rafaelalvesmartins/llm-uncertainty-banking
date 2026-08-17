import { defineConfig, devices } from "@playwright/test";

/**
 * E2E config for the Bridge UI frontend.
 *
 * - Uses the system Microsoft Edge (channel "msedge") so CI/dev does NOT need
 *   to download ~150 MB of Playwright browsers. Edge is Chromium-based.
 * - Reuses an already-running dev server on :3001 if present; otherwise boots
 *   `npm run dev -- -p 3001`. The Next proxy reads BRIDGE_API_URL (defaults to
 *   http://localhost:8000 via next.config.js), so the FastAPI backend must be
 *   up on :8000 for the data-bearing assertions to pass.
 */
const PORT = Number(process.env.E2E_PORT || 3001);
const BASE_URL = `http://localhost:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  // The backend (:8000) holds shared mutable state (semantic cache, audit
  // chain). Parallel workers clearing/populating the same cache race each
  // other, so run serially — the suite is fast (~30s).
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: BASE_URL,
    channel: "msedge",
    headless: true,
    trace: "retain-on-failure",
  },
  projects: [{ name: "edge", use: { ...devices["Desktop Chrome"], channel: "msedge" } }],
  webServer: {
    command: `npm run dev -- -p ${PORT}`,
    url: BASE_URL,
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
