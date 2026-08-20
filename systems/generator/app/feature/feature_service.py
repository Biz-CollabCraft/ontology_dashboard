"""Service for Extraction Plan and Mapping consumption, feature calculation, labeling, and NPY serialization."""

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
from systems.generator.model.model_training import asset_time_split
from systems.generator.app.extraction.extraction_service import (
    ExtractionService,
    extract_with_plan,
)
from systems.generator.app.extraction.extraction_repository import ExtractionRepository
from systems.generator.app.feature.feature_schema import (
    FeatureRequest,
    FeatureResponse,
    FeatureOutputsPayload,
)
from systems.generator.app.feature.feature_exception import (
    ExtractionPlanNotReadyError,
    ExtractionPlanVersionMismatchError,
    ExtractionPlanIntegrityError,
    ExtractionPlanContractInvalidError,
    OntologyMappingNotReadyError,
    OntologyMappingVersionMismatchError,
    OntologyMappingIntegrityError,
    OntologyMappingContractInvalidError,
    FailureDataNotReadyError,
    LabelContractInvalidError,
    LabelAnchorNotFoundError,
    FeatureBuildError,
    LabelBuildError,
    InsufficientTrainingDataError,
    FeatureSchemaMismatchError,
    LabelSchemaMismatchError,
    FeatureDatasetIntegrityError,
)
from systems.generator.app.feature.feature_repository import FeatureRepository
from systems.generator.app.feature.feature_schema_provider import FeatureSchemaProvider
from systems.generator.app.feature.label_schema_provider import (
    LabelSchemaProvider,
    LabelSchemaDefinition,
)
from systems.generator.feature.feature_catalog import load_catalog
from systems.generator.ontology_mapping.mapping_cache import MappingStore, MappingRecord
from systems.generator.app.extraction.extraction_profiler import load_family_registry

logger = logging.getLogger(__name__)


def compute_feature_dataset_version(
    dataset_id: str,
    dataset_version: str,
    failure_dataset_id: str,
    failure_dataset_version: str,
    extraction_plan_version: str,
    mapping_version: str,
    feature_schema_version: str,
    label_schema_version: str,
    prediction_horizon_hours: int,
) -> str:
    """Compute deterministic SHA-256 contract fingerprint for feature dataset version (9 elements)."""
    contract = {
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "extraction_plan_version": extraction_plan_version,
        "failure_dataset_id": failure_dataset_id,
        "failure_dataset_version": failure_dataset_version,
        "feature_schema_version": feature_schema_version,
        "label_schema_version": label_schema_version,
        "mapping_version": mapping_version,
        "prediction_horizon_hours": int(prediction_horizon_hours),
    }
    canonical_json = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()[:16]
    return f"feature-dataset-{fingerprint}"


