from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable


GEN_DATA_LAYER2_SOURCE_KIND = "gen_data_layer2_log"


def normalize_gen_data_layer2_rows(
    rows: Iterable[dict[str, Any]],
    *,
    feature_mapping: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Pivot gen_data Layer 2 log rows into canonical Observation-shaped rows.

    Layer 2 keeps one sensor value per row. The Product API should not consume
    that storage layout directly, so this adapter groups rows by asset and
    source timestamp and preserves bad/null values as data-quality metadata.
    """

    mapping = feature_mapping or {}
    grouped: dict[tuple[str, str], dict[str, Any]] = {}

    for source_index, row in enumerate(rows, start=1):
        asset_id, sensor_key = _parse_node_id(_required_text(row, "node_id"))
        observed_at = _normalize_timestamp(_required_text(row, "source_timestamp"))
        feature_key = mapping.get(sensor_key, sensor_key)
        group_key = (asset_id, observed_at)
        observation = grouped.setdefault(
            group_key,
            {
                "asset_id": asset_id,
                "observed_at": observed_at,
                "measurements": {},
                "quality": {},
                "source": {
                    "source_kind": GEN_DATA_LAYER2_SOURCE_KIND,
                    "node_ids": [],
                    "source_row_numbers": [],
                    "server_timestamps": [],
                },
            },
        )
        observation["measurements"][feature_key] = _number_or_none(row.get("value"))
        observation["quality"][feature_key] = {
            "quality_status": _quality_status(row.get("status_code")),
            "source_status_code": row.get("status_code"),
            "reason": row.get("reason"),
        }
        observation["source"]["node_ids"].append(row["node_id"])
        observation["source"]["source_row_numbers"].append(source_index)
        server_timestamp = row.get("server_timestamp")
        if server_timestamp is not None and str(server_timestamp).strip():
            observation["source"]["server_timestamps"].append(
                _normalize_timestamp(str(server_timestamp))
            )

    return sorted(grouped.values(), key=lambda item: (item["asset_id"], item["observed_at"]))


def _parse_node_id(node_id: str) -> tuple[str, str]:
    asset_id, separator, sensor_key = node_id.rpartition(".")
    if not separator or not asset_id or not sensor_key:
        raise ValueError("node_id must be formatted as '{asset_id}.{sensor_key}'")
    return asset_id, sensor_key


def _required_text(row: dict[str, Any], field: str) -> str:
    value = row.get(field)
    if value is None or str(value).strip() == "":
        raise ValueError(f"{field} is required")
    return str(value).strip()


def _normalize_timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _number_or_none(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    return float(value)


def _quality_status(status_code: Any) -> str:
    normalized = str(status_code or "").strip().lower()
    if normalized == "good":
        return "good"
    if normalized == "bad":
        return "bad"
    return "unknown"
