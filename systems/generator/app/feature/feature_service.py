"""Service for Extraction Plan and Mapping consumption, feature calculation, labeling, and NPY serialization."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import numpy as np
import pandas as pd

from systems.generator.generator_config import PATHS
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
)
from systems.generator.app.feature.feature_repository import FeatureRepository
from systems.generator.app.feature.feature_schema_provider import FeatureSchemaProvider
from systems.generator.feature.feature_catalog import load_catalog
from systems.generator.ontology_mapping.mapping_cache import MappingStore, MappingRecord
from systems.generator.app.extraction.extraction_profiler import load_family_registry

logger = logging.getLogger(__name__)


def compute_feature_dataset_version(
    dataset_id: str,
    dataset_version: str,
    extraction_plan_version: str,
    mapping_version: str,
    feature_schema_version: str,
    label_schema_version: str,
    prediction_horizon_hours: int,
) -> str:
    """Compute deterministic SHA-256 contract fingerprint for feature dataset version."""
    contract = {
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "extraction_plan_version": extraction_plan_version,
        "mapping_version": mapping_version,
        "feature_schema_version": feature_schema_version,
        "label_schema_version": label_schema_version,
        "prediction_horizon_hours": int(prediction_horizon_hours),
    }
    canonical_json = json.dumps(contract, sort_keys=True, separators=(",", ":"))
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
    ) -> None:
        self.extraction_repo = extraction_repo or ExtractionRepository()
        self.feature_repo = feature_repo or FeatureRepository()
        self.extraction_service = extraction_service or ExtractionService()
        self.schema_provider = schema_provider or FeatureSchemaProvider()

    def run_feature(self, request: FeatureRequest, request_id: Optional[str] = None) -> FeatureResponse:
        """Execute feature building, labeling, and NPY publication from validated Plan and Mapping."""
        req_id = request_id or f"req-{uuid.uuid4().hex[:12]}"
        run_id = f"feature-{uuid.uuid4().hex[:12]}"

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

        # 3. Compute contract fingerprint for feature_dataset_version
        feature_dataset_version = compute_feature_dataset_version(
            dataset_id=request.dataset_id,
            dataset_version=request.dataset_version,
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
            "mapping_version": request.mapping_version,
            "feature_schema_version": request.feature_schema_version,
            "label_schema_version": request.label_schema_version,
            "prediction_horizon_hours": request.prediction_horizon_hours,
        }

        # 4. Check existing immutable feature dataset
        existing_meta = self.feature_repo.find_feature_outputs(
            request.dataset_id,
            request.dataset_version,
            feature_dataset_version,
        )
        if existing_meta:
            meta_contract = existing_meta.get("contract", {})
            if all(meta_contract.get(k) == v for k, v in contract_payload.items()):
                logger.info(f"[FeatureService] Exact contract match, reusing feature outputs for {feature_dataset_version}")
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

        # 5. Extract data using plan
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

        # 8. Build horizon labels with strict fail-fast policy
        failures_df, failure_meta = self._resolve_failure_dataset(request.dataset_id)

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

        # 10. Prepare metadata
        metadata = {
            "contract": contract_payload,
            "dataset_id": request.dataset_id,
            "dataset_version": request.dataset_version,
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

        # 11. Atomic publish via repository
        uris = self.feature_repo.publish_feature_bundle(
            request.dataset_id,
            request.dataset_version,
            feature_dataset_version,
            X=X,
            y=y,
            feature_names=feature_names,
            metadata=metadata,
        )

        return FeatureResponse(
            request_id=req_id,
            run_id=run_id,
            status="succeeded",
            dataset_id=request.dataset_id,
            dataset_version=request.dataset_version,
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

    def _resolve_failure_dataset(self, dataset_id: str) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Resolve failure events dataframe and metadata, or raise FailureDataNotReadyError."""
        # 1. Check Stage 0 family registry
        registry = load_family_registry()
        failures_key = next((f for f in registry if "failure" in f.lower() or "maint" in f.lower()), None)
        if failures_key:
            fail_path = PATHS.data_dir / failures_key
            if not fail_path.exists():
                fail_path = PATHS.data_preprocessed / failures_key
            if fail_path.exists():
                meta = registry.get(failures_key, {})
                df = pd.read_csv(fail_path) if fail_path.suffix.lower() == ".csv" else pd.read_excel(fail_path)
                return df, meta

        # 2. Check for specific failure dataset file in data directories
        candidates = [
            PATHS.data_dir / f"{dataset_id}_failures.csv",
            PATHS.data_dir / "failure_events.csv",
            PATHS.data_dir / "failures.csv",
            PATHS.data_preprocessed / f"{dataset_id}_failures.csv",
            PATHS.data_preprocessed / "failure_events.csv",
            PATHS.data_preprocessed / "failures.csv",
        ]
        for cand in candidates:
            if cand.is_file():
                df = pd.read_csv(cand) if cand.suffix.lower() == ".csv" else pd.read_excel(cand)
                return df, {}

        # If no failure file is present at all, raise FailureDataNotReadyError
        raise FailureDataNotReadyError(
            f"데이터셋 '{dataset_id}'에 매칭되는 고장 이력 데이터(failure_events.csv)를 찾을 수 없습니다."
        )
