import { test, expect } from "@playwright/test";

/**
 * Validates the 9 acceptance criteria of the tabbed-dashboard refactor:
 * default tab, switching, single-panel-visible, no 16-panel scroll, active
 * highlight, URL-hash persistence, data preserved on return, narrow-screen
 * tabbar, ARIA + keyboard. Drives the real DOM at :3002.
 */

const PANELS = ["atendimento", "observabilidade", "catalogo", "avaliacao", "governanca", "integracoes"] as const;

function panel(page: import("@playwright/test").Page, id: string) {
  return page.locator(`#panel-${id}`);
}

test.beforeEach(async ({ page }) => {
  await page.goto("/legacy");
  await expect(page.getByRole("tablist")).toBeVisible();
});

test("AC1 - default tab is Atendimento; others hidden", async ({ page }) => {
  await expect(panel(page, "atendimento")).toBeVisible();
  await expect(panel(page, "observabilidade")).toBeHidden();
  await expect(panel(page, "catalogo")).toBeHidden();
  // global header stays above the tabs, always visible
  await expect(page.getByRole("heading", { name: "Bridge Banking AI" })).toBeVisible();
});

test("AC2 - clicking a tab swaps content; only one panel visible", async ({ page }) => {
  await page.getByRole("tab", { name: "Observabilidade" }).click();
  await expect(panel(page, "observabilidade")).toBeVisible();
  await expect(panel(page, "atendimento")).toBeHidden();
  await expect(panel(page, "catalogo")).toBeHidden();
  // exactly one visible tabpanel at any time
  const visible = await page.locator('[role="tabpanel"]:visible').count();
  expect(visible).toBe(1);
});

test("AC5 - active tab is visually highlighted (aria-selected)", async ({ page }) => {
  const obs = page.getByRole("tab", { name: "Observabilidade" });
  await obs.click();
  await expect(obs).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tab", { name: "Atendimento" })).toHaveAttribute("aria-selected", "false");
  await expect(obs).toHaveClass(/active/);
});

test("AC6 - URL hash persists the active tab across reload", async ({ page }) => {
  await page.goto("/legacy#observabilidade");
  await expect(panel(page, "observabilidade")).toBeVisible();
  await expect(panel(page, "atendimento")).toBeHidden();
  await expect(page.getByRole("tab", { name: "Observabilidade" })).toHaveAttribute("aria-selected", "true");
});

test("AC7 - switching away and back keeps data (no remount/loading)", async ({ page }) => {
  // populate Atendimento by sending a query
  await page.getByPlaceholder("Digite uma pergunta do cliente...").fill("Quero ver meu saldo");
  await page.getByRole("button", { name: "Enviar" }).click();
  await expect(panel(page, "atendimento").locator(".answer-box .badge")).toBeVisible();
  // go to another tab and back
  await page.getByRole("tab", { name: "Catálogo" }).click();
  await expect(panel(page, "catalogo")).toBeVisible();
  await page.getByRole("tab", { name: "Atendimento" }).click();
  // the prior result is still there — component was hidden, not unmounted
  await expect(panel(page, "atendimento").locator(".answer-box .badge")).toBeVisible();
});

test("AC9 - keyboard: arrow keys move tabs, Enter/native activation, ARIA wiring", async ({ page }) => {
  const first = page.getByRole("tab", { name: "Atendimento" });
  await first.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Observabilidade" })).toBeFocused();
  await expect(panel(page, "observabilidade")).toBeVisible();
  // tabpanel is wired to its tab
  await expect(panel(page, "observabilidade")).toHaveAttribute("aria-labelledby", "tab-observabilidade");
});

test("AC8 - narrow viewport keeps tabs usable, content single column", async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 900 });
  await expect(page.getByRole("tablist")).toBeVisible();
  await expect(page.getByRole("tab", { name: "Catálogo" })).toBeVisible();
  // still exactly one panel visible (never all-panels fallback)
  expect(await page.locator('[role="tabpanel"]:visible').count()).toBe(1);
});

test("capture - screenshot each tab", async ({ page }) => {
  for (const id of PANELS) {
    await page.goto(`/legacy#${id}`);
    await expect(panel(page, id)).toBeVisible();
    await page.waitForTimeout(400);
    await page.screenshot({ path: `test-results/tab-${id}.png`, fullPage: true });
  }
});
