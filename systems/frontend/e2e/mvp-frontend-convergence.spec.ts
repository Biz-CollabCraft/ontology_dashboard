import { expect, type Page, test } from "@playwright/test";

const PROJECT = "manufacturing-demo-project";
const MVP_PATH = `/app/projects/${PROJECT}/mvp`;
const CLASSIC_OVERVIEW_PATH = `${MVP_PATH}?view=overview&dashboard=classic`;
const WORKFLOW_FIELD_OVERVIEW_PATH = `${MVP_PATH}?view=overview&dashboard=workflow&role=field_operator&workspace_id=manufacturing-demo&asset_id=CNC-S04-L02-03&event_id=EVT-GS-004`;
const WORKFLOW_PROCESS_OVERVIEW_PATH = `${MVP_PATH}?view=overview&dashboard=workflow&role=process_manager&workspace_id=manufacturing-demo&asset_id=CNC-S04-L02-03&event_id=EVT-GS-004`;
const ACCOUNTS = {
  manager: ["manager@ontology.local", "Manager!2026"],
  engineer: ["engineer@ontology.local", "Engineer!2026"],
} as const;

async function login(page: Page, returnTo = MVP_PATH, account: keyof typeof ACCOUNTS = "manager") {
  const [email, password] = ACCOUNTS[account];
  await page.goto(`/login?returnTo=${encodeURIComponent(returnTo)}`);
  await page.getByLabel("이메일").fill(email);
  await page.getByLabel("비밀번호").fill(password);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/app/projects/${PROJECT}`));
}

test("login exposes only the two mentoring MVP roles", async ({ page }) => {
  await page.goto(`/login?returnTo=${encodeURIComponent(MVP_PATH)}`);

  const demoAccounts = page.getByRole("group", { name: "MVP 데모 계정" }).getByRole("button");
  await expect(demoAccounts).toHaveCount(2);
  await expect(page.getByRole("button", { name: /관리자·임원/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /실무 엔지니어/ })).toBeVisible();
  await expect(page.getByText("데이터 사이언티스트", { exact: true })).toHaveCount(0);
  await expect(page.getByText("FDE", { exact: true })).toHaveCount(0);

  await page.getByRole("button", { name: /관리자·임원/ }).click();
  await expect(page.getByLabel("이메일")).toHaveValue("manager@ontology.local");
  await expect(page.getByLabel("비밀번호")).toHaveValue("Manager!2026");

  await page.getByRole("button", { name: /실무 엔지니어/ }).click();
  await expect(page.getByLabel("이메일")).toHaveValue("engineer@ontology.local");
  await expect(page.getByLabel("비밀번호")).toHaveValue("Engineer!2026");
});

test("shows normal assets in the current-state overview", async ({ page }) => {
  await login(page, CLASSIC_OVERVIEW_PATH);
  await expect(page.getByTestId("mvp-overview")).toBeVisible();
  await expect(page.getByText("라인별 설비 상태", { exact: true })).toBeVisible();
  const lineStatuses = page.locator(".mvp-line-risk-list footer");
  await expect(lineStatuses.first()).toBeVisible();
  await expect(lineStatuses.first()).toContainText(/정상 \d+/);
});

test("keeps workflow role dashboards ordered around each role's first task", async ({ page }) => {
  await login(page, WORKFLOW_FIELD_OVERVIEW_PATH);
  await expect(page.getByTestId("mvp-overview")).toBeVisible();
  await expect(page.getByRole("heading", { name: "우선순위", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "작업 상태 큐" })).toBeVisible();
  const fieldPriority = await page.getByRole("heading", { name: "우선순위", exact: true }).boundingBox();
  const fieldQueue = await page.getByRole("region", { name: "작업 상태 큐" }).boundingBox();
  expect(fieldPriority?.y ?? 0).toBeLessThan(fieldQueue?.y ?? 0);

  await page.goto(WORKFLOW_PROCESS_OVERVIEW_PATH);
  await expect(page.getByTestId("mvp-overview")).toBeVisible();
  await expect(page.getByRole("heading", { name: "라인별 설비 영향 맵", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "작업 상태 큐" })).toBeVisible();
  const processMap = await page.getByRole("heading", { name: "라인별 설비 영향 맵", exact: true }).boundingBox();
  const processQueue = await page.getByRole("region", { name: "작업 상태 큐" }).boundingBox();
  expect(processMap?.y ?? 0).toBeLessThan(processQueue?.y ?? 0);
});

test("shows the SOP grounded AI review summary without mutating work state", async ({ page }) => {
  await login(page, `${MVP_PATH}?view=overview&dashboard=workflow&role=field_operator&workspace_id=manufacturing-demo&asset_id=CNC-S04-L04-01&event_id=EVT-GS-002`, "engineer");
  await expect(page.getByTestId("mvp-overview")).toBeVisible();
  await page.getByRole("button", { name: /공구\/금형 마모 의심 제안 #02/ }).click();
  const preview = page.getByRole("dialog", { name: "선택 설비 상세" });
  await expect(preview).toBeVisible();
  await preview.getByRole("tab", { name: "처리", exact: true }).click();
  await expect(preview.getByText("점검 요청 후보이며 작업요청이나 정비 조치는 실제 생성하지 않습니다.")).toBeVisible();
  await expect(preview.getByRole("region", { name: "AI 검토 요약" })).toContainText("검토 전용");
  await expect(preview.getByRole("region", { name: "AI 검토 요약" })).toContainText("상태 변경");
  await expect(preview.getByRole("region", { name: "AI 검토 요약" })).toContainText("불가");
  await expect(preview.getByRole("region", { name: "AI 검토 요약" })).toContainText("담당자 검토 초안");
  await expect(preview.getByRole("region", { name: "AI 검토 요약" })).toContainText("자동 승인을 수행하지 않습니다");
});

test("completes Overview to Objects to Operations to Reports Executive Brief without Analysis", async ({ page }) => {
  await login(page, CLASSIC_OVERVIEW_PATH);
  await expect(page.locator(".mvp-app")).toBeVisible();
  await expect(page.locator(".mvp-navigation nav button")).toHaveCount(4);
  await expect(page.getByText("Analysis", { exact: true })).toHaveCount(0);
  await expect(page.getByTestId("mvp-overview")).toBeVisible();
  await expect(page.locator(".mvp-kpi")).toHaveCount(6);
  await expect(page.locator(".mvp-priority-list button").first()).toBeVisible();

  await page.locator(".mvp-priority-list button").first().click();
  await expect(page).toHaveURL(/view=objects/);
  await expect(page.getByTestId("mvp-objects")).toBeVisible();
  await expect(page.locator(".mvp-object-row").first()).toBeVisible();
  await expect(page.locator(".mvp-object-inspector")).toBeVisible();

  await page.getByRole("button", { name: /작업요청 후보 열기/ }).click();
  await expect(page).toHaveURL(/view=operations/);
  await expect(page.getByTestId("mvp-operations")).toBeVisible();
  await expect(page.locator(".mvp-operation-hero")).toBeVisible();
  await expect(page.getByText("자동 정지 아님", { exact: true })).toBeVisible();
  await expect(page.getByText(/설비 제어 명령을 실행하지 않습니다/)).toBeVisible();
  await page.getByLabel("추가 메모 선택 입력").fill("E2E 검증: 현장 점검 전 정지 여부를 검토합니다.");
  await page.getByRole("button", { name: /정지 검토 요청 기록하기/ }).click();
  await expect(page.getByText("저장 완료", { exact: true })).toBeVisible();

  await page.locator(".mvp-report-bridge").click();
  await expect(page).toHaveURL(/view=reports/);
  await expect(page).toHaveURL(/report=executive-brief/);
  await expect(page.getByTestId("mvp-reports")).toBeVisible();
  await expect(page.getByTestId("mvp-executive-report")).toBeVisible();
  await expect(page.locator(".mvp-report-document")).toBeVisible();
  await expect(page.getByRole("button", { name: /A4 PDF/ })).toBeVisible();
  await expect(page.locator(".mvp-report-kpis article")).toHaveCount(5);
  await page.emulateMedia({ media: "print" });
  await expect.poll(() => page.locator(".mvp-global-header").evaluate((element) => getComputedStyle(element).display)).toBe("none");
  await expect(page.locator(".mvp-report-document")).toBeVisible();

  const query = new URL(page.url()).searchParams;
  expect(query.get("asset_id")).toBeTruthy();
  expect(query.get("event_id")).toBeTruthy();
});

test("covers Reports side-tab flow with summary graphs and report types", async ({ page }) => {
  await login(page, `${MVP_PATH}?view=reports&dashboard=classic&report=inspection-request`);
  await expect(page.getByTestId("mvp-reports")).toBeVisible();
  await expect(page.getByRole("tab", { name: /상태 요약/ })).toBeVisible();
  await expect(page.getByRole("tab", { name: /점검 요청/ })).toBeVisible();
  await expect(page.getByRole("tab", { name: /요약 보고서/ })).toBeVisible();
  await expect(page.getByRole("tab", { name: /Executive Brief/ })).toBeVisible();
  await expect(page.getByTestId("mvp-static-report")).toBeVisible();
  await expect(page.getByRole("heading", { name: "예지보전 점검 요청 보고서", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "관리자 판단", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "점검 항목", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "센서 참고값", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "근거 추적", exact: true })).toBeVisible();
  await expect(page.getByText("공기압축기 설비 참고도")).toBeVisible();

  const query = new URL(page.url()).searchParams;
  expect(query.get("view")).toBe("reports");
  expect(query.get("report")).toBe("inspection-request");
  expect(query.get("asset_id")).toBeTruthy();
  expect(query.get("event_id")).toBeTruthy();

  await page.locator(".mvp-navigation nav").getByRole("button", { name: /Overview/ }).click();
  await expect(page).toHaveURL(/view=overview/);
  await expect(page.getByTestId("mvp-overview")).toBeVisible();

  await page.getByRole("button", { name: /Reports/ }).click();
  await expect(page.getByTestId("mvp-reports")).toBeVisible();
  await page.getByRole("tab", { name: /상태 요약/ }).click();
  await expect(page.getByTestId("mvp-status-map-report")).toBeVisible();
  const statusMapNodes = page.locator(".mvp-reports-page .line-map .asset-node");
  const statusMapNodeCount = await statusMapNodes.count();
  expect(statusMapNodeCount).toBeGreaterThan(0);
  await expect(page.locator(".mvp-reports-page .line-map .asset-node.warning").first()).toBeVisible();
  await expect(page.locator(".mvp-reports-page .line-map .asset-node.attention").first()).toBeVisible();
  await expect(page.locator(".mvp-reports-page .line-map .asset-node:disabled")).toHaveCount(0);
  await statusMapNodes.nth(1).click();
  await expect(statusMapNodes.nth(1)).toHaveAttribute("aria-pressed", "true");
  await expect(statusMapNodes.nth(1)).toHaveClass(/selected/);
  await expect(page.locator(".mvp-reports-page .report-panel").getByText("선택 설비 상세")).toBeVisible();
  await page.getByRole("tab", { name: /요약 보고서/ }).click();
  await expect(page.getByTestId("mvp-summary-report")).toBeVisible();
  await expect(page.getByTestId("mvp-summary-map-report-graphs")).toBeVisible();
  await expect(page.getByText("상태 맵 · 라인 위험 · 선택 설비를 한 장으로 압축")).toBeVisible();
  await expect(page.getByText("상태 분포")).toBeVisible();
  await expect(page.getByText("라인별 평균 위험")).toBeVisible();
  await expect(page.getByText("위험 예측 확률")).toBeVisible();
  await expect(page.getByTestId("mvp-summary-graphs")).toBeVisible();
  await expect(page.getByRole("img", { name: /관측 흐름/ }).first()).toBeVisible();
  expect(await page.locator(".asset-series-chart").count()).toBeGreaterThanOrEqual(3);
  await expect(page.locator(".asset-crossing-marker").first()).toBeVisible();
  await expect(page.locator(".asset-history-section").first()).toBeVisible();
  await expect(page.getByText("설비 이력").first()).toBeVisible();
  await page.getByRole("tab", { name: /점검 요청/ }).click();
  await expect(page.getByTestId("mvp-static-report")).toBeVisible();
});

test("loads the Objects inspector through the AssetDetailViewModel API", async ({ page }) => {
  const detailViewResponses: string[] = [];
  page.on("response", (response) => {
    if (response.url().includes("/api/objects/CNC-S04-L04-01/detail-view") && response.ok()) {
      detailViewResponses.push(response.url());
    }
  });

  await login(page, `${MVP_PATH}?view=objects&dashboard=classic&asset_id=CNC-S04-L04-01&event_id=EVT-GS-002`);
  await expect(page.getByTestId("mvp-objects")).toBeVisible();
  await expect.poll(() => detailViewResponses.length).toBeGreaterThan(0);
  await expect(page.locator(".mvp-object-inspector")).toContainText("4구역 · 4셀 · CNC 가공기 1");
  await expect(page.locator(".mvp-object-inspector")).toContainText("공구 마모");
  expect(detailViewResponses[0]).toContain("dataset_version_id=");
});

test("separates manager decisions from field-operator notes using real permissions", async ({ page }) => {
  await login(page, `${MVP_PATH}?view=operations&dashboard=classic`, "engineer");
  await expect(page.getByTestId("mvp-operations")).toBeVisible();
  await expect(page.getByText("현재 역할에는 결정 기록 권한이 없습니다.", { exact: true })).toBeVisible();
  await expect(page.getByText("메모 기록 가능", { exact: true })).toBeVisible();
  await page.getByLabel("점검 결과 또는 전달 사항").fill("E2E 현장 메모: 공구 마모와 센서 연결 상태를 확인했습니다.");
  await page.getByRole("button", { name: "메모 저장", exact: true }).click();
  await expect(page.getByText("저장 완료", { exact: true })).toBeVisible();
  await expect(page.getByText(/현장 메모가 저장됐습니다/)).toBeVisible();
});

test("keeps direct links reproducible and renders invalid IDs as safe empty states", async ({ page }) => {
  const invalid = `${MVP_PATH}?view=objects&dashboard=classic&asset_id=missing-asset&event_id=missing-event&role=process_manager`;
  await login(page, invalid);
  await expect(page).toHaveURL(/asset_id=missing-asset/);
  await expect(page.getByTestId("mvp-objects")).toBeVisible();
  await expect(page.getByText(/요청한 설비 missing-asset/)).toBeVisible();

  await page.reload();
  await expect(page).toHaveURL(/asset_id=missing-asset/);
  await expect(page.getByText(/요청한 설비 missing-asset/)).toBeVisible();
});

test("isolates Canonical API failures and preserves the four-screen fallback flow", async ({ page }) => {
  await page.route("**/api/projects/*/workspaces/*/predictive-maintenance/**", async (route) => {
    await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: { code: "runtime_unavailable", message: "runtime unavailable in test" } }) });
  });
  await login(page, CLASSIC_OVERVIEW_PATH);
  await expect(page.getByTestId("mvp-overview")).toBeVisible();
  await expect(page.getByText("보조 데이터 표시", { exact: true })).toBeVisible();
  await expect(page.getByText(/부분 연결 경고/)).toBeVisible();
  await expect(page.locator(".mvp-priority-list button").first()).toBeVisible();
});

test("uses the verified report template when both LLM and deterministic report APIs fail", async ({ page }) => {
  await page.route("**/api/events/*/report", async (route) => {
    await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: { code: "report_unavailable", message: "report unavailable in test" } }) });
  });
  await page.route("**/api/projects/*/workspaces/*/predictive-maintenance/dashboard**", async (route) => {
    await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: { code: "runtime_unavailable", message: "runtime unavailable in test" } }) });
  });
  await login(page, `${MVP_PATH}?view=reports&dashboard=classic&report=executive-brief`);
  await expect(page.getByTestId("mvp-executive-report")).toBeVisible();
  await expect(page.getByText("근거 기반 보고서", { exact: true })).toBeVisible();
  await expect(page.locator(".mvp-report-document")).toBeVisible();
  await expect(page.getByText(/모델 확률은 실제 고장 발생을 확정하지 않습니다/)).toBeVisible();
});

test("keeps Reports inspection request available when predictive or report APIs fail", async ({ page }) => {
  await page.route("**/api/projects/*/workspaces/*/predictive-maintenance/dashboard**", async (route) => {
    await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: { code: "runtime_unavailable", message: "runtime unavailable in test" } }) });
  });
  await page.route("**/api/events/*/evidence", async (route) => {
    await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: { code: "evidence_unavailable", message: "evidence unavailable in test" } }) });
  });
  await page.route("**/api/events/*/report", async (route) => {
    await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: { code: "report_unavailable", message: "report unavailable in test" } }) });
  });
  await login(page, `${MVP_PATH}?view=reports&dashboard=classic&report=inspection-request`);
  await expect(page.getByTestId("mvp-reports")).toBeVisible();
  await expect(page.getByTestId("mvp-static-report")).toBeVisible();
  await expect(page.getByRole("heading", { name: "예지보전 점검 요청 보고서", exact: true })).toBeVisible();
  await expect(page.getByText("이 리포트는 점검 요청 산출물입니다.")).toBeVisible();
});

test("keeps all MVP views inside a 390px mobile viewport and exposes compact navigation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page, CLASSIC_OVERVIEW_PATH);
  await expect(page.locator(".mvp-app")).toBeVisible();

  await page.getByRole("button", { name: "메뉴 열기" }).click();
  await expect(page.locator(".mvp-navigation")).toHaveClass(/is-open/);
  for (const label of ["Overview", "Assets", "작업요청", "Reports"]) {
    await page.locator(".mvp-navigation nav").getByRole("button", { name: new RegExp(label) }).first().click();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    if (label !== "Reports") await page.getByRole("button", { name: "메뉴 열기" }).click();
  }
});

test("redirects a legacy project surface to the official Week 2 MVP", async ({ page }) => {
  await login(page, CLASSIC_OVERVIEW_PATH);
  await page.goto(`/app/projects/${PROJECT}/blueprint-v2`);
  await expect(page).toHaveURL(new RegExp(`${MVP_PATH}$`));
  await expect(page.getByTestId("mvp-overview")).toBeVisible({ timeout: 15_000 });
});

test("logs out from the official MVP shell", async ({ page }) => {
  await login(page, CLASSIC_OVERVIEW_PATH);
  await expect(page.getByTestId("mvp-overview")).toBeVisible();
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("button", { name: "로그인", exact: true })).toBeVisible();
});
