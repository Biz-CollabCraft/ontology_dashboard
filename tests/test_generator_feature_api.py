"""Integration and regression test suite for Generator Feature domain (POST /feature) and Feature Dataset Bundle."""

from __future__ import annotations

import inspect
import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from systems.generator.app.feature.feature_exception import (
    FeatureContractError,
    FeatureLabelAlignmentError,
    FeatureSchemaMismatchError,
)
from systems.generator.app.feature.feature_repository import (
    FeatureRepository,
    compute_feature_dataset_version,
)
from systems.generator.app.feature.feature_router import post_feature
from systems.generator.app.feature.feature_schema_provider import FeatureItem
from systems.generator.app.feature.feature_service import FeatureService
from systems.generator.app.feature.label_schema_provider import LabelSchemaSpec
from systems.generator.app.main import create_app
from systems.generator.generator_config import PATHS


@pytest.fixture
def test_client():
    """Create isolated FastAPI test client with valid observation dataset in data_dir."""
    dataset_name = "ai4i_feature_test"
    csv_file = PATHS.data_dir / f"{dataset_name}.csv"
    PATHS.data_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create canonical observation dataset with realistic variation
    np.random.seed(42)
    n_rows = 50
    times = pd.date_range("2026-01-01 00:00:00", periods=n_rows, freq="h")

    # Failures at index 10 (2026-01-01 10:00) and index 35 (2026-01-02 11:00)
    failures = np.zeros(n_rows, dtype=int)
    failures[10] = 1
    failures[35] = 1

    df_obs = pd.DataFrame({
        "UDI": range(1, n_rows + 1),
        "Product ID": [f"L{i % 2 + 1:04d}" for i in range(n_rows)],
        "Type": ["L"] * n_rows,
        "Air temperature [K]": np.random.normal(298.1, 1.0, n_rows),
        "Process temperature [K]": np.random.normal(308.6, 1.0, n_rows),
        "Rotational speed [rpm]": np.random.normal(1500, 30, n_rows),
        "Torque [Nm]": np.random.normal(40.0, 3.0, n_rows),
        "Tool wear [min]": np.linspace(0, 200, n_rows),
        "Machine failure": failures,
        "observed_at": times.strftime("%Y-%m-%d %H:%M:%S"),
    })
    df_obs.to_csv(csv_file, index=False)

    app = create_app()
    client = TestClient(app)

    # 2. Execute preprocessing to get valid plan
    prep_req = {
        "dataset_id": dataset_name,
        "dataset_version": "v1.0",
        "force_reanalyze": True,
    }
    resp = client.post("/preprocessing", json=prep_req)
    assert resp.status_code == 200, resp.text
    prep_data = resp.json()

    yield {
        "client": client,
        "dataset_id": dataset_name,
        "plan_id": prep_data["preprocessing_plan_id"],
        "plan_version": prep_data["preprocessing_plan_version"],
    }

    # Cleanup
    if csv_file.exists():
        csv_file.unlink()
    models_store = getattr(PATHS, "models_store", Path("models_store"))
    shutil.rmtree(models_store / "cache" / "features" / dataset_name, ignore_errors=True)
    shutil.rmtree(models_store / "cache" / "preprocessing_plans" / dataset_name, ignore_errors=True)


# ==========================================
# 1. Feature Schema & Missing Value Tests
# ==========================================

