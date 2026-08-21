"""Feature domain service orchestrating input resolution, feature/label construction, allowlisting, and bundle publishing."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import numpy as np
import pandas as pd

from systems.generator.generator_config import PATHS
from systems.generator.feature.feature_builder import build_features
from systems.generator.feature.feature_label_service import build_labels
from systems.generator.feature.feature_catalog import load_catalog
from systems.generator.ontology_mapping.mapping_cache import MappingStore
from systems.generator.app.preprocessing.preprocessing_repository import PreprocessingRepository
from systems.generator.app.preprocessing.preprocessing_profiler import load_family_registry
from systems.generator.app.feature.feature_exception import (
    FeatureError,
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
from systems.generator.app.feature.feature_repository import FeatureRepository, compute_file_sha256
from systems.generator.app.feature.feature_schema_provider import FeatureSchemaProvider
from systems.generator.app.feature.label_schema_provider import LabelSchemaProvider

logger = logging.getLogger(__name__)


def _is_within_allowed_root(path: Path, allowed_roots: list[Path]) -> bool:
    """Check if the resolved path is strictly within any of the allowed root directories."""
    resolved_path = path.resolve()
    for root in allowed_roots:
        try:
            resolved_path.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


class FeatureService:
    """Orchestrates Feature generation, validation, and immutable bundle publishing."""

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
        """Resolve and load telemetry observation dataset, returning (df, path, sha256)."""
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
            PATHS.data_dir / dataset_id,
            PATHS.data_preprocessed / dataset_id,
        ]

        found_path: Optional[Path] = None
        for cand in candidates:
            resolved = cand.resolve()
            if not _is_within_allowed_root(resolved, allowed_roots):
                continue
            if resolved.is_file():
                found_path = resolved
                break
            if resolved.is_dir():
                for child in sorted(resolved.iterdir()):
                    resolved_child = child.resolve()
                    if _is_within_allowed_root(resolved_child, allowed_roots) and resolved_child.is_file():
                        if resolved_child.suffix.lower() in (".csv", ".xlsx", ".xls"):
                            found_path = resolved_child
                            break
                if found_path:
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
        """Resolve and load Preprocessing Plan, returning (plan_dict, uri, sha256)."""
        plan = self.preprocessing_repo.find_plan(dataset_id, dataset_version)
        plan_path = self.preprocessing_repo.get_plan_path(dataset_id, dataset_version)

        if not plan or not plan_path.is_file():
            # Fallback check by raw version string if cached differently
            plan_path = self.preprocessing_repo.base_dir / f"{plan_version}.json"
            if plan_path.is_file():
                try:
                    with open(plan_path, "r", encoding="utf-8") as f:
                        plan = json.load(f)
                except Exception:
                    plan = None

        if not plan or not plan_path.is_file():
            raise FeatureInputNotFoundError(
                f"요청한 Preprocessing Plan을 찾을 수 없습니다: version='{plan_version}' (dataset='{dataset_id}:{dataset_version}')"
            )

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
    ) -> tuple[MappingStore, str, str]:
        """Resolve and load Ontology Mapping, returning (mapping_store, uri, sha256)."""
        from systems.generator.ontology_mapping.mapping_cache import MappingRecord

        mapping_store = MappingStore()
        mapping_file = PATHS.models_store / "cache" / "mappings" / f"{mapping_version}.json"

        if mapping_file.is_file():
            try:
                with open(mapping_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for k, v in data.items():
                    if isinstance(v, str):
                        mapping_store.add_mapping(MappingRecord(
                            source_field=k,
                            target_ontology=v,
                            source="inferred",
                            confidence=1.0,
                            status="confirmed",
                        ))
                    elif isinstance(v, dict):
                        mapping_store.add_mapping(MappingRecord(source_field=k, **v))
                sha256 = compute_file_sha256(mapping_file)
                repo_root = PATHS.models_store.parent
                uri = str(mapping_file.relative_to(repo_root).as_posix())
                return mapping_store, uri, sha256
            except Exception as exc:
                logger.warning(f"[FeatureService] Failed to load mapping from {mapping_file}: {exc}")

        # Fallback to in-memory / legacy mapping cache file
        legacy_file = PATHS.models_store / "cache" / "ontology_mappings.json"
        if legacy_file.is_file():
            sha256 = compute_file_sha256(legacy_file)
            uri = "models_store/cache/ontology_mappings.json"
            return mapping_store, uri, sha256

        # Deterministic dummy hash if no disk file exists
        dummy_content = f"ontology-mapping-{mapping_version}".encode("utf-8")
        sha256 = hashlib.sha256(dummy_content).hexdigest()
        uri = f"models_store/cache/mappings/{mapping_version}.json"
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

        # 1. Resolve Preprocessing Plan
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

        # 3. Resolve Failure Dataset
        failures_df, fail_path, fail_sha256, failure_meta = self._resolve_failure_dataset(
            request.failure_dataset_id,
            request.failure_dataset_version,
            telemetry_df=telemetry_df,
            plan=plan,
        )

        # 4. Resolve Ontology Mapping
        mapping_store, map_uri, map_sha256 = self._resolve_ontology_mapping(
            request.mapping_version,
        )

        # 5. Resolve and validate Feature Schema & Label Schema definitions
        feat_schema_def = self.feature_schema_provider.get_schema(request.feature_schema_version)
        feat_schema_sha256 = feat_schema_def.compute_checksum()

        label_schema_def = self.label_schema_provider.validate_label_schema(
            request.label_schema_version,
            requested_horizon_hours=request.prediction_horizon_hours,
        )
        label_schema_sha256 = label_schema_def.compute_checksum()

        # 6. Build canonical inputs metadata and deterministic version
        inputs_metadata = {
            "dataset_id": request.dataset_id,
            "dataset_version": request.dataset_version,
            "dataset_checksum": obs_sha256,
            "failure_dataset_id": request.failure_dataset_id,
            "failure_dataset_version": request.failure_dataset_version,
            "failure_dataset_checksum": fail_sha256,
            "preprocessing_plan_version": request.preprocessing_plan_version,
            "preprocessing_plan_checksum": plan_sha256,
            "mapping_version": request.mapping_version,
            "mapping_checksum": map_sha256,
            "feature_schema_version": request.feature_schema_version,
            "feature_schema_checksum": feat_schema_sha256,
            "label_schema_version": request.label_schema_version,
            "label_schema_checksum": label_schema_sha256,
        }

        prediction_contract = {
            "prediction_horizon_hours": request.prediction_horizon_hours,
        }

        canonical_manifest = {
            **inputs_metadata,
            **prediction_contract,
            "feature_catalog_version": "v1.0",
            "code_revision": "generator-feature-pipeline-v1",
        }
        canonical_json = json.dumps(canonical_manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        feature_dataset_version = f"feature-dataset-{hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()[:16]}"

        # 7. Check if existing bundle can be reused (when rebuild_npy=False)
        if not request.rebuild_npy:
            existing_meta = self.feature_repo.find_feature_bundle(
                request.dataset_id,
                request.dataset_version,
                feature_dataset_version,
            )
            if existing_meta:
                # Verify exact input and contract match
                if existing_meta.get("inputs") == inputs_metadata and existing_meta.get("prediction_contract") == prediction_contract:
                    logger.info(f"[FeatureService] Reusing existing Feature Dataset Bundle: {feature_dataset_version}")
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

        # 11. Extract row_metadata (asset_id, timestamp) for tracking
        id_col = plan.get("id_column") or "machineID"
        if id_col not in labeled_df.columns:
            for cand in ("asset_id", "machineID", "equipment_id", "machine_id", "device_id", "UDI", "Product ID", "id"):
                if cand in labeled_df.columns:
                    id_col = cand
                    break

        time_col = plan.get("time_column") or "observed_at"
        if time_col not in labeled_df.columns:
            for cand in ("observed_at", "datetime", "timestamp", "time", "ts", "date"):
                if cand in labeled_df.columns:
                    time_col = cand
                    break

        row_metadata: list[dict[str, Any]] = []
        for idx, (_, row) in enumerate(labeled_df.iterrows()):
            row_metadata.append({
                "row_index": idx,
                "asset_id": str(row.get(id_col, "")),
                "timestamp": str(row.get(time_col, "")),
            })

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
