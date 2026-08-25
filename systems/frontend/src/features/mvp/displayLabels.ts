export const ASSET_FIELD_LABELS: Record<string, string> = {
  "CNC-S01-L01-01": "1구역 · 1셀 · CNC 가공기 1",
  "CNC-S04-L04-01": "4구역 · 4셀 · CNC 가공기 1",
  "CNC-S01-L04-03": "1구역 · 4셀 · CNC 가공기 3",
  "CNC-S04-L02-03": "4구역 · 2셀 · CNC 가공기 3",
  "CNC-S03-L01-03": "3구역 · 1셀 · CNC 가공기 3",
  "CNC-S02-L02-02": "2구역 · 2셀 · CNC 가공기 2",
  "CNC-S04-L05-01": "4구역 · 5셀 · CNC 가공기 1",
  "CNC-S04-L04-02": "4구역 · 4셀 · CNC 가공기 2",
};

export const SENSOR_FIELD_LABELS: Record<string, string> = {
  rotation_raw: "회전 평균",
  vibration_raw: "진동 평균",
  air_temperature_k: "흡입 공기 온도",
  process_temperature_k: "가공부 온도",
  rotational_speed_rpm: "주축 회전수",
  torque_nm: "구동 토크",
  tool_wear_min: "공구 사용 시간",
  mechanical_power_w: "모터 출력",
  overstrain_index: "과부하 누적 지표",
  temperature_difference_k: "공정-공기 온도차",
};

export const EVENT_FIELD_LABELS: Record<string, string> = {
  "EVT-GS-001": "1구역 1셀 정상 관찰",
  "EVT-GS-002": "4구역 4셀 공구 마모 점검",
  "EVT-GS-003": "1구역 4셀 열 해소 점검",
  "EVT-GS-004": "4구역 2셀 구동부 과부하 긴급 검토",
  "EVT-GS-005": "3구역 1셀 복합 원인 점검",
  "EVT-GS-006": "2구역 2셀 저신뢰 관측 확인",
  "EVT-GS-007": "4구역 5셀 센서 데이터 확인",
  "EVT-GS-008": "4구역 4셀 보고서 생성 경로 확인",
};

export const FIELD_FACTOR_LABELS: Record<string, { item: string; symptom: string; locationHint: string }> = {
  air_temperature_k: { item: "흡입 공기 온도 확인", symptom: "주변 온도 조건 변화", locationHint: "흡입부/주변 환경" },
  process_temperature_k: { item: "가공부 열 축적 확인", symptom: "공정 온도 상승", locationHint: "가공부/냉각 흐름" },
  rotational_speed_rpm: { item: "주축 회전수 확인", symptom: "회전수 이상", locationHint: "모터/축 연결부" },
  torque_nm: { item: "구동 토크 확인", symptom: "토크 상승", locationHint: "모터/축/벨트" },
  tool_wear_min: { item: "공구 사용 시간 확인", symptom: "공구 사용 시간 누적", locationHint: "공구대/금형 접촉부" },
  mechanical_power_w: { item: "모터 출력 확인", symptom: "모터 출력 부하 상승", locationHint: "모터/전원부" },
  overstrain_index: { item: "프레스 과부하 확인", symptom: "과부하 누적", locationHint: "프레스 구동부" },
  temperature_difference_k: { item: "공정-공기 온도차 확인", symptom: "열 해소 불균형", locationHint: "냉각/배기 흐름" },
};

export const FAILURE_TYPE_LABELS: Record<string, string> = {
  power_or_overstrain_failure: "구동부 과부하 의심",
  tool_wear_failure: "공구/금형 마모 의심",
  heat_dissipation_failure: "냉각/열 해소 이상 의심",
  invalid_sensor_data: "센서 데이터 품질 확인",
  multi_factor_risk: "복합 원인 의심",
  uncertain: "고장 유형 불확실",
  unavailable: "고장 유형 근거 부족",
};

const PRODUCTION_IMPACT_LABELS: Record<string, string> = {
  none: "영향 없음",
  low: "낮음",
  medium: "중간",
  high: "높음",
};

const REVIEW_PRIORITY_LABELS: Record<string, string> = {
  immediate: "즉시 검토",
  high: "높음",
  medium: "중간",
  low: "낮음",
};

interface DisplayAssetLike {
  assetId: string;
  displayName?: string | null;
}

interface DisplayEventLike {
  eventId?: string | null;
  assetId: string;
  assetName?: string | null;
}

interface DisplayFactorLike {
  feature: string;
  label?: string | null;
}

export function displayAssetName(asset: DisplayAssetLike | null | undefined): string {
  if (!asset) return "선택된 설비 없음";
  return ASSET_FIELD_LABELS[asset.assetId] ?? asset.displayName ?? asset.assetId;
}

export function displayAssetShortName(asset: DisplayAssetLike | null | undefined): string {
  if (!asset) return "-";
  const mappedName = displayAssetName(asset);
  const unitSuffix = mappedName.match(/(\d+)호기$/)?.[1];
  if (unitSuffix) return `${Number(unitSuffix)}호기`;
  const mSeriesSuffix = asset.assetId.match(/^M-(\d+)$/)?.[1];
  if (mSeriesSuffix) return `${Number(mSeriesSuffix)}호기`;
  const trailingNumber = asset.assetId.match(/(\d+)$/)?.[1];
  return trailingNumber ? `${Number(trailingNumber)}호기` : mappedName;
}

export function displayEventAssetName(event: DisplayEventLike): string {
  return ASSET_FIELD_LABELS[event.assetId] ?? event.assetName ?? event.assetId;
}

export function displayEventLabel(event: Pick<DisplayEventLike, "eventId"> | string | null | undefined): string {
  const eventId = typeof event === "string" ? event : event?.eventId;
  if (!eventId) return "이벤트 미선택";
  return EVENT_FIELD_LABELS[eventId] ?? eventId;
}

export function displaySensorLabel(key: string, fallback?: string | null): string {
  return SENSOR_FIELD_LABELS[key] ?? fallback ?? key;
}

export function displayAssetType(value?: string | null): string {
  if (!value) return "설비 유형 미제공";
  if (value.toLowerCase().includes("compressor")) return "공기압축기";
  if (value.toLowerCase().includes("cnc")) return "CNC 가공기";
  return value;
}

export function fieldFactorItem(factor: DisplayFactorLike): string {
  return FIELD_FACTOR_LABELS[factor.feature]?.item ?? displaySensorLabel(factor.feature, factor.label);
}

export function fieldFactorSymptom(factor: DisplayFactorLike): string {
  return FIELD_FACTOR_LABELS[factor.feature]?.symptom ?? factor.label ?? factor.feature;
}

export function fieldFactorLocation(factor: Pick<DisplayFactorLike, "feature">): string {
  return FIELD_FACTOR_LABELS[factor.feature]?.locationHint ?? "점검 위치 확인";
}

export function fieldFailureLabel(value: string): string {
  return FAILURE_TYPE_LABELS[value] ?? value;
}

export function displayProductionImpact(value?: string | null): string {
  if (!value) return "생산 영향 수준 미제공";
  return PRODUCTION_IMPACT_LABELS[value] ?? value;
}

export function displayReviewPriority(value?: string | null): string {
  if (!value) return "검토 우선순위 미제공";
  return REVIEW_PRIORITY_LABELS[value] ?? value;
}
