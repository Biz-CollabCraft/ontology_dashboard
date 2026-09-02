import { expect, type Page, test } from "@playwright/test";

const PROJECT = "manufacturing-demo-project";
const PATH = `/app/projects/${PROJECT}/operations?view=overview&dashboard=workflow&role=process_manager&workspace_id=manufacturing-demo&workspace_shell=reliability`;
const REPORT_PATH = `/app/projects/${PROJECT}/operations/report-draft?view=reports&dashboard=workflow&role=process_manager&workspace_id=manufacturing-demo&workspace_shell=reliability`;

async function login(page: Page) {
  await page.goto(`/login?returnTo=${encodeURIComponent(PATH)}`);
  await page.getByLabel("이메일").fill("manager@ontology.local");
  await page.getByLabel("비밀번호").fill("Manager!2026");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/app/projects/${PROJECT}/operations`), { timeout: 10_000 });
}

test("uses a light Korean placeholder before the reliability workspace is ready", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("ontology-dashboard-theme", "dark");
    window.localStorage.setItem("ontology-dashboard:locale", "en-US");
    window.localStorage.removeItem("ontology-dashboard:reliability-theme");
    window.localStorage.removeItem("ontology-dashboard:reliability-locale");
  });

  await page.route(`**/api/projects/${PROJECT}`, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 800));
    await route.continue();
  });

  await login(page);

  const routePlaceholder = page.locator(".reliability-route-placeholder");
  await expect(routePlaceholder).toBeVisible();
  await expect(page.getByText("Validating Project scope", { exact: true })).toHaveCount(0);
  await expect(page.locator(".route-loading")).toHaveCount(0);

  const placeholder = page.locator(".rw-preview-loading-placeholder");
  await expect(placeholder).toBeVisible();
  await expect(placeholder.getByRole("heading", { name: "운영 워크스페이스를 준비하고 있습니다" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "ko-KR");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

  await expect(page.locator(".rw-preview-shell:not(.rw-preview-loading-placeholder)")).toBeVisible({ timeout: 15_000 });
  await expect(page.locator("html")).toHaveAttribute("lang", "ko-KR");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

  const shell = page.locator(".rw-preview-shell:not(.rw-preview-loading-placeholder)");
  await expect(shell.locator(".operational-focus")).toHaveCount(0);
  const liveKpis = shell.locator(".operations-live-kpi-grid");
  const factoryMap = shell.locator(".operations-factory-map-panel").first();
  await expect(liveKpis).toBeVisible();
  await expect(factoryMap).toBeVisible();
  const [kpiBox, mapBox] = await Promise.all([liveKpis.boundingBox(), factoryMap.boundingBox()]);
  expect(kpiBox?.y ?? Number.POSITIVE_INFINITY).toBeLessThan(mapBox?.y ?? Number.NEGATIVE_INFINITY);
  const lightSurfaces = await shell.evaluate((element) => {
    const sample = (selector: string) => {
      const target = element.querySelector<HTMLElement>(selector);
      if (!target) return null;
      const style = getComputedStyle(target);
      return { backgroundColor: style.backgroundColor, backgroundImage: style.backgroundImage };
    };
    const shellStyle = getComputedStyle(element);
    return {
      themeBackground: shellStyle.getPropertyValue("--rw-bg").trim(),
      rail: sample(".rw-preview-left"),
      main: sample(".rw-preview-main"),
      bottom: sample(".rw-preview-bottom"),
    };
  });
  expect(lightSurfaces.themeBackground).toBe("#f3f6f9");
  expect(lightSurfaces.rail?.backgroundImage).toContain("rgb(251, 252, 253)");
  expect(lightSurfaces.main?.backgroundImage).toContain("rgb(247, 249, 251)");
  expect(lightSurfaces.bottom?.backgroundColor).toBe("rgba(255, 255, 255, 0.98)");
});

test("keeps navigation expanded on laptop widths and wraps Korean copy by word boundary", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 800 });
  await login(page);

  const shell = page.locator(".rw-preview-shell:not(.rw-preview-loading-placeholder)");
  await expect(shell).toBeVisible({ timeout: 15_000 });
  const rail = shell.locator(".rw-preview-left");
  const firstNavCopy = rail.locator("nav button").first().locator("div");
  await expect(firstNavCopy).toBeVisible();

  const desktopGeometry = await rail.evaluate((element) => {
    const style = getComputedStyle(element);
    return { width: element.getBoundingClientRect().width, display: style.display };
  });
  expect(desktopGeometry.width).toBeGreaterThanOrEqual(220);
  expect(desktopGeometry.display).not.toBe("none");

  const detailWrap = await shell.locator(".rw-preview-page-heading p").evaluate((element) => {
    const style = getComputedStyle(element);
    return { wordBreak: style.wordBreak, overflowWrap: style.overflowWrap };
  });
  expect(detailWrap.wordBreak).toBe("keep-all");
  expect(detailWrap.overflowWrap).toBe("break-word");

  await page.setViewportSize({ width: 900, height: 800 });
  await expect(firstNavCopy).toBeVisible();
  expect((await rail.boundingBox())?.width ?? 0).toBeGreaterThanOrEqual(220);

  await shell.getByRole("button", { name: "Collapse navigation" }).click();
  await expect(firstNavCopy).toBeHidden();
  expect((await rail.boundingBox())?.width ?? Number.POSITIVE_INFINITY).toBeLessThanOrEqual(60);
});

test("keeps login and reliability workspace inside a phone viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/login?returnTo=${encodeURIComponent(PATH)}`);

  const loginGeometry = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    documentWidth: document.documentElement.scrollWidth,
  }));
  expect(loginGeometry.documentWidth).toBeLessThanOrEqual(loginGeometry.viewport + 1);

  await page.getByLabel("이메일").fill("manager@ontology.local");
  await page.getByLabel("비밀번호").fill("Manager!2026");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/app/projects/${PROJECT}/operations`), { timeout: 10_000 });

  const shell = page.locator(".rw-preview-shell:not(.rw-preview-loading-placeholder)");
  await expect(shell).toBeVisible({ timeout: 15_000 });
  const geometry = await shell.evaluate((element) => {
    const main = element.querySelector<HTMLElement>(".rw-preview-main");
    return {
      viewport: document.documentElement.clientWidth,
      documentWidth: document.documentElement.scrollWidth,
      mainClientWidth: main?.clientWidth ?? 0,
      mainScrollWidth: main?.scrollWidth ?? 0,
    };
  });
  expect(geometry.documentWidth).toBeLessThanOrEqual(geometry.viewport + 1);
  expect(geometry.mainScrollWidth).toBeLessThanOrEqual(geometry.mainClientWidth + 1);

  const openNav = shell.getByRole("button", { name: "Open navigation" });
  await openNav.click();
  const rail = shell.locator(".rw-preview-left");
  await expect(rail.locator("nav button").first().locator("div")).toBeVisible();
  const railBox = await rail.boundingBox();
  expect(railBox?.width ?? 0).toBeGreaterThan(220);
  expect(railBox?.width ?? Number.POSITIVE_INFINITY).toBeLessThan(390);
});

test("keeps grounded report surfaces light and derives assistant copy from live context", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("ontology-dashboard:reliability-theme", "light");
    window.localStorage.setItem("ontology-dashboard:reliability-locale", "ko-KR");
  });
  await login(page);
  await page.goto(REPORT_PATH);

  const shell = page.locator(".rw-preview-shell:not(.rw-preview-loading-placeholder)");
  await expect(shell).toBeVisible({ timeout: 15_000 });
  const reportSurface = shell.locator('[data-surface="report-draft"]');
  await expect(reportSurface).toBeVisible({ timeout: 15_000 });
  await expect(reportSurface.getByText("역할별 보고 요약", { exact: true })).toBeVisible();
  const reportBlockBackground = await reportSurface.locator(".rw-composed-block").filter({ hasText: "역할별 보고 요약" }).first().evaluate((element) => getComputedStyle(element).backgroundColor);
  expect(reportBlockBackground).toBe("rgb(255, 255, 255)");

  await shell.getByRole("button", { name: /Assistant/ }).click();
  const assistant = page.getByRole("dialog", { name: "Reliability Assistant" });
  await expect(assistant).toBeVisible();
  await expect(assistant).not.toContainText("local_sop_metadata_retriever");
  await expect(assistant.getByRole("button", { name: "지금 승인해야 하는 조치는 무엇인가요?", exact: true })).toBeVisible();
  await expect(assistant.getByRole("button", { name: "생산 영향은 어느 정도인가요?", exact: true })).toBeVisible();
  await expect(assistant.getByRole("button", { name: "경영진 보고 초안을 만들어줘", exact: true })).toBeVisible();
});

test("uses wall-clock assets and renders connected observation history", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("ontology-dashboard:reliability-theme", "light");
    window.localStorage.setItem("ontology-dashboard:reliability-locale", "ko-KR");
  });
  await login(page);

  const shell = page.locator(".rw-preview-shell:not(.rw-preview-loading-placeholder)");
  await expect(shell).toBeVisible({ timeout: 15_000 });
  const factoryMap = shell.locator(".operations-factory-map-panel").first();
  await expect(factoryMap).toBeVisible();
  await expect(factoryMap.locator(".operations-factory-asset-node")).toHaveCount(100, { timeout: 15_000 });
  await expect(factoryMap).not.toContainText("설비 정보 준비 중");
  await expect(shell).not.toContainText("2026. 09. 12");

  const connectedAsset = factoryMap.locator(".operations-factory-asset-node:not(.slot)").first();
  await expect(connectedAsset).toBeVisible();
  await connectedAsset.click();

  const drawer = shell.getByRole("dialog", { name: "선택 설비 상세" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByText("최신 관측 기준", { exact: false })).toBeVisible({ timeout: 15_000 });
  const featureMonitor = drawer.locator(".operations-live-feature-monitor");
  const featureSeriesCount = await featureMonitor.locator(".asset-series-line").count();
  if (featureSeriesCount === 0) await expect(featureMonitor).toContainText("센서 이력 없음");
  else expect(featureSeriesCount).toBeGreaterThan(0);
  await expect(drawer).not.toContainText("pressure_raw_6h_max_abs");
  await expect(drawer).not.toContainText("vibration_raw_6h_max_abs");
  await expect(drawer).not.toContainText("relative_vibration_z_6h_max_abs");
  await expect(drawer).not.toContainText("SSE 수신 대기");
  await expect(drawer).not.toContainText("재생성 권한 없음");
});

test("requires report type review before opening the browser print flow", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("ontology-dashboard:reliability-theme", "light");
    window.localStorage.setItem("ontology-dashboard:reliability-locale", "ko-KR");
  });
  await login(page);

  const shell = page.locator(".rw-preview-shell:not(.rw-preview-loading-placeholder)");
  await expect(shell).toBeVisible({ timeout: 15_000 });
  await shell.locator(".operations-factory-asset-node:not(.slot)").first().click();

  const detailDrawer = page.getByRole("dialog", { name: "선택 설비 상세" });
  await expect(detailDrawer).toBeVisible({ timeout: 15_000 });
  await detailDrawer.getByRole("button", { name: "보고서 출력" }).click();

  const outputDialog = page.getByRole("dialog", { name: "보고서 출력 유형 선택" });
  await expect(outputDialog).toBeVisible();
  for (const label of ["상태 요약", "점검 요청", "요약 보고서", "Executive Brief"]) {
    await expect(outputDialog.getByRole("button", { name: new RegExp(label) })).toBeVisible();
  }
  await expect(outputDialog.getByLabel("선택한 출력 내용 확인")).toBeVisible();
  await expect(outputDialog.getByRole("button", { name: "확인 후 출력" })).toBeVisible();
});
