// Stored AI prose is supplementary; structured facts and permissions remain authoritative.
export function acceptedBrief(response,assetId){
 if(!response?.summary)return null;
 if(response.summary.asset_id!==assetId)throw new Error('AI 브리핑 설비 불일치');
 return response.summary.mode==='llm'&&!response.trace?.fallback&&response.trace?.materialization?.status==='ready'?response.summary:null;
}
// A missing role quote uses common prose, never another role's quote.
export function roleBrief(summary,role){
 const quote=summary?.role_summaries?.find(item=>item.role===role)?.quote;
 return typeof quote==='string'&&quote.trim()?quote:summary?.summary||'';
}
export function briefPresentation(state){
 const b=state.aiBrief;
 let status=state.aiGenerating?'생성 중':state.aiLoading?'조회 중':state.aiFallback?'기본 근거 제공':state.aiError|| (b?'저장됨':state.canGenerateAi?'요청 시 생성':'생성 권한 없음');
 return {aiStatus:status,aiButtonLabel:state.aiGenerating?'생성 중':b?'다시 생성':'생성',aiDisabled:!state.canGenerateAi||state.aiGenerating||state.aiLoading||!state.detail||!!state.error,aiHelp:state.aiError||'',aiAvailabilityNote:state.detail&&!state.error?'현재 상태와 판단 근거는 AI 설명 생성 여부와 관계없이 제공됩니다.':'현재 설비 정보를 먼저 확인하세요.'};
}

// Initial creation may reuse a watcher result completed since the last GET.
// Only the visible "다시 생성" action opts into replacing a ready explanation.
export function briefingGenerationTrigger(state){
 return state.aiBrief?'ui_manual_regeneration':'manual_materialization';
}
