import { test, expect } from "@playwright/test";

test("cited evidence opens its object path and is removed on selection and work changes", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  let pending = false;
  await page.route("**/api/objects/*/agent-review-summary?*", async route => {
    const asset = new URL(route.request().url()).pathname.split("/")[3];
    await route.fulfill({json: {summary: pending ? null : {asset_id:asset,mode:"llm",summary:`${asset} 설비의 납기를 확인하세요. [[ref:1]]`,source_refs:["delivery"],limitations:[],role_summaries:[]},trace:{fallback:false,materialization:{status:pending?"stale":"ready",summary_key:`key-${asset}`}}}});
  });
  await page.route("**/api/objects/*/agent-review-packet?*", async route => {
    const asset = new URL(route.request().url()).pathname.split("/")[3];
    const step = (source_type:string,source_id:string,target_type:string,target_id:string) => ({edge_id:source_id+target_id,source_type,source_id,target_type,target_id,relationship_type:"linked",source_refs:["delivery"],source_version:"v1"});
    await route.fulfill({json:{project_id:"project",asset_id:asset,generated_at:"2026-09-09T00:00:00Z",snapshot_basis:{event_id:`event-${asset}`},source_refs:["delivery"],evidence_context:{selected_basis:[{
      candidate_id:"delivery",source_ref:"delivery",fact_type:"delivery_commitments",value_summary:"",
      display_fields:[{label:"납품 약정 수량",value:"200"},{label:"납기",value:"2026-09-10 18:00"}],
      relation_paths:[{steps:[step("asset",asset,"operation","OP-20"),step("operation","OP-20","order","ORDER-10"),step("order","ORDER-10","delivery","DELIVERY-10")]}],
    }]}}});
  });
  await page.goto("/e2e/fixtures/evidence-navigation-preview.html");
  await page.getByText("근거",{exact:true}).click();
  await expect(page.getByLabel("연결 근거 상세")).toContainText("납품 약정 수량: 200");
  await expect(page.getByLabel("근거 연결 경로").locator("li")).toHaveText(["A","OP-20","ORDER-10","DELIVERY-10"]);
  await page.screenshot({path:"test-results/evidence-navigation-desktop.png",fullPage:true});
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path:"test-results/evidence-navigation-mobile.png",fullPage:true});
  await page.getByRole("button",{name:"다른 사건 선택"}).click();
  await expect(page.getByLabel("연결 근거 상세")).toHaveCount(0);
  await expect(page.locator(".natural-briefing-accessible")).toContainText("B 설비");
  await page.getByText("근거",{exact:true}).click();
  await expect(page.getByLabel("연결 근거 상세")).toContainText("B · event-B");
  pending = true;
  await page.getByRole("button",{name:"작업 상태 갱신"}).click();
  await expect(page.getByLabel("연결 근거 상세")).toHaveCount(0);
  await expect(page.locator(".natural-briefing-accessible")).toHaveCount(0);
});

test("withdraws an old briefing when evidence changes without a new observation", async ({ page }) => {
  await page.emulateMedia({reducedMotion:"reduce"});
  let changed=false;
  await page.route("**/api/objects/*/agent-review-summary?*",route=>route.fulfill({json:{summary:changed?null:{asset_id:"A",mode:"llm",summary:"이전 정비 기록에 따른 설명 [[ref:1]]",source_refs:["record"],limitations:[],role_summaries:[]},trace:{fallback:false,materialization:{status:changed?"pending":"ready",summary_key:"old-key"}}}}));
  await page.route("**/api/objects/*/agent-review-packet?*",async route=>{
    expect(new URL(route.request().url()).searchParams.get("expected_summary_key")).toBe("old-key");
    changed=true;
    await route.fulfill({status:409,json:{detail:{code:"briefing_evidence_changed",message:"changed"}}});
  });
  await page.goto("/e2e/fixtures/evidence-navigation-preview.html");
  await page.getByText("근거",{exact:true}).click();
  await expect(page.locator(".natural-briefing-accessible")).toHaveCount(0);
  await expect(page.getByRole("status")).toContainText("브리핑이 아직 없습니다");
});