def test_feature_generation_success_and_bundle_contract(test_client):
    """Test successful feature generation and verify 5-file bundle integrity and order."""
    client = test_client["client"]
    dataset_id = test_client["dataset_id"]
    plan_id = test_client["plan_id"]
    plan_ver = test_client["plan_version"]

    req_payload = {
        "dataset_id": dataset_id,
        "dataset_version": "v1.0",
        "failure_source_mode": "embedded_observation",
        "preprocessing_plan_id": plan_id,
        "preprocessing_plan_version": plan_ver,
        "feature_schema_version": "ai4i-feature-v1",
        "label_schema_version": "ai4i-label-24h-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    }

    resp = client.post("/feature", json=req_payload, headers={"X-Request-ID": "req-feature-test-01"})
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("X-Request-ID") == "req-feature-test-01"

    data = resp.json()
    assert data["status"] == "succeeded"
    assert data["preprocessing_plan_id"] == plan_id
    assert data["preprocessing_plan_version"] == plan_ver

    outputs = data["outputs"]
    assert outputs["feature_count"] == 5
    # 2 active failure rows dropped from 50 rows -> 48 rows
    assert outputs["row_count"] == 48

    feat_ver = outputs["feature_dataset_version"]
    assert feat_ver.startswith("feature-dataset-")

    # Verify 5 physical files
    bundle_dir = PATHS.models_store / "cache" / "features" / dataset_id / "v1.0" / feat_ver
    assert bundle_dir.exists()
    assert (bundle_dir / "features.npy").exists()
    assert (bundle_dir / "labels.npy").exists()
    assert (bundle_dir / "feature_columns.json").exists()
    assert (bundle_dir / "row_metadata.json").exists()
    assert (bundle_dir / "feature_metadata.json").exists()

    # Verify column order in feature_columns.json exactly matches ai4i-feature-v1.json
    with open(bundle_dir / "feature_columns.json", "r", encoding="utf-8") as f:
        col_info = json.load(f)
    assert col_info["columns"] == [
        "Air temperature [K]",
        "Process temperature [K]",
        "Rotational speed [rpm]",
        "Torque [Nm]",
        "Tool wear [min]",
    ]

    # Verify provenance metadata completeness
    with open(bundle_dir / "feature_metadata.json", "r", encoding="utf-8") as f:
        meta = json.load(f)
    prov = meta["provenance"]
    assert prov["observation_dataset_id"] == dataset_id
    assert prov["observation_dataset_version"] == "v1.0"
    assert "observation_dataset_sha256" in prov
    assert "preprocessing_plan_id" in prov
    assert "preprocessing_plan_version" in prov
    assert "feature_schema_version" in prov
    assert "label_schema_version" in prov
    assert prov["prediction_horizon_hours"] == 24
    assert prov["failure_source_mode"] == "embedded_observation"


def test_transformed_lag_ffill_preserves_lag_semantics():
    """Test that missing-value ffill on lag operations forward-fills the computed lag series, not the raw source."""
    df = pd.DataFrame({
        "asset_id": ["A", "A", "A"],
        "observed_at": ["2026-01-01 01:00", "2026-01-01 02:00", "2026-01-01 03:00"],
        "pressure": [10.0, 20.0, 30.0],
    })
    service = FeatureService()
    item = FeatureItem(
        feature_name="pressure_lag_1",
        source_field="pressure",
        operation="lag",
        parameters={"periods": 1},
        missing_value_policy="ffill",
    )
    comp_df, drop_mask = service._compute_features_and_missing_masks(df, [item], "asset_id")

    # Raw is [10, 20, 30]. lag(1) gives [NaN, 10, 20].
    # ffill on lag(1) with 0-fill gives [0, 10, 20], NOT [10, 20, 30]!
    assert comp_df["pressure_lag_1"].tolist() == [0.0, 10.0, 20.0]
    assert drop_mask.sum() == 0


def test_transformed_diff_ffill_preserves_diff_semantics():
    """Test that missing-value ffill on diff operations forward-fills the computed diff series, not the raw source."""
    df = pd.DataFrame({
        "asset_id": ["A", "A", "A"],
        "observed_at": ["2026-01-01 01:00", "2026-01-01 02:00", "2026-01-01 03:00"],
        "temperature": [10.0, 15.0, 25.0],
    })
    service = FeatureService()
    item = FeatureItem(
        feature_name="temp_diff_1",
        source_field="temperature",
        operation="diff",
        parameters={"periods": 1},
        missing_value_policy="ffill",
    )
    comp_df, drop_mask = service._compute_features_and_missing_masks(df, [item], "asset_id")

    # Raw is [10, 15, 25]. diff(1) gives [NaN, 5, 10].
    # ffill with 0-fill gives [0, 5, 10], NOT [10, 15, 25]!
    assert comp_df["temp_diff_1"].tolist() == [0.0, 5.0, 10.0]


def test_ffill_does_not_cross_asset_boundary():
    """Test that forward-filling never leaks values across asset boundaries."""
    df = pd.DataFrame({
        "asset_id": ["Asset_A", "Asset_A", "Asset_B", "Asset_B"],
        "observed_at": ["2026-01-01 01:00", "2026-01-01 02:00", "2026-01-01 01:00", "2026-01-01 02:00"],
        "val": [10.0, 20.0, np.nan, 40.0],
    })
    service = FeatureService()
    item = FeatureItem(
        feature_name="val_ffill",
        source_field="val",
        operation="raw",
        missing_value_policy="ffill",
    )
    comp_df, _ = service._compute_features_and_missing_masks(df, [item], "asset_id")

    # Asset_B's first value was NaN; it must NOT take 20.0 from Asset_A!
    assert comp_df["val_ffill"].tolist() == [10.0, 20.0, 0.0, 40.0]


def test_missing_value_policies_drop_fill_error():
    """Test drop, fill_zero, ffill, and error missing value policies."""
    df = pd.DataFrame({
        "asset_id": ["A", "A", "A", "A"],
        "observed_at": ["2026-01-01 01:00", "2026-01-01 02:00", "2026-01-01 03:00", "2026-01-01 04:00"],
        "val": [10.0, np.nan, 30.0, np.nan],
    })

    service = FeatureService()

    # 1. missing_value_policy = "drop"
    items_drop = [FeatureItem(feature_name="f_drop", source_field="val", operation="raw", missing_value_policy="drop")]
    comp_df, drop_mask = service._compute_features_and_missing_masks(df, items_drop, "asset_id")
    assert drop_mask.sum() == 2

    # 2. missing_value_policy = "fill_zero"
    items_zero = [FeatureItem(feature_name="f_zero", source_field="val", operation="raw", missing_value_policy="fill_zero")]
    comp_df_zero, drop_mask_zero = service._compute_features_and_missing_masks(df, items_zero, "asset_id")
    assert drop_mask_zero.sum() == 0
    assert (comp_df_zero["f_zero"] == 0.0).sum() == 2

    # 3. missing_value_policy = "ffill"
    items_ffill = [FeatureItem(feature_name="f_ffill", source_field="val", operation="raw", missing_value_policy="ffill")]
    comp_df_ffill, drop_mask_ffill = service._compute_features_and_missing_masks(df, items_ffill, "asset_id")
    assert drop_mask_ffill.sum() == 0
    assert comp_df_ffill["f_ffill"].tolist() == [10.0, 10.0, 30.0, 30.0]

    # 4. missing_value_policy = "error"
    items_error = [FeatureItem(feature_name="f_err", source_field="val", operation="raw", missing_value_policy="error")]
    with pytest.raises(Exception) as exc_info:
        service._compute_features_and_missing_masks(df, items_error, "asset_id")
    assert "결측값" in str(exc_info.value)


# ==========================================
# 2. Failure Source Contract & Fail-Closed
# ==========================================

def test_external_failure_dataset_missing_returns_404(test_client):
    """Test 404 when requested failure_dataset_id in external_dataset mode does not exist."""
    client = test_client["client"]
    dataset_id = test_client["dataset_id"]
    plan_id = test_client["plan_id"]
    plan_ver = test_client["plan_version"]

    resp = client.post("/feature", json={
        "dataset_id": dataset_id,
        "dataset_version": "v1.0",
        "failure_source_mode": "external_dataset",
        "failure_dataset_id": "nonexistent_failure_ds",
        "failure_dataset_version": "v1.0",
        "preprocessing_plan_id": plan_id,
        "preprocessing_plan_version": plan_ver,
        "feature_schema_version": "ai4i-feature-v1",
        "label_schema_version": "ai4i-label-24h-v1",
    })
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FEATURE_INPUT_NOT_FOUND"


def test_external_failure_provenance_uses_actual_failure_file(test_client, tmp_path):
    """Test that external_dataset mode records actual failure dataset SHA-256 and URI in provenance."""
    client = test_client["client"]
    dataset_id = test_client["dataset_id"]
    plan_id = test_client["plan_id"]
    plan_ver = test_client["plan_version"]

    # Create real dedicated external failure dataset
    fail_ds_name = "test_custom_failures"
    fail_file = PATHS.data_dir / f"{fail_ds_name}.csv"
    df_fail = pd.DataFrame({
        "Product ID": ["L0001", "L0002"],
        "failure_point": ["2026-01-01 10:00:00", "2026-01-02 11:00:00"],
        "period_end": ["2026-01-01 11:00:00", "2026-01-02 12:00:00"],
    })
    df_fail.to_csv(fail_file, index=False)

    try:
        resp = client.post("/feature", json={
            "dataset_id": dataset_id,
            "dataset_version": "v1.0",
            "failure_source_mode": "external_dataset",
            "failure_dataset_id": fail_ds_name,
            "failure_dataset_version": "v1.0",
            "preprocessing_plan_id": plan_id,
            "preprocessing_plan_version": plan_ver,
            "feature_schema_version": "ai4i-feature-v1",
            "label_schema_version": "ai4i-label-24h-v1",
            "prediction_horizon_hours": 24,
            "rebuild_npy": True,
        })
        assert resp.status_code == 200, resp.text
        feat_ver = resp.json()["outputs"]["feature_dataset_version"]

        bundle_dir = PATHS.models_store / "cache" / "features" / dataset_id / "v1.0" / feat_ver
        with open(bundle_dir / "feature_metadata.json", "r", encoding="utf-8") as f:
            meta = json.load(f)

        prov = meta["provenance"]
        assert prov["failure_source_mode"] == "external_dataset"
        assert prov["failure_dataset_id"] == fail_ds_name
        assert prov["failure_dataset_version"] == "v1.0"
        assert prov["failure_dataset_sha256"] is not None
        assert "data/" in prov["failure_dataset_uri"]
    finally:
        if fail_file.exists():
            fail_file.unlink()


def test_embedded_failure_requires_explicit_mode(test_client):
    """Test that embedded_observation mode executes without failure_dataset_id/version."""
    client = test_client["client"]
    dataset_id = test_client["dataset_id"]
    plan_id = test_client["plan_id"]
    plan_ver = test_client["plan_version"]

    resp = client.post("/feature", json={
        "dataset_id": dataset_id,
        "dataset_version": "v1.0",
        "failure_source_mode": "embedded_observation",
        "preprocessing_plan_id": plan_id,
        "preprocessing_plan_version": plan_ver,
        "feature_schema_version": "ai4i-feature-v1",
        "label_schema_version": "ai4i-label-24h-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    })
    assert resp.status_code == 200
    assert resp.json()["failure_source_mode"] == "embedded_observation"


def test_embedded_failure_without_indicator_returns_422(test_client):
    """Test 422 when embedded_observation mode is requested on a dataset without failure indicator."""
    client = test_client["client"]
    plan_id = test_client["plan_id"]
    plan_ver = test_client["plan_version"]

    # Create dataset without Machine failure column
    no_fail_id = "ai4i_no_fail_col"
    csv_file = PATHS.data_dir / f"{no_fail_id}.csv"
    df = pd.DataFrame({
        "UDI": [1, 2, 3],
        "Product ID": ["L0001", "L0001", "L0001"],
        "Air temperature [K]": [298.1, 298.2, 298.3],
        "Process temperature [K]": [308.1, 308.2, 308.3],
        "Rotational speed [rpm]": [1500, 1500, 1500],
        "Torque [Nm]": [40.0, 40.0, 40.0],
        "Tool wear [min]": [0, 5, 10],
        "observed_at": ["2026-01-01 01:00", "2026-01-01 02:00", "2026-01-01 03:00"],
    })
    df.to_csv(csv_file, index=False)

    try:
        # Preprocess
        prep_res = client.post("/preprocessing", json={"dataset_id": no_fail_id, "dataset_version": "v1.0", "force_reanalyze": True})
        p_id = prep_res.json()["preprocessing_plan_id"]
        p_ver = prep_res.json()["preprocessing_plan_version"]

        resp = client.post("/feature", json={
            "dataset_id": no_fail_id,
            "dataset_version": "v1.0",
            "failure_source_mode": "embedded_observation",
            "preprocessing_plan_id": p_id,
            "preprocessing_plan_version": p_ver,
            "feature_schema_version": "ai4i-feature-v1",
            "label_schema_version": "ai4i-label-24h-v1",
        })
        assert resp.status_code == 422
        assert "failure indicator" in resp.json()["error"]["message"]
    finally:
        if csv_file.exists():
            csv_file.unlink()


def test_failure_source_mode_changes_feature_dataset_version():
    """Test that different failure_source_mode produces different feature_dataset_version hashes."""
    base_fp = {
        "observation_dataset_id": "ds-1",
        "observation_dataset_version": "v1.0",
        "observation_dataset_sha256": "abc",
        "preprocessing_plan_id": "pp-1",
        "preprocessing_plan_version": "pp-v1",
        "preprocessing_plan_sha256": "def",
        "feature_schema_version": "f-v1",
        "feature_schema_sha256": "ghi",
        "label_schema_version": "l-v1",
        "label_schema_sha256": "jkl",
        "prediction_horizon_hours": 24,
        "feature_engine_version": "1.0",
    }

    fp_external = {
        **base_fp,
        "failure_source_mode": "external_dataset",
        "failure_dataset_id": "fail-ds",
        "failure_dataset_version": "v1.0",
        "failure_dataset_sha256": "hash123",
    }
    fp_embedded = {
        **base_fp,
        "failure_source_mode": "embedded_observation",
        "failure_dataset_id": None,
        "failure_dataset_version": None,
        "failure_dataset_sha256": None,
    }

    v_ext = compute_feature_dataset_version(fp_external)
    v_emb = compute_feature_dataset_version(fp_embedded)

    assert v_ext != v_emb


# ==========================================
# 3. Failure Asset Identity & Exclusion Tests
# ==========================================

def test_failure_event_affects_only_matching_asset():
    """Test that a failure event for Asset_A affects ONLY Asset_A, leaving Asset_B unaffected."""
    times = pd.date_range("2026-01-01 00:00:00", periods=5, freq="h")
    df_obs = pd.DataFrame({
        "asset_id": ["Asset_A"] * 5 + ["Asset_B"] * 5,
        "observed_at": list(times) + list(times),
        "val": range(10),
    })

    # Failure only for Asset_A at 03:00
    df_fail = pd.DataFrame({
        "asset_id": ["Asset_A"],
        "failure_point": [times[3]],
        "period_end": [times[4]],
    })

    label_spec = LabelSchemaSpec(
        schema_version="test-schema",
        prediction_task="binary_failure_within_horizon",
        prediction_horizon_hours=2,
        anchor="failure_point",
        exclusion_end="period_end",
    )

    service = FeatureService()
    labels, drop_mask = service._generate_labels_and_exclusion_mask(
        working_df=df_obs,
        fail_df=df_fail,
        label_schema=label_spec,
        id_col="asset_id",
        time_col="observed_at",
        failure_source_mode="external_dataset",
    )

    # For Asset_A: 01:00 & 02:00 in horizon [01:00, 03:00) -> label 1; 03:00 & 04:00 in [03:00, 04:00] -> dropped
    # For Asset_B: all labels 0, none dropped
    assert labels.iloc[5:].sum() == 0
    assert drop_mask.iloc[5:].sum() == 0
    assert labels.iloc[1:3].sum() == 2
    assert drop_mask.iloc[3:5].sum() == 2


def test_external_failure_missing_asset_column_returns_422():
    """Test 422 when multi-asset observation has no matching asset ID column in failure dataset."""
    df_obs = pd.DataFrame({
        "asset_id": ["A", "B"],
        "observed_at": ["2026-01-01 01:00", "2026-01-01 02:00"],
    })
    df_fail = pd.DataFrame({
        "failure_point": ["2026-01-01 01:00"],
        "period_end": ["2026-01-01 02:00"],
    })
    label_spec = LabelSchemaSpec(schema_version="v1", prediction_task="t", prediction_horizon_hours=24)

    service = FeatureService()
    with pytest.raises(FeatureLabelAlignmentError) as exc_info:
        service._generate_labels_and_exclusion_mask(df_obs, df_fail, label_spec, "asset_id", "observed_at", "external_dataset")
    assert "Failure asset ID 컬럼이 Failure 데이터셋에 없습니다" in str(exc_info.value)


def test_failure_asset_not_in_observation_returns_422():
    """Test 422 when failure event references an unknown asset not in observation dataset."""
    df_obs = pd.DataFrame({
        "asset_id": ["Asset_A", "Asset_B"],
        "observed_at": ["2026-01-01 01:00", "2026-01-01 02:00"],
    })
    df_fail = pd.DataFrame({
        "asset_id": ["UNKNOWN_ASSET_XYZ"],
        "failure_point": ["2026-01-01 01:00"],
        "period_end": ["2026-01-01 02:00"],
    })
    label_spec = LabelSchemaSpec(schema_version="v1", prediction_task="t", prediction_horizon_hours=24)

    service = FeatureService()
    with pytest.raises(FeatureLabelAlignmentError) as exc_info:
        service._generate_labels_and_exclusion_mask(df_obs, df_fail, label_spec, "asset_id", "observed_at", "external_dataset")
    assert "Observation Dataset에 존재하지 않습니다" in str(exc_info.value)


def test_required_exclusion_end_missing_returns_422():
    """Test 422 when Label Schema declares exclusion_end but failure dataset lacks that column."""
    df_obs = pd.DataFrame({"asset_id": ["A"], "observed_at": ["2026-01-01 01:00"]})
    df_fail = pd.DataFrame({"asset_id": ["A"], "failure_point": ["2026-01-01 01:00"]})
    label_spec = LabelSchemaSpec(
        schema_version="v1",
        prediction_task="t",
        prediction_horizon_hours=24,
        anchor="failure_point",
        exclusion_end="declared_period_end",
    )

    service = FeatureService()
    with pytest.raises(FeatureSchemaMismatchError) as exc_info:
        service._generate_labels_and_exclusion_mask(df_obs, df_fail, label_spec, "asset_id", "observed_at", "external_dataset")
    assert "exclusion_end 컬럼 'declared_period_end'이 Failure 데이터셋에 없습니다" in str(exc_info.value)


def test_exclusion_end_before_anchor_returns_422():
    """Test 422 when failure event has exclusion_end < anchor."""
    df_obs = pd.DataFrame({"asset_id": ["A"], "observed_at": ["2026-01-01 01:00"]})
    df_fail = pd.DataFrame({
        "asset_id": ["A"],
        "failure_point": ["2026-01-01 10:00:00"],
        "period_end": ["2026-01-01 08:00:00"],  # Before anchor
    })
    label_spec = LabelSchemaSpec(
        schema_version="v1",
        prediction_task="t",
        prediction_horizon_hours=24,
        anchor="failure_point",
        exclusion_end="period_end",
    )

    service = FeatureService()
    with pytest.raises(FeatureContractError) as exc_info:
        service._generate_labels_and_exclusion_mask(df_obs, df_fail, label_spec, "asset_id", "observed_at", "external_dataset")
    assert "보다 앞섭니다" in str(exc_info.value)


def test_invalid_failure_timestamp_returns_422():
    """Test 422 when failure event contains invalid/unparseable timestamp (NaT)."""
    df_obs = pd.DataFrame({"asset_id": ["A"], "observed_at": ["2026-01-01 01:00"]})
    df_fail = pd.DataFrame({
        "asset_id": ["A"],
        "failure_point": ["NOT_A_VALID_DATE"],
        "period_end": ["2026-01-01 08:00:00"],
    })
    label_spec = LabelSchemaSpec(schema_version="v1", prediction_task="t", prediction_horizon_hours=24, anchor="failure_point")

    service = FeatureService()
    with pytest.raises(FeatureContractError) as exc_info:
        service._generate_labels_and_exclusion_mask(df_obs, df_fail, label_spec, "asset_id", "observed_at", "external_dataset")
    assert "타임스탬프" in str(exc_info.value)


def test_active_failure_interval_is_fully_removed(test_client):
    """Test that all rows in [anchor, exclusion_end] are dropped from published bundle."""
    client = test_client["client"]
    dataset_id = test_client["dataset_id"]
    plan_id = test_client["plan_id"]
    plan_ver = test_client["plan_version"]

    fail_ds = "test_interval_failures"
    fail_file = PATHS.data_dir / f"{fail_ds}.csv"
    df_fail = pd.DataFrame({
        "Product ID": ["L0001"],
        "failure_point": ["2026-01-01 10:00:00"],
        "period_end": ["2026-01-01 12:00:00"],
    })
    df_fail.to_csv(fail_file, index=False)

    try:
        resp = client.post("/feature", json={
            "dataset_id": dataset_id,
            "dataset_version": "v1.0",
            "failure_source_mode": "external_dataset",
            "failure_dataset_id": fail_ds,
            "failure_dataset_version": "v1.0",
            "preprocessing_plan_id": plan_id,
            "preprocessing_plan_version": plan_ver,
            "feature_schema_version": "ai4i-feature-v1",
            "label_schema_version": "ai4i-label-24h-v1",
            "prediction_horizon_hours": 24,
            "rebuild_npy": True,
        })
        assert resp.status_code == 200
        feat_ver = resp.json()["outputs"]["feature_dataset_version"]

        bundle_dir = PATHS.models_store / "cache" / "features" / dataset_id / "v1.0" / feat_ver
        with open(bundle_dir / "row_metadata.json", "r", encoding="utf-8") as f:
            rows = json.load(f)

        # Ensure timestamps 10:00, 11:00, 12:00 for L0001 are NOT in row metadata
        excluded_times = {"2026-01-01 10:00:00", "2026-01-01 11:00:00", "2026-01-01 12:00:00"}
        for r in rows:
            if r["asset_id"] == "L0001":
                assert r["timestamp"] not in excluded_times
    finally:
        if fail_file.exists():
            fail_file.unlink()


def test_logical_uri_outside_root_raises_error():
    """Test that get_logical_uri rejects paths outside repo root and data_dir."""
    repo = FeatureRepository()
    with pytest.raises(FeatureContractError) as exc_info:
        repo.get_logical_uri(Path("Z:/forbidden/secret_cmd.exe") if os.name == "nt" else Path("/opt/forbidden/secret.csv"))
    assert "논리 URI로 변환할 수 없는 허용 범위 밖의 경로" in str(exc_info.value)


def test_feature_endpoint_is_synchronous():
    """Verify that POST /feature is a synchronous function executed in worker threads."""
    assert inspect.iscoroutinefunction(post_feature) is False
