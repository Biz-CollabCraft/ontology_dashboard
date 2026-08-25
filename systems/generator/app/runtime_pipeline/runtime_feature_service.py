"""Service for extracting label-free 2D float64 Runtime Features for inference."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from systems.generator.generator_config import PATHS
from systems.generator.file_integrity import compute_file_sha256
from systems.generator.app.feature.feature_schema_provider import (
    FeatureItem,
    FeatureSchemaProvider,
    FeatureSchemaSpec,
)
from systems.generator.app.runtime_pipeline.pipeline_exception import (
    PipelineFeatureSchemaMismatchError,
    PipelineHistoryInsufficientError,
    PipelineRuntimeFeatureFailedError,
)
from systems.generator.app.runtime_pipeline.pipeline_schema import (
    ArtifactReference,
)

logger = logging.getLogger(__name__)


@dataclass
class RuntimeFeatureBundle:
    """In-memory bundle returned from computation before atomic persistence."""
    features: np.ndarray
    feature_columns: list[str]
    row_metadata: list[dict[str, Any]]
    runtime_feature_version: str
    feature_schema_version: str
    dataset_id: str
    dataset_version: str


class RuntimeFeatureService:
    """Extracts label-free numeric feature matrices matching Model Artifact recipe contracts."""

    def __init__(
        self,
        schema_provider: Optional[FeatureSchemaProvider] = None,
        cache_dir: Optional[Path] = None,
    ) -> None:
        self.schema_provider = schema_provider or FeatureSchemaProvider()
        if cache_dir is None:
            models_store = getattr(PATHS, "models_store", Path("models_store"))
            self.cache_dir = Path(models_store) / "cache" / "runtime_features"
        else:
            self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def extract_and_publish(
        self,
        *,
        preprocessed_df: pd.DataFrame,
        feature_schema_dict: dict[str, Any],
        history_requirement_dict: dict[str, Any],
        dataset_id: str = "canonical-ai4i-v1",
        dataset_version: str = "canonical-ai4i-physics-v3.1",
    ) -> tuple[RuntimeFeatureBundle, ArtifactReference]:
        """Compute runtime feature matrix and atomically publish npy artifact."""
        if preprocessed_df.empty:
            raise PipelineRuntimeFeatureFailedError("전처리된 데이터프레임이 비어 있습니다.")

        # 1. Validate against history requirement
        min_rows = int(history_requirement_dict.get("minimum_history_rows", 1))
        if len(preprocessed_df) < min_rows:
            raise PipelineHistoryInsufficientError(
                f"관측 이력 행 수가 부족합니다: 요구치={min_rows}, 실제={len(preprocessed_df)}",
                details=[{"minimum_history_rows": min_rows, "actual_rows": len(preprocessed_df)}],
            )

        req_cols = history_requirement_dict.get("required_columns", [])
        missing_req = [c for c in req_cols if c not in preprocessed_df.columns]
        if missing_req:
            raise PipelineFeatureSchemaMismatchError(
                f"Model Artifact가 요구하는 필수 센서 컬럼이 누락되었습니다: {missing_req}",
                details=[{"missing_columns": missing_req}],
            )

        # 2. Parse feature schema
        try:
            schema_spec: FeatureSchemaSpec = self.schema_provider.parse_schema_dict(feature_schema_dict)
        except Exception as exc:
            raise PipelineFeatureSchemaMismatchError(f"Feature Schema 유효성 검증 실패: {exc}") from exc

        # 3. Calculate features column by column
        feature_cols: list[str] = []
        calculated_series: dict[str, np.ndarray] = {}

        df_sorted = preprocessed_df.copy()
        if "timestamp" in df_sorted.columns:
            try:
                df_sorted["timestamp"] = pd.to_datetime(df_sorted["timestamp"], utc=True)
                df_sorted = df_sorted.sort_values(by=["timestamp"]).reset_index(drop=True)
            except Exception:
                pass

        for item in schema_spec.features:
            col_name = item.feature_name
            src_col = item.source_field
            op = item.operation
            params = item.parameters or {}
            mv_policy = item.missing_value_policy

            if src_col not in df_sorted.columns:
                raise PipelineFeatureSchemaMismatchError(
                    f"Feature '{col_name}'의 원본 필드 '{src_col}'이 데이터셋에 없습니다.",
                    details=[{"feature_name": col_name, "source_field": src_col}],
                )

            src_series = pd.to_numeric(df_sorted[src_col], errors="coerce")

            if op == "raw":
                res = src_series.values
            elif op in ("lag", "diff"):
                periods = int(params.get("periods", 1))
                if op == "lag":
                    res = src_series.shift(periods).values
                else:
                    res = src_series.diff(periods).values
            elif "rolling" in op:
                window = int(params.get("window", 3))
                min_p = int(params.get("min_periods", 1))
                r = src_series.rolling(window=window, min_periods=min_p)
                if op == "rolling_mean":
                    res = r.mean().values
                elif op == "rolling_std":
                    res = r.std().values
                elif op == "rolling_max":
                    res = r.max().values
                elif op == "rolling_min":
                    res = r.min().values
                else:
                    res = src_series.values
            elif op == "ewm_mean":
                span = int(params.get("span", 3))
                res = src_series.ewm(span=span, adjust=False).mean().values
            else:
                res = src_series.values

            # Missing value handling
            s_res = pd.Series(res, dtype="float64")
            if s_res.isna().any():
                if mv_policy == "ffill":
                    s_res = s_res.ffill().bfill().fillna(0.0)
                elif mv_policy == "fill_zero":
                    s_res = s_res.fillna(0.0)
                elif mv_policy == "drop":
                    s_res = s_res.fillna(0.0)
                else:
                    s_res = s_res.fillna(0.0)

            calculated_series[col_name] = s_res.values.astype(np.float64)
            feature_cols.append(col_name)

        # Assemble 2D float64 matrix
        matrix_list = [calculated_series[c] for c in feature_cols]
        features_matrix = np.column_stack(matrix_list).astype(np.float64)

        if np.isnan(features_matrix).any() or np.isinf(features_matrix).any():
            features_matrix = np.nan_to_num(features_matrix, nan=0.0, posinf=1e6, neginf=-1e6)

        # Row metadata
        row_metadata = []
        for idx in range(len(df_sorted)):
            row = df_sorted.iloc[idx]
            asset_id = str(row.get("asset_id") or row.get("Product ID") or "default_asset")
            ts = str(row.get("timestamp") or row.get("observed_at") or "")
            row_metadata.append({"row_index": idx, "asset_id": asset_id, "timestamp": ts})

        feat_hash = hashlib.sha256(features_matrix.tobytes()).hexdigest()[:16]
        runtime_feature_version = f"runtime-feat-{feat_hash}"

        bundle = RuntimeFeatureBundle(
            features=features_matrix,
            feature_columns=feature_cols,
            row_metadata=row_metadata,
            runtime_feature_version=runtime_feature_version,
            feature_schema_version=schema_spec.schema_version,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
        )

        # 4. Atomic file persistence of features.npy
        dest_npy = self.cache_dir / f"{runtime_feature_version}.npy"
        temp_npy = self.cache_dir / f".tmp_{uuid.uuid4().hex}_{runtime_feature_version}.npy"
        try:
            with open(temp_npy, "wb") as f:
                np.save(f, features_matrix, allow_pickle=False)
                f.flush()
                os.fsync(f.fileno())
            temp_npy.replace(dest_npy)
        except Exception as exc:
            if temp_npy.exists():
                try:
                    temp_npy.unlink()
                except Exception:
                    pass
            raise PipelineRuntimeFeatureFailedError(f"Runtime Feature npy 저장 실패: {exc}") from exc

        sha256 = compute_file_sha256(dest_npy)
        size_bytes = dest_npy.stat().st_size
        ref = ArtifactReference(
            uri=str(dest_npy).replace("\\", "/"),
            sha256=sha256,
            role="runtime_features",
            size_bytes=size_bytes,
        )

        return bundle, ref
