import { test, expect } from "@playwright/test";

/**
 * Unified console shell (unification Phase 4/5).
 *
 * The console is served at "/" (next.config.js rewrite) and also at "/console".
 * Each of the 10 views — the 6 curated ones + the 4 groups that host the legacy
 * panels — lives behind a rail click (not its own route). These tests validate
 * the SHELL and navigation; they do not depend on the backend (the shell and the
 * topbar render client-side even if the views show an error state).
 */

const VIEWS = [
  "Dashboard",
  "Flow",
  "Connections",
  "Policies",
  "Audit",
  "Observ.",
  "Governance",
  "Config",
] as const;

test.describe("unified console", () => {
  test("root / serves the console with an 8-item rail", async ({ page }) => {
    await page.goto("/");
    const rail = page.locator(".bc-rail");
    await expect(rail).toBeVisible();
    await expect(rail.locator(".bc-rail-item")).toHaveCount(8);
    for (const v of VIEWS) {
      await expect(rail.getByRole("button", { name: v, exact: true })).toBeVisible();
    }
  });

  test("clicking each rail item mounts the matching view", async ({ page }) => {
    await page.goto("/");
    for (const v of VIEWS) {
      await page.locator(".bc-rail").getByRole("button", { name: v, exact: true }).click();
      await expect(page.locator(".bc-topbar h1")).toHaveText(v);
      await expect(page.locator(".bc-content")).toBeVisible();
    }
  });

  test("/console serves the same shell", async ({ page }) => {
    await page.goto("/console");
    await expect(page.locator(".bc-rail .bc-rail-item")).toHaveCount(8);
  });

  test("navigating the console raises no app runtime error", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto("/");
    for (const v of ["Audit", "Governance"] as const) {
      await page.locator(".bc-rail").getByRole("button", { name: v, exact: true }).click();
      await expect(page.locator(".bc-content")).toBeVisible();
    }
    expect(errors, errors.join("\n")).toHaveLength(0);
  });
});
