// Only redirects the test page's replay API address to the isolated real-chain bridge.
// No prediction, packet, workflow, stored summary, or read response is mocked in the browser.
import {createRequire} from 'node:module';import {fileURLToPath} from 'node:url';import path from 'node:path';import fs from 'node:fs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const {chromium,expect}=createRequire(root+'/systems/frontend/package.json')('@playwright/test');
const browser=await chromium.launch();const p=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
const errors=[],checked=[];p.on('pageerror',e=>errors.push(e.message));
await p.route('http://127.0.0.1:8328/api/demo-briefing/**',async route=>{const response=await route.fetch({url:route.request().url().replace(':8328',':8338')});await route.fulfill({response});});
const button=p.getByRole('button',{name:'브리핑 검증',exact:true});
try{
 await p.goto('http://127.0.0.1:3318/demo-briefing.html');await expect(button).toBeEnabled();
 for(let id=1;id<=8;id++){
  const delivered=p.waitForResponse(r=>r.url().endsWith(`/cases/${id}`)&&r.request().method()==='GET');
  await p.getByLabel('입력 사례').selectOption(String(id));const delivery=await (await delivered).json();await expect(button).toBeEnabled();
  await expect(p.locator('.engineer-evidence-summary header')).toContainText(delivery.view_model.asset.asset_id);
  const observedValues=await p.locator('.engineer-live-signals article strong').allTextContents();
  for(const [i,feature] of delivery.view_model.features.slice(0,3).entries()){if(feature.current.value!==null)expect(observedValues[i]).toContain(Number(feature.current.value).toLocaleString('ko-KR',{maximumFractionDigits:2}));}
  const result=p.waitForResponse(r=>r.url().endsWith(`/cases/${id}/validate`));await button.click();const wire=await (await result).json();
  expect(wire.chain.stored_status).toBe('ready');expect(wire.chain.business_state_unchanged).toBe(true);expect(wire.chain.workflow.workflow.terminal_status).toBe('completed');
  for(const role of ['process_engineer','maintenance_technician','process_manager']){
   await p.getByLabel('확인 관점').selectOption(role);await expect(p.locator('.natural-briefing-line')).toHaveCount(3);
   await expect(p.locator('.natural-briefing time')).toHaveAttribute('datetime',delivery.view_model.snapshot_basis.observed_at);
   const quote=wire.summary.role_summaries.find(r=>r.role===role).quote;
   const actual=await p.locator('.natural-briefing-line > p').allTextContents();
   expect(actual.map(s=>s.trim())).toEqual(quote.split('\n').map(s=>s.replaceAll('**','').trim()));
   await expect(p.getByRole('button',{name:'근거를 읽고 확인',exact:true})).toBeEnabled();
   checked.push({caseId:id,role,summaryId:wire.chain.summary_id,workflowRunId:wire.chain.workflow_run_id});
  }
 }
 const failed=p.waitForResponse(r=>r.url().endsWith('/validate'));await p.getByRole('button',{name:'검증 실패 시연',exact:true}).click();const failedWire=await (await failed).json();
 expect(failedWire.chain.stored_status).toBe('fallback');expect(failedWire.chain.workflow.workflow.terminal_status).toBe('partial');
 await expect(p.locator('.natural-briefing-line')).toHaveCount(0);await expect(p.getByRole('button',{name:'근거를 읽고 확인',exact:true})).toBeDisabled();
 expect(errors).toEqual([]);
 const proof=await (await p.request.get('http://127.0.0.1:8338/proof')).json();
 fs.writeFileSync('/private/tmp/prediction-to-screen-chain-results.json',JSON.stringify({checked,failedResponseBlocked:true,errors,proof},null,2));
 console.log(JSON.stringify({normalRoleCases:checked.length,failedResponseBlocked:true,errors}));
}finally{await browser.close();}
