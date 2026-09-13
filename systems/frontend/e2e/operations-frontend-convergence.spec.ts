import { expect, test, type Page } from "@playwright/test";

const PROJECT = "manufacturing-demo-project";
const OPERATIONS_PATH = `/app/projects/${PROJECT}/operations`;

const ACCOUNTS = {
  manager: ["manager@ontology.local", "Manager!2026"],
  engineer: ["engineer@ontology.local", "Engineer!2026"],
  technician: ["technician@ontology.local", "Technician!2026"],
} as const;

async function signIn(
  page: Page,
  account: keyof typeof ACCOUNTS = "manager",
  returnTo = `${OPERATIONS_PATH}?dashboard=workflow&view=overview`,
) {
  const [email, password] = ACCOUNTS[account];
  await page.goto(`/login?returnTo=${encodeURIComponent(returnTo)}`);
  await page.getByLabel("이메일").fill(email);
  await page.getByLabel("비밀번호").fill(password);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/app/projects/${PROJECT}/operations`));
}

test("single login screen exposes the three demo work roles", async ({ page }) => {
  await page.goto("/login");

  await expect(page.getByRole("heading", { name: "실시간 설비 현황에서 점검·정비와 생산 대응까지" })).toBeVisible();
  await expect(page.getByRole("group", { name: "역할별 계정" })).toBeVisible();
  await expect(page.getByRole("button", { name: "엔지니어", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "보전팀", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "생산 관리자", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "생산 관리자", exact: true }).click();
  await expect(page.getByLabel("이메일")).toHaveValue("manager@ontology.local");
  await expect(page.getByLabel("비밀번호")).toHaveValue("Manager!2026");
});

test("canonical operations overview renders the PR163 workflow surface", async ({ page }) => {
  await signIn(page);

  await expect(page.locator(".operations-app")).toBeVisible();
  await expect(page.getByTestId("operations-overview")).toBeVisible();
  await expect(page.getByText("공장 설비 상태맵", { exact: true })).toBeVisible();
  await expect(page.locator(".operations-factory-asset-node")).toHaveCount(100);
  await expect(page).toHaveURL(/dashboard=workflow/);
  await expect(page).toHaveURL(/view=overview/);
});

test("manager can switch workflow lens on the same screen without signing in again", async ({ page }) => {
  await signIn(page);
  const roleSelect = page.locator(".operations-header-actions select");

  await expect(roleSelect).toHaveValue("process_manager");
  await roleSelect.selectOption("field_operator");
  await expect(page).toHaveURL(/role=field_operator/);
  await expect(page.getByTestId("operations-overview")).toBeVisible();
  await expect(page.locator(".operations-page-heading h1")).toHaveText("점검 요청 · 의심 부품 · 처리 작업");
  await expect(page).not.toHaveURL(/\/login/);

  await roleSelect.selectOption("process_manager");
  await expect(page).toHaveURL(/role=process_manager/);
  await expect(page.locator(".operations-page-heading h1")).toHaveText("공정 리스크 · 계획 영향 · 진행 현황");
});

test("asset selection opens the evidence and workflow detail drawer", async ({ page }) => {
  await signIn(page);
  const actionable = page.getByRole("button", { name: /CNC-S04-L04-01/ });
  await expect(actionable).toBeVisible();
  await actionable.click();

  const drawer = page.getByRole("dialog", { name: "선택 설비 상세" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole("tab", { name: "상태", exact: true })).toBeVisible();
  await expect(drawer.getByRole("tab", { name: "처리", exact: true })).toBeVisible();
});

test("legacy project surfaces converge to the canonical operations route", async ({ page }) => {
  await signIn(page);
  await page.goto(`/app/projects/${PROJECT}/blueprint-v2`);

  await expect(page).toHaveURL(new RegExp(`/app/projects/${PROJECT}/operations`));
  await expect(page.getByTestId("operations-overview")).toBeVisible();
});

test("operations stays usable at a mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page);

  await expect(page.locator(".operations-app")).toBeVisible();
  await page.getByRole("button", { name: "메뉴 열기" }).click();
  await expect(page.locator(".operations-navigation")).toHaveClass(/is-open/);
  await expect(page.locator(".operations-navigation nav button").first()).toBeVisible();
});
