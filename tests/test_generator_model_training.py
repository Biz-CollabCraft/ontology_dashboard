"""Tests for Generator multi-model training pipeline, feature allowlists, and Model Artifact publication."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from systems.backend.app.diagnosis.artifact_provider import LocalModelArtifactProvider
from systems.generator.model import (
    FRAMEWORK_BY_ALGORITHM,
    MODEL_SPECS,
    REGISTERED_MODELS,
    LightGBMModel,
    ModelRegistry,
    ModelScore,
    RandomForestModel,
    XGBoostModel,
    asset_time_split,
    get_model_class,
    publish_model_artifact,
    validate_manifest,
)


def _make_synthetic_labeled_dataset(n_samples: int = 100) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01 00:00:00", periods=n_samples, freq="1h")
    assets = ["ASSET_1" if i < n_samples // 2 else "ASSET_2" for i in range(n_samples)]
    np.random.seed(42)

    return pd.DataFrame({
        "asset_id": assets,
        "observed_at": dates,
        "period_start": dates,  # metadata leakage candidate
        "vibration_mean_3h": np.random.normal(10.0, 2.0, n_samples),
        "temperature_std_6h": np.random.normal(50.0, 5.0, n_samples),
        "pressure_raw": np.random.normal(100.0, 10.0, n_samples),
        "label": np.random.choice([0, 1], size=n_samples, p=[0.8, 0.2]),
    })


def test_model_package_import_contract():
    """Test 1: systems.generator.model imports without prediction package reverse dependency and has REGISTERED_MODELS."""
    import systems.generator.model as model_pkg

    assert hasattr(model_pkg, "train_all")
    assert hasattr(model_pkg, "publish_model_artifact")
    assert hasattr(model_pkg, "REGISTERED_MODELS")
    assert len(model_pkg.REGISTERED_MODELS) == 3
    assert "systems.generator.prediction" not in sys.modules


def test_model_specs_and_framework_mapping():
    """Test 2: get_model_class dynamically loads algorithm classes and verifies framework mapping."""
    assert set(REGISTERED_MODELS.keys()) == {"lightgbm", "xgboost", "random_forest"}
    assert FRAMEWORK_BY_ALGORITHM["lightgbm"] == "lightgbm"
    assert FRAMEWORK_BY_ALGORITHM["xgboost"] == "xgboost"
    assert FRAMEWORK_BY_ALGORITHM["random_forest"] == "scikit-learn"

    rf_cls = get_model_class("random_forest")
    assert rf_cls is RandomForestModel
    assert rf_cls.framework == "scikit-learn"

    lgb_cls = get_model_class("lightgbm")
    assert lgb_cls is LightGBMModel

    xgb_cls = get_model_class("xgboost")
    assert xgb_cls is XGBoostModel

    with pytest.raises(ValueError, match="Unknown model algorithm"):
        get_model_class("unknown_algo")


def test_asset_time_split_prevents_future_leakage():
    """Test 3: asset_time_split sorts each asset chronologically and separates past/future."""
    df = _make_synthetic_labeled_dataset(60)

    # Shuffle input rows to test order independence
    shuffled_df = df.sample(frac=1.0, random_state=123).reset_index(drop=True)

    train_df, val_df, test_df = asset_time_split(shuffled_df, id_col="asset_id", time_col="observed_at", test_size=0.2, val_size=0.2)

    assert len(train_df) + len(val_df) + len(test_df) == len(df)

    for asset_name in ("ASSET_1", "ASSET_2"):
        t_asset = train_df[train_df["asset_id"] == asset_name]
        v_asset = val_df[val_df["asset_id"] == asset_name]
        te_asset = test_df[test_df["asset_id"] == asset_name]

        if not t_asset.empty and not v_asset.empty:
            assert t_asset["observed_at"].max() <= v_asset["observed_at"].min()
        if not v_asset.empty and not te_asset.empty:
            assert v_asset["observed_at"].max() <= te_asset["observed_at"].min()


def test_explicit_feature_schema_allowlist_excludes_metadata():
    """Test 4: Only declared feature allowlist columns are used in model training."""
    df = _make_synthetic_labeled_dataset(60)
    rf_cls = get_model_class("random_forest")
    model = rf_cls()

    declared_features = ["vibration_mean_3h", "temperature_std_6h", "pressure_raw"]
    model.train(df, feature_names=declared_features, target_col="label", id_col="asset_id", time_col="observed_at")

    assert model.feature_cols == declared_features
    assert "asset_id" not in model.feature_cols
    assert "observed_at" not in model.feature_cols
    assert "period_start" not in model.feature_cols
    assert "label" not in model.feature_cols


def test_models_train_predict_proba_and_explain(tmp_path):
    """Test 5: LightGBM, XGBoost, and RandomForest train, predict ModelScore, and predict probabilities."""
    df = _make_synthetic_labeled_dataset(60)
    features = ["vibration_mean_3h", "temperature_std_6h", "pressure_raw"]

    for algo_name in ("random_forest", "lightgbm", "xgboost"):
        cls = get_model_class(algo_name)
        model = cls()
        model.train(df, feature_names=features, target_col="label")

        # Probability prediction test
        probs = model.predict_proba(df[features])
        assert probs.ndim == 2
        assert probs.shape == (len(df), 2)
        assert np.all((probs >= 0.0) & (probs <= 1.0))

        # ModelScore predict & explain test
        score = model.predict(df[features])
        assert isinstance(score, ModelScore)
        assert 0.0 <= score.probability <= 1.0
        assert score.predicted_class in (0, 1)
        assert set(score.feature_importance.keys()) == set(features)

        # Save and load round-trip
        save_file = str(tmp_path / f"{algo_name}.joblib")
        model.save(save_file)

        loaded_model = cls()
        loaded_model.load(save_file)
        assert loaded_model.feature_cols == features

        loaded_probs = loaded_model.predict_proba(df[features])
        assert np.allclose(probs, loaded_probs)


def test_missing_feature_column_raises_error():
    """Test 6: Missing declared feature column in inference DataFrame raises a clear ValueError."""
    df = _make_synthetic_labeled_dataset(40)
    features = ["vibration_mean_3h", "temperature_std_6h", "pressure_raw"]

    rf_cls = get_model_class("random_forest")
    model = rf_cls()
    model.train(df, feature_names=features, target_col="label")

    incomplete_df = df[["vibration_mean_3h", "temperature_std_6h"]]
    with pytest.raises(ValueError, match="missing required features"):
        model.predict_proba(incomplete_df)


def test_canonical_model_artifact_publish_and_backend_roundtrip(tmp_path):
    """Test 7: Generator publish_model_artifact produces 6 files and is verifiable by Backend LocalModelArtifactProvider."""
    df = _make_synthetic_labeled_dataset(40)
    features = ["vibration_mean_3h", "temperature_std_6h", "pressure_raw"]

    rf_cls = get_model_class("random_forest")
    model = rf_cls()
    model.train(df, feature_names=features, target_col="label")

    model_file = tmp_path / "model.joblib"
    model.save(model_file)

    artifact_root = tmp_path / "artifacts"
    artifact_uri = f"file://{artifact_root.resolve()}"

    model_id = "pdm-cnc-tool-wear-random-forest"
    model_version = "v1"

    dest = publish_model_artifact(
        artifact_uri=artifact_uri,
        model_id=model_id,
        model_version=model_version,
        dataset_version="ds-v1",
        feature_schema_version="pdm-feature-v1",
        model_file=model_file,
        feature_schema={
            "schema_version": "pdm-feature-v1",
            "features": features,
            "target": "label",
            "prediction_task": "binary_failure_within_horizon",
        },
        training_config={
            "algorithm": "random_forest",
            "framework": "scikit-learn",
            "feature_count": len(features),
            "split_strategy": "asset_time_split",
            "target_name": "label",
            "random_seed": 42,
        },
        metrics={"validation_metrics": {"precision": 0.85, "recall": 0.80}},
        provenance={"training": {"run_id": "run-test-01", "publisher": "systems/generator"}},
        compatibility={"runtime": "ontology_dashboard.systems.backend.diagnosis", "feature_executor_version": "pdm-feature-executor-v1", "prediction_task": "binary_failure_within_horizon"},
    )

    assert dest.exists()
    assert (dest / "manifest.json").exists()
    assert (dest / "model.joblib").exists()
    assert (dest / "feature_schema.json").exists()
    assert (dest / "label_schema.json").exists()
    assert (dest / "history_requirement.json").exists()
    assert (dest / "metrics.json").exists()

    # Backend loader verification
    provider = LocalModelArtifactProvider(f"file://{dest.resolve()}")
    loaded = provider.load()
    assert loaded.manifest["model_id"] == model_id
    assert loaded.manifest["model_version"] == model_version
    assert loaded.feature_schema["features"] == features

    # Test duplicate publish fails (immutability guarantee)
    with pytest.raises(FileExistsError, match="Model Artifact already published"):
        publish_model_artifact(
            artifact_uri=artifact_uri,
            model_id=model_id,
            model_version=model_version,
            dataset_version="ds-v1",
            feature_schema_version="pdm-feature-v1",
            model_file=model_file,
            feature_schema={"schema_version": "pdm-feature-v1", "features": features},
            training_config={"algorithm": "random_forest"},
            metrics={},
            provenance={},
            compatibility={},
        )