class FeatureService:
    """Orchestrates Feature, Label, and NPY generation workflows without mutating mapping state."""

    def __init__(
        self,
        extraction_repo: Optional[ExtractionRepository] = None,
        feature_repo: Optional[FeatureRepository] = None,
        extraction_service: Optional[ExtractionService] = None,
        schema_provider: Optional[FeatureSchemaProvider] = None,
        label_schema_provider: Optional[LabelSchemaProvider] = None,
    ) -> None:
        self.extraction_repo = extraction_repo or ExtractionRepository()
        self.feature_repo = feature_repo or FeatureRepository()
        self.extraction_service = extraction_service or ExtractionService()
        self.schema_provider = schema_provider or FeatureSchemaProvider()
        self.label_schema_provider = label_schema_provider or LabelSchemaProvider()

    def run_feature(self, request: FeatureRequest, request_id: Optional[str] = None) -> FeatureResponse:
        """Execute feature building, labeling, and NPY publication from validated Plan and Mapping."""
        req_id = request_id or f"req-{uuid.uuid4().hex[:12]}"
        run_id = f"feature-{uuid.uuid4().hex[:12]}"

        # 0. Validate Label Schema existence and exact rules
        label_schema_def = self.label_schema_provider.validate_label_schema(
            schema_version=request.label_schema_version,
            requested_horizon_hours=request.prediction_horizon_hours,
        )

        # 1. Retrieve & validate Extraction Plan (content-addressed hash verification)
        plan = self.extraction_repo.find_plan(
            request.dataset_id,
            request.dataset_version,
            request.extraction_plan_version,
        )

        # 2. Retrieve & validate Ontology Mapping (content-addressed hash verification)
        mapping_data = self.extraction_repo.find_mapping(
            request.dataset_id,
            request.dataset_version,
            request.mapping_version,
        )

        # 3. Compute contract fingerprint for feature_dataset_version (9 contract keys)
        feature_dataset_version = compute_feature_dataset_version(
            dataset_id=request.dataset_id,
            dataset_version=request.dataset_version,
            failure_dataset_id=request.failure_dataset_id,
            failure_dataset_version=request.failure_dataset_version,
            extraction_plan_version=request.extraction_plan_version,
            mapping_version=request.mapping_version,
            feature_schema_version=request.feature_schema_version,
            label_schema_version=request.label_schema_version,
            prediction_horizon_hours=request.prediction_horizon_hours,
        )

        contract_payload = {
            "dataset_id": request.dataset_id,
            "dataset_version": request.dataset_version,
            "extraction_plan_version": request.extraction_plan_version,
            "failure_dataset_id": request.failure_dataset_id,
            "failure_dataset_version": request.failure_dataset_version,
            "feature_schema_version": request.feature_schema_version,
            "label_schema_version": request.label_schema_version,
            "mapping_version": request.mapping_version,
            "prediction_horizon_hours": request.prediction_horizon_hours,
        }

        # 4. Check existing immutable feature dataset with full bundle validation
        target_dir = self.feature_repo.get_feature_dir(
            request.dataset_id,
            request.dataset_version,
            feature_dataset_version,
        )
        if target_dir.exists():
            existing_meta = self.feature_repo.validate_feature_bundle(
                request.dataset_id,
                request.dataset_version,
                feature_dataset_version,
                expected_contract=contract_payload,
            )
            logger.info(f"[FeatureService] Exact contract match and bundle validated, reusing feature outputs for {feature_dataset_version}")
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
                extraction_plan_version=request.extraction_plan_version,
                mapping_version=request.mapping_version,
                feature_schema_version=request.feature_schema_version,
                label_schema_version=request.label_schema_version,
                outputs=FeatureOutputsPayload(
                    feature_dataset_version=feature_dataset_version,
                    row_count=existing_meta.get("row_count", 0),
                    feature_count=existing_meta.get("feature_count", 0),
                    features_uri=uris["features_uri"],
                    labels_uri=uris["labels_uri"],
                    metadata_uri=uris["metadata_uri"],
                ),
            )

        # 5. Extract telemetry data using plan
        from systems.generator.app.extraction.extraction_schema import ExtractionRequest
        dummy_req = ExtractionRequest(
            dataset_id=request.dataset_id,
            dataset_version=request.dataset_version,
            force_reanalyze=False,
        )
        dataset_path = self.extraction_service._resolve_dataset_path(dummy_req)
        extracted_df = extract_with_plan(str(dataset_path), plan)

        # Drop any preexisting label column from extracted_df before official horizon labeling
        features_input_df = extracted_df.drop(columns=["label"], errors="ignore")

        # 6. Load dataset-scoped MappingStore from published mapping file
        dataset_store = MappingStore()
        for source_field, rec_data in mapping_data.items():
            dataset_store.add_mapping(
                MappingRecord(
                    source_field=source_field,
                    target_ontology=rec_data["target_ontology"],
                    source=rec_data.get("source", "mapping_agent"),
                    confidence=float(rec_data.get("confidence", 1.0)),
                    status=rec_data.get("status", "auto_mapped"),
                )
            )

        # 7. Build time-series features using loaded mappings (NO map_all_sources call!)
        from systems.generator.feature.feature_builder import build_features
        from systems.generator.feature.feature_label_service import build_labels

        catalog = load_catalog()
        try:
            features_df = build_features(features_input_df, dataset_store, catalog, plan=plan)
        except Exception as exc:
            logger.exception(f"[FeatureService] Feature building failed: {exc}")
            raise FeatureBuildError(f"시계열 피처 생성 중 오류가 발생했습니다: {exc}") from exc

        # 8. Resolve explicit failure dataset and build horizon labels
        failures_df, failure_meta = self._resolve_failure_dataset(
            failure_dataset_id=request.failure_dataset_id,
            failure_dataset_version=request.failure_dataset_version,
            telemetry_df=features_input_df,
            plan=plan,
        )

        try:
            labeled_df = build_labels(
                features_df,
                failures_df,
                failure_meta=failure_meta,
                prediction_horizon_hours=request.prediction_horizon_hours,
                plan=plan,
            )
        except (FailureDataNotReadyError, LabelContractInvalidError, LabelAnchorNotFoundError, InsufficientTrainingDataError):
            raise
        except Exception as exc:
            logger.exception(f"[FeatureService] Label building failed: {exc}")
            raise LabelBuildError(f"라벨링 생성 중 오류가 발생했습니다: {exc}") from exc

        # Validate label column
        if "label" not in labeled_df.columns:
            raise LabelContractInvalidError("라벨링 결과에 필수 'label' 컬럼이 존재하지 않습니다.")

        label_values = set(pd.unique(labeled_df["label"]))
        if not label_values.issubset({0, 1}):
            raise LabelContractInvalidError(f"라벨 컬럼 값이 {{0, 1}} 범위를 벗어납니다: {label_values}")

        positive_count = int((labeled_df["label"] == 1).sum())
        if positive_count == 0:
            raise InsufficientTrainingDataError(
                f"고장 예측 구간(horizon={request.prediction_horizon_hours}h) 내에 발생한 Positive 고장 샘플이 0건입니다 (최소 1건 이상의 고장 데이터 필요).",
                code="INSUFFICIENT_POSITIVE_SAMPLES",
            )

        # 9. Apply Feature Schema allowlist & exact order
        feature_names, filtered_features_df = self.schema_provider.validate_and_filter_features(
            schema_version=request.feature_schema_version,
            available_df=labeled_df,
            plan=plan,
        )

        X = filtered_features_df.to_numpy(dtype=np.float64)
        y = labeled_df["label"].to_numpy(dtype=np.int64)

        if X.shape[0] == 0:
            raise InsufficientTrainingDataError("학습에 유효한 데이터 행이 0건입니다.", code="INSUFFICIENT_TRAINING_DATA")

        # 10. Prepare metadata and compute chronological split indices
        id_col = plan.get("id_column") or "asset_id"
        time_col = plan.get("time_column") or "timestamp"
        split_indices = None
        row_metadata = None

        if id_col in labeled_df.columns and time_col in labeled_df.columns:
            try:
                train_sub, val_sub, test_sub = asset_time_split(labeled_df, id_col=id_col, time_col=time_col)
                split_indices = {
                    "train": train_sub.index.tolist(),
                    "val": val_sub.index.tolist(),
                    "test": test_sub.index.tolist(),
                }
                row_metadata = {
                    "asset_ids": labeled_df[id_col].astype(str).tolist(),
                    "timestamps": labeled_df[time_col].astype(str).tolist(),
                }
            except Exception as exc:
                logger.warning(f"[FeatureService] Could not precompute asset_time_split indices: {exc}")

        metadata = {
            "contract": contract_payload,
            "dataset_id": request.dataset_id,
            "dataset_version": request.dataset_version,
            "failure_dataset_id": request.failure_dataset_id,
            "failure_dataset_version": request.failure_dataset_version,
            "extraction_plan_version": request.extraction_plan_version,
            "mapping_version": request.mapping_version,
            "feature_schema_version": request.feature_schema_version,
            "label_schema_version": request.label_schema_version,
            "prediction_horizon_hours": request.prediction_horizon_hours,
            "feature_dataset_version": feature_dataset_version,
            "feature_columns": feature_names,
            "row_count": int(X.shape[0]),
            "feature_count": int(X.shape[1]),
            "positive_count": positive_count,
            "dtype": str(X.dtype),
            "id_column": plan.get("id_column"),
            "time_column": plan.get("time_column"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
        }
        if split_indices:
            metadata["split_indices"] = split_indices

        # 11. Atomic publish via repository
        uris = self.feature_repo.publish_feature_bundle(
            request.dataset_id,
            request.dataset_version,
            feature_dataset_version,
            X=X,
            y=y,
            feature_names=feature_names,
            metadata=metadata,
            row_metadata=row_metadata,
        )

        return FeatureResponse(
            request_id=req_id,
            run_id=run_id,
            status="succeeded",
            dataset_id=request.dataset_id,
            dataset_version=request.dataset_version,
            failure_dataset_id=request.failure_dataset_id,
            failure_dataset_version=request.failure_dataset_version,
            extraction_plan_version=request.extraction_plan_version,
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

    def _resolve_failure_dataset(
        self,
        failure_dataset_id: str,
        failure_dataset_version: str,
        telemetry_df: pd.DataFrame,
        plan: dict | None = None,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Explicitly resolve and validate failure dataset with equipment identifier compatibility."""
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
            if any(resolved.is_relative_to(root) for root in allowed_roots) and cand.is_file():
                found_path = cand
                break

        meta: dict[str, Any] = {}
        if not found_path:
            # Check family registry for exact failure dataset key
            registry = load_family_registry()
            if failure_dataset_id in registry:
                fail_rel = failure_dataset_id
                meta = registry.get(failure_dataset_id, {})
                for root in allowed_roots:
                    cand = root / fail_rel
                    if cand.is_file():
                        found_path = cand
                        break

        if not found_path or not found_path.is_file():
            raise FailureDataNotReadyError(
                f"요청한 Failure 데이터셋 '{failure_dataset_id}' (버전 '{failure_dataset_version}')을 찾을 수 없습니다."
            )

        try:
            if found_path.suffix.lower() in (".xlsx", ".xls"):
                f_df = pd.read_excel(found_path)
            else:
                f_df = pd.read_csv(found_path)
        except Exception as exc:
            raise FailureDataNotReadyError(f"Failure 데이터셋 파일({found_path}) 로드 실패: {exc}") from exc

        if f_df.empty:
            raise FailureDataNotReadyError(f"Failure 데이터셋 '{failure_dataset_id}'이 비어 있습니다.")

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
            raise LabelContractInvalidError(f"Failure 데이터셋에서 설비 ID 컬럼을 찾을 수 없습니다 (사용 가능한 컬럼: {list(f_df.columns)}).")

        # Identify Failure anchor column
        time_cols_meta = meta.get("time_columns", [])
        anchor_col = next((c["name"] for c in time_cols_meta if c.get("semantic") == "failure_point"), None)
        if not anchor_col or anchor_col not in f_df.columns:
            for candidate in ("observed_at", "datetime", "timestamp", "time", "ts", "date", "failure_point"):
                if candidate in f_df.columns:
                    anchor_col = candidate
                    break

        if not anchor_col or anchor_col not in f_df.columns:
            raise LabelAnchorNotFoundError(f"Failure 데이터셋에서 anchor(failure_point) 컬럼을 찾을 수 없습니다 (사용 가능한 컬럼: {list(f_df.columns)}).")

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
                raise LabelContractInvalidError(
                    f"Telemetry 데이터셋과 Failure 데이터셋의 설비 식별 체계(Asset IDs)가 호환되지 않습니다. "
                    f"(Telemetry: {list(telem_assets)[:3]}, Failure: {list(fail_assets)[:3]})"
                )

        return f_df, meta
