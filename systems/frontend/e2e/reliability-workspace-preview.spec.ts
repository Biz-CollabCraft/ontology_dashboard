import { expect, type Page, test } from "@playwright/test";

const PROJECT = "manufacturing-demo-project";
const PATH = `/app/projects/${PROJECT}/operations?view=overview&dashboard=workflow&role=process_manager&workspace_id=manufacturing-demo&workspace_shell=reliability`;
const REPORT_PATH = `/app/projects/${PROJECT}/operations/report-draft?view=reports&dashboard=workflow&role=process_manager&workspace_id=manufacturing-demo&workspace_shell=reliability`;

async function login(page: Page) {
  await page.goto(`/login?returnTo=${encodeURIComponent(PATH)}`);
  await page.getByLabel(/이메일|Email/).fill("manager@ontology.local");
  await page.getByLabel(/비밀번호|Password/).fill("Manager!2026");
  await page.getByRole("button", { name: /로그인|Sign in/, exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/app/projects/${PROJECT}/operations`), { timeout: 10_000 });
}

async function loginAs(page: Page, email: string, password: string, returnTo = PATH) {
  await page.goto(`/login?returnTo=${encodeURIComponent(returnTo)}`);
  await page.getByLabel(/이메일|Email/).fill(email);
  await page.getByLabel(/비밀번호|Password/).fill(password);
  await page.getByRole("button", { name: /로그인|Sign in/, exact: true }).click();
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

  await shell.getByRole("button", { name: "환경설정" }).click();
  await shell.getByRole("button", { name: "발표/프로젝터", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-density", "comfortable");
  await shell.locator(".rw-preview-page-heading").click({ position: { x: 12, y: 12 } });
  await shell.getByRole("button", { name: "Collapse navigation" }).click();
  await expect(firstNavCopy).toBeHidden();
  expect((await rail.boundingBox())?.width ?? Number.POSITIVE_INFINITY).toBeLessThanOrEqual(60);
  await shell.getByRole("button", { name: "Open navigation" }).click();
  await shell.getByRole("button", { name: "환경설정" }).click();
  await shell.getByRole("button", { name: "데스크톱", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-density", "standard");
});

test("keeps login and reliability workspace inside a phone viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/login?returnTo=${encodeURIComponent(PATH)}`);

  const loginGeometry = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    documentWidth: document.documentElement.scrollWidth,
  }));
  expect(loginGeometry.documentWidth).toBeLessThanOrEqual(loginGeometry.viewport + 1);

  await page.getByLabel(/이메일|Email/).fill("manager@ontology.local");
  await page.getByLabel(/비밀번호|Password/).fill("Manager!2026");
  await page.getByRole("button", { name: /로그인|Sign in/, exact: true }).click();
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
  await expect(featureMonitor).not.toContainText("센서 이력 로딩 중", { timeout: 15_000 });
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

