import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { decisionDetailFixture } from "./fixtures/decision-detail.fixture";
import { decisionSessionWireFixture } from "./fixtures/decision-proposal.fixture";
// Reuse the repository's explicitly seeded DEMO_ACCOUNTS, never store credentials here.
const seed = readFileSync("../backend/app/identity/identity_schema.py", "utf8").split("DEMO_ACCOUNTS:")[1];
const account = seed.match(/"email": "([^"]+)",\s*"password": "([^"]+)",\s*"display_name": "[^"]+",\s*"roles": \["process_manager"\]/);
const path = "/app/projects/manufacturing-demo-project/operations?view=overview&workspace_id=manufacturing-demo";
test("real backend failure is visible; contract-backed case fits desktop and mobile without reports", async ({ page }) => {
  if (!account) throw new Error("Seeded manager test account unavailable");
  const errors: string[] = [], reportRequests: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  page.on("request", request => { if (/\/api\/.*\/report(?:[/?]|$)/.test(request.url())) reportRequests.push(request.url()); });
  await page.goto("/login?returnTo=" + encodeURIComponent(path));
  await page.getByLabel("이메일").fill(account[1]);
  await page.getByLabel("비밀번호").fill(account[2]);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page.locator(".dw-machines")).not.toHaveCount(0, { timeout: 20000 });
  await expect(page.getByRole("navigation", { name: "주요 화면" })).not.toContainText("보고서");
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.screenshot({ path: "test-results/decision-workspace-overview.png", fullPage: true });
  await page.locator(".dw-machine").filter({ hasText: "이상 건 확인" }).first().click();
  await expect(page.getByText("판단 근거 확인 필요", { exact: true })).toBeVisible({ timeout: 20000 });
  await expect(page.locator(".dw-case-grid")).toHaveCount(0);
  await page.route("**/api/objects/*/detail-view?*", async route => {
    const url = new URL(route.request().url());
    const assetId = decodeURIComponent(url.pathname.split("/")[3]);
    await route.fulfill({ json: decisionDetailFixture(url.searchParams.get("event_id")!, assetId, url.searchParams.get("dataset_version_id")!) });
  });
  await page.route("**/api/objects/*/agent-review-summary?*", route => route.fulfill({ json: { summary: null, trace: { provider: "none", fallback: false, reason: "pending", validation_errors: [], materialization: { status: "pending" } } } }));
  await page.route("**/maintenance/events/*/lineage", route => route.fulfill({ json: { work_orders: [], inspection_results: [], recommendations: [], maintenance_actions: [], maintenance_events: [], cost_analyses: [] } }));
  await page.getByRole("button", { name: "다시 확인", exact: true }).click();
  await expect(page.getByRole("heading", { name: "판단 조건과 근거" })).toBeVisible({ timeout: 20000 });
  await page.getByRole("button", { name: "점검 요청", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("button", { name: "점검 작업요청 생성", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "닫기", exact: true }).click();
  await expect(page.locator(".dw-flow li")).toHaveCount(5);
  await expect(page.getByRole("heading", { name: "위험도와 설비 신호" })).toBeVisible();
  await expect(page.getByLabel("센서·분석 지표")).toBeVisible();
  await expect(page.locator(".dw-live")).toContainText("관측 기준");
  await expect(page.locator(".dw-app")).not.toContainText("NEXT DECISION");
  await expect(page.getByRole("heading", { name: "다음 판단", exact: true })).toBeVisible();
  expect(await page.locator(".dw-workflow > div > button").count()).toBeLessThanOrEqual(2);
  await page.screenshot({ path: "test-results/decision-workspace-case.png", fullPage: true });
  for (const width of [768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  }
  await page.screenshot({ path: "test-results/decision-workspace-mobile.png", fullPage: true });
  await page.getByRole("button", { name: "공장 현황", exact: true }).last().click();
  await expect(page.getByLabel("설비 검색")).toBeVisible();
  await page.getByLabel("설비 검색").fill("NOT-A-REAL-ASSET");
  await expect(page.getByText("조건에 맞는 설비가 없습니다")).toBeVisible();
  expect(reportRequests).toEqual([]);
  await expect(page.locator(".dw-proposal")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("fixture-backed proposal selection -> human review -> existing closed-loop UI; no mutation before approval", async ({ page }) => {
  if (!account) throw new Error("Seeded manager test account unavailable");
  // Fixture-backed HTTP contract verification, including the real adapter.
  let wire: ReturnType<typeof decisionSessionWireFixture>;
  await page.route("**/api/objects/*/decision-sessions**", async route => {
    if (!wire) throw new Error("detail must load before decision request");
    await route.fulfill({json:wire});
  });
  await page.route("**/api/objects/*/detail-view?*", async route => {
    const url = new URL(route.request().url());
    const eventId = url.searchParams.get("event_id")!, assetId = decodeURIComponent(url.pathname.split("/")[3]);
    const detail = decisionDetailFixture(eventId, assetId, url.searchParams.get("dataset_version_id")!);
    const b = detail.snapshot_basis;
    wire = decisionSessionWireFixture({projectId:url.searchParams.get("project_id")!,workspaceId:url.searchParams.get("workspace_id")!,eventId,assetId,
      snapshotBasis:{artifactId:b.artifact_id,evidencePayloadReference:b.evidence_payload_reference,assetId:b.asset_id,eventId:b.event_id,
        observedAt:b.observed_at,modelVersion:b.model_version,datasetVersion:b.dataset_version,sourceSha256:b.source_sha256}});
    await route.fulfill({ json: detail });
  });
  await page.route("**/maintenance/events/*/lineage", route => route.fulfill({ json: { work_orders: [], inspection_results: [], recommendations: [], maintenance_actions: [], maintenance_events: [], cost_analyses: [] } }));
  const mutations: string[] = [], errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  page.on("request", r => { if (r.method() !== "GET" && r.url().includes("/maintenance/")) mutations.push(r.url()); });
  await page.goto("/login?returnTo=" + encodeURIComponent(path));
  await page.getByLabel("이메일").fill(account[1]);
  await page.getByLabel("비밀번호").fill(account[2]);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await page.locator(".dw-machine").filter({ hasText: "이상 건 확인" }).first().click();
  await expect(page.getByRole("heading", { name: "판단 조건과 근거" })).toBeVisible();
  await expect(page.locator(".dw-decision-conditions")).toContainText("생산 영향: 높음");
  await expect(page.locator(".dw-decision-conditions")).toContainText("실제 부품 예약 상태");
  await expect(page.locator(".dw-decision-conditions")).toContainText("120분");
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.locator(".dw-proposal").getByRole("button", { name: "점검 요청", exact: true }).click();
    await expect(page.getByRole("region", { name: "사용자 검토" })).toBeVisible();
    await expect(page.getByRole("dialog")).not.toBeVisible();
    expect(mutations).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await page.screenshot({ path: `test-results/decision-proposal-review-${width}.png`, fullPage: true });
    await page.getByRole("button", { name: "검토 후 요청 내용 확인", exact: true }).click();
    await expect(page.getByRole("region", { name: "Closed-loop 작업 실행" })).toBeVisible();
    await expect(page.getByRole("button", { name: "점검 작업요청 생성", exact: true })).toBeEnabled();
    expect(mutations).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await page.getByRole("button", { name: "닫기", exact: true }).click();
  }
  expect(errors).toEqual([]);
});
