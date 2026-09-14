import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
const labels: Record<string,string> = { MONITOR:"계속 모니터링", REQUEST_ADDITIONAL_DIAGNOSIS:"추가 진단 요청", REQUEST_INSPECTION:"점검 요청", REQUEST_MAINTENANCE:"정비 요청", REVIEW_PLANNED_MAINTENANCE:"계획 정비 검토" };
const selectedEvent = process.env.DECISION_LIVE_EVENT_ID;
const assets = process.env.DECISION_LIVE_ASSET_ID ? [process.env.DECISION_LIVE_ASSET_ID] : ["CNC-S04-L02-03","CMP-S03-L03-01"];
for (const asset of assets) {
test(`real local backend: ${asset} decision -> human review, no fixtures or workflow mutation`, async ({ page }) => {
  test.skip(process.env.DECISION_LIVE_UI !== "1", "Requires explicitly selected existing local backend");
  test.setTimeout(90000);
  const seed = readFileSync("../backend/app/identity/identity_schema.py", "utf8").split("DEMO_ACCOUNTS:")[1];
  const account = seed.match(/"email": "([^"]+)",\s*"password": "([^"]+)",\s*"display_name": "[^"]+",\s*"roles": \["process_manager"\]/);
  if (!account) throw new Error("Seeded manager unavailable");
  const mutations: string[] = [], errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  page.on("request", r => { if (r.method() !== "GET" && r.url().includes("/maintenance/")) mutations.push(r.url()); });
  await page.goto("/login?returnTo=" + encodeURIComponent("/app/projects/manufacturing-demo-project/operations?view=overview&workspace_id=manufacturing-demo"));
  await page.getByLabel("이메일").fill(account[1]);
  await page.getByLabel("비밀번호").fill(account[2]);
  await page.getByRole("button", {name:"로그인",exact:true}).click();
  await page.getByLabel("설비 검색").fill(asset);
  const detailPromise = page.waitForResponse(r => r.url().includes(`/api/objects/${asset}/detail-view`));
  const sessionPromise = page.waitForResponse(r => r.request().method()==="POST" && r.url().includes(`/api/objects/${asset}/decision-sessions`));
  if (selectedEvent) {
    await page.goto("/app/projects/manufacturing-demo-project/operations?" + new URLSearchParams({
      view:"operations", workspace_id:"manufacturing-demo", asset_id:asset, event_id:selectedEvent,
    }));
  } else {
    await page.locator(".dw-machine").filter({hasText:asset}).click();
  }
  const detailResponse = await detailPromise;
  expect(detailResponse.status()).toBe(200);
  const detail = await detailResponse.json();
  expect(detail.data_status.source).toBe("canonical");
  expect(detail.snapshot_basis.asset_id).toBe(asset);
  expect(detail.snapshot_basis.evidence_payload_reference).toBeTruthy();
  expect(detail.risk_series.length).toBeGreaterThan(0);
  const sessionResponse=await sessionPromise;
  expect(sessionResponse.status()).toBe(200);
  const wire=await sessionResponse.json(), s=wire.session;
  expect(s.snapshot_basis).toEqual(detail.snapshot_basis);
  expect(s.mutation_attempted).toBe(false);
  expect(s.status).toBe("ready_for_review");
  expect(s.allowed_actions).toContain(s.proposal.recommended_action);
  await expect(page.getByRole("heading",{name:"판단 조건과 근거"})).toBeVisible();
  const proposal=page.locator(".dw-proposal");
  await expect(proposal.getByRole("button",{name:labels[s.proposal.recommended_action],exact:true})).toBeEnabled();
  expect(await proposal.locator("button").count()).toBeLessThanOrEqual(2);
  await proposal.getByRole("button",{name:labels[s.proposal.recommended_action],exact:true}).click();
  await expect(page.getByRole("region",{name:"사용자 검토"})).toBeVisible();
  expect(mutations).toEqual([]);
  for(const width of [1440,768,390]) {
    await page.setViewportSize({width,height:1000});
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await page.screenshot({path:`test-results/decision-live-${asset}-${width}.png`,fullPage:true});
  }
  if(wire.execution_bindings[s.proposal.recommended_action]) {
    await page.getByRole("button",{name:"검토 후 요청 내용 확인",exact:true}).click();
    await expect(page.getByRole("region",{name:"Closed-loop 작업 실행"})).toBeVisible();
    await expect(page.getByRole("button",{name:"점검 작업요청 생성",exact:true})).toBeEnabled();
  }
  expect(mutations).toEqual([]);
  expect(errors).toEqual([]);
});
}