test("connects search, settings dismissal, locale, theme, presets, and assistant prompts", async ({ page }) => {
  await page.goto(`/login?returnTo=${encodeURIComponent(PATH)}`);
  const display = page.locator(".od-display-menu");
  await display.locator(":scope > summary").click();
  await page.getByRole("button", { name: "English", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("lang", "en-US");
  await expect(page.getByRole("heading", { name: "Find abnormal equipment by location and alert first." })).toBeVisible();
  await expect(page.getByLabel("Email")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeVisible();
  await page.mouse.click(12, 180);
  await expect(display).not.toHaveAttribute("open", "");

  await display.locator(":scope > summary").click();
  await page.getByRole("button", { name: "Dark", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "한국어", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("lang", "ko-KR");
  await expect(page.getByRole("heading", { name: "이상 설비를 위치와 알림으로 먼저 찾습니다." })).toBeVisible();
  await page.mouse.click(12, 180);

  await page.getByLabel("이메일").fill("manager@ontology.local");
  await page.getByLabel("비밀번호").fill("Manager!2026");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  const shell = page.locator(".rw-preview-shell:not(.rw-preview-loading-placeholder)");
  await expect(shell).toBeVisible({ timeout: 15_000 });

  await shell.getByRole("button", { name: "Reliability Operations 검색" }).click();
  const palette = page.getByRole("dialog", { name: "Reliability Operations 검색" });
  await expect(palette).toBeVisible();
  await palette.getByLabel("메뉴, 설비 또는 Event 검색").fill("Decision Case");
  await palette.getByRole("button", { name: /Decision Case/ }).first().click();
  await expect(page).toHaveURL(/\/operations\/decision-case/);
  await expect(shell.getByRole("heading", { name: "하나의 사건을 끝까지 추적" })).toBeVisible();

  await shell.getByRole("button", { name: "환경설정" }).click();
  await expect(shell.locator(".rw-preview-settings-panel")).toBeVisible();
  await shell.locator(".rw-preview-page-heading").click({ position: { x: 12, y: 12 } });
  await expect(shell.locator(".rw-preview-settings-panel")).toBeHidden();

  await shell.getByRole("button", { name: "환경설정" }).click();
  await shell.getByRole("button", { name: "발표/프로젝터", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-density", "comfortable");
  const presentationCopySize = await shell.locator(".rw-composed-list small").first().evaluate((element) => parseFloat(getComputedStyle(element).fontSize));
  expect(presentationCopySize).toBeGreaterThanOrEqual(12);
  await shell.getByRole("button", { name: "데스크톱", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-density", "standard");
  await shell.locator(".rw-preview-page-heading").click({ position: { x: 12, y: 12 } });

  await shell.getByRole("button", { name: /Assistant/ }).click();
  const assistant = page.getByRole("dialog", { name: "Reliability Assistant" });
  await expect(assistant).toBeVisible();
  await assistant.getByRole("button", { name: "생산 영향은 어느 정도인가요?", exact: true }).click();
  await expect(assistant.locator(".rw-context-assistant__message.is-user")).toHaveCount(1);
  await expect(assistant.locator(".rw-context-assistant__message.is-assistant:not(.is-loading)")).toHaveCount(1, { timeout: 12_000 });
  await expect(assistant.locator(".rw-context-assistant__message.is-loading")).toHaveCount(0, { timeout: 12_000 });
});

test("keeps factory status focused and avoids repeating the full map on operations status", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await login(page);
  const shell = page.locator(".rw-preview-shell:not(.rw-preview-loading-placeholder)");
  await expect(shell).toBeVisible({ timeout: 15_000 });
  await expect(shell).toHaveAttribute("data-active-surface", "factory-status");
  await expect(shell.locator(".operations-live-kpi-grid")).toBeVisible();
  await expect(shell.locator(".operations-factory-map-panel")).toBeVisible();
  await expect(shell.locator(".operations-monitoring-summary")).toBeHidden();
  await expect(shell.locator(".operations-work-queue-board")).toBeHidden();
  const zoneColumns = await shell.locator(".operations-factory-line-map").evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(" ").length);
  expect(zoneColumns).toBe(2);

  const mainGeometry = await shell.locator(".rw-preview-main").evaluate((element) => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
  }));
  expect(mainGeometry.scrollHeight / Math.max(1, mainGeometry.clientHeight)).toBeLessThan(2.2);

  await shell.locator(".rw-preview-left nav button").filter({ hasText: "운영 현황" }).click();
  await expect(page).toHaveURL(/\/operations\/operations-status/);
  const composed = shell.locator('[data-surface="operations-status"]');
  await expect(composed).toBeVisible();
  await expect(composed).not.toHaveAttribute("data-composition", /factory-map/);
  await expect(composed.locator(".rw-factory-map")).toHaveCount(0);
});

test("uses grouped manager IA, exception-first factory map, persistent case anchor, and adaptive lifecycle", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await login(page);
  const shell = page.locator(".rw-preview-shell:not(.rw-preview-loading-placeholder)");
  await expect(shell).toBeVisible({ timeout: 15_000 });

  const rail = shell.locator(".rw-preview-left");
  for (const group of ["OBSERVE · 감지", "DECIDE · 판단", "FOLLOW-UP · 후속"]) {
    await expect(rail.getByText(group, { exact: true })).toBeVisible();
  }
  await expect(rail.locator("nav")).not.toContainText("01");
  await expect(rail.locator(".rw-preview-nav-group").filter({ hasText: "FOLLOW-UP · 후속" })).toContainText("보고");
  await expect(rail.locator(".rw-preview-nav-group").filter({ hasText: "FOLLOW-UP · 후속" })).toContainText("Archive");

  const lifecycle = shell.locator(".lifecycle-instrument");
  await expect(shell.locator(".rw-preview-selection-anchor")).toHaveCount(0);
  await expect(lifecycle).toHaveClass(/is-idle/);

  const factoryMap = shell.locator(".operations-factory-map-panel");
  await expect(factoryMap.getByRole("button", { name: "이상만 강조", exact: true })).toHaveClass(/is-active/);
  expect(await factoryMap.locator(".operations-factory-asset-node.normal.is-deemphasized").count()).toBeGreaterThan(0);
  await factoryMap.getByRole("button", { name: "전체 설비", exact: true }).click();
  await expect(factoryMap.locator(".operations-factory-map")).toHaveClass(/focus-all/);
  await factoryMap.getByRole("button", { name: "이상만 강조", exact: true }).click();

  const abnormal = factoryMap.locator(".operations-factory-asset-node:not(.normal):not(.slot)").first();
  await abnormal.click();
  await expect(shell.getByRole("dialog", { name: "선택 설비 상세" })).toBeVisible();
  await page.keyboard.press("Escape");
  const anchor = shell.locator(".rw-preview-selection-anchor");
  await expect(anchor).toBeVisible();
  await expect(anchor).toContainText("선택 Case");
  await expect(anchor).toContainText("위험");
  await expect(lifecycle).toHaveClass(/is-compact/);

  await rail.locator("nav button").filter({ hasText: "Decision Case" }).click();
  await expect(shell).toHaveAttribute("data-active-surface", "decision-case");
  await expect(anchor).toBeVisible();
  await expect(lifecycle).toHaveClass(/is-full/);
  await expect(shell.getByRole("button", { name: "보고 초안 이어보기", exact: true })).toBeVisible();

  await rail.locator("nav button").filter({ hasText: "운영 현황" }).click();
  await expect(shell.locator(".rw-composition-reason")).toContainText(/우선순위 상승/);
  await expect(shell.locator(".rw-composition-reason")).toContainText(/현재 운영 상태에 따라 중요한 블록/);
});

test("separates executive primary decisions from evidence and detail", async ({ page }) => {
  await loginAs(page, "executive@ontology.local", "Executive!2026");
  const shell = page.locator(".rw-preview-shell:not(.rw-preview-loading-placeholder)");
  await expect(shell).toBeVisible({ timeout: 15_000 });
  const groups = shell.locator(".rw-preview-nav-group");
  const primary = groups.filter({ hasText: "PRIMARY · 경영 판단" });
  const evidence = groups.filter({ hasText: "EVIDENCE · 근거/상세" });
  await expect(primary).toBeVisible();
  await expect(evidence).toBeVisible();
  await expect(primary.locator("button")).toHaveCount(5);
  await expect(evidence.locator("button")).toHaveCount(3);
  for (const label of ["Executive Brief", "운영 리스크", "운영 KPI", "의사결정 병목", "보고 산출물"]) {
    await expect(primary).toContainText(label);
  }
  for (const label of ["정비 효과", "개선 과제", "설비 상태 근거"]) {
    await expect(evidence).toContainText(label);
  }
});

test("organizes engineering navigation by work intent instead of duplicated data types", async ({ page }) => {
  await loginAs(page, "engineer@ontology.local", "Engineer!2026");
  const shell = page.locator(".rw-preview-shell:not(.rw-preview-loading-placeholder)");
  await expect(shell).toBeVisible({ timeout: 15_000 });
  const rail = shell.locator(".rw-preview-left");
  for (const label of ["설비 현황", "모니터링", "원인 분석", "점검", "정비 효과", "정비 이력", "현장 기록"]) {
    await expect(rail.locator("nav button").filter({ hasText: label })).toHaveCount(1);
  }
  await expect(rail.locator("nav button").filter({ hasText: "센서 피쳐" })).toHaveCount(0);
  await expect(rail.locator("nav button").filter({ hasText: "점검 · 정비 이력" })).toHaveCount(0);
  for (const group of ["OBSERVE · 감지", "DIAGNOSE · 진단", "LEARN · 이력"]) {
    await expect(rail.getByText(group, { exact: true })).toBeVisible();
  }
});
