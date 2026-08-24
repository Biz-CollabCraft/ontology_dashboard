import { describe, expect, it } from "vitest";
import type { EventSummary } from "../../../types";
import {
  adaptEvent,
  applyAssetDetailViewModel,
  buildTemplateReport,
  composeEventDetail,
  computeLineRisk,
  computeMetrics,
  mergeAssets,
  normalizeActivity,
  normalizeDecision,
  normalizeRiskStatus,
} from "./mvpAdapters";

const event: EventSummary = {
  event_id: "EVENT-001",
  scenario_id: "scenario-1",
  equipment: {
    equipment_id: "CNC-001",
    display_name: "CNC 001",
    line: "Line A",
    criticality: "high",
    assigned_engineer: "Engineer A",
    last_maintenance_date: "2026-08-01",
    estimated_downtime_minutes: 120,
    spare_part_available: false,
  },
  status: "critical",
  failure_probability: 0.92,
  confidence: "high",
  predicted_failure_type: "tool_wear",
  recommended_decision: "review_shutdown",
  observed_at: "2026-08-06T03:00:00Z",
  dataset_version_id: "dsv-canonical-v3-1",
};

describe("MVP adapter contract", () => {
  it("normalizes statuses and only uses the approved decision enum", () => {
    expect(normalizeRiskStatus("danger")).toBe("critical");
    expect(normalizeRiskStatus("unknown")).toBe("data_quality_hold");
    expect(normalizeRiskStatus(undefined)).toBe("data_quality_hold");
    expect(normalizeDecision("automatic shutdown")).toBe("review_shutdown");
    expect(normalizeDecision("inspect bearings")).toBe("request_inspection");
  });

  it("keeps data-quality hold out of failure probability presentation", () => {
    const adapted = adaptEvent({ ...event, status: "data_quality_hold", failure_probability: 0.98 });
    expect(adapted.status).toBe("data_quality_hold");
    expect(adapted.failureProbability).toBeNull();
    expect(adapted.recommendedDecision).toBe("hold_for_data_check");
  });

  it("merges Result Artifact fields with operational Event context", () => {
    const operational = adaptEvent(event);
    const assets = mergeAssets([{
      artifact_id: "RESULT#CNC-001",
      asset_id: "CNC-001",
      asset_type: "cnc",
      site_id: "SITE-1",
      cell_id: "CELL-1",
      observed_at: "2026-08-06T03:00:00Z",
      prediction_task: "binary_failure_within_horizon",
      failure_probability: 0.92,
      predicted_failure_type: "failure_risk",
      status_grade: "critical",
      confidence: 0.88,
      top_factors: [{ rank: 1, feature: "tool_wear_min", feature_value: 210, signed_contribution: 0.42, direction: "risk_up", explanation_method: "shap" }],
      recommended_action: { action: "review_shutdown", priority: "critical", semantic_type: "policy_recommendation", approval_state: "not_requested", execution_state: "not_executed", creates_work_order_automatically: false },
      provenance: { dataset_id: "dataset-1", dataset_version_id: "dsv-canonical-v3-1", source_version: "Canonical V3.1", bundle_checksum_sha256: "a".repeat(64), model_version: "model-1", schema_version: "result-artifact-v1.0", prediction_task: "binary_failure_within_horizon" },
    }], [operational]);

    expect(assets).toHaveLength(1);
    expect(assets[0]).toEqual(expect.objectContaining({
      displayName: "CNC 001",
      line: "Line A",
      eventId: "EVENT-001",
      confidence: "high",
    }));
    expect(assets[0].topFactors[0].feature).toBe("tool_wear_min");
    expect(assets[0].provenance.modelVersion).toBe("model-1");
  });

  it("does not synthesize criticality from risk when operational context is missing", () => {
    const assets = mergeAssets([{
      artifact_id: "RESULT#CNC-009",
      asset_id: "CNC-009",
      asset_type: "cnc",
      site_id: "SITE-1",
      cell_id: "CELL-1",
      observed_at: "2026-08-06T03:00:00Z",
      prediction_task: "binary_failure_within_horizon",
      failure_probability: 0.94,
      predicted_failure_type: "failure_risk",
      status_grade: "critical",
      confidence: 0.88,
      top_factors: [],
      recommended_action: { action: "review_shutdown", priority: "critical", semantic_type: "policy_recommendation", approval_state: "not_requested", execution_state: "not_executed", creates_work_order_automatically: false },
      provenance: { dataset_id: "dataset-1", dataset_version_id: "dsv-canonical-v3-1", source_version: "Canonical V3.1", bundle_checksum_sha256: "a".repeat(64), model_version: "model-1", schema_version: "result-artifact-v1.0", prediction_task: "binary_failure_within_horizon" },
    }], []);

    expect(assets[0].status).toBe("critical");
    expect(assets[0].criticality).toBeNull();
  });

  it("does not synthesize downtime impact when operational context is missing", () => {
    const adapted = adaptEvent({
      ...event,
      equipment: {
        ...event.equipment,
        estimated_downtime_minutes: undefined,
      },
    } as unknown as EventSummary);

    expect(adapted.estimatedDowntimeMinutes).toBeNull();
  });

  it("derives the same metrics and line summary used by all four screens", () => {
    const events = [adaptEvent(event), adaptEvent({ ...event, event_id: "EVENT-002", equipment: { ...event.equipment, equipment_id: "CNC-002" }, status: "warning", failure_probability: 0.65 })];
    const assets = mergeAssets([], events);
    expect(computeMetrics(assets, events)).toEqual(expect.objectContaining({ critical: 1, warning: 1, estimatedDowntimeMinutes: 240 }));
    expect(computeLineRisk(assets)[0]).toEqual(expect.objectContaining({ line: "Line A", normal: 0, critical: 1, warning: 1 }));
  });

  it("keeps one asset row when multiple events reference the same equipment", () => {
    const events = [
      adaptEvent(event),
      adaptEvent({ ...event, event_id: "EVENT-002", observed_at: "2026-08-06T04:00:00Z" }),
    ];
    const assets = mergeAssets([], events);
    expect(assets).toHaveLength(1);
    expect(assets[0].assetId).toBe("CNC-001");
  });

  it("uses a verified template when report generation is unavailable", () => {
    const adapted = adaptEvent(event);
    const report = buildTemplateReport(adapted, computeMetrics(mergeAssets([], [adapted]), [adapted]));
    expect(report.mode).toBe("template-fallback");
    expect(report.sections.map((section) => section.id)).toContain("executive-summary");
    expect(report.limitations.join(" ")).toContain("고장");
  });

  it("normalizes decisions, notes, and conversations into one audit timeline", () => {
    const activity = normalizeActivity({
      decisions: [{ id: "d1", decision: "request_inspection", actor: "Manager", note: "Check tool", created_at: "2026-08-06T04:00:00Z" }],
      notes: [{ id: "n1", actor: "Engineer", body: "Tool checked", created_at: "2026-08-06T05:00:00Z" }],
      conversations: [],
    });
    expect(activity.map((item) => item.kind)).toEqual(["note", "decision"]);
    expect(activity[1].decision).toBe("request_inspection");
  });

  it("maps compressor evidence to compressor sensor fields", () => {
    const evidence = {
      observation: {
        asset_type: "compressor",
        voltage_raw: 171.2,
        rotation_raw: 448.4,
        pressure_raw: 101.5,
        vibration_raw: 42.1,
        relative_vibration_z: 1.2,
        relative_vibration_zone: "B",
      },
      top_factors: [],
      lineage: {},
      maintenance_context: { source_refs: [] },
      model: {},
    } as never;

    const event = adaptEvent({
      event_id: "compressor-event",
      equipment: { equipment_id: "CMP-001", display_name: "CMP-001", line: "S01 / L01", criticality: "medium" },
      status: "attention",
      failure_probability: 0.3,
      confidence: "70%",
      predicted_failure_type: "no_significant_risk",
      recommended_decision: "request_inspection",
      observed_at: "2026-08-01T00:00:00Z",
      dataset_version_id: "dsv-test",
    } as never);
    const detail = composeEventDetail({ event, evidence, report: null, activity: null });

    expect(detail.sensors.map((item) => item.id)).toEqual([
      "voltage_raw",
      "rotation_raw",
      "pressure_raw",
      "vibration_raw",
      "relative_vibration_z",
      "relative_vibration_zone",
    ]);
  });

  it("preserves AssetDetailViewModel current/history, gaps, and nullable freshness", () => {
    const adapted = adaptEvent(event);
    const detail = composeEventDetail({ event: adapted, evidence: null, report: null, activity: null });
    const enriched = applyAssetDetailViewModel(detail, {
      asset: {
        asset_id: "CNC-001",
        asset_type: "cnc",
        observed_at: "2026-08-06T03:00:00Z",
      },
      risk: {
        current: 0.92,
        threshold: 0.7,
        status_grade: "critical",
        prediction_horizon_hours: 24,
      },
      risk_series: [],
      features: [{
        key: "tool_wear_min",
        label: "공구 마모",
        unit: "분",
        current: {
          observed_at: "2026-08-06T03:00:00Z",
          value: 210,
          quality_status: "good",
        },
        history: {
          source_ref: "observation-series://CNC-001/tool_wear_min",
          points: [{
            observed_at: "2026-08-06T02:00:00Z",
            value: 200,
            quality_status: "good",
          }],
        },
        top_factor: {
          rank: 1,
          contribution: 0.42,
          direction: "risk_up",
          explanation_method: "shap",
          evidence_field_id: "features.tool_wear_min",
        },
      }],
      equipment_history: [{
        occurred_at: "2026-08-05T00:00:00Z",
        kind: "inspection",
        tone: "attention",
        description: "이전 점검 기록",
        source: "maintenance-read-model",
      }],
      evidence: {
        artifact_id: "RESULT#CNC-001",
        model_version: "model-1",
        dataset_version: "dsv-canonical-v3-1",
        source_kind: "runtime_inference",
        gaps: [{
          field: "asset.criticality",
          reason: "equipment master unavailable",
          owner_domain: "maintenance",
        }],
      },
      data_status: {
        source: "canonical",
        is_stale: null,
        is_data_quality_hold: false,
        warnings: [],
      },
    });

    expect(enriched.sensors[0]).toEqual(expect.objectContaining({
      observedAt: "2026-08-06T03:00:00Z",
      historySourceRef: "observation-series://CNC-001/tool_wear_min",
      historyPointCount: 1,
    }));
    expect(enriched.evidenceGaps[0]).toEqual(expect.objectContaining({ field: "asset.criticality" }));
    expect(enriched.assetDetailStatus?.isStale).toBeNull();
    expect(enriched.equipmentHistory[0].source).toBe("maintenance-read-model");
  });
});
