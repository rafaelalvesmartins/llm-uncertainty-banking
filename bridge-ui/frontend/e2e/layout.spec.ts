import { test, expect } from "@playwright/test";

/**
 * Layout-quality checks that still hold under the tabbed dashboard: equal-height
 * cards within a visible tab, primary vs secondary visual weight, compact
 * multi-column Intent Catalog, single-column on narrow screens. Each test opens
 * the relevant tab first (content lives in tabpanels now).
 */

test("equal-height cards within the active tab (no large vertical gap)", async ({ page }) => {
  // Atendimento still uses .grid (Query + Pipeline side by side); Observ./Catálogo
  // use masonry now (covered by polish.spec). Check equal-height where grid applies.
  await page.goto("/legacy#atendimento");
  await expect(page.locator("#panel-atendimento")).toBeVisible();
  const grids = page.locator("#panel-atendimento .grid");
  const n = await grids.count();
  let worst = 0;
  for (let g = 0; g < n; g++) {
    const cards = grids.nth(g).locator(":scope > .card");
    const c = await cards.count();
    if (c < 2) continue;
    const boxes = [];
    for (let i = 0; i < c; i++) {
      const b = await cards.nth(i).boundingBox();
      if (b) boxes.push(b);
    }
    const rows = new Map<number, number[]>();
    for (const b of boxes) {
      const key = [...rows.keys()].find((k) => Math.abs(k - b.y) < 8);
      const rk = key ?? b.y;
      rows.set(rk, [...(rows.get(rk) ?? []), b.height]);
    }
    for (const heights of rows.values()) {
      if (heights.length < 2) continue;
      worst = Math.max(worst, Math.max(...heights) - Math.min(...heights));
    }
  }
  expect(worst).toBeLessThan(24);
});

test("primary and secondary cards differ in background", async ({ page }) => {
  await page.goto("/legacy#atendimento");
  const primary = page.locator("#panel-atendimento .card").first();
  await page.goto("/legacy#observabilidade");
  const secondary = page.locator("#panel-observabilidade .card").first();
  const bgPrimary = await primary.evaluate((el) => getComputedStyle(el).backgroundColor).catch(() => "");
  const bgSecondary = await secondary.evaluate((el) => getComputedStyle(el).backgroundColor);
  // re-read primary on its own tab (it's hidden now); compare class instead
  await page.goto("/legacy#atendimento");
  const bgPrimary2 = await page.locator("#panel-atendimento .card").first()
    .evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(bgPrimary2).not.toBe(bgSecondary);
});

test("Intent Catalog uses a multi-column grid", async ({ page }) => {
  await page.goto("/legacy#catalogo");
  const grid = page.locator(".intent-grid");
  await expect(grid).toBeVisible();
  const cols = await grid.evaluate(
    (el) => getComputedStyle(el).gridTemplateColumns.split(" ").length,
  );
  expect(cols).toBeGreaterThan(1);
});

test("collapses to one column on a narrow viewport", async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 900 });
  await page.goto("/legacy#atendimento");
  const cards = page.locator("#panel-atendimento .grid").first().locator(":scope > .card");
  const a = await cards.nth(0).boundingBox();
  const b = await cards.nth(1).boundingBox();
  expect(a && b).toBeTruthy();
  if (a && b) expect(Math.abs(a.x - b.x)).toBeLessThan(8);
});
