import { expect, test } from "@playwright/test";

const pull = (number: number, head: string, base = "main") => ({
  number,
  title: `PR ${number} dashboard fixture`,
  html_url: `https://github.com/Biz-CollabCraft/ontology_dashboard/pull/${number}`,
  user: { login: "tester", type: "User" },
  head: { ref: head, sha: `${number}`.repeat(40).slice(0, 40) },
  base: { ref: base },
  draft: false,
  mergeable: true,
  mergeable_state: "clean",
  created_at: "2026-08-18T00:00:00Z",
  updated_at: "2026-08-18T01:00:00Z",
});
test("renders live-shaped PR dependencies, filters and detail drawer without login", async ({ page }) => {
  const pulls = [pull(21, "feature/a"), pull(22, "feature/b", "feature/a"), pull(40, "feature/c")];
  const productApiRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.origin === "http://127.0.0.1:3200" && url.pathname.startsWith("/api/")) {
      productApiRequests.push(url.pathname);
    }
  });
  await page.route("https://api.github.com/repos/Biz-CollabCraft/ontology_dashboard/**", async (route) => {
    const url = new URL(route.request().url());
    let body: unknown = {};
    if (url.pathname.endsWith("/pulls") && url.searchParams.get("state") === "open") body = pulls;
    else if (/\/pulls\/\d+$/.test(url.pathname)) body = pulls.find((item) => url.pathname.endsWith(`/${item.number}`));
    else if (/\/pulls\/\d+\/reviews$/.test(url.pathname)) body = [{ user: { login: "reviewer", type: "User" }, state: "APPROVED", body: "LGTM" }];
    else if (/\/commits\/[0-9]+\/check-runs$/.test(url.pathname)) body = { check_runs: [{ name: "Architecture", status: "completed", conclusion: "success" }] };
    else if (/\/pulls\/\d+\/commits$/.test(url.pathname)) body = [];
    else if (url.pathname.endsWith("/commits")) body = [];
    await route.fulfill({ status: 200, contentType: "application/json", headers: { "x-ratelimit-remaining": "58" }, body: JSON.stringify(body) });
  });

  await page.goto("/dev_dashboard");
  await expect(page.getByTestId("dev-dashboard")).toBeVisible();
  await expect(page.getByText("Open PRs").locator("..").getByText("3")).toBeVisible();
  await expect(page.getByTestId("pr-flow-graph")).toBeVisible();
  await expect(page.locator(".dev-pr-node")).toHaveCount(3);
  await expect(page.getByTestId("pr-flow-graph")).toHaveAttribute("data-edge-count", "1");

  await page.getByLabel("Search PRs").fill("PR 40");
  await expect(page.locator(".dev-pr-node")).toHaveCount(1);
  await expect(page.locator(".dev-pr-node")).toContainText("#40");
  await page.getByLabel("Search PRs").fill("");
  await expect(page.locator(".dev-pr-node")).toHaveCount(3);

  await page.locator(".dev-pr-node").filter({ hasText: "#22" }).evaluate((node) => {
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await expect(page.getByRole("dialog", { name: "PR #22 details" })).toBeVisible();
  await expect(page.getByText("Depends on").locator("..")).toContainText("#21");
  expect(productApiRequests).toEqual([]);
});
// This smoke test intentionally runs without the product backend or login flow.
