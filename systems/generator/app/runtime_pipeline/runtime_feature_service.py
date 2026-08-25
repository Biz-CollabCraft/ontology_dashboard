"""Service for extracting label-free 2D float64 Runtime Features for inference."""

from __future__ import annotations

import hashlib
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
    PipelineAssetIdMissingError,
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
            self.cache_dir = PATHS.runtime_feature_root
        else:
            self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_id_and_time_columns(
        self,
        df: pd.DataFrame,
        id_column: Optional[str] = None,
        time_column: Optional[str] = None,
    ) -> tuple[str, Optional[str]]:
        """Identify asset ID and timestamp columns with fail-closed missing ID check."""
        target_id_col = id_column
        if not target_id_col:
            for candidate in ("asset_id", "Product ID", "UDI", "equipment_id", "machine_id"):
                if candidate in df.columns:
                    target_id_col = candidate
                    break

        if not target_id_col or target_id_col not in df.columns:
            raise PipelineAssetIdMissingError(
                "데이터셋에 설비 식별자(asset_id) 컬럼이 누락되었습니다. 임의의 default_asset 대체는 금지됩니다.",
                details=[{"columns": list(df.columns)}],
                retryable=False,
            )

        if df[target_id_col].isna().all():
            raise PipelineAssetIdMissingError(
                f"설비 식별자 컬럼 '{target_id_col}'의 모든 값이 결측치(NaN/None)입니다.",
                details=[{"id_column": target_id_col}],
                retryable=False,
            )

        target_time_col = time_column
        if not target_time_col:
            for candidate in ("timestamp", "observed_at", "time", "date", "datetime"):
                if candidate in df.columns:
                    target_time_col = candidate
                    break

        return target_id_col, target_time_col

    def _calculate_feature_series(
        self,
        series: pd.Series,
        op: str,
        params: dict[str, Any],
        mv_policy: str,
    ) -> pd.Series:
        """Compute single feature series within an isolated asset group."""
        numeric_series = pd.to_numeric(series, errors="coerce")

        if op == "raw":
            res = numeric_series
        elif op in ("lag", "diff"):
            periods = int(params.get("periods", 1))
            if op == "lag":
                res = numeric_series.shift(periods)
            else:
                res = numeric_series.diff(periods)
        elif "rolling" in op:
            window = int(params.get("window", 3))
            min_p = int(params.get("min_periods", 1))
            r = numeric_series.rolling(window=window, min_periods=min_p)
            if op == "rolling_mean":
                res = r.mean()
            elif op == "rolling_std":
                res = r.std()
            elif op == "rolling_max":
                res = r.max()
            elif op == "rolling_min":
                res = r.min()
            else:
                res = numeric_series
        elif op == "ewm_mean":
            span = int(params.get("span", 3))
            res = numeric_series.ewm(span=span, adjust=False).mean()
        else:
            res = numeric_series

        # Apply missing value policy strictly within group
        if res.isna().any():
            if mv_policy == "ffill":
                res = res.ffill().bfill().fillna(0.0)
            elif mv_policy == "fill_zero":
                res = res.fillna(0.0)
            elif mv_policy == "drop":
                res = res.fillna(0.0)
            else:
                res = res.fillna(0.0)

        return res.astype("float64")

    def extract_and_publish(
        self,
        *,
        preprocessed_df: pd.DataFrame,
        feature_schema_dict: dict[str, Any],
        history_requirement_dict: dict[str, Any],
        id_column: Optional[str] = None,
        time_column: Optional[str] = None,
        dataset_id: str = "canonical-ai4i-v1",
        dataset_version: str = "canonical-ai4i-physics-v3.1",
    ) -> tuple[RuntimeFeatureBundle, ArtifactReference]:
        """Compute runtime feature matrix with equipment-isolated timeseries and publish npy artifact."""
        if preprocessed_df.empty:
            raise PipelineRuntimeFeatureFailedError("전처리된 데이터프레임이 비어 있습니다.")

        # 1. Validate asset ID and sort deterministically
        id_col, time_col = self._resolve_id_and_time_columns(preprocessed_df, id_column, time_column)

        df_sorted = preprocessed_df.copy()
        if time_col and time_col in df_sorted.columns:
            try:
                df_sorted[time_col] = pd.to_datetime(df_sorted[time_col], utc=True)
            except Exception:
                pass
            df_sorted = df_sorted.sort_values(by=[id_col, time_col]).reset_index(drop=True)
        else:
            df_sorted = df_sorted.sort_values(by=[id_col]).reset_index(drop=True)

        # 2. Validate against history requirement
        min_rows = int(history_requirement_dict.get("minimum_history_rows", 1))
        if len(df_sorted) < min_rows:
            raise PipelineHistoryInsufficientError(
                f"관측 이력 행 수가 부족합니다: 요구치={min_rows}, 실제={len(df_sorted)}",
                details=[{"minimum_history_rows": min_rows, "actual_rows": len(df_sorted)}],
            )

        req_cols = history_requirement_dict.get("required_columns", [])
        missing_req = [c for c in req_cols if c not in df_sorted.columns]
        if missing_req:
            raise PipelineFeatureSchemaMismatchError(
                f"Model Artifact가 요구하는 필수 센서 컬럼이 누락되었습니다: {missing_req}",
                details=[{"missing_columns": missing_req}],
            )

        # 3. Parse feature schema
        try:
            schema_spec: FeatureSchemaSpec = self.schema_provider.parse_schema_dict(feature_schema_dict)
        except Exception as exc:
            raise PipelineFeatureSchemaMismatchError(f"Feature Schema 유효성 검증 실패: {exc}") from exc

        # 4. Calculate features column by column with strict equipment isolation (groupby id_col)
        feature_cols: list[str] = []
        feature_data_dict: dict[str, np.ndarray] = {}

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

            # Isolated per asset calculation
            grouped_calc = df_sorted.groupby(id_col, group_keys=False, sort=False)[src_col].apply(
                lambda s: self._calculate_feature_series(s, op, params, mv_policy)
            )

            feature_data_dict[col_name] = grouped_calc.values.astype(np.float64)
            feature_cols.append(col_name)

        # 5. Assemble 2D float64 matrix
        matrix_list = [feature_data_dict[c] for c in feature_cols]
        features_matrix = np.column_stack(matrix_list).astype(np.float64)

        if np.isnan(features_matrix).any() or np.isinf(features_matrix).any():
            features_matrix = np.nan_to_num(features_matrix, nan=0.0, posinf=1e6, neginf=-1e6)

        # 6. Row metadata
        row_metadata = []
        for idx in range(len(df_sorted)):
            row = df_sorted.iloc[idx]
            asset_val = str(row.get(id_col))
            ts_val = str(row.get(time_col)) if time_col else ""
            row_metadata.append({"row_index": idx, "asset_id": asset_val, "timestamp": ts_val})

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

        # 7. Atomic file persistence of features.npy
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
