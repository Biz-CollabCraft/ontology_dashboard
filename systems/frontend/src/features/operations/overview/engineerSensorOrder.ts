// Display order is independent of risk contribution and API response order.
const CNC_ORDER = [
  "tool_wear_min", "torque_nm", "process_temperature_k", "rotational_speed_rpm",
  "air_temperature_k", "spindle_vibration", "rotation_raw", "vibration_raw",
  "pressure_raw", "voltage_raw", "current_raw", "air_pressure", "flow_rate",
  "relative_vibration_z", "mechanical_power_w", "power_w",
  "temperature_difference_k", "temperature_gap_k",
];
const COMPRESSOR_ORDER = [
  "pressure_raw", "vibration_raw", "rotation_raw", "voltage_raw", "current_raw",
  "air_pressure", "flow_rate", "air_temperature_k", "relative_vibration_z",
  "mechanical_power_w", "power_w",
];
export function orderEngineerSensors<T extends { feature: string }>(
  assetId: string, sensors: readonly T[],
): T[] {
  const order = assetId.toUpperCase().startsWith("CMP-") ? COMPRESSOR_ORDER : CNC_ORDER;
  const rank = (feature: string) => {
    const index = order.indexOf(feature);
    return index < 0 ? order.length : index;
  };
  return [...sensors].sort((a, b) => rank(a.feature) - rank(b.feature)
    || (a.feature < b.feature ? -1 : a.feature > b.feature ? 1 : 0));
}
