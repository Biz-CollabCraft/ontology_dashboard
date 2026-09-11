import { expect, it } from "vitest";
import { orderEngineerSensors } from "./engineerSensorOrder";
const sensors = (...keys: string[]) => keys.map(feature => ({ feature, points: [{ value: 5 }] }));
const keys = (values: { feature: string }[]) => values.map(v => v.feature);
it("keeps CNC order across reversed incoming rankings without modifying data", () => {
  const incoming = sensors("rotational_speed_rpm", "tool_wear_min", "process_temperature_k", "torque_nm");
  const original = [...incoming];
  const ordered = orderEngineerSensors("CNC-S01-L01-01", incoming);
  expect(keys(ordered)).toEqual(["tool_wear_min", "torque_nm", "process_temperature_k", "rotational_speed_rpm"]);
  expect(orderEngineerSensors("CNC-S02-L02-02", [...incoming].reverse())).toEqual(ordered);
  expect(incoming).toEqual(original);
  expect(ordered[0]).toBe(incoming[1]);
});
it("uses the same compressor order on every update", () => {
  const incoming = sensors("current_raw", "rotation_raw", "voltage_raw", "pressure_raw", "vibration_raw");
  const ordered = orderEngineerSensors("CMP-S01-L01-01", incoming);
  expect(keys(ordered)).toEqual(["pressure_raw", "vibration_raw", "rotation_raw", "voltage_raw", "current_raw"]);
  expect(orderEngineerSensors("CMP-S04-L05-01", [...incoming].reverse())).toEqual(ordered);
});
it("retains unknown sensors in deterministic order after known sensors", () => {
  const incoming = sensors("z_new", "torque_nm", "a_new");
  expect(keys(orderEngineerSensors("CNC-S01-L01-01", incoming))).toEqual(["torque_nm", "a_new", "z_new"]);
  expect(orderEngineerSensors("CNC-S01-L01-01", [])).toEqual([]);
});
it("does not fabricate missing measurements or change observation values", () => {
  const incoming = sensors("rotational_speed_rpm");
  expect(orderEngineerSensors("CNC-S01-L01-01", incoming)).toEqual(incoming);
});
