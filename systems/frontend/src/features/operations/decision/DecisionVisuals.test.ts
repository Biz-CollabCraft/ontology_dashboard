import { describe, expect, it } from "vitest";
import { chartGeometry } from "./DecisionVisuals";
import { factorLabel, fieldText, lineLabel, measurement } from "./decisionLabels";
describe("field labels and measured charts", () => {
  it("maps runtime fields without presenting model scores as physical units", () => {
    expect(factorLabel("torque_nm_6h_mean")).toBe("토크 · 6시간 평균");
    expect(measurement(1.2, "model_unit")).toBe("1.2 모델 환산값");
    expect(fieldText("Unassigned · policy review")).toBe("미배정 · 조치 기준 검토");
    expect(lineLabel("S04 / S04-L02")).toBe("4구역 · 2셀");
  });
  it("uses elapsed time and breaks lines for missing or bad observations", () => {
    const result=chartGeometry([
      {observedAt:"2026-08-29T00:00:00Z", value:1},
      {observedAt:"2026-08-29T01:00:00Z", value:null},
      {observedAt:"2026-08-29T02:00:00Z", value:2, qualityStatus:"bad"},
      {observedAt:"2026-08-29T10:00:00Z", value:3},
    ],false);
    expect(result.segments).toHaveLength(2);
    expect(result.coordinates[1].x).toBeCloseTo(113);
    expect(result.coordinates[2].y).toBeNull();
  });
  it("does not fabricate an empty history",()=>{
    expect(chartGeometry([],false).hasValues).toBe(false);
  });
});
