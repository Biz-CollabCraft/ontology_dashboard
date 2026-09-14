import {it,expect} from 'vitest';
import {roleContext} from './roleContext.js';
it('separates role-specific fields and removes duplicate/internal rows',()=>{
 const rows=['설비 종류','마지막 정비 경과','공기 공급 대상','생산 영향 계산 조건','계획 정비 · 잔여 차질','정비 작업 상태','조치 기준 적용 모델','정비 준비 상태 · 자료 상태'].map(label=>({label,value:'값'}));
 const base={context:rows,opCtx:rows};
 const labels=v=>roleContext(v).map(r=>r.label);
 expect(labels(base)).toEqual(['설비 종류','마지막 정비 경과','공기 공급 대상']);
 expect(labels({...base,isMaint:true})).toEqual(['설비 종류','마지막 정비 경과','정비 작업 상태']);
 expect(labels({...base,isPlan:true})).toEqual(['설비 종류','공기 공급 대상','생산 영향 계산 조건','계획 정비 · 잔여 차질','정비 작업 상태']);
});
