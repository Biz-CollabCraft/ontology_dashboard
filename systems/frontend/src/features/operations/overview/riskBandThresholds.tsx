export const GEN_DATA_RISK_THRESHOLDS = {
  attention: 0.2,
  warning: 0.45,
  critical: 0.75,
} as const;

const criticalY = (1 - GEN_DATA_RISK_THRESHOLDS.critical) * 100;
const attentionY = (1 - GEN_DATA_RISK_THRESHOLDS.attention) * 100;

export function statusFromGenDataRisk(risk: number) {
  if (risk >= GEN_DATA_RISK_THRESHOLDS.critical) return "critical";
  if (risk >= GEN_DATA_RISK_THRESHOLDS.warning) return "warning";
  if (risk >= GEN_DATA_RISK_THRESHOLDS.attention) return "attention";
  return "normal";
}

export function GenDataRiskBandBackground() {
  return (
    <>
      <rect y="0" width="100" height={criticalY} className="risk-zone" />
      <rect
        y={criticalY}
        width="100"
        height={attentionY - criticalY}
        className="attention-zone"
      />
      <rect
        y={attentionY}
        width="100"
        height={100 - attentionY}
        className="normal-zone"
      />
      <line
        className="risk-critical-threshold"
        x1="0"
        x2="100"
        y1={criticalY}
        y2={criticalY}
      />
      <line
        className="risk-attention-threshold"
        x1="0"
        x2="100"
        y1={attentionY}
        y2={attentionY}
      />
    </>
  );
}
