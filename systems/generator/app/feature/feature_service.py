"""Service for Extraction Plan and Mapping consumption, feature calculation, labeling, and NPY serialization."""

from __future__ import annotations

import hashlib
import json
import logging
import re
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
    LabelSchemaMismatchError,
    FeatureDatasetIntegrityError,
    SourceDatasetIntegrityError,
    SourceDatasetVersionMismatchError,
    FailureDatasetVersionMismatchError,
    TrainingSplitMetadataMissingError,
)
from systems.generator.app.feature.feature_repository import FeatureRepository, compute_file_sha256
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

        # 2. Mandatory Extraction Plan source contract validation (no legacy fallback)
        plan_source = plan.get("source") if isinstance(plan, dict) else None
        if not plan_source or not isinstance(plan_source, dict):
            raise SourceDatasetIntegrityError(
                "Extraction Plan에 필수 메타데이터인 'source' 객체가 누락되었습니다. "
                "구형 Extraction Plan은 지원되지 않으므로 POST /extraction을 다시 실행해 주세요."
            )

        for required_key in ("dataset_id", "dataset_version", "source_uri", "sha256"):
            if not plan_source.get(required_key):
                raise SourceDatasetIntegrityError(
                    f"Extraction Plan의 source에 필수 필드 '{required_key}'가 누락되었습니다."
                )

        if (
            plan_source.get("dataset_id") != request.dataset_id
            or plan_source.get("dataset_version") != request.dataset_version
        ):
            raise SourceDatasetVersionMismatchError(
                f"Extraction Plan의 source 정보({plan_source.get('dataset_id')}/{plan_source.get('dataset_version')})가 "
                f"요청({request.dataset_id}/{request.dataset_version})과 일치하지 않습니다."
            )

        source_uri_declared = plan_source.get("source_uri")
        if (
            not source_uri_declared
            or ".." in source_uri_declared
            or Path(source_uri_declared).is_absolute()
            or ":" in source_uri_declared
        ):
            raise SourceDatasetIntegrityError(f"Extraction Plan의 source_uri가 유효하지 않습니다: {source_uri_declared!r}")

        sha256_declared = plan_source.get("sha256")
        if not sha256_declared or not re.fullmatch(r"^[0-9a-f]{64}$", str(sha256_declared)):
            raise SourceDatasetIntegrityError(
                f"Extraction Plan의 source sha256 형식이 유효하지 않습니다 (64자리 소문자 hex 필요): {sha256_declared!r}"
            )

        allowed_roots = [PATHS.data_dir.resolve(), PATHS.data_preprocessed.resolve()]
        source_file = None
        for root in allowed_roots:
            cand = (root / source_uri_declared).resolve()
            try:
                cand.relative_to(root)
                if cand.is_file():
                    source_file = cand
                    break
            except ValueError:
                continue

        if not source_file:
            raise SourceDatasetIntegrityError(f"Extraction Plan에 선언된 원본 파일 '{source_uri_declared}'을 찾을 수 없습니다.")

        actual_source_sha = compute_file_sha256(source_file)
        if actual_source_sha != sha256_declared:
            raise SourceDatasetIntegrityError(
                f"Sensor 원본 파일 '{source_uri_declared}'의 SHA-256 해시가 일치하지 않습니다 "
                f"(선언={sha256_declared}, 실제={actual_source_sha})."
            )

        source_sha256 = actual_source_sha
        source_uri_clean = source_uri_declared

        # 3. Locate & validate Failure Dataset file and compute SHA-256
        failure_file, failure_sha256, failure_uri_clean = self._locate_failure_file(
            request.failure_dataset_id,
            request.failure_dataset_version,
        )

        # 4. Retrieve & validate Ontology Mapping (content-addressed hash verification)
        mapping_data = self.extraction_repo.find_mapping(
            request.dataset_id,
            request.dataset_version,
            request.mapping_version,
        )

        # 5. Compute contract fingerprint for feature_dataset_version (9 contract keys)
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

        # 6. Check existing immutable feature dataset with full bundle validation AND raw sources re-verification
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

            # Re-verify raw source provenance in existing bundle metadata
            src_meta = existing_meta.get("source_dataset", {})
            fail_meta = existing_meta.get("failure_dataset", {})

            if (
                src_meta.get("dataset_id") != plan_source["dataset_id"]
                or src_meta.get("dataset_version") != plan_source["dataset_version"]
                or src_meta.get("source_uri") != plan_source["source_uri"]
                or src_meta.get("sha256") != actual_source_sha
            ):
                raise SourceDatasetIntegrityError(
                    "기존 Feature Bundle의 Sensor 원본 메타데이터(source_dataset)가 현재 Sensor 원본 파일 또는 Extraction Plan과 일치하지 않습니다."
                )

            if (
                fail_meta.get("dataset_id") != request.failure_dataset_id
                or fail_meta.get("dataset_version") != request.failure_dataset_version
                or fail_meta.get("source_uri") != failure_uri_clean
                or fail_meta.get("sha256") != failure_sha256
            ):
                raise FeatureDatasetIntegrityError(
                    "기존 Feature Bundle의 Failure 원본 메타데이터(failure_dataset)가 현재 Failure 파일과 일치하지 않습니다."
                )

            logger.info(f"[FeatureService] Exact contract match, bundle validated, and raw sources re-verified, reusing feature outputs for {feature_dataset_version}")
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

        # 7. Extract telemetry data using verified plan and sensor source
        extracted_df = extract_with_plan(str(source_file), plan)

        # Drop any preexisting label column from extracted_df before official horizon labeling
        features_input_df = extracted_df.drop(columns=["label"], errors="ignore")

        # 8. Load dataset-scoped MappingStore from published mapping file
        dataset_store = MappingStore()
        for source_field, rec_data in mapping_data.items():
            rec = MappingRecord(
                source_field=source_field,
                target_ontology=rec_data.get("target_ontology", source_field),
                source=rec_data.get("source", "mapping_agent"),
                confidence=float(rec_data.get("confidence", 1.0)),
                status=rec_data.get("status", "auto_mapped"),
            )
            dataset_store.add_mapping(rec)

        # 9. Build features
        try:
            from systems.generator.feature.feature_builder import build_features
            catalog = load_catalog()
            features_df = build_features(
                features_input_df,
                store=dataset_store,
                catalog=catalog,
                plan=plan,
            )
        except Exception as exc:
            raise FeatureBuildError(f"Feature 추출 실행 실패: {exc}") from exc

        # 10. Load and validate Failure dataset DataFrame
        failures_df, fail_meta = self._load_and_validate_failure_df(
            failure_file,
            plan=plan,
            telemetry_df=features_input_df,
        )

        # 11. Build labels
        try:
            from systems.generator.feature.feature_label_service import build_labels
            labeled_df = build_labels(
                features_df=features_df,
                failures_df=failures_df,
                failure_meta=fail_meta,
                prediction_horizon_hours=request.prediction_horizon_hours,
                plan=plan,
            )
        except (InsufficientTrainingDataError, LabelContractInvalidError, LabelAnchorNotFoundError, LabelSchemaMismatchError):
            raise
        except Exception as exc:
            raise LabelBuildError(f"고장 라벨 생성 실행 실패: {exc}") from exc

        if labeled_df.empty:
            raise InsufficientTrainingDataError("라벨링 후 데이터셋이 비어 있습니다.")

        # Strict Feature Schema allowlist & exact order validation directly on labeled_df
        feature_names, filtered_features_df = self.schema_provider.validate_and_filter_features(
            request.feature_schema_version,
            labeled_df,
            plan=plan,
        )
        X = filtered_features_df.values.astype(np.float64)

        if np.isnan(X).any() or np.isinf(X).any():
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

        y = labeled_df["label"].values.astype(np.int64)
        positive_count = int(np.sum(y == 1))
        if positive_count == 0:
            raise InsufficientTrainingDataError(
                f"고장 예측 구간(horizon={request.prediction_horizon_hours}h) 내 발생한 Positive 고장 샘플이 0건입니다 (최소 1건 이상 발생 필요).",
                code="INSUFFICIENT_POSITIVE_SAMPLES",
            )

        # 12. Compute strict chronological asset-time split indices and row metadata
        id_col = plan.get("id_column") if plan and isinstance(plan, dict) else None
        if id_col and id_col not in labeled_df.columns:
            raise TrainingSplitMetadataMissingError(
                f"Extraction Plan에 명시된 ID 컬럼 '{id_col}'을 데이터에서 찾을 수 없습니다."
            )
        if not id_col:
            for cand in ("asset_id", "machineID", "equipment_id", "machine_id", "device_id", "UDI", "Product ID", "id", "asset", "machine"):
                if cand in labeled_df.columns:
                    id_col = cand
                    break

        time_col = plan.get("time_column") if plan and isinstance(plan, dict) else None
        if time_col and time_col not in labeled_df.columns:
            raise TrainingSplitMetadataMissingError(
                f"Extraction Plan에 명시된 타임스탬프 컬럼 '{time_col}'을 데이터에서 찾을 수 없습니다."
            )
        if not time_col:
            for cand in ("observed_at", "datetime", "timestamp", "time", "date", "ts"):
                if cand in labeled_df.columns:
                    time_col = cand
                    break

        if not id_col or id_col not in labeled_df.columns:
            raise TrainingSplitMetadataMissingError(
                "설비 분할(asset_time_split)에 필요한 ID 컬럼을 데이터에서 찾을 수 없습니다."
            )
        if not time_col or time_col not in labeled_df.columns:
            raise TrainingSplitMetadataMissingError(
                "시간순 분할(asset_time_split)에 필요한 타임스탬프 컬럼을 데이터에서 찾을 수 없습니다."
            )

        from systems.generator.model.model_training import (
            compute_asset_time_split_indices,
            validate_split_indices,
        )

        try:
            train_idx, val_idx, test_idx = compute_asset_time_split_indices(
                labeled_df,
                id_col=id_col,
                time_col=time_col,
            )
        except Exception as exc:
            raise TrainingSplitMetadataMissingError(
                f"설비별 시간순 분할 인덱스(asset_time_split) 산출 실패: {exc}"
            ) from exc

        split_indices = {
            "train": train_idx,
            "val": val_idx,
            "test": test_idx,
        }
        asset_ids_list = labeled_df[id_col].astype(str).tolist()
        timestamps_list = labeled_df[time_col].astype(str).tolist()

        if len(asset_ids_list) != int(X.shape[0]) or len(timestamps_list) != int(X.shape[0]):
            raise TrainingSplitMetadataMissingError(
                f"row_metadata 행 수({len(asset_ids_list)})와 Feature 행 수({X.shape[0]})가 일치하지 않습니다."
            )

        # Validate split indices
        try:
            validate_split_indices(
                split_indices=split_indices,
                total_rows=int(X.shape[0]),
                asset_ids=asset_ids_list,
                timestamps=timestamps_list,
            )
        except Exception as exc:
            raise TrainingSplitMetadataMissingError(
                f"생성된 split_indices 유효성 검증 실패: {exc}"
            ) from exc

        row_metadata = {
            "asset_ids": asset_ids_list,
            "timestamps": timestamps_list,
        }

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
            "id_column": id_col,
            "time_column": time_col,
            "split_indices": split_indices,
            "source_dataset": {
                "dataset_id": request.dataset_id,
                "dataset_version": request.dataset_version,
                "source_uri": source_uri_clean,
                "sha256": source_sha256,
            },
            "failure_dataset": {
                "dataset_id": request.failure_dataset_id,
                "dataset_version": request.failure_dataset_version,
                "source_uri": failure_uri_clean,
                "sha256": failure_sha256,
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
        }

        # 13. Atomic publish via repository
        uris = self.feature_repo.publish_feature_bundle(
            dataset_id=request.dataset_id,
            dataset_version=request.dataset_version,
            feature_dataset_version=feature_dataset_version,
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

    def _locate_failure_file(
        self,
        failure_dataset_id: str,
        failure_dataset_version: str,
    ) -> tuple[Path, str, str]:
        """Locate the failure dataset file adhering to exact version path conventions and calculate its SHA-256."""
        allowed_roots = [PATHS.data_dir.resolve(), PATHS.data_preprocessed.resolve()]

        if not failure_dataset_id or ".." in failure_dataset_id or "/" in failure_dataset_id or "\\" in failure_dataset_id or ":" in failure_dataset_id:
            raise FailureDataNotReadyError(f"잘못된 failure_dataset_id 식별자입니다: {failure_dataset_id!r}")
        if not failure_dataset_version or ".." in failure_dataset_version or "/" in failure_dataset_version or "\\" in failure_dataset_version or ":" in failure_dataset_version:
            raise FailureDataNotReadyError(f"잘못된 failure_dataset_version 식별자입니다: {failure_dataset_version!r}")


        # Strictly require version in the path
        candidates = [
            PATHS.data_dir / failure_dataset_id / f"{failure_dataset_version}.csv",
            PATHS.data_dir / failure_dataset_id / f"{failure_dataset_version}.xlsx",
            PATHS.data_dir / failure_dataset_id / f"{failure_dataset_version}.xls",
            PATHS.data_dir / failure_dataset_id / failure_dataset_version / "input.csv",
            PATHS.data_preprocessed / failure_dataset_id / failure_dataset_version / "input.csv",
            PATHS.data_preprocessed / failure_dataset_id / f"{failure_dataset_version}.csv",
            PATHS.data_preprocessed / failure_dataset_id / f"{failure_dataset_version}.xlsx",
            PATHS.data_preprocessed / failure_dataset_id / f"{failure_dataset_version}.xls",
            PATHS.data_dir / f"{failure_dataset_id}_{failure_dataset_version}.csv",
            PATHS.data_preprocessed / f"{failure_dataset_id}_{failure_dataset_version}.csv",
        ]

        found_path: Optional[Path] = None
        for cand in candidates:
            resolved = cand.resolve()
            if any(resolved.is_relative_to(root) for root in allowed_roots) and cand.is_file():
                found_path = cand
                break

        if not found_path or not found_path.is_file():
            raise FailureDatasetVersionMismatchError(
                f"요청한 Failure 데이터셋 '{failure_dataset_id}' (버전 '{failure_dataset_version}')에 해당하는 파일을 찾을 수 없습니다."
            )

        failure_sha256 = compute_file_sha256(found_path)
        try:
            failure_uri_clean = str(found_path.relative_to(PATHS.data_dir.resolve()).as_posix())
        except ValueError:
            try:
                failure_uri_clean = str(found_path.relative_to(PATHS.data_preprocessed.resolve()).as_posix())
            except ValueError:
                failure_uri_clean = found_path.name

        return found_path, failure_sha256, failure_uri_clean

    def _load_and_validate_failure_df(
        self,
        failure_file: Path,
        plan: dict[str, Any],
        telemetry_df: pd.DataFrame,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Load and validate failure dataframe columns and asset ID compatibility."""
        try:
            if failure_file.suffix.lower() in (".xlsx", ".xls"):
                f_df = pd.read_excel(failure_file)
            else:
                f_df = pd.read_csv(failure_file)
        except Exception as exc:
            raise FailureDataNotReadyError(f"Failure 데이터셋 파일({failure_file}) 로드 실패: {exc}") from exc

        if f_df.empty:
            raise FailureDataNotReadyError("Failure 데이터셋이 비어 있습니다.")

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
        anchor_col = None
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

        meta = {
            "failure_id_column": fail_id_col,
            "anchor_column": anchor_col,
        }
        return f_df, meta
