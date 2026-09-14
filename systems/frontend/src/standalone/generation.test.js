// @vitest-environment node
import {afterEach, expect, it, vi} from 'vitest';
import {readFileSync} from 'node:fs';
import {webcrypto} from 'node:crypto';
import {createContext, runInContext} from 'node:vm';
import {createOperationsAgentReviewSummary} from '../api';
import {acceptedBrief, briefingGenerationTrigger} from './aiBrief';
afterEach(()=>vi.unstubAllGlobals());
it.each([false,true])('standalone uses the HTTP-safe API (existing=%s)',async existing=>{
 const summary={asset_id:'A',mode:'llm'};
 const response={summary,trace:{fallback:false,materialization:{status:'ready'}}};
 const fetch=vi.fn().mockResolvedValue({ok:true,status:200,json:async()=>response});
 vi.stubGlobal('fetch',fetch);vi.stubGlobal('document',{cookie:'ontology_csrf=test-csrf'});
 vi.stubGlobal('crypto',{getRandomValues:webcrypto.getRandomValues.bind(webcrypto)});
 const state={canGenerateAi:true,detail:{},selectedAssetId:'A',selectedEventId:'E',model:{context:{datasetVersionId:'V'}},aiBrief:existing?summary:null};
 const source=readFileSync(new URL('./main.js',import.meta.url),'utf8');
 const handler=source.slice(source.indexOf('async function generateAi(data){'),source.indexOf('async function save(data)'));
 const context=createContext({state,generation:1,projectId:'P',controller:{signal:new AbortController().signal},emit(){},createOperationsAgentReviewSummary,acceptedBrief,briefingGenerationTrigger,loadAiBrief:vi.fn(),errorText:e=>e.message});
 runInContext(handler,context);await context.generateAi({assetId:'A',eventId:'E'});
 expect(state.aiError).toBeNull();expect(fetch).toHaveBeenCalledOnce();
 const [url,options]=fetch.mock.calls[0];
 expect(url).toContain(`trigger=${existing?'ui_manual_regeneration':'manual_materialization'}`);
 expect(url).toContain('event_id=E');expect(url).toContain('dataset_version_id=V');
 expect(options.method).toBe('POST');expect(options.headers.get('Idempotency-Key')).toMatch(/^[0-9a-f-]{36}$/);
 expect(options.headers.get('X-CSRF-Token')).toBe('test-csrf');expect(state.aiGenerating).toBe(false);
});
