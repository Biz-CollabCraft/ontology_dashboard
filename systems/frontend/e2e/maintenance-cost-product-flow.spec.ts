import { expect, type Page, test } from "@playwright/test";

const PROJECT = "manufacturing-demo-project";
const WORKSPACE = "manufacturing-demo";
const EVENT = "EVT-GS-004";
const PATH = `/app/projects/${PROJECT}/mvp?view=overview&dashboard=workflow&role=process_manager&workspace_id=${WORKSPACE}&asset_id=CNC-S04-L02-03&event_id=${EVENT}`;

async function login(page: Page) {
  await page.goto(`/login?returnTo=${encodeURIComponent(PATH)}`);
  await page.getByLabel("이메일").fill("manager@ontology.local");
  await page.getByLabel("비밀번호").fill("Manager!2026");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/app/projects/${PROJECT}`));
}

test("runs cost analysis only on request and keeps option selection proposed", async ({ page }) => {
  let analysisCreated = false;
  let recommendationCreated = false;
  let calculationRequests = 0;
  let selectionRequests = 0;

  const analysis = {
    schema_version: "maintenance-cost-scenario-v1.0",
    analysis_id: "COST-ANALYSIS-E2E",
    organization_id: "org-demo",
    project_id: PROJECT,
    workspace_id: WORKSPACE,
    asset_id: "CNC-S04-L02-03",
    equipment_id: "CNC-S04-L02-03",
    calculated_at: "2026-08-31T03:00:00Z",
    based_on: {
      product_result_id: "RESULT-E2E",
      evidence_id: "EVIDENCE-E2E",
      inspection_work_order_id: "INSPECTION-WO-E2E",
      inspection_result_id: "INSPECTION-RESULT-E2E",
      sop_id: "SOP-DEMO-CNC-ROTATING-ASSEMBLY-001",
      sop_version: "demo-2026-08-28",
    },
    currency: "KRW",
    currency_minor_unit: 0,
    options: [
      ["OPTION-IMMEDIATE", "immediate", 120_000],
      ["OPTION-PLANNED", "planned_window", 90_000],
      ["OPTION-REINSPECT", "reinspect_after", 160_000],
      ["OPTION-NONE", "no_action_baseline", 300_000],
    ].map(([optionId, timing, cost]) => ({
      option_id: optionId,
      action_candidate_id: "ACTION-CANDIDATE-E2E",
      action_code: "TOOL_REPLACEMENT",
      execution_timing: timing,
      calculation_status: "calculated",
      total_expected_cost: { low_minor: cost, base_minor: cost, high_minor: cost },
      expected_downtime: { low_minutes: 30, base_minutes: 30, high_minutes: 30 },
      confidence: "medium",
      missing_inputs: [],
    })),
    lowest_calculated_cost_option_id: "OPTION-PLANNED",
    assumptions: [],
    input_sources: [],
    missing_inputs: [],
    price_version: "user-input-2026-08-31",
    calculation_policy_version: "maintenance-cost-policy-v1",
    limitations: [
      "DECISION_SUPPORT_ONLY",
      "NOT_RECOMMENDATION",
      "NOT_APPROVAL",
      "NOT_EXECUTION_COMMAND",
      "COST_ESTIMATE_NOT_GUARANTEE",
    ],
  };

  await page.route("**/api/projects/*/workspaces/*/maintenance/events/*/lineage", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        event_id: EVENT,
        work_orders: [{
          work_order_id: "INSPECTION-WO-E2E",
          work_type: "inspection",
          status: "completed",
        }],
        inspection_results: [{
          inspection_result_id: "INSPECTION-RESULT-E2E",
          work_order_id: "INSPECTION-WO-E2E",
          event_id: EVENT,
          asset_id: "CNC-S04-L02-03",
          equipment_id: "CNC-S04-L02-03",
          outcome: "maintenance_recommended",
          recorded_at: "2026-08-31T02:00:00Z",
        }],
        cost_analyses: analysisCreated ? [analysis] : [],
        recommendations: recommendationCreated ? [{
          recommendation_id: "REC-COST-E2E",
          status: "proposed",
          source_inspection_work_order_id: "INSPECTION-WO-E2E",
          source_inspection_reference: "INSPECTION-RESULT-E2E",
          source_cost_analysis_id: analysis.analysis_id,
          source_cost_option_id: "OPTION-IMMEDIATE",
          source_action_candidate_id: "ACTION-CANDIDATE-E2E",
          action_code: "TOOL_REPLACEMENT",
        }] : [],
      }),
    });
  });

  await page.route("**/api/projects/*/workspaces/*/maintenance/inspection-results/*/cost-analyses", async (route) => {
    calculationRequests += 1;
    const request = route.request().postDataJSON();
    expect(request.scenarios).toHaveLength(4);
    expect(request.asset_id).toBeUndefined();
    analysisCreated = true;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        analysis_id: analysis.analysis_id,
        calculation_status: "calculated",
        cost_analysis: analysis,
        replayed: false,
      }),
    });
  });

  await page.route("**/api/projects/*/workspaces/*/maintenance/cost-analyses/*/options/*/recommendations", async (route) => {
    selectionRequests += 1;
    expect(route.request().postDataJSON()).toEqual({
      basis: ["다음 교대 전 즉시 교체가 운영상 적절함"],
    });
    recommendationCreated = true;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        recommendation_id: "REC-COST-E2E",
        recommendation_status: "proposed",
      }),
    });
  });

  await login(page);
  await page.locator(".mvp-factory-asset-node.is-selected").click();
  await page.getByRole("tab", { name: "처리", exact: true }).click();
  const panel = page.getByRole("region", { name: "정비 비용 분석" });
  await expect(panel).toBeVisible();
  expect(calculationRequests).toBe(0);

  await panel.getByRole("button", { name: "비용 분석 입력", exact: true }).click();
  await panel.getByLabel("참고한 SOP ID").fill("SOP-DEMO-CNC-ROTATING-ASSEMBLY-001");
  await panel.getByLabel("SOP 버전").fill("demo-2026-08-28");
  const inputs = panel.locator(".mvp-cost-inputs fieldset input");
  await expect(inputs).toHaveCount(28);
  for (let index = 0; index < 28; index += 1) await inputs.nth(index).fill("10");
  await panel.getByRole("button", { name: "비용 계산", exact: true }).click();

  await expect.poll(() => calculationRequests).toBe(1);
  await expect(panel.getByText("계산상 최저비용", { exact: true })).toBeVisible();
  await panel.getByPlaceholder("사용자가 이 시점을 선택한 이유").fill("다음 교대 전 즉시 교체가 운영상 적절함");
  await panel.getByRole("button", { name: "이 시점 선택", exact: true }).first().click();

  await expect.poll(() => selectionRequests).toBe(1);
  await expect(panel.getByText(/제안 상태로 생성되었습니다/)).toBeVisible();
  await expect(panel.getByText(/별도 승인 전에는 WorkOrder가 생성되지 않습니다/)).toBeVisible();
  await expect(panel.getByRole("button", { name: "제안 생성됨", exact: true })).toBeDisabled();
  const blockedOption = panel.getByRole("button", { name: "이미 정비안 선택됨", exact: true });
  await expect(blockedOption).toBeDisabled();
  await blockedOption.evaluate((button: HTMLButtonElement) => button.click());
  expect(selectionRequests).toBe(1);
});

test("does not expose a previous inspection's cost analysis for a newer inspection", async ({ page }) => {
  await page.route("**/api/projects/*/workspaces/*/maintenance/events/*/lineage", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        event_id: EVENT,
        work_orders: [
          { work_order_id: "INSPECTION-WO-A", work_type: "inspection", status: "completed" },
          { work_order_id: "INSPECTION-WO-B", work_type: "inspection", status: "completed" },
        ],
        inspection_results: [
          {
            inspection_result_id: "INSPECTION-RESULT-A",
            work_order_id: "INSPECTION-WO-A",
            event_id: EVENT,
            asset_id: "CNC-S04-L02-03",
            equipment_id: "CNC-S04-L02-03",
            outcome: "maintenance_recommended",
            recorded_at: "2026-08-31T02:00:00Z",
          },
          {
            inspection_result_id: "INSPECTION-RESULT-B",
            work_order_id: "INSPECTION-WO-B",
            event_id: EVENT,
            asset_id: "CNC-S04-L02-03",
            equipment_id: "CNC-S04-L02-03",
            outcome: "maintenance_recommended",
            recorded_at: "2026-08-31T03:00:00Z",
          },
        ],
        cost_analyses: [{
          schema_version: "maintenance-cost-scenario-v1.0",
          analysis_id: "COST-ANALYSIS-A",
          organization_id: "org-demo",
          project_id: PROJECT,
          workspace_id: WORKSPACE,
          asset_id: "CNC-S04-L02-03",
          equipment_id: "CNC-S04-L02-03",
          calculated_at: "2026-08-31T02:30:00Z",
          based_on: {
            product_result_id: "RESULT-E2E",
            evidence_id: "EVIDENCE-E2E",
            inspection_work_order_id: "INSPECTION-WO-A",
            inspection_result_id: "INSPECTION-RESULT-A",
            sop_id: "SOP-DEMO-CNC-ROTATING-ASSEMBLY-001",
            sop_version: "demo-2026-08-28",
          },
          currency: "KRW",
          currency_minor_unit: 0,
          options: [],
          lowest_calculated_cost_option_id: null,
          assumptions: [],
          input_sources: [],
          missing_inputs: [],
          price_version: "user-input-2026-08-31",
          calculation_policy_version: "maintenance-cost-policy-v1",
          limitations: [],
        }],
        recommendations: [],
      }),
    });
  });

  await login(page);
  await page.locator(".mvp-factory-asset-node.is-selected").click();
  await page.getByRole("tab", { name: "처리", exact: true }).click();
  const panel = page.getByRole("region", { name: "정비 비용 분석" });

  await expect(panel).toBeVisible();
  await expect(panel.getByRole("button", { name: "비용 분석 입력", exact: true })).toBeVisible();
  await expect(panel.getByText("최근 분석", { exact: true })).toHaveCount(0);
  await expect(panel.getByRole("button", { name: "이 시점 선택", exact: true })).toHaveCount(0);
});
