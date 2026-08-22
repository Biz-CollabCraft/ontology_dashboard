"""Feature and Label generation service orchestrating the 15-step pipeline."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from systems.generator.generator_config import PATHS
from systems.generator.file_integrity import compute_file_sha256
from systems.generator.ontology_mapping.mapping_cache import MappingStore, MappingRecord
from systems.generator.feature.feature_builder import build_features
from systems.generator.feature.feature_catalog import load_catalog
from systems.generator.feature.feature_label_service import build_labels
from systems.generator.app.preprocessing.preprocessing_profiler import load_family_registry
from systems.generator.app.preprocessing.preprocessing_service import _is_within_allowed_root
from systems.generator.app.preprocessing.preprocessing_repository import PreprocessingRepository
from systems.generator.app.preprocessing.preprocessing_exception import (
    DatasetNotFoundError,
    DatasetContractError,
    PreprocessingError,
)

from systems.generator.app.feature.feature_exception import (
    FeatureInputNotFoundError,
    FeatureContractError,
    FeatureSchemaMismatchError,
    FeatureLabelAlignmentError,
    FeatureDatasetIntegrityError,
    FeaturePublishConflictError,
    InsufficientTrainingDataError,
)
from systems.generator.app.feature.feature_schema import (
    FeatureRequest,
    FeatureResponse,
    FeatureOutputsPayload,
)
from systems.generator.app.feature.feature_schema_provider import FeatureSchemaProvider
from systems.generator.app.feature.label_schema_provider import LabelSchemaProvider
from systems.generator.app.feature.feature_repository import FeatureRepository

logger = logging.getLogger(__name__)

CATALOG_VERSION = "2026.08-feature-catalog-v1"
CODE_REVISION = "2026.08-fastapi-feature-v1"


class FeatureService:
    """Orchestrates end-to-end Feature and Label engineering and publishes immutable Feature Dataset Bundles."""

    def __init__(
        self,
        feature_repo: Optional[FeatureRepository] = None,
        preprocessing_repo: Optional[PreprocessingRepository] = None,
        feature_schema_provider: Optional[FeatureSchemaProvider] = None,
        label_schema_provider: Optional[LabelSchemaProvider] = None,
    ) -> None:
        self.feature_repo = feature_repo or FeatureRepository()
        self.preprocessing_repo = preprocessing_repo or PreprocessingRepository()
        self.feature_schema_provider = feature_schema_provider or FeatureSchemaProvider()
        self.label_schema_provider = label_schema_provider or LabelSchemaProvider()

    def _resolve_observation_dataset(
        self,
        dataset_id: str,
        dataset_version: str,
    ) -> tuple[pd.DataFrame, Path, str]:
        """Resolve, validate, and load observation dataset, returning (df, path, sha256)."""
        allowed_roots = [PATHS.data_dir.resolve(), PATHS.data_preprocessed.resolve()]

        candidates: list[Path] = [
            PATHS.data_dir / dataset_id / f"{dataset_version}.csv",
            PATHS.data_dir / dataset_id / f"{dataset_version}.xlsx",
            PATHS.data_dir / dataset_id / f"{dataset_version}.xls",
            PATHS.data_preprocessed / dataset_id / f"{dataset_version}.csv",
            PATHS.data_preprocessed / dataset_id / f"{dataset_version}.xlsx",
            PATHS.data_preprocessed / dataset_id / f"{dataset_version}.xls",
            PATHS.data_dir / f"{dataset_id}_{dataset_version}.csv",
            PATHS.data_preprocessed / f"{dataset_id}_{dataset_version}.csv",
            PATHS.data_dir / f"{dataset_id}.csv",
            PATHS.data_preprocessed / f"{dataset_id}.csv",
            PATHS.data_dir / dataset_id / "input.csv",
            PATHS.data_preprocessed / dataset_id / "input.csv",
        ]

        found_path: Optional[Path] = None
        for cand in candidates:
            resolved = cand.resolve()
            if _is_within_allowed_root(resolved, allowed_roots) and resolved.is_file():
                found_path = resolved
                break

        if not found_path or not found_path.is_file():
            raise FeatureInputNotFoundError(
                f"요청한 Observation 데이터셋 '{dataset_id}' (버전 '{dataset_version}')을 허용된 데이터 루트에서 찾을 수 없습니다."
            )

        try:
            if found_path.suffix.lower() in (".xlsx", ".xls"):
                df = pd.read_excel(found_path)
            else:
                df = pd.read_csv(found_path)
        except Exception as exc:
            raise FeatureInputNotFoundError(f"Observation 데이터셋 파일({found_path}) 로드 실패: {exc}") from exc

        if df.empty:
            raise FeatureContractError(f"Observation 데이터셋 '{dataset_id}'이 비어 있습니다.")

        sha256 = compute_file_sha256(found_path)
        return df, found_path, sha256

    def _resolve_failure_dataset(
        self,
        failure_dataset_id: str,
        failure_dataset_version: str,
        telemetry_df: pd.DataFrame,
        plan: dict[str, Any] | None = None,
    ) -> tuple[pd.DataFrame, Path, str, dict[str, Any]]:
        """Resolve, validate, and load failure dataset, returning (df, path, sha256, meta)."""
        allowed_roots = [PATHS.data_dir.resolve(), PATHS.data_preprocessed.resolve()]

        candidates: list[Path] = [
            PATHS.data_dir / failure_dataset_id / f"{failure_dataset_version}.csv",
            PATHS.data_dir / failure_dataset_id / f"{failure_dataset_version}.xlsx",
            PATHS.data_dir / failure_dataset_id / f"{failure_dataset_version}.xls",
            PATHS.data_preprocessed / failure_dataset_id / f"{failure_dataset_version}.csv",
            PATHS.data_preprocessed / failure_dataset_id / f"{failure_dataset_version}.xlsx",
            PATHS.data_preprocessed / failure_dataset_id / f"{failure_dataset_version}.xls",
            PATHS.data_dir / f"{failure_dataset_id}_{failure_dataset_version}.csv",
            PATHS.data_preprocessed / f"{failure_dataset_id}_{failure_dataset_version}.csv",
            PATHS.data_dir / f"{failure_dataset_id}.csv",
            PATHS.data_preprocessed / f"{failure_dataset_id}.csv",
            PATHS.data_dir / failure_dataset_id / "input.csv",
            PATHS.data_preprocessed / failure_dataset_id / "input.csv",
        ]

        found_path: Optional[Path] = None
        for cand in candidates:
            resolved = cand.resolve()
            if _is_within_allowed_root(resolved, allowed_roots) and resolved.is_file():
                found_path = resolved
                break

        meta: dict[str, Any] = {}
        if not found_path:
            # Check family registry for exact failure dataset key
            registry = load_family_registry()
            if failure_dataset_id in registry:
                meta = registry.get(failure_dataset_id, {})
                for root in allowed_roots:
                    cand = (root / failure_dataset_id).resolve()
                    if _is_within_allowed_root(cand, allowed_roots) and cand.is_file():
                        found_path = cand
                        break

        if not found_path or not found_path.is_file():
            raise FeatureInputNotFoundError(
                f"요청한 Failure 데이터셋 '{failure_dataset_id}' (버전 '{failure_dataset_version}')을 허용된 데이터 루트에서 찾을 수 없습니다."
            )

        try:
            if found_path.suffix.lower() in (".xlsx", ".xls"):
                f_df = pd.read_excel(found_path)
            else:
                f_df = pd.read_csv(found_path)
        except Exception as exc:
            raise FeatureInputNotFoundError(f"Failure 데이터셋 파일({found_path}) 로드 실패: {exc}") from exc

        if f_df.empty:
            raise FeatureContractError(f"Failure 데이터셋 '{failure_dataset_id}'이 비어 있습니다.")

        # Identify Failure ID column
        fail_id_col = None
        if plan and isinstance(plan, dict):
            fail_id_col = plan.get("id_column")
        if not fail_id_col or fail_id_col not in f_df.columns:
            for candidate in ("asset_id", "machineID", "equipment_id", "machine_id", "device_id", "UDI", "Product ID", "id"):
                if candidate in f_df.columns:
                    fail_id_col = candidate
                    break

        if not fail_id_col or fail_id_col not in f_df.columns:
            raise FeatureLabelAlignmentError(
                f"Failure 데이터셋에서 설비 ID 컬럼을 찾을 수 없습니다 (사용 가능한 컬럼: {list(f_df.columns)})."
            )

        # Identify Failure anchor column
        time_cols_meta = meta.get("time_columns", [])
        anchor_col = next((c["name"] for c in time_cols_meta if c.get("semantic") == "failure_point"), None)
        if not anchor_col or anchor_col not in f_df.columns:
            for candidate in ("observed_at", "datetime", "timestamp", "time", "ts", "date", "failure_point"):
                if candidate in f_df.columns:
                    anchor_col = candidate
                    break

        if not anchor_col or anchor_col not in f_df.columns:
            raise FeatureLabelAlignmentError(
                f"Failure 데이터셋에서 anchor(failure_point) 컬럼을 찾을 수 없습니다 (사용 가능한 컬럼: {list(f_df.columns)})."
            )

        # Verify equipment identifier compatibility with telemetry data
        telem_id_col = plan.get("id_column") if plan and isinstance(plan, dict) else None
        if not telem_id_col or telem_id_col not in telemetry_df.columns:
            for candidate in ("asset_id", "machineID", "equipment_id", "machine_id", "device_id", "UDI", "Product ID", "id"):
                if candidate in telemetry_df.columns:
                    telem_id_col = candidate
                    break

        if telem_id_col and telem_id_col in telemetry_df.columns:
            telem_assets = set(telemetry_df[telem_id_col].dropna().astype(str))
            fail_assets = set(f_df[fail_id_col].dropna().astype(str))
            if telem_assets and fail_assets and not telem_assets.intersection(fail_assets):
                raise FeatureLabelAlignmentError(
                    f"Telemetry 데이터셋과 Failure 데이터셋의 설비 식별 체계(Asset IDs)가 호환되지 않습니다. "
                    f"(Telemetry: {list(telem_assets)[:3]}, Failure: {list(fail_assets)[:3]})"
                )

        sha256 = compute_file_sha256(found_path)
        return f_df, found_path, sha256, meta

    def _resolve_preprocessing_plan(
        self,
        dataset_id: str,
        dataset_version: str,
        plan_version: str,
    ) -> tuple[dict[str, Any], str, str]:
        """Resolve and strictly validate Preprocessing Plan, returning (plan_dict, uri, sha256)."""
        try:
            plan = self.preprocessing_repo.load_plan(dataset_id, dataset_version, plan_version)
        except DatasetNotFoundError as exc:
            raise FeatureInputNotFoundError(str(exc)) from exc
        except (DatasetContractError, PreprocessingError, Exception) as exc:
            raise FeatureContractError(f"Preprocessing Plan 계약 검증 실패: {exc}") from exc

        # Resolve exact path and checksum
        plan_path = self.preprocessing_repo.get_plan_path(dataset_id, dataset_version)
        if not plan_path.is_file():
            alt_path = self.preprocessing_repo.base_dir / f"{plan_version}.json"
            if alt_path.is_file():
                plan_path = alt_path

        sha256 = compute_file_sha256(plan_path)
        try:
            repo_root = PATHS.models_store.parent
            uri = str(plan_path.relative_to(repo_root).as_posix())
        except Exception:
            uri = f"models_store/cache/preprocessing_plans/{plan_path.name}"

        return plan, uri, sha256

    def _resolve_ontology_mapping(
        self,
        mapping_version: str,
        dataset_id: Optional[str] = None,
        dataset_version: Optional[str] = None,
    ) -> tuple[MappingStore, str, str]:
        """Resolve and strictly validate Ontology Mapping without silent dummy fallbacks."""
        candidates: list[Path] = [
            PATHS.models_store / "cache" / "mappings" / f"{mapping_version}.json",
        ]
        if dataset_id and dataset_version:
            candidates.append(PATHS.models_store / "cache" / "mappings" / dataset_id / dataset_version / f"{mapping_version}.json")

        mapping_file: Optional[Path] = None
        for cand in candidates:
            if cand.is_file():
                mapping_file = cand
                break

        if not mapping_file:
            # Check legacy cache file
            legacy_file = PATHS.models_store / "cache" / "ontology_mappings.json"
            if legacy_file.is_file():
                try:
                    with open(legacy_file, "r", encoding="utf-8") as f:
                        legacy_data = json.load(f)
                    file_ver = legacy_data.get("mapping_version")
                    if file_ver and file_ver == mapping_version:
                        mapping_file = legacy_file
                    else:
                        raise FeatureContractError(
                            f"Legacy mapping 파일의 version('{file_ver}')이 요청된 mapping_version('{mapping_version}')과 일치하지 않습니다."
                        )
                except FeatureContractError:
                    raise
                except Exception as exc:
                    raise FeatureContractError(f"Legacy mapping 파일 파싱 실패: {exc}") from exc

        if not mapping_file or not mapping_file.is_file():
            raise FeatureInputNotFoundError(
                f"요청한 Ontology Mapping 파일을 찾을 수 없습니다: mapping_version='{mapping_version}'"
            )

        try:
            with open(mapping_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            raise FeatureContractError(f"Ontology Mapping 파일 파싱 실패 ({mapping_file.name}): {exc}") from exc

        if not isinstance(data, dict):
            raise FeatureContractError(f"Ontology Mapping 형식이 올바르지 않습니다 (dict 기대, {type(data).__name__} 수신)")

        # Verify version if specified inside JSON
        file_ver = data.get("mapping_version")
        if file_ver and file_ver != mapping_version:
            raise FeatureContractError(
                f"Mapping 파일 내부 version ('{file_ver}')이 요청된 mapping_version ('{mapping_version}')과 일치하지 않습니다."
            )

        mapping_store = MappingStore()
        items_to_parse = data.get("mappings", data) if isinstance(data.get("mappings"), dict) else data
        item_count = 0
        for k, v in items_to_parse.items():
            if k in ("mapping_version", "dataset_id", "dataset_version", "created_at", "fingerprint"):
                continue
            if isinstance(v, str):
                mapping_store.add_mapping(MappingRecord(
                    source_field=k,
                    target_ontology=v,
                    source="inferred",
                    confidence=1.0,
                    status="confirmed",
                ))
                item_count += 1
            elif isinstance(v, dict):
                mapping_store.add_mapping(MappingRecord(source_field=k, **v))
                item_count += 1

        if item_count == 0:
            raise FeatureContractError(f"Ontology Mapping 항목이 0개입니다: '{mapping_version}'")

        sha256 = compute_file_sha256(mapping_file)
        try:
            repo_root = PATHS.models_store.parent
            uri = str(mapping_file.relative_to(repo_root).as_posix())
        except Exception:
            uri = f"models_store/cache/mappings/{mapping_file.name}"

        return mapping_store, uri, sha256

    def run_feature_pipeline(
        self,
        request: FeatureRequest,
        request_id: Optional[str] = None,
    ) -> FeatureResponse:
        """Execute full feature & label generation workflow and atomically publish Feature Dataset Bundle."""
        req_id = request_id or f"req-{uuid.uuid4().hex[:12]}"
        run_id = f"feature-{uuid.uuid4().hex[:12]}"
        created_at = datetime.now(timezone.utc).isoformat()

        logger.info(
            f"[FeatureService] Starting feature pipeline: dataset={request.dataset_id}:{request.dataset_version}, "
            f"failure={request.failure_dataset_id}:{request.failure_dataset_version}, run_id={run_id}"
        )

        # 1. Resolve Preprocessing Plan (fail-fast on version or contract mismatch)
        plan, plan_uri, plan_sha256 = self._resolve_preprocessing_plan(
            request.dataset_id,
            request.dataset_version,
            request.preprocessing_plan_version,
        )

        # 2. Resolve Observation Dataset
        telemetry_df, obs_path, obs_sha256 = self._resolve_observation_dataset(
            request.dataset_id,
            request.dataset_version,
        )

        # Early check for valid ID and timestamp columns in Observation dataset
        id_candidate = plan.get("id_column") if plan and isinstance(plan, dict) else None
        if not id_candidate or id_candidate not in telemetry_df.columns:
            for cand in ("asset_id", "machineID", "equipment_id", "machine_id", "device_id", "UDI", "Product ID", "id"):
                if cand in telemetry_df.columns:
                    id_candidate = cand
                    break

        time_candidate = plan.get("time_column") if plan and isinstance(plan, dict) else None
        if not time_candidate or time_candidate not in telemetry_df.columns:
            for cand in ("observed_at", "datetime", "timestamp", "time", "ts", "date"):
                if cand in telemetry_df.columns:
                    time_candidate = cand
                    break

        if not id_candidate or id_candidate not in telemetry_df.columns:
            raise FeatureLabelAlignmentError(
                f"설비 ID 컬럼을 확정할 수 없습니다. (사용 가능한 컬럼: {list(telemetry_df.columns)})"
            )
        if not time_candidate or time_candidate not in telemetry_df.columns:
            raise FeatureLabelAlignmentError(
                f"타임스탬프 컬럼을 확정할 수 없습니다. (사용 가능한 컬럼: {list(telemetry_df.columns)})"
            )

        id_series_str = telemetry_df[id_candidate].astype(str).str.strip()
        time_series_str = telemetry_df[time_candidate].astype(str).str.strip()
        if (id_series_str == "").all() or id_series_str.isna().all():
            raise FeatureLabelAlignmentError(f"Observation 데이터셋의 설비 ID({id_candidate}) 값이 전부 비어 있습니다.")
        if (time_series_str == "").all() or time_series_str.isna().all():
            raise FeatureLabelAlignmentError(f"Observation 데이터셋의 타임스탬프({time_candidate}) 값이 전부 비어 있습니다.")

        # 3. Resolve Failure Dataset & validate alignment
        failures_df, fail_path, fail_sha256, failure_meta = self._resolve_failure_dataset(
            request.failure_dataset_id,
            request.failure_dataset_version,
            telemetry_df=telemetry_df,
            plan=plan,
        )

        # 4. Resolve Ontology Mapping (fail-fast on missing/corrupted/mismatched version)
        mapping_store, mapping_uri, mapping_sha256 = self._resolve_ontology_mapping(
            request.mapping_version,
            dataset_id=request.dataset_id,
            dataset_version=request.dataset_version,
        )

        # 5. Resolve and validate Feature & Label Schemas
        feature_schema_def = self.feature_schema_provider.get_schema(request.feature_schema_version)
        label_schema_def = self.label_schema_provider.validate_label_schema(
            request.label_schema_version,
            request.prediction_horizon_hours,
        )

        # 6. Compute deterministic Feature Dataset Version
        repo_root = PATHS.models_store.parent
        try:
            obs_logical_uri = str(obs_path.relative_to(repo_root).as_posix())
        except Exception:
            obs_logical_uri = f"data/{obs_path.name}"

        try:
            fail_logical_uri = str(fail_path.relative_to(repo_root).as_posix())
        except Exception:
            fail_logical_uri = f"data/{fail_path.name}"

        inputs_metadata = {
            "dataset_id": request.dataset_id,
            "dataset_version": request.dataset_version,
            "dataset_uri": obs_logical_uri,
            "dataset_checksum": obs_sha256,
            "dataset_provider": "local_file_adapter",
            "dataset_version_verified": False,
            "failure_dataset_id": request.failure_dataset_id,
            "failure_dataset_version": request.failure_dataset_version,
            "failure_dataset_uri": fail_logical_uri,
            "failure_dataset_checksum": fail_sha256,
            "failure_dataset_provider": "local_file_adapter",
            "failure_dataset_version_verified": False,
            "preprocessing_plan_version": request.preprocessing_plan_version,
            "preprocessing_plan_uri": plan_uri,
            "preprocessing_plan_checksum": plan_sha256,
            "mapping_version": request.mapping_version,
            "mapping_uri": mapping_uri,
            "mapping_checksum": mapping_sha256,
            "feature_schema_version": request.feature_schema_version,
            "feature_schema_checksum": feature_schema_def.compute_checksum(),
            "label_schema_version": request.label_schema_version,
            "label_schema_checksum": label_schema_def.compute_checksum(),
        }

        prediction_contract = {
            "prediction_horizon_hours": request.prediction_horizon_hours,
            "feature_catalog_version": CATALOG_VERSION,
            "code_revision": CODE_REVISION,
        }

        feature_dataset_version = self.compute_feature_dataset_version(inputs_metadata, prediction_contract)
        logger.info(f"[FeatureService] Computed deterministic feature_dataset_version: {feature_dataset_version}")

        # 7. Check if immutable bundle already exists (rebuild_npy=False reuse optimization)
        if not request.rebuild_npy:
            existing_meta = self.feature_repo.find_feature_bundle(
                dataset_id=request.dataset_id,
                dataset_version=request.dataset_version,
                feature_dataset_version=feature_dataset_version,
                expected_inputs=inputs_metadata,
                expected_horizon=request.prediction_horizon_hours,
            )
            if existing_meta:
                logger.info(f"[FeatureService] Deterministic bundle '{feature_dataset_version}' exists and verified. Reusing.")
                uris = self.feature_repo._build_logical_uris(
                    request.dataset_id,
                    request.dataset_version,
                    feature_dataset_version,
                )
                return FeatureResponse(
                    request_id=req_id,
                    run_id=run_id,
                    status="succeeded",
                    dataset_id=request.dataset_id,
                    dataset_version=request.dataset_version,
                    failure_dataset_id=request.failure_dataset_id,
                    failure_dataset_version=request.failure_dataset_version,
                    preprocessing_plan_version=request.preprocessing_plan_version,
                    mapping_version=request.mapping_version,
                    feature_schema_version=request.feature_schema_version,
                    label_schema_version=request.label_schema_version,
                    outputs=FeatureOutputsPayload(
                        feature_dataset_version=feature_dataset_version,
                        row_count=existing_meta["shape"]["row_count"],
                        feature_count=existing_meta["shape"]["feature_count"],
                        features_uri=uris["features_uri"],
                        labels_uri=uris["labels_uri"],
                        metadata_uri=uris["metadata_uri"],
                    ),
                )

        # 8. Execute Feature Construction
        catalog = load_catalog()
        features_df = build_features(
            telemetry_df,
            store=mapping_store,
            catalog=catalog,
            plan=plan,
            single_asset=False,
        )

        if features_df.empty:
            raise InsufficientTrainingDataError("Feature 생성 결과 DataFrame이 비어 있습니다.")

        # 9. Execute Label Construction
        labeled_df = build_labels(
            features_df,
            failures_df,
            failure_meta=failure_meta,
            prediction_horizon_hours=request.prediction_horizon_hours,
            plan=plan,
        )

        if labeled_df.empty:
            raise InsufficientTrainingDataError("Label 생성 후 유효한 데이터 행이 0건입니다.")

        # 10. Apply Feature Schema allowlist & extract numeric X matrix
        feature_names, X_df = self.feature_schema_provider.validate_and_filter_features(
            request.feature_schema_version,
            labeled_df,
            plan=plan,
        )

        X = X_df.to_numpy(dtype=np.float64)
        y = labeled_df["label"].to_numpy(dtype=np.int64)

        if X.shape[0] == 0:
            raise InsufficientTrainingDataError("학습에 유효한 데이터 행이 0건입니다.")

        if not np.isfinite(X).all():
            raise FeatureContractError("Feature 행렬에 NaN 또는 Inf 값이 포함되어 있습니다.")
        if not np.isfinite(y).all():
            raise FeatureContractError("Label 배열에 NaN 또는 Inf 값이 포함되어 있습니다.")
        if not set(np.unique(y)).issubset({0, 1}):
            raise FeatureLabelAlignmentError(f"Label 값이 {{0, 1}} 범위를 벗어납니다: {set(np.unique(y))}")

        # 11. Extract row_metadata (asset_id, timestamp) for tracking with fail-fast
        id_col = plan.get("id_column") if plan and isinstance(plan, dict) else None
        if not id_col or id_col not in labeled_df.columns:
            for cand in ("asset_id", "machineID", "equipment_id", "machine_id", "device_id", "UDI", "Product ID", "id"):
                if cand in labeled_df.columns:
                    id_col = cand
                    break

        time_col = plan.get("time_column") if plan and isinstance(plan, dict) else None
        if not time_col or time_col not in labeled_df.columns:
            for cand in ("observed_at", "datetime", "timestamp", "time", "ts", "date"):
                if cand in labeled_df.columns:
                    time_col = cand
                    break

        if not id_col or id_col not in labeled_df.columns:
            raise FeatureLabelAlignmentError(
                f"Row metadata 작성을 위한 설비 ID 컬럼을 확정할 수 없습니다. (사용 가능한 컬럼: {list(labeled_df.columns)})"
            )
        if not time_col or time_col not in labeled_df.columns:
            raise FeatureLabelAlignmentError(
                f"Row metadata 작성을 위한 타임스탬프 컬럼을 확정할 수 없습니다. (사용 가능한 컬럼: {list(labeled_df.columns)})"
            )

        row_metadata: list[dict[str, Any]] = []
        for idx, (_, row) in enumerate(labeled_df.iterrows()):
            asset_val = str(row[id_col]).strip() if pd.notna(row[id_col]) else ""
            time_val = str(row[time_col]).strip() if pd.notna(row[time_col]) else ""
            if not asset_val:
                raise FeatureLabelAlignmentError(f"Row {idx}: 설비 ID(asset_id) 값이 비어 있습니다.")
            if not time_val:
                raise FeatureLabelAlignmentError(f"Row {idx}: 타임스탬프(timestamp) 값이 비어 있습니다.")

            row_metadata.append({
                "row_index": idx,
                "asset_id": asset_val,
                "timestamp": time_val,
            })

        if not (X.shape[0] == y.shape[0] == len(row_metadata)):
            raise FeatureLabelAlignmentError(
                f"데이터 행 수 불일치: X={X.shape[0]}, y={y.shape[0]}, row_metadata={len(row_metadata)}"
            )

        # 12. Publish Feature Dataset Bundle atomically
        uris = self.feature_repo.publish_feature_bundle(
            dataset_id=request.dataset_id,
            dataset_version=request.dataset_version,
            feature_dataset_version=feature_dataset_version,
            X=X,
            y=y,
            feature_names=feature_names,
            row_metadata=row_metadata,
            inputs_metadata=inputs_metadata,
            prediction_contract=prediction_contract,
            run_id=run_id,
            created_at=created_at,
        )

        return FeatureResponse(
            request_id=req_id,
            run_id=run_id,
            status="succeeded",
            dataset_id=request.dataset_id,
            dataset_version=request.dataset_version,
            failure_dataset_id=request.failure_dataset_id,
            failure_dataset_version=request.failure_dataset_version,
            preprocessing_plan_version=request.preprocessing_plan_version,
            mapping_version=request.mapping_version,
            feature_schema_version=request.feature_schema_version,
            label_schema_version=request.label_schema_version,
            outputs=FeatureOutputsPayload(
                feature_dataset_version=feature_dataset_version,
                row_count=int(X.shape[0]),
                feature_count=int(X.shape[1]),
                features_uri=uris["features_uri"],
                labels_uri=uris["labels_uri"],
                metadata_uri=uris["metadata_uri"],
            ),
        )

    def compute_feature_dataset_version(
        self,
        inputs: dict[str, Any],
        prediction_contract: dict[str, Any],
    ) -> str:
        """Compute 16-character deterministic sha256 hash representing unique immutable Feature Dataset."""
        import hashlib

        canonical_dict = {
            "dataset_id": inputs["dataset_id"],
            "dataset_version": inputs["dataset_version"],
            "dataset_checksum": inputs["dataset_checksum"],
            "failure_dataset_id": inputs["failure_dataset_id"],
            "failure_dataset_version": inputs["failure_dataset_version"],
            "failure_dataset_checksum": inputs["failure_dataset_checksum"],
            "preprocessing_plan_version": inputs["preprocessing_plan_version"],
            "preprocessing_plan_checksum": inputs["preprocessing_plan_checksum"],
            "mapping_version": inputs["mapping_version"],
            "mapping_checksum": inputs["mapping_checksum"],
            "feature_schema_version": inputs["feature_schema_version"],
            "feature_schema_checksum": inputs["feature_schema_checksum"],
            "label_schema_version": inputs["label_schema_version"],
            "label_schema_checksum": inputs["label_schema_checksum"],
            "prediction_horizon_hours": prediction_contract["prediction_horizon_hours"],
            "feature_catalog_version": prediction_contract["feature_catalog_version"],
            "code_revision": prediction_contract["code_revision"],
        }
        canonical_json = json.dumps(canonical_dict, sort_keys=True, ensure_ascii=False)
        full_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        return f"feature-dataset-{full_hash[:16]}"
