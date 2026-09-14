import {it,expect} from 'vitest';
import {mapRoleData} from './roleData.js';
const helpers={number:v=>v==null?'미산정':String(v),date:v=>v,label:v=>v};
it('maps order progress without requiring daily planning',()=>{
 const v={isPlan:true};const state={contextRead:{domains:{production:{context:{status:'available',data:{production_orders:[{order_id:'O',required_quantity:200,completed_quantity:150}],wip:[{order_id:'O',quantity:50}]}}}},production_impact:{options:[{option:'stop_now',state:'calculated',required_units:50,remaining_exposed_units:50,primary_capacity_after_action:0}]}}};
 mapRoleData(v,state,helpers);expect(v.kpis.map(k=>k.value)).toEqual(['200','150','50']);expect(v.shifts[0].madePct).toBe('75%');expect(v.variants[0].short).toBe('50개');
});
it('distinguishes empty maintenance candidates from missing context',()=>{
 const v={isMaint:true};mapRoleData(v,{lineage:{work_orders:[]},contextRead:{domains:{maintenance_readiness:{context:{status:'available',data:{technician_candidates:[],maintenance_windows:[],part_requirements:[]}}}}}},helpers);
 expect(v.kpis.map(k=>k.value)).toEqual(['0','0','0']);expect(v.windows[0].state).toBe('후보 없음');expect(v.curReqId).toBe('작업지시 없음');expect(v.procurementEmpty).toBe('등록된 필요 부품 없음');
 const other={isMaint:true};mapRoleData(other,{},helpers);expect(other.kpis[1].value).toBe('자료 없음');
});
