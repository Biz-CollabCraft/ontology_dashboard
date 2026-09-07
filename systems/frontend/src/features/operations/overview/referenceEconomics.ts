import basis from "./production-economic-basis.v1.json";
export { basis as economicBasis };
export function referenceEconomics(assetId: string, stopMinutes?: number | null) {
  const kind = assetId.startsWith("CNC-") ? "CNC" : assetId.startsWith("CMP-") ? "CMP" : null;
  if (!kind) return null;
  const profile = basis.profiles[kind];
  const param = (key: string) => basis.parameters.find(p => p.key === key)!.value;
  const hourlyUnits = param("units_per_hour") * profile.affected_cnc;
  const hourlyProductionCost = hourlyUnits * param("unit_production_cost");
  const hourlyOpportunity = hourlyUnits * param("unit_contribution");
  const validTime = typeof stopMinutes === "number" && Number.isFinite(stopMinutes) && stopMinutes >= 0;
  return { version: basis.version, profile, hourlyUnits,
    hourlyProductionCost: Math.round(hourlyProductionCost), hourlyOpportunity: Math.round(hourlyOpportunity),
    dailyCapacity: Math.floor(hourlyUnits * param("daily_hours")),
    lostUnits: validTime ? Math.ceil(hourlyUnits * stopMinutes / 60) : null,
    stopExposure: validTime ? Math.round(hourlyOpportunity * stopMinutes / 60) : null,
    labor: Math.round(param("labor_hourly") * profile.labor_minutes / 60),
    parts: profile.parts_cost,
  };
}
