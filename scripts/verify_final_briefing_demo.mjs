// Real local replay API, no browser network stubs or model calls.
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import fs from 'node:fs';
const root=process.env.DEMO_REPO || path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const require=createRequire(root+'/systems/frontend/package.json');
const {chromium,expect}=require('@playwright/test');
const output=process.env.BRIEFING_SCREENSHOT_DIR||'/private/tmp/final-briefing-demo-captures';fs.mkdirSync(output,{recursive:true});
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1100}});
const errors=[],requests=[],results=[];
page.on('pageerror',e=>errors.push(e.message));
page.on('request',r=>{if(r.method()==='POST')requests.push(r.url());});
try{
 await page.goto('http://127.0.0.1:3318/demo-briefing.html');
 const validate=page.getByRole('button',{name:'브리핑 검증',exact:true}), confirm=page.getByRole('button',{name:'근거를 읽고 확인',exact:true});
 await expect(validate).toBeEnabled();await expect(confirm).toBeDisabled();await expect(page.locator('.natural-briefing-line')).toHaveCount(0);
 await page.screenshot({path:output+'/pending.png',fullPage:true});
 await validate.click();await expect(page.locator('.natural-briefing-prose')).toHaveAttribute('data-streaming','true');
 const h=await page.locator('.natural-briefing-prose').evaluate(e=>e.clientHeight);
 await expect(page.locator('.natural-briefing-prose')).toHaveAttribute('data-streaming','false',{timeout:8000});
 if(h!==await page.locator('.natural-briefing-prose').evaluate(e=>e.clientHeight))throw Error('stream changed layout');
 await expect(page.locator('.natural-briefing-cursor')).toHaveCount(1);
 await expect(page.locator('.natural-briefing-line').last().locator('strong')).not.toHaveCount(0);
 await confirm.click();await expect(page.getByRole('button',{name:'엔지니어 확인 완료'})).toBeDisabled();
 await page.screenshot({path:output+'/engineering-ready.png',fullPage:true});
 await validate.click();await expect(page.locator('.natural-briefing-prose')).toHaveAttribute('data-streaming','false');
 await page.emulateMedia({reducedMotion:'reduce'});
 for(const caseId of [1,2,3,4,5,6,7,8]){
  if(await page.getByLabel('입력 사례').inputValue()!==String(caseId)){
   const loaded=page.waitForResponse(r=>r.url().endsWith(`/cases/${caseId}`)&&r.request().method()==='GET');
   await page.getByLabel('입력 사례').selectOption(String(caseId));await loaded;await expect(confirm).toBeDisabled();
  }
  await expect(validate).toBeEnabled();await validate.click();await expect(page.locator('.natural-briefing-prose')).toHaveAttribute('data-streaming','false');
  for(const role of ['process_engineer','maintenance_technician','process_manager']){
   await page.getByLabel('확인 관점').selectOption(role);
   await expect(page.locator('.natural-briefing-prose')).toHaveAttribute('data-streaming','false');
   await page.locator('details').evaluateAll(ds=>ds.forEach(d=>d.open=true));
   const text=await page.locator('body').innerText();
   if(/maintenance_recommended|fixture|스냅샷|N·m|\bmin\b|\[\[ref:|source_ref|schema_version|owner_domain|RESULT#|closed-loop:\/\/|\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(text))throw Error(`raw text leaked: ${caseId}/${role}`);
   const lines=await page.locator('.natural-briefing-line').count();if(lines<3||lines>5)throw Error(`sentence lines ${caseId}/${role}: ${lines}`);
   if(await page.locator('.natural-briefing').evaluate(e=>e.scrollWidth>e.clientWidth))throw Error('overflow');
   if(caseId===3){
    if(role==='maintenance_technician'&&!text.includes('착수'))throw Error('missing execution boundary');
    await page.locator('details').evaluateAll(ds=>ds.forEach(d=>d.open=false));
    await page.screenshot({path:`${output}/${role}-ready.png`,fullPage:true});
   }
   results.push({caseId,role,lines,ready:true});
  }
 }
 await page.getByRole('button',{name:'검증 실패 시연',exact:true}).click();
 await expect(page.locator('.natural-briefing-line')).toHaveCount(0);await expect(confirm).toBeDisabled();
 await expect(page.locator('.natural-briefing-status')).toContainText('검증을 통과하지 못한 응답');
 if((await page.locator('body').innerText()).includes('AI가 자동 승인'))throw Error('rejected prose visible');
 await page.screenshot({path:output+'/fallback.png',fullPage:true});
 if(errors.length||requests.some(url=>!url.startsWith('http://127.0.0.1:8328/api/demo-briefing/cases/')))throw Error(JSON.stringify({errors,requests}));
 fs.writeFileSync(output+'/verification.json',JSON.stringify({cases:results,initialStreaming:true,stableHeight:true,noReplay:true,pending:true,fallback:true,confirmation:true,errors,requests},null,2));
 console.log(JSON.stringify({roleCases:results.length,initialStreaming:true,noReplay:true,fallback:true,errors,postCount:requests.length,output}));
}finally{await browser.close();}
