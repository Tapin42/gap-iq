import { expect, test } from "@playwright/test";

import { ReplayServer } from "./replay-server";

const HIDDEN_SLUG = "boncelet-peter";

function storageKey(edition: string): string {
  return `gap-iq:hidden-athletes:${edition}`;
}

test.describe.configure({ mode: "serial" });

test.describe("Roster hide/unhide", () => {
  let server: ReplayServer;

  test.afterEach(async () => {
    await server?.stop();
  });

  test("hide, unhide, and persist hidden athletes in localStorage", async ({ page }) => {
    server = await ReplayServer.start(32);

    const metaResponse = await page.request.get("http://127.0.0.1:8477/api/meta");
    const meta = (await metaResponse.json()) as { event: { edition: string } };
    const edition = meta.event.edition;
    const key = storageKey(edition);

    await page.goto("/");
    await page.evaluate((storageKey) => localStorage.removeItem(storageKey), key);
    await page.reload();
    await page.waitForResponse((response) => response.url().includes("/api/meta") && response.ok());

    await expect(page.getByTestId(`hide-${HIDDEN_SLUG}`)).toBeVisible();
    await page.getByTestId(`hide-${HIDDEN_SLUG}`).click();
    await expect(page.getByTestId(`hide-${HIDDEN_SLUG}`)).not.toBeVisible();
    await expect(page.getByText(/1 hidden athlete/)).toBeVisible();

    await page.getByTestId("hidden-section-toggle").click();
    await expect(page.getByTestId(`unhide-${HIDDEN_SLUG}`)).toBeVisible();

    await page.getByTestId(`unhide-${HIDDEN_SLUG}`).click();
    await expect(page.getByTestId(`hide-${HIDDEN_SLUG}`)).toBeVisible();
    await expect(page.getByText(/hidden athlete/)).not.toBeVisible();

    await page.getByTestId(`hide-${HIDDEN_SLUG}`).click();
    await expect(page.getByTestId(`hide-${HIDDEN_SLUG}`)).not.toBeVisible();

    await page.reload();
    await page.waitForResponse((response) => response.url().includes("/api/meta") && response.ok());
    await expect(page.getByText(/1 hidden athlete/)).toBeVisible();
    await expect(page.getByTestId(`hide-${HIDDEN_SLUG}`)).not.toBeVisible();

    const stored = await page.evaluate((storageKey) => localStorage.getItem(storageKey), key);
    expect(stored).toContain(HIDDEN_SLUG);
  });
});
