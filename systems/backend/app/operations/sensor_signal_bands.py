from __future__ import annotations

from typing import Any


ATTENTION_CONTRIBUTION = 0.20
CRITICAL_CONTRIBUTION = 0.75


def _range(status: str, lower: float | None, upper: float | None) -> dict[str, Any]:
    return {"status": status, "lower": lower, "upper": upper}


def _high_is_risky(*, attention: float, critical: float) -> list[dict[str, Any]]:
    return [
        _range("normal", None, attention),
        _range("attention", attention, critical),
        _range("critical", critical, None),
    ]


def _distance_from_center_is_risky(
    *, center: float, attention_delta: float, critical_delta: float
) -> list[dict[str, Any]]:
    return [
        _range("critical", None, center - critical_delta),
        _range("attention", center - critical_delta, center - attention_delta),
        _range("normal", center - attention_delta, center + attention_delta),
        _range("attention", center + attention_delta, center + critical_delta),
        _range("critical", center + critical_delta, None),
    ]


def sensor_signal_bands(feature: str) -> dict[str, Any] | None:
    """Sensor-specific visual bands derived from gen_data risk inputs.

    The frontend uses this only to color chart backgrounds. It follows the same
    contribution thresholds as the file-backed demo path, so each sensor is
    shown against its own scale instead of a generic risk-score scale.
    """

    ranges: list[dict[str, Any]] | None = None
    basis = "gen_data 센서 기여도 기준"

    if feature == "tool_wear_min":
        ranges = _high_is_risky(
            attention=240.0 * ATTENTION_CONTRIBUTION,
            critical=240.0 * CRITICAL_CONTRIBUTION,
        )
    elif feature == "torque_nm":
        ranges = _high_is_risky(
            attention=80.0 * ATTENTION_CONTRIBUTION,
            critical=80.0 * CRITICAL_CONTRIBUTION,
        )
    elif feature == "process_temperature_k":
        ranges = _high_is_risky(
            attention=305.0 + (20.0 * ATTENTION_CONTRIBUTION),
            critical=305.0 + (20.0 * CRITICAL_CONTRIBUTION),
        )
    elif feature == "rotational_speed_rpm":
        ranges = _distance_from_center_is_risky(
            center=1500.0,
            attention_delta=900.0 * ATTENTION_CONTRIBUTION,
            critical_delta=900.0 * CRITICAL_CONTRIBUTION,
        )
    elif feature == "relative_vibration_z":
        ranges = _distance_from_center_is_risky(
            center=0.0,
            attention_delta=4.0 * ATTENTION_CONTRIBUTION,
            critical_delta=4.0 * CRITICAL_CONTRIBUTION,
        )
    elif feature == "vibration_raw":
        ranges = _high_is_risky(
            attention=80.0 * ATTENTION_CONTRIBUTION,
            critical=80.0 * CRITICAL_CONTRIBUTION,
        )
    elif feature == "pressure_raw":
        ranges = _distance_from_center_is_risky(
            center=100.0,
            attention_delta=35.0 * ATTENTION_CONTRIBUTION,
            critical_delta=35.0 * CRITICAL_CONTRIBUTION,
        )
    elif feature == "rotation_raw":
        ranges = _distance_from_center_is_risky(
            center=450.0,
            attention_delta=250.0 * ATTENTION_CONTRIBUTION,
            critical_delta=250.0 * CRITICAL_CONTRIBUTION,
        )

    if ranges is None:
        return None

    return {
        "source": "gen_data_measurement_factor_policy_v1",
        "basis": basis,
        "ranges": ranges,
    }
