import type { AssetDetailViewModel } from "../../src/features/operations/api/operationsContracts";
export function decisionDetailFixture(eventId: string, assetId: string, dataset = "dsv-canonical-v3-1"): AssetDetailViewModel {
  const observed = "2026-09-13T01:24:00Z";
  return {
    snapshot_basis: { artifact_id: "artifact-test", evidence_payload_reference: "evidence://artifact-test", asset_id: assetId, event_id: eventId, observed_at: observed, model_version: "model-test", dataset_version: dataset, source_sha256: "a".repeat(64) },
    asset: { asset_id: assetId, asset_type: "cnc", observed_at: observed, criticality: "high", criticality_basis: [], criticality_source: "equipment_master" },
    risk: { current: .82, threshold: .7, status_grade: "warning", prediction_horizon_hours: 24 },
    risk_series: [],
    features: [{ key: "tool_wear_min", label: "공구 누적 사용시간", unit: "분", current: { observed_at: observed, value: 210, quality_status: "good" }, history: { points: [] }, top_factor: { rank: 1, contribution: .4, direction: "risk_up", explanation_method: "shap" } }],
    equipment_history: [],
    maintenance_context: { last_maintenance_days_ago: 12, similar_events_30d: 2, open_work_order_exists: false },
    inspection_targets: [],
    operation_context: { load_level: "high", runtime_hours_7d: 120, production_impact: "high", event_impact: { event_id: eventId, equipment_id: assetId, line: "S04-L02", product_variant: "A", screen_priority: "plan_at_risk", impact_status: "estimated", estimated_lost_units: 25, basis: { estimated_downtime_minutes: 120, asset_units_per_hour: 12.5, formula: "minutes / 60 * units_per_hour" } } },
    review_priority: null,
    evidence: { artifact_id: "artifact-test", model_version: "model-test", dataset_version: dataset, source_kind: "runtime_inference", gaps: [{ field: "inspection", reason: "현장 점검 결과를 확인해야 합니다.", owner_domain: "maintenance" }] },
    data_status: { source: "canonical", is_stale: false, is_data_quality_hold: false, warnings: [] },
    closed_loop: {
      work_orders: [], inspection_results: [], maintenance_actions: [], maintenance_events: [], activities: [], runtime_status: null,
      available_actions: [{ action_id: "request_inspection_work_order", target_type: "event", target_id: eventId, label: "점검 요청", disabled_reason: null }],
      lifecycle_summary: { current_step: "evidence", current_step_label: "근거 확인", completed_steps: ["prediction"], next_step: "inspection_requested", source: "backend_closed_loop_policy" },
      primary_action: { action_id: "request_inspection_work_order", target_type: "event", target_id: eventId, label: "점검 요청", owner_role: "process_manager", owner_label: "생산 관리자", requires_input: true },
      timeline: [],
    },
  };
}
