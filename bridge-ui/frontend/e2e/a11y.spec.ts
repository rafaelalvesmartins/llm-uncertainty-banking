import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * Accessibility smoke test. Loads the console and each rail view and fails on any
 * serious/critical axe violation. Landed after the Wave-4 a11y fixes (planning/38)
 * so it starts green — a citable artifact for a bank's vendor/VPAT questionnaire.
 * The shell renders client-side, so this does not depend on the backend.
 */

// The consolidated rail's view ids (see ConsoleShell.CONSOLE_VIEWS) plus /legacy.
const VIEW_HASHES = [
  "dashboard",
  "flow",
  "connections",
  "policies",
  "audit",
  "observability",
  "governance",
  "config",
] as const;

async function seriousViolations(page: import("@playwright/test").Page) {
  const results = await new AxeBuilder({ page }).analyze();
  return results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

test.describe("accessibility (axe)", () => {
  for (const hash of VIEW_HASHES) {
    test(`console #${hash} has no serious/critical a11y violations`, async ({ page }) => {
      await page.goto(`/console#${hash}`);
      await page.locator(".bc-content").waitFor();
      const v = await seriousViolations(page);
      expect(v, `axe: ${v.map((x) => x.id).join(", ")}`).toEqual([]);
    });
  }

  test("legacy dashboard has no serious/critical a11y violations", async ({ page }) => {
    await page.goto("/legacy");
    const v = await seriousViolations(page);
    expect(v, `axe: ${v.map((x) => x.id).join(", ")}`).toEqual([]);
  });
});
