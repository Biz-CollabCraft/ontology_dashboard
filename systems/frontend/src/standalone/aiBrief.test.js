import {it,expect} from 'vitest';
import {acceptedBrief,briefPresentation,roleBrief} from './aiBrief.js';
it('selects exactly the requested role and falls back to common legacy prose',()=>{
 const summary={summary:'공통 근거',role_summaries:[{role:'process_engineer',quote:'엔지니어 근거'},{role:'maintenance_technician',quote:'정비 준비'},{role:'process_manager',quote:'생산 영향'}]};
 expect(roleBrief(summary,'process_engineer')).toBe('엔지니어 근거');
 expect(roleBrief(summary,'maintenance_technician')).toBe('정비 준비');
 expect(roleBrief(summary,'process_manager')).toBe('생산 영향');
 expect(roleBrief({...summary,role_summaries:[{role:'field_operator',quote:'옛 현장 문장'}]},'process_engineer')).toBe('공통 근거');
 expect(roleBrief({...summary,role_summaries:[{role:'maintenance_technician',quote:' '}]},'maintenance_technician')).toBe('공통 근거');
});
it('accepts only validated stored LLM prose for this asset',()=>{const r={summary:{asset_id:'A',mode:'llm',summary:'근거'},trace:{fallback:false,materialization:{status:'ready'}}};expect(acceptedBrief(r,'A')).toBe(r.summary);expect(()=>acceptedBrief(r,'B')).toThrow();expect(acceptedBrief({...r,trace:{fallback:true,materialization:{status:'fallback'}}},'A')).toBeNull();expect(acceptedBrief({summary:null},'A')).toBeNull();});
it('does not grant generation rights through display tabs',()=>{expect(briefPresentation({detail:{},canGenerateAi:false}).aiDisabled).toBe(true);expect(briefPresentation({detail:{},canGenerateAi:true,aiGenerating:true}).aiDisabled).toBe(true);expect(briefPresentation({detail:{},canGenerateAi:true,aiError:'403'}).aiStatus).toBe('403');});
it('keeps current evidence available while AI is pending, generating, or fallback',()=>{
 for(const flags of [{},{aiGenerating:true},{aiFallback:{reason:'TimeoutError'}}]){
  const v=briefPresentation({detail:{},canGenerateAi:true,...flags});
  expect(v.aiAvailabilityNote).toContain('현재 상태와 판단 근거');
 }
 expect(briefPresentation({detail:{},canGenerateAi:true,aiFallback:{}}).aiStatus).toBe('기본 근거 제공');
 expect(briefPresentation({detail:{},canGenerateAi:true,aiGenerating:true,aiLoading:true}).aiStatus).toBe('생성 중');
});
