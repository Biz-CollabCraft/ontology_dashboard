import { expect, test } from "@playwright/test";

const PROJECT = "manufacturing-demo-project";
const WORKSPACE = "manufacturing-demo";
const API_URL = process.env.PLAYWRIGHT_API_URL ?? "http://127.0.0.1:8100";
const PATH = `/app/projects/${PROJECT}/operations?view=overview&dashboard=workflow&role=process_manager&workspace_id=${WORKSPACE}&asset_id=CNC-S04-L02-03&event_id=EVT-GS-004`;

test("PR 163 live gen-data to PostgreSQL to operations screen smoke", async ({ page }) => {
  await page.route("**/api/auth/login", async (route) => {
    await route.continue({
      headers: {
        ...route.request().headers(),
        "X-Forwarded-For": "127.0.0.163",
      },
    });
  }, { times: 1 });

  await page.goto(`/login?returnTo=${encodeURIComponent(PATH)}`);
  await page.getByLabel("이메일").fill("manager@ontology.local");
  await page.getByLabel("비밀번호").fill("Manager!2026");
  await page.getByRole("button", { name: "로그인", exact: true }).click();

  await expect(page).toHaveURL(new RegExp(`/app/projects/${PROJECT}/operations`));
  await expect(page.getByText("실시간 설비 현황", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "공장 전체 상태와 알림을 한눈에 확인" })).toBeVisible();
  await expect(page.locator(".operations-factory-asset-node")).toHaveCount(100);
  await expect(page.getByText("마지막 수신 시각", { exact: true })).toBeVisible();

  const dashboard = await page.evaluate(async ({ apiUrl, project, workspace }) => {
    const response = await fetch(
      `${apiUrl}/api/projects/${project}/workspaces/${workspace}/predictive-maintenance/dashboard?role=manager&intent=overview&locale=ko-KR`,
      { credentials: "include" },
    );
    if (!response.ok) throw new Error(`dashboard API failed: ${response.status}`);
    return response.json();
  }, { apiUrl: API_URL, project: PROJECT, workspace: WORKSPACE });

  expect(dashboard.data_source?.source_version).toBe("gen-data-wall-clock-live-v2");
  expect(dashboard.data_source?.record_count).toBeGreaterThan(0);
  expect(dashboard.events?.length ?? 0).toBeGreaterThan(0);
});
