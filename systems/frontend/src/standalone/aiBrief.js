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
 let status=state.aiLoading?'조회 중':state.aiGenerating?'생성 중':state.aiError|| (b?'저장됨':state.aiFallback?'검증 실패':state.canGenerateAi?'생성 대기':'생성 권한 없음');
 return {aiStatus:status,aiButtonLabel:state.aiGenerating?'생성 중':b?'다시 생성':'생성',aiDisabled:!state.canGenerateAi||state.aiGenerating||state.aiLoading||!state.detail||!!state.error,aiHelp:state.aiError||''};
}
