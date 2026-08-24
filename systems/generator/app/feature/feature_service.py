"""Feature Service coordinating dataset loading, feature calculations, horizon labeling, and bundle publishing."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from systems.generator.app.feature.feature_exception import (
    FeatureContractError,
    FeatureDatasetIntegrityError,
    FeatureInputNotFoundError,
    FeatureLabelAlignmentError,
    FeatureSchemaMismatchError,
    InsufficientTrainingDataError,
)
from systems.generator.app.feature.feature_repository import (
    FeatureRepository,
    compute_feature_dataset_version,
)
from systems.generator.app.feature.feature_schema import (
    FeatureOutputsPayload,
    FeatureRequest,
    FeatureResponse,
)
from systems.generator.app.feature.feature_schema_provider import (
    FeatureItem,
    FeatureSchemaProvider,
)
from systems.generator.app.feature.label_schema_provider import (
    LabelSchemaProvider,
    LabelSchemaSpec,
)
from systems.generator.app.preprocessing.preprocessing_exception import DatasetNotFoundError
from systems.generator.app.preprocessing.preprocessing_repository import PreprocessingRepository
from systems.generator.common.timestamp_canonicalizer import canonicalize_timestamp_series
from systems.generator.file_integrity import compute_file_sha256
from systems.generator.generator_config import PATHS

logger = logging.getLogger(__name__)


class FeatureService:
    """Service handling Feature Dataset Bundle generation, deterministic alignment, and execution."""

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
        clean_id = dataset_id.strip()
        clean_ver = dataset_version.strip()

        if ".." in clean_id or ".." in clean_ver or "/" in clean_id or "\\" in clean_id:
            raise FeatureContractError(f"안전하지 않은 데이터셋 식별자입니다: dataset_id='{dataset_id}', version='{dataset_version}'")

        search_candidates = [
            Path(f"data/{clean_id}.csv"),
            Path(f"data/{clean_id}_{clean_ver}.csv"),
            Path(f"data/{clean_id}/{clean_ver}.csv"),
            Path(f"data/{clean_id}/{clean_ver}/data.csv"),
            Path(f"data_preprocessed/{kind}/{clean_id}/{clean_ver}/{kind}.jsonl"),
            Path(f"data_preprocessed/{kind}/{clean_id}/{clean_ver}/data.csv"),
            Path(f"data/{clean_id}/canonical-{clean_ver}.csv"),
        ]
        for cand in search_candidates:
            if cand.exists() and cand.is_file():
                if not self._is_within_allowed_root(cand):
                    raise FeatureContractError(f"안전하지 않은 데이터셋 경로 접근이 감지되었습니다: {cand}")
                return cand.resolve()

        # Check in root data directory
        data_dir = getattr(PATHS, "data_dir", Path("data"))
        direct = Path(data_dir) / f"{clean_id}.csv"
        if direct.exists() and direct.is_file():
            if not self._is_within_allowed_root(direct):
                raise FeatureContractError(f"안전하지 않은 데이터셋 경로 접근이 감지되었습니다: {direct}")
            return direct.resolve()

        raise FeatureInputNotFoundError(
            f"{kind.capitalize()} 데이터셋 파일을 찾을 수 없습니다: dataset_id='{clean_id}', dataset_version='{clean_ver}'"
        )

    def _load_dataframe(self, path: Path) -> pd.DataFrame:
        """Load tabular data from CSV or JSONL."""
        try:
            if path.suffix.lower() == ".jsonl":
                return pd.read_json(path, lines=True)
            return pd.read_csv(path)
        except Exception as exc:
            raise FeatureContractError(f"데이터셋 파일 파싱 실패 ({path.name}): {exc}") from exc

    def _prepare_canonical_working_df(
        self,
        obs_df: pd.DataFrame,
        id_col: str | None,
        time_col: str | None,
    ) -> tuple[pd.DataFrame, str | None, str | None]:
        """Normalize timestamps and perform stable sorting by asset ID and time."""
        working_df = obs_df.copy()

        # Determine and normalize time column
        resolved_time_col = time_col
        if not resolved_time_col or resolved_time_col not in working_df.columns:
            for candidate in ["observed_at", "timestamp", "datetime", "date", "time"]:
                if candidate in working_df.columns:
                    resolved_time_col = candidate
                    break

        if resolved_time_col and resolved_time_col in working_df.columns:
            working_df[resolved_time_col] = canonicalize_timestamp_series(
                working_df[resolved_time_col], col_name=resolved_time_col
            )

        # Determine asset ID column
        resolved_id_col = id_col
        if not resolved_id_col or resolved_id_col not in working_df.columns:
            for candidate in ["asset_id", "machineID", "Product ID", "product_id", "UDI", "udi"]:
                if candidate in working_df.columns:
                    resolved_id_col = candidate
                    break

        # Stable sort
        sort_cols = []
        if resolved_id_col and resolved_id_col in working_df.columns:
            sort_cols.append(resolved_id_col)
        if resolved_time_col and resolved_time_col in working_df.columns:
            sort_cols.append(resolved_time_col)

        if sort_cols:
            working_df = working_df.sort_values(by=sort_cols, kind="mergesort").reset_index(drop=True)
        else:
            working_df = working_df.reset_index(drop=True)

        return working_df, resolved_id_col, resolved_time_col

    def _compute_features_and_missing_masks(
        self,
        working_df: pd.DataFrame,
        feature_items: list[FeatureItem],
        id_col: str | None,
    ) -> tuple[pd.DataFrame, pd.Series]:
        """Compute feature transformations according to schema and track missing value masks."""
        computed_df = pd.DataFrame(index=working_df.index)
        missing_drop_mask = pd.Series(False, index=working_df.index)

        for item in feature_items:
            src = item.source_field
            if src not in working_df.columns:
                raise FeatureSchemaMismatchError(
                    f"Feature Schema의 source_field '{src}'가 Observation 데이터셋에 존재하지 않습니다."
                )

            op = item.operation
            params = item.parameters or {}
            mv_policy = item.missing_value_policy or "drop"

            # Execute operation without arbitrary premature fillna
            if op == "raw":
                try:
                    series = working_df[src].astype(float)
                except (ValueError, TypeError) as exc:
                    raise FeatureContractError(f"Feature '{item.feature_name}'의 수치형 변환 실패: {exc}") from exc
            elif op in ("rolling_mean", "rolling_std", "rolling_max", "rolling_min"):
                window = params.get("window", 5)
                min_periods = params.get("min_periods", 1)
                if id_col and id_col in working_df.columns:
                    grouped = working_df.groupby(id_col)[src]
                    if op == "rolling_mean":
                        series = grouped.transform(lambda s: s.rolling(window, min_periods=min_periods).mean())
                    elif op == "rolling_std":
                        series = grouped.transform(lambda s: s.rolling(window, min_periods=min_periods).std())
                    elif op == "rolling_max":
                        series = grouped.transform(lambda s: s.rolling(window, min_periods=min_periods).max())
                    elif op == "rolling_min":
                        series = grouped.transform(lambda s: s.rolling(window, min_periods=min_periods).min())
                else:
                    rolling_obj = working_df[src].rolling(window, min_periods=min_periods)
                    if op == "rolling_mean":
                        series = rolling_obj.mean()
                    elif op == "rolling_std":
                        series = rolling_obj.std()
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

            # Enforce missing value policy
            if mv_policy == "drop":
                nan_mask = series.isna()
                missing_drop_mask |= nan_mask
            elif mv_policy == "fill_zero":
                series = series.fillna(0.0)
            elif mv_policy == "ffill":
                if id_col and id_col in working_df.columns:
                    series = working_df.groupby(id_col)[src].ffill().fillna(0.0)
                else:
                    series = series.ffill().fillna(0.0)
            elif mv_policy == "error":
                if series.isna().any():
                    raise FeatureDatasetIntegrityError(
                        f"Feature '{item.feature_name}'에 결측값(NaN)이 존재합니다 (missing_value_policy='error')."
                    )
            else:
                raise FeatureSchemaMismatchError(
                    f"지원하지 않는 missing_value_policy입니다: '{mv_policy}'. (허용: drop, fill_zero, ffill, error)"
                )

            computed_df[item.feature_name] = series.astype(float)

        return computed_df, missing_drop_mask

    def _generate_labels_and_exclusion_mask(
        self,
        working_df: pd.DataFrame,
        fail_df: pd.DataFrame,
        label_schema: LabelSchemaSpec,
        id_col: str | None,
        time_col: str | None,
    ) -> tuple[pd.Series, pd.Series]:
        """Generate binary labels using [anchor - horizon, anchor) and mark [anchor, exclusion_end] active failures."""
        labels_series = pd.Series(0, index=working_df.index, dtype=np.int64)
        active_failure_drop_mask = pd.Series(False, index=working_df.index)

        horizon_delta = pd.Timedelta(hours=label_schema.prediction_horizon_hours)

        # 1. External Failure Dataset provided
        if not fail_df.empty:
            f_df = fail_df.copy()

            # Filter only active failure event rows if a failure indicator column exists in fail_df
            for cand in ["Machine failure", "failure", "is_failure", "is_failed", "target"]:
                if cand in f_df.columns:
                    f_df = f_df[f_df[cand] > 0]
                    break

            # Remove degradation_start leakage columns from failure DataFrame if present
            for deg_col in ["degradation_start", "degradation_started_at", "period_start"]:
                if deg_col in f_df.columns:
                    f_df = f_df.drop(columns=[deg_col])

            # Resolve anchor and exclusion_end columns
            anchor_col = label_schema.anchor
            if anchor_col not in f_df.columns:
                for cand in ["observed_at", "timestamp", "failure_point", "datetime", "date", "time", "failure_occurred_at"]:
                    if cand in f_df.columns:
                        anchor_col = cand
                        break

            if anchor_col not in f_df.columns:
                raise FeatureContractError(
                    f"Failure 데이터셋에 anchor 컬럼 ('{label_schema.anchor}')을 찾을 수 없습니다."
                )

            f_df[anchor_col] = canonicalize_timestamp_series(f_df[anchor_col], col_name=anchor_col)

            ex_end_col = label_schema.exclusion_end
            if ex_end_col and ex_end_col in f_df.columns:
                f_df[ex_end_col] = canonicalize_timestamp_series(f_df[ex_end_col], col_name=ex_end_col)
            else:
                ex_end_col = None

            # Resolve failure asset ID column
            fail_id_col = id_col
            if not fail_id_col or fail_id_col not in f_df.columns:
                for cand in ["asset_id", "machineID", "Product ID", "product_id", "UDI", "udi"]:
                    if cand in f_df.columns:
                        fail_id_col = cand
                        break

            # Apply horizon and exclusion logic per failure event
            for _, row in f_df.iterrows():
                f_time = row[anchor_col]
                if pd.isna(f_time):
                    continue

                h_start = f_time - horizon_delta

                if id_col and fail_id_col and id_col in working_df.columns and fail_id_col in row:
                    asset_mask = (working_df[id_col] == row[fail_id_col])
                else:
                    asset_mask = pd.Series(True, index=working_df.index)

                if time_col and time_col in working_df.columns:
                    # 1. Positive window: [f_time - horizon, f_time)
                    pos_mask = asset_mask & (working_df[time_col] >= h_start) & (working_df[time_col] < f_time)
                    labels_series.loc[pos_mask] = 1

                    # 2. Active failure exclusion: [f_time, ex_end]
                    if ex_end_col and pd.notna(row.get(ex_end_col)):
                        ex_end = row[ex_end_col]
                        ex_mask = asset_mask & (working_df[time_col] >= f_time) & (working_df[time_col] <= ex_end)
                    else:
                        ex_mask = asset_mask & (working_df[time_col] == f_time)
                    active_failure_drop_mask |= ex_mask

            return labels_series, active_failure_drop_mask

        # 2. Tabular failure indicators inside Observation dataset (e.g. AI4I machine failure)
        # Convert failure indicator rows into failure events and apply official horizon formula
        failure_indicator_col = None
        for cand in ["Machine failure", "failure", "is_failure", "target"]:
            if cand in working_df.columns:
                failure_indicator_col = cand
                break

        if failure_indicator_col is not None and time_col and time_col in working_df.columns:
            fail_indices = working_df.index[working_df[failure_indicator_col] > 0].tolist()
            for f_idx in fail_indices:
                f_time = working_df[time_col].iloc[f_idx]
                if pd.isna(f_time):
                    continue

                h_start = f_time - horizon_delta

                if id_col and id_col in working_df.columns:
                    target_asset = working_df[id_col].iloc[f_idx]
                    asset_mask = (working_df[id_col] == target_asset)
                else:
                    asset_mask = pd.Series(True, index=working_df.index)

                # Positive window: [f_time - horizon, f_time)
                pos_mask = asset_mask & (working_df[time_col] >= h_start) & (working_df[time_col] < f_time)
                labels_series.loc[pos_mask] = 1

                # Active failure exclusion: [f_time, f_time]
                ex_mask = asset_mask & (working_df[time_col] == f_time)
                active_failure_drop_mask |= ex_mask

        return labels_series, active_failure_drop_mask

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
        plan_uri = self.feature_repo.get_logical_uri(plan_file)

        # 2. Find and validate Observation Dataset file
        obs_file = self._find_dataset_file(request.dataset_id, request.dataset_version, kind="observations")
        obs_sha256 = compute_file_sha256(obs_file)
        obs_uri = self.feature_repo.get_logical_uri(obs_file)
        obs_df = self._load_dataframe(obs_file)
        if obs_df.empty:
            raise InsufficientTrainingDataError("Observation 데이터셋이 비어 있습니다 (0행).")

        # 3. Find and validate Failure Dataset file
        try:
            fail_file = self._find_dataset_file(request.failure_dataset_id, request.failure_dataset_version, kind="failures")
            fail_sha256 = compute_file_sha256(fail_file)
            fail_uri = self.feature_repo.get_logical_uri(fail_file)
            fail_df = self._load_dataframe(fail_file)
        except FeatureInputNotFoundError:
            # Fallback when failure events are embedded in observation dataset
            fail_file = obs_file
            fail_sha256 = obs_sha256
            fail_uri = obs_uri
            fail_df = pd.DataFrame()

        # 4. Resolve Feature Schema & Label Schema from files
        feature_schema = self.feature_schema_provider.get_feature_schema(
            schema_version=request.feature_schema_version,
        )
        feature_schema_sha256 = feature_schema.compute_checksum()
        feature_schema_uri = self.feature_repo.get_logical_uri(feature_schema.schema_file_path) if feature_schema.schema_file_path else f"schemas/features/{request.feature_schema_version}.json"

        label_schema = self.label_schema_provider.get_label_schema(
            schema_version=request.label_schema_version,
            requested_horizon_hours=request.prediction_horizon_hours,
        )
        label_schema_sha256 = label_schema.compute_checksum()
        label_schema_uri = self.feature_repo.get_logical_uri(label_schema.schema_file_path) if label_schema.schema_file_path else f"schemas/labels/{request.label_schema_version}.json"

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

        # 7. Prepare Canonical Working DataFrame
        plan_id_col = plan.get("id_column")
        plan_time_col = plan.get("time_column")
        working_df, id_col, time_col = self._prepare_canonical_working_df(
            obs_df=obs_df,
            id_col=plan_id_col,
            time_col=plan_time_col,
        )

        # 8. Compute Features & Missing Masks
        computed_features_df, missing_drop_mask = self._compute_features_and_missing_masks(
            working_df=working_df,
            feature_items=feature_schema.features,
            id_col=id_col,
        )

        # 9. Compute Labels & Active Failure Drop Mask
        labels_series, active_failure_drop_mask = self._generate_labels_and_exclusion_mask(
            working_df=working_df,
            fail_df=fail_df,
            label_schema=label_schema,
            id_col=id_col,
            time_col=time_col,
        )

        # 10. Align Surviving Rows across Features, Labels, and Row Metadata
        combined_drop_mask = missing_drop_mask | active_failure_drop_mask
        keep_mask = ~combined_drop_mask

        surviving_features_df = computed_features_df[keep_mask].copy()
        surviving_labels_series = labels_series[keep_mask].copy()
        surviving_working_df = working_df[keep_mask].copy()

        ordered_feature_names = feature_schema.feature_names
        features_matrix = surviving_features_df[ordered_feature_names].to_numpy(dtype=np.float64)
        labels_array = surviving_labels_series.to_numpy(dtype=np.int64)

        surviving_count = len(surviving_working_df)
        if features_matrix.shape[0] != surviving_count or labels_array.shape[0] != surviving_count:
            raise FeatureLabelAlignmentError("Feature matrix, Labels, row_metadata 행 정렬에 실패했습니다.")

        if surviving_count == 0:
            raise InsufficientTrainingDataError("모든 행이 제외 또는 결측치 처리되어 유효한 학습 데이터가 0행입니다.")

        # Build row metadata
        row_metadata = []
        for idx in range(surviving_count):
            asset_val = str(surviving_working_df[id_col].iloc[idx]) if (id_col and id_col in surviving_working_df.columns) else f"row_{idx}"
            time_val = str(surviving_working_df[time_col].iloc[idx]) if (time_col and time_col in surviving_working_df.columns) else f"t_{idx}"
            row_metadata.append({"asset_id": asset_val, "timestamp": time_val})

        # 11. Build Complete Provenance Metadata
        provenance_meta = {
            "observation_dataset_id": request.dataset_id,
            "observation_dataset_version": request.dataset_version,
            "observation_dataset_sha256": obs_sha256,
            "observation_dataset_uri": obs_uri,
            "failure_dataset_id": request.failure_dataset_id,
            "failure_dataset_version": request.failure_dataset_version,
            "failure_dataset_sha256": fail_sha256,
            "failure_dataset_uri": fail_uri,
            "preprocessing_plan_id": request.preprocessing_plan_id,
            "preprocessing_plan_version": request.preprocessing_plan_version,
            "preprocessing_plan_sha256": plan_sha256,
            "preprocessing_plan_uri": plan_uri,
            "feature_schema_version": request.feature_schema_version,
            "feature_schema_sha256": feature_schema_sha256,
            "feature_schema_uri": feature_schema_uri,
            "label_schema_version": request.label_schema_version,
            "label_schema_sha256": label_schema_sha256,
            "label_schema_uri": label_schema_uri,
            "prediction_horizon_hours": request.prediction_horizon_hours,
            "feature_engine_version": "1.0",
        }

        # 12. Publish Bundle Atomically
        published = self.feature_repo.publish_bundle(
            dataset_id=request.dataset_id,
            dataset_version=request.dataset_version,
            feature_dataset_version=feature_dataset_version,
            features=features_matrix,
            labels=labels_array,
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
