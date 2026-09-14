import assert from 'node:assert/strict';
import {chromium} from '@playwright/test';
const browser=await chromium.launch();const b='http://127.0.0.1:13311';const a=process.env.ASSET_ID||'CNC-S01-L02-01',event='RESULT#'+a+'#2026-08-29T23:00:00+09:00';
for(const [name,password,tab] of [['engineer','Engineer!2026','엔지니어'],['manager','Manager!2026','생산관리자'],['technician','Technician!2026','보전팀']]){
 const ctx=await browser.newContext({viewport:{width:1440,height:1100}});const login=await ctx.request.post(b+'/api/auth/login',{data:{email:name+'@ontology.local',password}});if(!login.ok())throw Error(name+' login '+login.status());
 const p=await ctx.newPage();p.on('pageerror',e=>console.log('PAGEERROR',e.message));await p.goto(b+'/factory-status-original/index.html?'+new URLSearchParams({project:'manufacturing-demo-project',workspace:'manufacturing-demo',asset:a,event}));await p.waitForFunction(()=>window.factoryState?.lineage&&!window.factoryState?.aiLoading);await p.getByRole('button',{name:new RegExp('^'+tab)}).click();
 const bars=await p.locator('div[style*="height: 110px"] > div').evaluateAll(els=>els.filter(e=>e.getBoundingClientRect().height>0).length);
 assert.ok(bars>=576,'four observed series must render 144 bars each');
 console.log(name,'visible bars',bars,'AI',await p.evaluate(()=>({ready:!!window.factoryState.aiBrief,canGenerate:window.factoryState.canGenerateAi,error:window.factoryState.aiError})));
 if(process.env.GENERATE_AI==='1'&&name==='manager'&&!await p.evaluate(()=>!!window.factoryState.aiBrief)){
  await p.locator('div[aria-label="AI 브리핑"]:visible button').filter({hasText:/^(생성|다시 생성)$/}).click();await p.waitForFunction(()=>!window.factoryState.aiGenerating,{},{timeout:90000});console.log('GENERATION',await p.evaluate(()=>({ready:!!window.factoryState.aiBrief,error:window.factoryState.aiError,fallback:!!window.factoryState.aiFallback})));
 }
 const body=await p.locator('body').innerText();
 if(name==='manager'){assert.ok(body.includes('주문 기준 완료 수량'));assert.ok(body.includes('잔여 차질'));}
 if(name==='technician')assert.ok(body.includes('등록된 필요 부품 없음'));
 assert.equal(await p.evaluate(()=>window.factoryState.canGenerateAi),name==='manager');
 if(process.env.EXPECT_AI==='1')assert.ok(await p.evaluate(()=>!!window.factoryState.aiBrief),'stored accepted AI summary must be readable');await p.screenshot({path:'../../docs/eval/standalone-page-2026-09-06/mapping-'+name+'.png',fullPage:true});await ctx.close();
}
await browser.close();
