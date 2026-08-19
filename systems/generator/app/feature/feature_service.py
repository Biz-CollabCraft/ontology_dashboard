"""Service for Extraction Plan consumption, feature calculation, labeling, and NPY serialization."""

from __future__ import annotations

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
    FeatureBuildError,
    LabelBuildError,
    InsufficientTrainingDataError,
)
from systems.generator.app.feature.feature_repository import FeatureRepository
from systems.generator.feature.feature_builder import build_features
from systems.generator.feature.feature_catalog import load_catalog
from systems.generator.feature.feature_label_service import build_labels
from systems.generator.ontology_mapping.mapping_cache import get_mapping_store, reload_mapping_store
from systems.generator.ontology_mapping.mapping_agent import map_all_sources
from systems.generator.app.extraction.extraction_profiler import load_family_registry

logger = logging.getLogger(__name__)


class FeatureService:
    """Orchestrates Feature, Label, and NPY generation workflows."""

    def __init__(
        self,
        extraction_repo: Optional[ExtractionRepository] = None,
        feature_repo: Optional[FeatureRepository] = None,
        extraction_service: Optional[ExtractionService] = None,
    ) -> None:
        self.extraction_repo = extraction_repo or ExtractionRepository()
        self.feature_repo = feature_repo or FeatureRepository()
        self.extraction_service = extraction_service or ExtractionService()

    def run_feature(self, request: FeatureRequest, request_id: Optional[str] = None) -> FeatureResponse:
        """Execute feature building, labeling, and NPY publication from a validated Extraction Plan."""
        req_id = request_id or f"req-{uuid.uuid4().hex[:12]}"
        run_id = f"feature-{uuid.uuid4().hex[:12]}"

        # 1. Retrieve & validate Extraction Plan
        plan = self.extraction_repo.find_plan(request.dataset_id, request.dataset_version)
        if not plan:
            raise ExtractionPlanNotReadyError(
                f"요청한 Extraction Plan이 없습니다 (dataset_id='{request.dataset_id}', "
                f"version='{request.dataset_version}'). 먼저 POST /extraction을 실행해 주세요."
            )

        expected_plan_version = f"extraction-plan-{request.dataset_id}-{request.dataset_version}"
        if request.extraction_plan_version != expected_plan_version:
            raise ExtractionPlanVersionMismatchError(
                f"요청한 extraction_plan_version '{request.extraction_plan_version}'이 "
                f"기대되는 Plan 버전 '{expected_plan_version}'과 일치하지 않습니다."
            )

        # 2. Derive stable feature dataset version
        feature_dataset_version = f"feature-dataset-{request.dataset_id}-{request.dataset_version}"

        # 3. Check existing if not force
        if not request.force:
            existing_meta = self.feature_repo.find_feature_outputs(
                request.dataset_id,
                request.dataset_version,
                feature_dataset_version,
            )
            if existing_meta:
                logger.info(f"[FeatureService] Reusing existing feature outputs for {feature_dataset_version}")
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

        # 4. Extract data using plan
        from systems.generator.app.extraction.extraction_schema import ExtractionRequest
        dummy_req = ExtractionRequest(
            dataset_id=request.dataset_id,
            dataset_version=request.dataset_version,
            force_reanalyze=False,
        )
        dataset_path = self.extraction_service._resolve_dataset_path(dummy_req)
        extracted_df = extract_with_plan(str(dataset_path), plan)

        # 5. Apply Ontology Mapping
        store = get_mapping_store()
        key_name = os.path.splitext(dataset_path.name)[0]
        sources_dict = {key_name: extracted_df}
        try:
            map_all_sources(sources_dict, store)
            reload_mapping_store()
        except Exception as e:
            logger.warning(f"[FeatureService] Ontology mapping note: {e}")

        # 6. Build time-series features
        catalog = load_catalog()
        try:
            features_df = build_features(extracted_df, store, catalog, plan=plan)
        except Exception as exc:
            logger.exception(f"[FeatureService] Feature building failed: {exc}")
            raise FeatureBuildError(f"시계열 피처 생성 중 오류가 발생했습니다: {exc}") from exc

        # 7. Build horizon labels
        # Check for matching failure file or construct self-contained labels
        registry = load_family_registry()
        failures_key = next((f for f in registry if "failure" in f.lower() or "maint" in f.lower()), None)
        failure_meta = registry.get(failures_key, {}) if failures_key else {}

        if failures_key and (PATHS.data_dir / failures_key).exists():
            failures_path = PATHS.data_dir / failures_key
            failures_df = pd.read_csv(failures_path) if failures_path.suffix.lower() == ".csv" else pd.read_excel(failures_path)
        else:
            failures_df = pd.DataFrame()

        try:
            labeled_df = build_labels(
                features_df,
                failures_df,
                failure_meta=failure_meta,
                prediction_horizon_hours=request.prediction_horizon_hours,
                plan=plan,
            )
        except Exception as exc:
            logger.exception(f"[FeatureService] Label building failed: {exc}")
            raise LabelBuildError(f"라벨링 생성 중 오류가 발생했습니다: {exc}") from exc

        # 8. Feature Schema allowlist filtering
        id_col = plan.get("id_column") or "asset_id"
        time_col = plan.get("time_column") or "observed_at"

        exclude_cols = set(filter(None, [
            "datetime", "observed_at", "machineID", "asset_id", "label",
            "period_start", "anchor", "failure_point", "exclusion_end", "degradation_start",
            id_col, time_col
        ]))

        feature_names = [
            c for c in labeled_df.columns
            if c not in exclude_cols and pd.api.types.is_numeric_dtype(labeled_df[c])
        ]

        if not feature_names:
            raise InsufficientTrainingDataError(
                f"No numeric feature columns found in dataset '{request.dataset_id}'. "
                f"Available columns: {list(labeled_df.columns)}"
            )

        # Sort feature names deterministically
        feature_names = sorted(feature_names)

        X = labeled_df[feature_names].to_numpy(dtype=np.float64)
        y = labeled_df["label"].to_numpy(dtype=np.int64) if "label" in labeled_df.columns else np.zeros(len(labeled_df), dtype=np.int64)

        # 9. Prepare metadata
        metadata = {
            "dataset_id": request.dataset_id,
            "dataset_version": request.dataset_version,
            "extraction_plan_version": request.extraction_plan_version,
            "feature_schema_version": request.feature_schema_version,
            "label_schema_version": request.label_schema_version,
            "prediction_horizon_hours": request.prediction_horizon_hours,
            "feature_dataset_version": feature_dataset_version,
            "feature_columns": feature_names,
            "row_count": int(X.shape[0]),
            "feature_count": int(X.shape[1]),
            "dtype": str(X.dtype),
            "id_column": id_col,
            "time_column": time_col,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
        }

        # 10. Atomic publish via repository
        uris = self.feature_repo.publish_feature_bundle(
            request.dataset_id,
            request.dataset_version,
            feature_dataset_version,
            X=X,
            y=y,
            feature_names=feature_names,
            metadata=metadata,
            overwrite=request.force,
        )

        return FeatureResponse(
            request_id=req_id,
            run_id=run_id,
            status="succeeded",
            dataset_id=request.dataset_id,
            dataset_version=request.dataset_version,
            extraction_plan_version=request.extraction_plan_version,
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
