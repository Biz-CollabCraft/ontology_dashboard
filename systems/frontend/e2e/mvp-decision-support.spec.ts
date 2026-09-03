import { expect, type Page, test } from "@playwright/test";

const PROJECT = "manufacturing-demo-project";
const PATH = `/app/projects/${PROJECT}/mvp?view=overview&dashboard=workflow&role=process_manager&workspace_id=manufacturing-demo&asset_id=CNC-S04-L02-03&event_id=EVT-GS-004`;
const ACCOUNTS = {
  manager: ["manager@ontology.local", "Manager!2026"],
  engineer: ["engineer@ontology.local", "Engineer!2026"],
} as const;
let loginAttempt = 40;

const brief = {
  schema_version: "operational-decision-brief-v1.0",
  frame: {
    evidence_snapshot_id: "ARTIFACT-GS-004",
    decision_as_of: "2026-09-03T00:00:00Z",
    actor_role: "process_manager",
    intent: "maintenance_timing_decision",
    risk_status: "critical",
    asset_id: "CNC-S04-L02-03",
    active_operation_ids: ["OP-MILL-20"],
    active_constraints: ["part_inventory"],
    context_version_set: {
      production: "OPS-DECISION-SNAPSHOT-2026-09-02-01",
      maintenance_readiness: "MAINT-READINESS-SNAPSHOT-2026-09-02-01",
      quality_delivery: "QUALITY-DELIVERY-SNAPSHOT-2026-09-02-01",
    },
  },
  why_now: {
    risk_status: "critical",
    asset_id: "CNC-S04-L02-03",
    order_ids: ["DEMO-PO-001"],
    wip_units: 200,
    lot_ids: ["DEMO-LOT-014"],
    earliest_due_at: "2026-09-03T18:00:00+09:00",
    decision_blockers: ["part_inventory"],
    source_refs: ["fixture:production", "fixture:maintenance"],
  },
  relationships: [{
    relationship_type: "asset_processes_order",
    from_ref: "CNC-S04-L02-03",
    to_ref: "DEMO-PO-001",
    status: "assumed_demo",
    source_refs: ["fixture:production"],
  }],
  readiness: { overall_state: "blocked" },
  option_comparison: [
    { option: "stop_now", calculation_state: "calculated", assumptions: {}, formula: "v1", source_refs: [] },
    { option: "planned_maintenance", calculation_state: "calculated", assumptions: {}, formula: "v1", source_refs: [] },
    { option: "continue_operation", calculation_state: "not_calculable", assumptions: {}, formula: null, source_refs: [] },
  ],
  gaps: [{
    state: "blocked",
    owner_domain: "maintenance_readiness",
    blocks_options: ["planned_maintenance"],
    detail: { reason: "part_inventory" },
  }],
  role_sections: ["why_now", "option_comparison"],
  source_classifications: {
    production: "synthetic_demo_context",
    maintenance_readiness: "synthetic_demo_context",
  },
  source_refs: ["fixture:production", "fixture:maintenance"],
  limitations: ["Demo context only."],
  mutation_available: false,
  recommendation: null,
};

async function login(page: Page, account: keyof typeof ACCOUNTS) {
  const [email, password] = ACCOUNTS[account];
  await page.route("**/api/auth/login", async (route) => {
    await route.continue({
      headers: {
        ...route.request().headers(),
        "X-Forwarded-For": `127.0.0.${++loginAttempt}`,
      },
    });
  }, { times: 1 });
  await page.goto(`/login?returnTo=${encodeURIComponent(PATH)}`);
  await page.getByLabel("이메일").fill(email);
  await page.getByLabel("비밀번호").fill(password);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/app/projects/${PROJECT}`));
}

async function openDecisionSupport(page: Page) {
  await expect(page.getByTestId("mvp-overview")).toBeVisible();
  await page.getByRole("button", { name: /위험 4구역 · 2셀 · CNC 가공기 3/ }).click();
  const dialog = page.getByRole("dialog", { name: "선택 설비 상세" });
  await expect(dialog).toBeVisible();
  return dialog.getByRole("region", { name: "운영 판단 지원" });
}

test("unmocked browser path materializes through FastAPI and SQLite", async ({ page }) => {
  await login(page, "manager");
  const panel = await openDecisionSupport(page);
  const responsePromise = page.waitForResponse((response) =>
    response.request().method() === "POST"
    && response.url().includes("/decision-support-brief"),
  );
  await panel.getByRole("button", { name: "맥락 갱신" }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  await expect(panel).toContainText("DEMO-PO-001");
  await expect(panel).toContainText("시간 검증 passed");
  await expect(panel).toContainText("자동 선택하지 않음");
  await expect(panel).toContainText("WorkOrder·정비 실행을 생성하지 않습니다");
});

test("manager materializes a decision brief and sees relationship context", async ({ page }) => {
  let stored = false;
  let postCount = 0;
  await page.route("**/api/objects/*/decision-support-brief?*", async (route) => {
    if (route.request().method() === "POST") {
      stored = true;
      postCount += 1;
    }
    await route.fulfill({
      status: stored ? 200 : 202,
      contentType: "application/json",
      body: JSON.stringify({
        brief: stored ? brief : null,
        trace: {
          status: stored ? "completed" : "pending",
          reason: stored ? null : "not_materialized",
          reused: route.request().method() === "GET" && stored,
          workflow_run_id: stored ? "ODR-E2E-001" : null,
          context_version_set: stored ? brief.frame.context_version_set : {},
          temporal_validation: stored ? "passed" : "not_measured",
        },
      }),
    });
  });

  await login(page, "manager");
  const panel = await openDecisionSupport(page);
  await expect(panel).toContainText("저장된 Brief가 없습니다");
  await panel.getByRole("button", { name: "맥락 갱신" }).click();
  await expect(panel).toContainText("DEMO-PO-001");
  await expect(panel).toContainText("CNC-S04-L02-03 → DEMO-PO-001");
  await expect(panel).toContainText("자동 선택하지 않음");
  await expect(panel).toContainText("WorkOrder·정비 실행을 생성하지 않습니다");
  expect(postCount).toBe(1);
});

test("engineer sees the decision panel as read only", async ({ page }) => {
  await page.route("**/api/objects/*/decision-support-brief?*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        brief,
        trace: {
          status: "completed",
          reason: null,
          reused: true,
          workflow_run_id: null,
          context_version_set: brief.frame.context_version_set,
          temporal_validation: "passed",
        },
      }),
    });
  });
  await login(page, "engineer");
  const panel = await openDecisionSupport(page);
  await expect(panel.getByRole("button", { name: "조회 전용" })).toBeDisabled();
  await expect(panel).toContainText("저장본 재사용");
});

test("partial context exposes gaps without inventing a recommendation", async ({ page }) => {
  await page.route("**/api/objects/*/decision-support-brief?*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        brief,
        trace: {
          status: "partial",
          reason: "context_gap",
          reused: true,
          workflow_run_id: "ODR-E2E-002",
          context_version_set: brief.frame.context_version_set,
          temporal_validation: "passed",
        },
      }),
    });
  });
  await login(page, "manager");
  const panel = await openDecisionSupport(page);
  await expect(panel).toContainText("Gap과 blocker");
  await expect(panel).toContainText("not_calculable");
  await expect(panel).not.toContainText("최적 선택");
  await expect(panel).not.toContainText("작업 생성");
});
