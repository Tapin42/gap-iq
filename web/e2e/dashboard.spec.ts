import { expect, test } from "@playwright/test";

import { ReplayServer } from "./replay-server";

test.describe.configure({ mode: "serial" });

test.describe("Furler replay dashboard copy", () => {
  let server: ReplayServer;

  test.afterEach(async () => {
    await server?.stop();
  });

  test("lone at mat does not read as sole division member", async ({ page }) => {
    server = await ReplayServer.start(255);
    await page.goto("/athlete/furler-mark");
    await expect(page.getByTestId("position-copy")).toContainText("only one at Bike - Wiliberg 3");
    await expect(page.getByTestId("position-copy")).toContainText("in M40-44");
    await expect(page.getByTestId("position-copy")).not.toContainText("of 1 in");
  });

  test("provisional lead at Run2 - Lap 2", async ({ page }) => {
    server = await ReplayServer.start(356);
    await page.goto("/athlete/furler-mark");
    await expect(page.getByTestId("position-copy")).toContainText("first of");
    await expect(page.getByTestId("position-copy")).toContainText("Run2 - Lap 2");
    await expect(page.getByTestId("position-copy")).toContainText("Division lead not confirmed yet");
  });

  test("finish shows full division field size", async ({ page }) => {
    server = await ReplayServer.start(600);
    await page.goto("/athlete/furler-mark");
    await expect(page.getByTestId("position-copy")).toContainText("of 12 in M40-44");
    await expect(page.getByTestId("position-copy")).toContainText("finished");
    await expect(page.getByText("2. Furler")).toBeVisible();
  });

  test("fresh pass does not show the same rival ahead and behind", async ({ page }) => {
    server = await ReplayServer.start(32);
    await page.goto("/athlete/furler-mark");
    await expect(page.getByText("Castellano")).toHaveCount(1);
    await expect(page.getByText("Leading M40-44.")).toBeVisible();
  });
});
