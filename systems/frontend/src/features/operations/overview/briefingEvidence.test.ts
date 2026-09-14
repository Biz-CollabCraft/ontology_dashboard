import { expect, it } from "vitest";
import { resolveBriefingEvidence } from "./briefingEvidence";
import type { OperationsAgentReviewPacket } from "../api/operationsContracts";

it("keeps independent facts from one cited document and their ordered object paths", () => {
  const path = { steps: [{edge_id:"r1",source_type:"asset",source_id:"A",relationship_type:"executes",target_type:"operation",target_id:"OP",source_refs:["doc"],source_version:"v1"}] };
  const packet = { source_refs: ["doc"], evidence_context: {selected_basis: [
    {candidate_id:"parts",source_ref:"doc",fact_type:"part_requirements",value_summary:"부품 부족",relation_paths:[path]},
    {candidate_id:"staff",source_ref:"doc",fact_type:"technician_candidates",value_summary:"작업자 부재",relation_paths:[]},
    {candidate_id:"other",source_ref:"other-doc",fact_type:"wip",value_summary:"다른 주문"},
  ]} } as unknown as OperationsAgentReviewPacket;
  const items = resolveBriefingEvidence(packet, ["doc"]);
  expect(items.map(item=>item.id)).toEqual(["parts","staff"]);
  expect(items[0].paths).toEqual([path]);
  expect(resolveBriefingEvidence(packet,["other-doc"])).toEqual([]);
});

it("resolves an artifact-wide citation without turning missing risk into zero", () => {
  const packet = {source_refs:["RESULT-A"],snapshot_basis:{artifact_id:"RESULT-A",evidence_payload_reference:"RESULT-A",observed_at:"2026-09-09T00:00:00Z"},
    risk_summary:{status_grade:null,failure_probability:null},evidence_gaps:[{field:"risk",reason:"센서 확인 필요"}],
    model_expression_context:{top_factors:[]}} as unknown as OperationsAgentReviewPacket;
  const items=resolveBriefingEvidence(packet,["RESULT-A"]);
  expect(items).toHaveLength(1);
  expect(items[0].details).toContainEqual({label:"확인 필요",value:"센서 확인 필요"});
  expect(items[0].text).not.toContain("0%");
});

it("shows scheduling blockers alongside the available time", () => {
  const packet={source_refs:["window"],evidence_context:{selected_basis:[{candidate_id:"window",source_ref:"window",fact_type:"maintenance_windows",display_fields:[
    {label:"시작 가능",value:"14:00"},{label:"승인 필요",value:"예"},{label:"기존 작업과 일정 충돌",value:"예"}],relation_paths:[]}]}} as unknown as OperationsAgentReviewPacket;
  expect(resolveBriefingEvidence(packet,["window"])[0].text).toBe("시작 가능: 14:00 · 승인 필요: 예 · 기존 작업과 일정 충돌: 예");
});


it("shows the recorded inspection findings and readable outcome", () => {
  const packet={source_refs:["inspection"],maintenance_history_summary:{inspection_results:[{
    record_id:"ir",source_ref:"inspection",summary:"maintenance_recommended",status:"maintenance_recommended",
    outcome:"maintenance_recommended",findings:["체결부 진동 이상"],recorded_at:"2026-09-09T12:00:00Z"}]}} as unknown as OperationsAgentReviewPacket;
  const text=resolveBriefingEvidence(packet,["inspection"])[0].text;
  expect(text).toContain("체결부 진동 이상");
  expect(text).toContain("정비 필요");
  expect(text).not.toContain("maintenance_recommended");
});

it("maps repeated gaps and UTC dates without exposing internal diagnostics", () => {
  const packet = {source_refs:["snapshot"],snapshot_basis:{artifact_id:"snapshot",observed_at:"2026-09-09T19:14:15Z"},
    evidence_gaps:[0,1,2].map(i=>({field:`features[${i}].baseline`,reason:"baseline basis is incomplete"}))} as unknown as OperationsAgentReviewPacket;
  const [item] = resolveBriefingEvidence(packet,["snapshot"]);
  expect(item.details).toEqual([{label:"확인 필요",value:"센서 정상 범위 기준 미확인"}]);
  expect(item.text).toContain("2026. 09. 10. 04:14 (한국 시간)");
  expect(JSON.stringify(item)).not.toContain("baseline basis");
});

it("maps coordination fields without empty approval dates and names workflow activities", () => {
  const packet = {source_refs:["order","activity"],maintenance_history_summary:{work_orders:[{
    record_id:"order",source_ref:"order",summary:"raw approval note",production_coordination:{status:"pending",request:{work_summary:"체결부 정비",downtime_minutes:30,affected_items:"압축 공기 공급 중단"},response:{scheduled_window:""}}}],
    activities:[{record_id:"activity",source_ref:"activity",activity_type:"inspection.result_recorded",recorded_at:"2026-09-09T12:00:00Z"}]}} as unknown as OperationsAgentReviewPacket;
  const [order,activity] = resolveBriefingEvidence(packet,packet.source_refs);
  expect(order.text).toBe("점검 완료 · 생산 승인 대기");
  expect(order.details).toEqual([{label:"정비 내용",value:"체결부 정비"},{label:"요청 정지 시간",value:"30분"},{label:"생산 영향",value:"압축 공기 공급 중단"}]);
  expect(activity.title).toBe("점검 결과 기록");
  expect(activity.details?.[0].value).toContain("21:00 (한국 시간)");
});
