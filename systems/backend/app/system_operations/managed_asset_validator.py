from __future__ import annotations

from typing import Any


IDENTITY_FIELDS = {
    "preprocessing_plan": ("preprocessing_plan_id", "preprocessing_plan_version"),
    "feature_schema": ("feature_schema_id", "feature_schema_version"),
    "label_schema": ("label_schema_id", "label_schema_version"),
    "history_requirement": ("history_requirement_id", "history_requirement_version"),
    "training_config": ("training_config_id", "training_config_version"),
}


def create_template(asset_type: str, asset_id: str, version: str) -> dict[str, Any]:
    id_field, version_field = IDENTITY_FIELDS[asset_type]
    payload: dict[str, Any] = {id_field: asset_id, version_field: version}
    if asset_type == "preprocessing_plan":
        payload.update({"dataset_id": "", "dataset_version": "", "id_column": "asset_id", "time_column": "time", "column_rules": [], "duplicate_policy": "error", "missing_value_policy": "error"})
    elif asset_type == "feature_schema":
        payload.update({"feature_executor_version": "pdm-feature-executor-v1", "features": []})
    elif asset_type == "label_schema":
        payload.update({"prediction_task": "binary_failure_within_horizon", "prediction_horizon_hours": 24, "positive_interval": "[anchor-horizon,anchor)", "active_failure_policy": "drop"})
    elif asset_type == "history_requirement":
        payload.update({"minimum_history_rows": 1, "maximum_lookback_hours": 24, "sampling_interval_seconds": 3600, "sufficiency_policy": "both_required", "missing_history_policy": "fail"})
    elif asset_type == "training_config":
        payload.update({"base_models": ["random_forest"], "random_seed": 42, "split_strategy": "asset_time_split", "split_ratio": {"train": 0.7, "validation": 0.15, "test": 0.15}, "primary_metric": "f1", "metrics": ["f1"], "target_name": "label", "hyperparameters": {}})
    return payload


def validate_payload(asset_type: str, asset_id: str, version: str, payload: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    errors: list[dict] = []
    warnings: list[dict] = []
    id_field, version_field = IDENTITY_FIELDS[asset_type]
    if payload.get(id_field) != asset_id or payload.get(version_field) != version:
        errors.append({"code": "SYSTEM_CONTRACT_IDENTITY_INVALID", "path": "/", "message": "Asset identity fields cannot be changed"})
    if asset_type == "preprocessing_plan":
        if not payload.get("dataset_id") or not payload.get("dataset_version"):
            errors.append({"code": "SYSTEM_CONTRACT_DATASET_IDENTITY_MISSING", "path": "/", "message": "dataset_id and dataset_version are required"})
        if not payload.get("id_column") or not payload.get("time_column"):
            errors.append({"code": "SYSTEM_CONTRACT_COLUMN_ROLE_MISSING", "path": "/", "message": "id_column and time_column are required"})
        if payload.get("duplicate_policy") not in {"error", "aggregate"}:
            errors.append({"code": "SYSTEM_CONTRACT_POLICY_INVALID", "path": "/duplicate_policy", "message": "Unsupported duplicate policy"})
        if payload.get("duplicate_policy") == "aggregate" and payload.get("aggregation") not in {"mean", "first", "sum"}:
            errors.append({"code": "SYSTEM_CONTRACT_AGGREGATION_MISSING", "path": "/aggregation", "message": "aggregate requires a supported aggregation"})
    elif asset_type == "feature_schema":
        features = payload.get("features")
        if not isinstance(features, list):
            errors.append({"code": "SYSTEM_CONTRACT_FEATURES_INVALID", "path": "/features", "message": "features must be an array"})
        else:
            names = [item.get("name") for item in features if isinstance(item, dict)]
            if None in names or len(names) != len(set(names)):
                errors.append({"code": "SYSTEM_CONTRACT_FEATURE_NAME_DUPLICATE", "path": "/features", "message": "Feature names must be present and unique"})
    elif asset_type == "label_schema":
        if payload.get("prediction_task") != "binary_failure_within_horizon" or not isinstance(payload.get("prediction_horizon_hours"), int) or payload.get("prediction_horizon_hours", 0) <= 0:
            errors.append({"code": "SYSTEM_CONTRACT_LABEL_INVALID", "path": "/prediction_horizon_hours", "message": "A positive binary failure horizon is required"})
        if payload.get("active_failure_policy") != "drop":
            errors.append({"code": "SYSTEM_CONTRACT_LABEL_LEAKAGE", "path": "/active_failure_policy", "message": "Active failure rows must be dropped"})
    elif asset_type == "history_requirement":
        if not isinstance(payload.get("minimum_history_rows"), int) or payload.get("minimum_history_rows", 0) <= 0:
            errors.append({"code": "SYSTEM_CONTRACT_HISTORY_INVALID", "path": "/minimum_history_rows", "message": "minimum_history_rows must be positive"})
        if not isinstance(payload.get("sampling_interval_seconds"), int) or payload.get("sampling_interval_seconds", 0) <= 0:
            errors.append({"code": "SYSTEM_CONTRACT_HISTORY_SAMPLING_MISSING", "path": "/sampling_interval_seconds", "message": "A positive sampling interval is required"})
    elif asset_type == "training_config":
        ratio = payload.get("split_ratio", {})
        if not isinstance(ratio, dict) or abs(sum(value for value in ratio.values() if isinstance(value, (int, float))) - 1.0) > 1e-9:
            errors.append({"code": "SYSTEM_CONTRACT_SPLIT_INVALID", "path": "/split_ratio", "message": "Split ratios must total 1"})
        metrics = payload.get("metrics", [])
        if payload.get("primary_metric") not in metrics:
            errors.append({"code": "SYSTEM_CONTRACT_PRIMARY_METRIC_INVALID", "path": "/primary_metric", "message": "primary_metric must appear in metrics"})
        if payload.get("split_strategy") != "asset_time_split":
            errors.append({"code": "SYSTEM_CONTRACT_SPLIT_STRATEGY_INVALID", "path": "/split_strategy", "message": "Only asset_time_split is supported"})
    return errors, warnings
