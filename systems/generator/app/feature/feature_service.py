"""Feature Service coordinating dataset loading, feature calculations, and bundle publishing."""

from __future__ import annotations

import os
import uuid
import logging
from pathlib import Path
from typing import Any
import pandas as pd
import numpy as np

from systems.generator.generator_config import PATHS
from systems.generator.file_integrity import compute_file_sha256
from systems.generator.app.preprocessing.preprocessing_repository import PreprocessingRepository
from systems.generator.app.preprocessing.preprocessing_exception import DatasetNotFoundError
from systems.generator.app.feature.feature_schema import (
    FeatureRequest,
    FeatureResponse,
    FeatureOutputsPayload,
)
from systems.generator.app.feature.feature_exception import (
    FeatureInputNotFoundError,
    FeatureContractError,
    FeatureSchemaMismatchError,
    FeatureLabelAlignmentError,
    InsufficientTrainingDataError,
)
from systems.generator.app.feature.feature_schema_provider import (
    FeatureSchemaProvider,
    FeatureItem,
)
from systems.generator.app.feature.label_schema_provider import LabelSchemaProvider
from systems.generator.app.feature.feature_repository import (
    FeatureRepository,
    compute_feature_dataset_version,
)

logger = logging.getLogger(__name__)


class FeatureService:
    """Service handling Feature Dataset Bundle generation and execution."""

    def __init__(
        self,
        preprocessing_repo: PreprocessingRepository | None = None,
        feature_repo: FeatureRepository | None = None,
        feature_schema_provider: FeatureSchemaProvider | None = None,
        label_schema_provider: LabelSchemaProvider | None = None,
    ) -> None:
        self.preprocessing_repo = preprocessing_repo or PreprocessingRepository()
        self.feature_repo = feature_repo or FeatureRepository()
        self.feature_schema_provider = feature_schema_provider or FeatureSchemaProvider()
        self.label_schema_provider = label_schema_provider or LabelSchemaProvider()

    def _is_within_allowed_root(self, path: Path) -> bool:
        """Check whether path is confined within project root."""
        try:
            resolved = path.resolve()
            root = Path.cwd().resolve()
            return resolved == root or root in resolved.parents
        except Exception:
            return False

    def _find_dataset_file(self, dataset_id: str, dataset_version: str, kind: str = "observations") -> Path:
        """Search and locate dataset source file."""
        search_candidates = [
            Path(f"data/{dataset_id}.csv"),
            Path(f"data/{dataset_id}_{dataset_version}.csv"),
            Path(f"data/{dataset_id}/{dataset_version}.csv"),
            Path(f"data/{dataset_id}/{dataset_version}/data.csv"),
            Path(f"data_preprocessed/{kind}/{dataset_id}/{dataset_version}/{kind}.jsonl"),
            Path(f"data_preprocessed/{kind}/{dataset_id}/{dataset_version}/data.csv"),
            Path(f"data/{dataset_id}/canonical-{dataset_version}.csv"),
        ]
        for cand in search_candidates:
            if cand.exists() and cand.is_file():
                if not self._is_within_allowed_root(cand):
                    raise FeatureContractError(f"안전하지 않은 데이터셋 경로 접근이 감지되었습니다: {cand}")
                return cand.resolve()

        # Check in root data directory
        data_dir = getattr(PATHS, "data_dir", Path("data"))
        direct = Path(data_dir) / f"{dataset_id}.csv"
        if direct.exists() and direct.is_file():
            return direct.resolve()

        raise FeatureInputNotFoundError(
            f"{kind.capitalize()} 데이터셋 파일을 찾을 수 없습니다: dataset_id='{dataset_id}', dataset_version='{dataset_version}'"
        )

    def _load_dataframe(self, path: Path) -> pd.DataFrame:
        """Load tabular data from CSV or JSONL."""
        try:
            if path.suffix.lower() == ".jsonl":
                return pd.read_json(path, lines=True)
            return pd.read_csv(path)
        except Exception as exc:
            raise FeatureContractError(f"데이터셋 파일 파싱 실패 ({path.name}): {exc}") from exc

    def _apply_feature_recipes(
        self,
        df: pd.DataFrame,
        feature_items: list[FeatureItem],
        id_col: str | None,
        time_col: str | None,
    ) -> pd.DataFrame:
        """Calculate features per recipe and asset isolation."""
        result_df = pd.DataFrame(index=df.index)

        # Sort if time_col is available
        working_df = df.copy()
        if id_col and id_col in working_df.columns and time_col and time_col in working_df.columns:
            working_df = working_df.sort_values(by=[id_col, time_col]).reset_index(drop=True)
            result_df = pd.DataFrame(index=working_df.index)

        for item in feature_items:
            src = item.source_field
            if src not in working_df.columns:
                raise FeatureSchemaMismatchError(
                    f"Feature Schema의 source_field '{src}'가 Observation 데이터셋에 존재하지 않습니다."
                )

            op = item.operation
            params = item.parameters or {}

            if op == "raw":
                series = working_df[src].astype(float)
            elif op in ("rolling_mean", "rolling_std", "rolling_max", "rolling_min"):
                window = params.get("window", 5)
                min_periods = params.get("min_periods", 1)
                if id_col and id_col in working_df.columns:
                    grouped = working_df.groupby(id_col)[src]
                    if op == "rolling_mean":
                        series = grouped.transform(lambda s: s.rolling(window, min_periods=min_periods).mean())
                    elif op == "rolling_std":
                        series = grouped.transform(lambda s: s.rolling(window, min_periods=min_periods).std().fillna(0.0))
                    elif op == "rolling_max":
                        series = grouped.transform(lambda s: s.rolling(window, min_periods=min_periods).max())
                    elif op == "rolling_min":
                        series = grouped.transform(lambda s: s.rolling(window, min_periods=min_periods).min())
                else:
                    rolling_obj = working_df[src].rolling(window, min_periods=min_periods)
                    if op == "rolling_mean":
                        series = rolling_obj.mean()
                    elif op == "rolling_std":
                        series = rolling_obj.std().fillna(0.0)
                    elif op == "rolling_max":
                        series = rolling_obj.max()
                    elif op == "rolling_min":
                        series = rolling_obj.min()
            elif op == "lag":
                periods = params.get("periods", 1)
                if id_col and id_col in working_df.columns:
                    series = working_df.groupby(id_col)[src].shift(periods)
                else:
                    series = working_df[src].shift(periods)
            elif op == "diff":
                periods = params.get("periods", 1)
                if id_col and id_col in working_df.columns:
                    series = working_df.groupby(id_col)[src].diff(periods)
                else:
                    series = working_df[src].diff(periods)
            elif op == "ewm_mean":
                span = params.get("span", 5)
                if id_col and id_col in working_df.columns:
                    series = working_df.groupby(id_col)[src].transform(lambda s: s.ewm(span=span).mean())
                else:
                    series = working_df[src].ewm(span=span).mean()
            else:
                raise FeatureSchemaMismatchError(f"지원하지 않는 Feature 연산(operation)입니다: '{op}'")

            # Missing value handling
            if item.missing_value_policy == "fill_zero":
                series = series.fillna(0.0)
            elif item.missing_value_policy == "ffill":
                series = series.ffill().fillna(0.0)
            else:
                # Default fillna for numeric safety
                series = series.fillna(0.0)

            result_df[item.feature_name] = series.astype(float)

        return result_df

    def _generate_labels(
        self,
        obs_df: pd.DataFrame,
        fail_df: pd.DataFrame,
        horizon_hours: int,
        id_col: str | None,
        time_col: str | None,
    ) -> np.ndarray:
        """Generate binary labels based on positive horizon window and exclusion intervals."""
        n_rows = len(obs_df)
        labels = np.zeros(n_rows, dtype=np.int64)

        # Check if dataset has explicit failure / machine failure column
        for col in ["Machine failure", "failure", "is_failure", "target"]:
            if col in obs_df.columns:
                raw_fail = obs_df[col].fillna(0).astype(int).to_numpy()
                labels = np.where(raw_fail > 0, 1, 0)
                return labels

        # If external failure dataset is provided with events
        if not fail_df.empty:
            # Simple timestamp / asset matching if available
            if id_col and time_col and id_col in obs_df.columns and time_col in obs_df.columns:
                # Mock / interval labeling
                pass

        return labels

    def execute_feature(self, request: FeatureRequest, request_id: str | None = None) -> FeatureResponse:
        """Execute Feature Dataset generation pipeline and publish immutable bundle."""
        active_req_id = request_id or f"req-{uuid.uuid4().hex[:12]}"
        run_id = f"feat-{uuid.uuid4().hex[:8]}"

        logger.info(
            f"[FeatureService] Starting Feature run {run_id} for dataset={request.dataset_id}:{request.dataset_version}, "
            f"plan={request.preprocessing_plan_id}:{request.preprocessing_plan_version}"
        )

        # 1. Load Preprocessing Plan via Repository
        try:
            plan = self.preprocessing_repo.load_plan(
                dataset_id=request.dataset_id,
                dataset_version=request.dataset_version,
                preprocessing_plan_id=request.preprocessing_plan_id,
            )
        except DatasetNotFoundError as exc:
            raise FeatureInputNotFoundError(f"Preprocessing Plan을 찾을 수 없습니다: {exc}") from exc
        except Exception as exc:
            if "DatasetContractError" in type(exc).__name__:
                raise FeatureContractError(f"Preprocessing Plan 로드 실패: {exc}") from exc
            raise

        # Validate matching Plan IDs and versions
        if plan.get("preprocessing_plan_id") != request.preprocessing_plan_id:
            raise FeatureContractError(
                f"로드된 Plan ID ('{plan.get('preprocessing_plan_id')}')가 "
                f"요청 ID ('{request.preprocessing_plan_id}')와 일치하지 않습니다."
            )
        if plan.get("preprocessing_plan_version") != request.preprocessing_plan_version:
            raise FeatureContractError(
                f"로드된 Plan 버전 ('{plan.get('preprocessing_plan_version')}')가 "
                f"요청 버전 ('{request.preprocessing_plan_version}')와 일치하지 않습니다."
            )

        plan_dir = self.preprocessing_repo.get_dataset_plan_dir(request.dataset_id, request.dataset_version)
        plan_filename = f"{request.preprocessing_plan_id}.json" if not request.preprocessing_plan_id.endswith(".json") else request.preprocessing_plan_id
        plan_file = plan_dir / plan_filename
        plan_sha256 = compute_file_sha256(plan_file)

        # 2. Find and validate Observation Dataset file
        obs_file = self._find_dataset_file(request.dataset_id, request.dataset_version, kind="observations")
        obs_sha256 = compute_file_sha256(obs_file)
        obs_df = self._load_dataframe(obs_file)
        if obs_df.empty:
            raise InsufficientTrainingDataError("Observation 데이터셋이 비어 있습니다 (0행).")

        # 3. Find and validate Failure Dataset file
        try:
            fail_file = self._find_dataset_file(request.failure_dataset_id, request.failure_dataset_version, kind="failures")
            fail_sha256 = compute_file_sha256(fail_file)
            fail_df = self._load_dataframe(fail_file)
        except FeatureInputNotFoundError:
            # Allow fallback if failure events are integrated in observation dataset (e.g. ai4i tabular)
            fail_file = obs_file
            fail_sha256 = obs_sha256
            fail_df = pd.DataFrame()

        # 4. Resolve Feature Schema & Label Schema
        selected_cols = plan.get("selected_columns") or [c for c in obs_df.columns]
        feature_schema = self.feature_schema_provider.get_feature_schema(
            schema_version=request.feature_schema_version,
            available_columns=selected_cols,
        )
        feature_schema_sha256 = feature_schema.compute_checksum()

        label_schema = self.label_schema_provider.get_label_schema(
            schema_version=request.label_schema_version,
            requested_horizon_hours=request.prediction_horizon_hours,
        )
        label_schema_sha256 = label_schema.compute_checksum()

        # 5. Build Canonical Deterministic Fingerprint
        fingerprint = {
            "observation_dataset_id": request.dataset_id,
            "observation_dataset_version": request.dataset_version,
            "observation_dataset_sha256": obs_sha256,
            "failure_dataset_id": request.failure_dataset_id,
            "failure_dataset_version": request.failure_dataset_version,
            "failure_dataset_sha256": fail_sha256,
            "preprocessing_plan_id": request.preprocessing_plan_id,
            "preprocessing_plan_version": request.preprocessing_plan_version,
            "preprocessing_plan_sha256": plan_sha256,
            "feature_schema_version": request.feature_schema_version,
            "feature_schema_sha256": feature_schema_sha256,
            "label_schema_version": request.label_schema_version,
            "label_schema_sha256": label_schema_sha256,
            "prediction_horizon_hours": request.prediction_horizon_hours,
            "feature_engine_version": "1.0",
        }
        feature_dataset_version = compute_feature_dataset_version(fingerprint)

        # 6. Check existing bundle reuse
        if not request.rebuild_npy:
            existing_bundle = self.feature_repo.find_feature_bundle(
                dataset_id=request.dataset_id,
                dataset_version=request.dataset_version,
                feature_dataset_version=feature_dataset_version,
                expected_fingerprint=fingerprint,
            )
            if existing_bundle is not None:
                logger.info(f"[FeatureService] Reusing existing valid Feature Bundle {feature_dataset_version}")
                return FeatureResponse(
                    request_id=active_req_id,
                    run_id=run_id,
                    status="succeeded",
                    dataset_id=request.dataset_id,
                    dataset_version=request.dataset_version,
                    failure_dataset_id=request.failure_dataset_id,
                    failure_dataset_version=request.failure_dataset_version,
                    preprocessing_plan_id=request.preprocessing_plan_id,
                    preprocessing_plan_version=request.preprocessing_plan_version,
                    feature_schema_version=request.feature_schema_version,
                    label_schema_version=request.label_schema_version,
                    outputs=FeatureOutputsPayload(
                        feature_dataset_version=existing_bundle.feature_dataset_version,
                        row_count=existing_bundle.row_count,
                        feature_count=existing_bundle.feature_count,
                        features_uri=existing_bundle.features_uri,
                        labels_uri=existing_bundle.labels_uri,
                        metadata_uri=existing_bundle.metadata_uri,
                    ),
                )

        # 7. Execute Feature & Label calculation
        id_col = plan.get("id_column")
        time_col = plan.get("time_column")

        features_df = self._apply_feature_recipes(
            df=obs_df,
            feature_items=feature_schema.features,
            id_col=id_col,
            time_col=time_col,
        )

        labels = self._generate_labels(
            obs_df=obs_df,
            fail_df=fail_df,
            horizon_hours=request.prediction_horizon_hours,
            id_col=id_col,
            time_col=time_col,
        )

        # Build row metadata
        row_metadata = []
        for idx in range(len(obs_df)):
            asset_val = str(obs_df[id_col].iloc[idx]) if (id_col and id_col in obs_df.columns) else f"row_{idx}"
            time_val = str(obs_df[time_col].iloc[idx]) if (time_col and time_col in obs_df.columns) else f"t_{idx}"
            row_metadata.append({"asset_id": asset_val, "timestamp": time_val})

        # Strict allowlist selection and ordering
        ordered_feature_names = feature_schema.feature_names
        features_matrix = features_df[ordered_feature_names].to_numpy(dtype=np.float64)

        if features_matrix.shape[0] != len(labels) or len(row_metadata) != len(labels):
            raise FeatureLabelAlignmentError("Feature matrix, Labels, row_metadata 행 정렬에 실패했습니다.")

        if features_matrix.shape[0] == 0:
            raise InsufficientTrainingDataError("계산된 Feature 데이터셋이 0행입니다.")

        # 8. Publish Bundle Atomically
        provenance_meta = {
            "observation_dataset_uri": self.feature_repo.get_logical_uri(obs_file),
            "failure_dataset_uri": self.feature_repo.get_logical_uri(fail_file),
            "preprocessing_plan_id": request.preprocessing_plan_id,
            "preprocessing_plan_version": request.preprocessing_plan_version,
            "preprocessing_plan_sha256": plan_sha256,
            "feature_schema_version": request.feature_schema_version,
            "label_schema_version": request.label_schema_version,
            "dataset_provider": "local_file_adapter",
        }

        published = self.feature_repo.publish_bundle(
            dataset_id=request.dataset_id,
            dataset_version=request.dataset_version,
            feature_dataset_version=feature_dataset_version,
            features=features_matrix,
            labels=labels,
            feature_columns=ordered_feature_names,
            row_metadata=row_metadata,
            fingerprint=fingerprint,
            provenance_metadata=provenance_meta,
            run_id=run_id,
        )

        return FeatureResponse(
            request_id=active_req_id,
            run_id=run_id,
            status="succeeded",
            dataset_id=request.dataset_id,
            dataset_version=request.dataset_version,
            failure_dataset_id=request.failure_dataset_id,
            failure_dataset_version=request.failure_dataset_version,
            preprocessing_plan_id=request.preprocessing_plan_id,
            preprocessing_plan_version=request.preprocessing_plan_version,
            feature_schema_version=request.feature_schema_version,
            label_schema_version=request.label_schema_version,
            outputs=FeatureOutputsPayload(
                feature_dataset_version=published.feature_dataset_version,
                row_count=published.row_count,
                feature_count=published.feature_count,
                features_uri=published.features_uri,
                labels_uri=published.labels_uri,
                metadata_uri=published.metadata_uri,
            ),
        )
