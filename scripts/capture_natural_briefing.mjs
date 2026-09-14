// UI replay only: local Gold v5 prose; no live LLM calls or operational mutations.
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const baseURL=process.env.BRIEFING_PREVIEW_URL || 'http://127.0.0.1:3318';
const require=createRequire(root+'/systems/frontend/package.json');
const {chromium}=require('@playwright/test');
const gold=JSON.parse(fs.readFileSync(root+'/tests/fixtures/agent_review_packets/natural_briefing_v5/gold-v5.json'));
const reference=JSON.parse(fs.readFileSync(root+'/systems/frontend/e2e/fixtures/natural-briefing-preview.json')).reference;
const packet=JSON.parse(fs.readFileSync(root+'/tests/fixtures/agent_review_packets/GS-002.json'));
const observed=packet.snapshot_basis.observed_at;
const asset={assetId:'CNC-S01-L01-01',displayName:'1구역 1셀 CNC 가공기 1',assetType:'cnc',line:'S01',cell:'S01-L01',site:'공장 A',status:'critical',failureProbability:.89,confidence:'high',criticality:'high',assignedEngineer:'설비 담당',estimatedDowntimeMinutes:120,sparePartAvailable:null,predictedFailureType:'tool_wear',recommendedDecision:'review_shutdown',observedAt:observed,eventId:'EVT-GS-002',topFactors:[{id:'torque',feature:'torque_nm',label:'토크',value:68,unit:'N·m',contribution:.42,direction:'risk_up'},{id:'wear',feature:'tool_wear_min',label:'공구 사용시간',value:210,unit:'min',contribution:.28,direction:'risk_up'}],riskHistory:[.25,.29,.4,.54,.67,.82,.89].map((value,i)=>({value,observedAt:`2026-09-08T01:${String(i*8).padStart(2,'0')}:00Z`})),sensorHistory:[]};
Object.assign(asset,{assetId:packet.asset_id,displayName:packet.asset_label,line:'S04',cell:'S04-L04',status:'warning',failureProbability:packet.risk_summary.failure_probability,estimatedDowntimeMinutes:120,topFactors:packet.model_expression_context.top_factors.map((f,i)=>({id:String(i),feature:f.feature,label:f.display_name,value:f.value,unit:f.unit,contribution:f.contribution,direction:f.direction})),riskHistory:[{value:packet.risk_summary.failure_probability,observedAt:observed}]});
const order={asset_type:'cnc',work_order_id:'inspection-review-0001',asset_id:asset.assetId,event_id:asset.eventId,equipment_id:asset.assetId,status:'requested',assigned_to:'review-user',assigned_to_display_name:'보전 담당',created_at:observed,inspection_result:null};
const coordination={work_order_id:order.work_order_id,asset_id:asset.assetId,event_id:asset.eventId,request_id:'review-request-1',status:'pending',work_order_status:'approved',request:{work_summary:'공구 상태 확인과 점검 범위 검토',downtime_minutes:120,affected_items:'가공 품목',note:''},requested_by:'review-user',requested_by_name:'보전 담당',requested_at:observed,response:null,responded_at:null,responded_by:null,responded_by_name:null};
const model={context:{projectId:'manufacturing-demo-project',workspaceId:'manufacturing-demo',workspaceName:'공장 A · 고정 입력 화면 검토',datasetVersionId:'review-fixture',observedAt:observed,warnings:[]},assets:[asset],events:[],metrics:{critical:1,warning:0,attention:0,normal:0,estimatedDowntimeMinutes:120}};
const detail={asset:{asset_id:asset.assetId,display_name:asset.displayName,observed_at:observed},snapshot_basis:{asset_id:asset.assetId,event_id:asset.eventId,observed_at:observed},risk:{current:.89},risk_series:[],features:[],operation_context:{production_plan:null,capacity_model:{asset_units_per_hour:12.5},event_impact:{estimated_lost_units:25}}};
const browser=await chromium.launch({headless:true});
const screenshots=process.env.BRIEFING_SCREENSHOT_DIR || '/tmp/ontology-natural-briefing-screenshots';fs.mkdirSync(screenshots,{recursive:true});
for(const persona of ['engineering','maintenance','production']){
 const page=await browser.newPage({viewport:{width:1440,height:1000},deviceScaleFactor:1});const errors=[];let posts=0;
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')console.log(m.text());});page.on('requestfailed',r=>console.log(r.url(),r.failure()));
 await page.addInitScript(data=>{window.__BRIEFING_FIXTURE__=data;},{model,orders:[order]});
 await page.route('**/health/ready', route=>route.fulfill({json:{status:'ok'}}));
 await page.route('**/api/**',async route=>{
  const url=route.request().url();if(!new URL(url).pathname.startsWith('/api/'))return route.continue();if(route.request().method()==='POST')posts++;
  let data={items:[]};
  if(url.includes('/agent-review-summary'))data={summary:{...reference,schema_version:'agent-review-summary-v1.1',mode:'llm',asset_id:asset.assetId,source_refs:[],limitations:[]},trace:{fallback:false,materialization:{status:'ready'}}};
  else if(url.includes('/detail-view'))data=detail;
  else if(url.includes('/inspection-coordinations'))data={items:[coordination]};
  else if(url.includes('/lineage'))data={event_id:asset.eventId,work_orders:[],inspection_results:[],recommendations:[],cost_analyses:[]};
  else if(url.includes('/auth/me'))data={user:null,csrf_token:null};
  await route.fulfill({json:data});
 });
 await page.goto(baseURL+'/e2e/fixtures/natural-briefing-preview.html?persona='+persona);
 if(persona==='maintenance')await page.locator('.maintenance-request-item').first().click();
 try { await page.locator('.natural-briefing-line').first().waitFor({timeout:10000}); } catch(e) { console.log(JSON.stringify({errors,body:(await page.locator('body').innerText()).slice(0,3000)}));await browser.close();throw e; }
 await page.locator('.natural-briefing').scrollIntoViewIfNeeded();
 await page.screenshot({path:`${screenshots}/${persona}.png`,fullPage:true});
 const metrics=await page.locator('.natural-briefing').evaluate(el=>({width:el.clientWidth,height:el.clientHeight,lines:el.querySelectorAll('.natural-briefing-line').length,overflow:el.scrollWidth>el.clientWidth}));
 if(posts||errors.length||metrics.overflow)throw new Error(JSON.stringify({persona,posts,errors,metrics}));
 console.log(JSON.stringify({persona,posts,errors,metrics}));
 await page.close();
}
await browser.close();
