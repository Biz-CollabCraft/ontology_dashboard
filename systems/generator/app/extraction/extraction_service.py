"""Extraction domain service for orchestrating dataset resolution, planning, mapping, and execution."""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any, Optional
import pandas as pd

from systems.generator.generator_config import PATHS
from systems.generator.app.extraction.extraction_planner import ExtractionPlanner
from systems.generator.app.extraction.extraction_repository import ExtractionRepository
from systems.generator.app.extraction.extraction_schema import (
    ExtractionRequest,
    ExtractionResponse,
    ExtractionPlanResponse,
    ExtractionResultPayload,
)
from systems.generator.app.extraction.extraction_exception import (
    ExtractionError,
    DatasetNotFoundError,
    DatasetContractError,
    ExtractionRoleError,
    ExtractionPlanValidationError,
    ExtractionPlanPublishError,
)

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = (".csv", ".xlsx", ".xls")
_last_plans: dict[str, Any] = {}


def get_last_plans() -> dict[str, Any]:
    """Return in-memory cached plans from previous extractions."""
    return dict(_last_plans)


def extract_with_plan(filepath: str, plan: dict[str, Any]) -> pd.DataFrame:
    """Execute dataframe loading and transformation based on the validated plan."""
    ext = os.path.splitext(filepath)[1].lower()
    logger.info(f"[Extractor] Reading file '{filepath}' (ext: {ext})...")

    if ext == ".csv":
        df = pd.read_csv(filepath)
    elif ext in (".xlsx", ".xls"):
        df = pd.read_excel(filepath)
    else:
        raise ValueError(f"Unsupported file extension: {ext}")

    structure_type = plan.get("structure_type", "tabular_column_as_attribute")
    selected_cols = plan.get("selected_columns")

    if structure_type == "tabular_column_as_attribute":
        if selected_cols:
            valid_cols = [c for c in selected_cols if c in df.columns]
        else:
            valid_cols = list(df.columns)

        if not valid_cols:
            logger.warning(f"[Extractor] None of selected columns {selected_cols} exist in '{filepath}'. Keeping all.")
            valid_cols = list(df.columns)

        extracted_df = df[valid_cols].copy()

        id_col = plan.get("id_column")
        time_col = plan.get("time_column")
        if time_col and time_col in extracted_df.columns:
            try:
                extracted_df[time_col] = pd.to_datetime(extracted_df[time_col])
            except Exception:
                pass

        if id_col and time_col and id_col in extracted_df.columns and time_col in extracted_df.columns:
            dup_key = [id_col, time_col]
            has_duplicates = extracted_df.duplicated(subset=dup_key).any()
            if has_duplicates:
                dup_policy = plan.get("duplicate_policy", "error")
                aggfunc = plan.get("aggregation")
                if dup_policy == "aggregate" and aggfunc:
                    numeric_cols = [
                        c for c in extracted_df.columns
                        if c not in dup_key and pd.api.types.is_numeric_dtype(extracted_df[c])
                    ]
                    non_numeric_cols = [c for c in extracted_df.columns if c not in dup_key and c not in numeric_cols]
                    for c in non_numeric_cols:
                        per_group_nunique = extracted_df.groupby(dup_key)[c].nunique()
                        if (per_group_nunique > 1).any():
                            raise ValueError(
                                f"Cannot deduplicate non-numeric column '{c}' with conflicting "
                                f"values within the same {dup_key} group; no aggregation policy "
                                f"is defined for non-numeric conflicts"
                            )
                    agg_map = {c: aggfunc for c in numeric_cols}
                    agg_map.update({c: "first" for c in non_numeric_cols})
                    extracted_df = extracted_df.groupby(dup_key, as_index=False).agg(agg_map)
                    extracted_df = extracted_df.sort_values(by=dup_key).reset_index(drop=True)
                else:
                    raise ValueError(
                        f"Duplicate rows found for key {dup_key} and duplicate_policy="
                        f"{dup_policy!r}; set plan.duplicate_policy='aggregate' with an "
                        f"aggregation function, or deduplicate the source data"
                    )

        logger.info(f"[Extractor] Successfully extracted {len(valid_cols)} columns from '{filepath}'. Output shape: {extracted_df.shape}")
        return extracted_df

    elif structure_type == "tabular_row_as_attribute":
        logger.info(f"[Extractor] Performing contract-driven tabular_row_as_attribute transform for '{filepath}'...")
        id_col = plan.get("id_column")
        time_col = plan.get("time_column")
        attr_col = plan.get("attribute_column")
        val_col = plan.get("value_column")

        missing_roles = []
        if not id_col:
            missing_roles.append("id_column")
        if not attr_col:
            missing_roles.append("attribute_column")
        if not val_col:
            missing_roles.append("value_column")

        if missing_roles:
            raise ExtractionRoleError(
                f"Long-format extraction for '{filepath}' failed: missing required role(s) {missing_roles}. "
                f"Specified roles: id_column={id_col!r}, attribute_column={attr_col!r}, value_column={val_col!r}, time_column={time_col!r}."
            )

        missing_cols = [c for c in [id_col, attr_col, val_col] if c not in df.columns]
        if time_col and time_col not in df.columns:
            missing_cols.append(time_col)

        if missing_cols:
            raise ExtractionPlanValidationError(
                f"Long-format extraction for '{filepath}' failed: specified role columns {missing_cols} not found in DataFrame."
            )

        roles = [id_col, attr_col, val_col]
        if time_col:
            roles.append(time_col)
        if len(roles) != len(set(roles)):
            raise ExtractionPlanValidationError(
                f"Long-format extraction for '{filepath}' failed: role columns must be unique and cannot overlap: {roles}."
            )

        index_cols = [id_col]
        if time_col:
            index_cols.append(time_col)
            if time_col in df.columns:
                try:
                    df[time_col] = pd.to_datetime(df[time_col])
                except Exception:
                    pass

        has_duplicates = df.duplicated(subset=index_cols + [attr_col]).any()
        if has_duplicates:
            dup_policy = plan.get("duplicate_policy", "error")
            aggfunc = plan.get("aggregation")
            if dup_policy == "aggregate" and aggfunc:
                logger.info(f"[Extractor] Long-format duplicate rows found; aggregating by {aggfunc} on '{val_col}'...")
                df = df.groupby(index_cols + [attr_col], as_index=False)[val_col].agg(aggfunc)
            else:
                raise ValueError(
                    f"Duplicate rows found for key {index_cols + [attr_col]} and duplicate_policy="
                    f"{dup_policy!r}; set plan.duplicate_policy='aggregate' with an "
                    f"aggregation function, or deduplicate the source data"
                )

        logger.info(f"[Extractor] Pivoting DataFrame with index={index_cols}, columns={attr_col}, values={val_col}...")
        pivoted_df = df.pivot(index=index_cols, columns=attr_col, values=val_col).reset_index()
        pivoted_df.columns.name = None

        if selected_cols:
            keep_cols = [c for c in index_cols if c in pivoted_df.columns]
            for c in selected_cols:
                if c in pivoted_df.columns and c not in keep_cols:
                    keep_cols.append(c)
            pivoted_df = pivoted_df[keep_cols]

        logger.info(f"[Extractor] Long-format transform complete. Output shape: {pivoted_df.shape}")
        return pivoted_df

    else:
        raise ValueError(f"Unknown structure_type: '{structure_type}'")


def load_all_sources(data_dir: str | Path | None = None, force_reanalyze: bool = False) -> dict[str, pd.DataFrame]:
    """Parse and extract all supported source files into DataFrames."""
    target_data_dir = Path(data_dir).resolve() if data_dir else PATHS.data_dir
    sources: dict[str, pd.DataFrame] = {}

    if not target_data_dir.exists():
        logger.warning(f"[Extractor] Target data directory does not exist: {target_data_dir}")
        return sources

    for root, _, files in os.walk(target_data_dir):
        for f in sorted(files):
            ext = os.path.splitext(f)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, target_data_dir)
                source_key = os.path.splitext(f)[0]

                logger.info(f"[Extractor] Loading source: '{rel_path}' as key '{source_key}'")
                if force_reanalyze or source_key not in _last_plans:
                    try:
                        preview_df = pd.read_csv(full_path, nrows=50) if ext == ".csv" else pd.read_excel(full_path, nrows=50)
                        planner = ExtractionPlanner()
                        plan_resp = planner.build_plan(str(preview_df.head(20).to_dict(orient="records")), list(preview_df.columns), filename=f)
                        _last_plans[source_key] = plan_resp.model_dump()
                    except Exception as e:
                        logger.warning(f"[Extractor] Fallback to default plan for '{f}': {e}")
                        _last_plans[source_key] = {"structure_type": "tabular_column_as_attribute", "selected_columns": []}

                plan = _last_plans[source_key]
                try:
                    df = extract_with_plan(full_path, plan)
                    sources[source_key] = df
                except Exception as e:
                    logger.error(f"[Extractor] Failed to extract source '{full_path}': {e}")
                    raise

    return sources


class ExtractionService:
    """Orchestration service for Extraction and Ontology Mapping domain."""

    def __init__(
        self,
        planner: Optional[ExtractionPlanner] = None,
        repository: Optional[ExtractionRepository] = None,
    ) -> None:
        self.planner = planner or ExtractionPlanner()
        self.repository = repository or ExtractionRepository()

    def _resolve_dataset_path(self, request: ExtractionRequest) -> Path:
        """Resolve dataset_id / dataset_version / source_uri to a concrete readable file path."""
        if request.source_uri:
            p = Path(request.source_uri)
            if p.is_file():
                return p
            root_p = PATHS.models_store.parent / request.source_uri
            if root_p.is_file():
                return root_p
            for base in (PATHS.data_dir, PATHS.data_preprocessed):
                candidate = base / request.source_uri
                if candidate.is_file():
                    return candidate

        candidates = [
            PATHS.data_dir / request.dataset_id / f"{request.dataset_version}.csv",
            PATHS.data_dir / f"{request.dataset_id}.csv",
            PATHS.data_dir / request.dataset_id / "input.csv",
            PATHS.data_preprocessed / request.dataset_id / f"{request.dataset_version}.csv",
            PATHS.data_preprocessed / f"{request.dataset_id}.csv",
            PATHS.data_preprocessed / request.dataset_id / "input.csv",
            PATHS.data_dir / request.dataset_id,
            PATHS.data_preprocessed / request.dataset_id,
        ]

        for cand in candidates:
            if cand.is_file():
                return cand
            if cand.is_dir():
                for child in sorted(cand.iterdir()):
                    if child.is_file() and child.suffix.lower() in SUPPORTED_EXTENSIONS:
                        return child

        raise DatasetNotFoundError(
            f"데이터셋을 찾을 수 없습니다: dataset_id='{request.dataset_id}', "
            f"version='{request.dataset_version}', source_uri='{request.source_uri}'"
        )

    def validate_plan(self, df_preview: pd.DataFrame, plan: dict[str, Any]) -> None:
        """Validate extraction plan against actual dataframe preview."""
        cols = list(df_preview.columns)
        st_type = plan.get("structure_type", "tabular_column_as_attribute")

        if st_type == "tabular_row_as_attribute":
            id_col = plan.get("id_column")
            attr_col = plan.get("attribute_column")
            val_col = plan.get("value_column")
            time_col = plan.get("time_column")

            missing_roles = []
            if not id_col:
                missing_roles.append("id_column")
            if not attr_col:
                missing_roles.append("attribute_column")
            if not val_col:
                missing_roles.append("value_column")

            if missing_roles:
                raise ExtractionRoleError(
                    f"Long-format extraction failed: missing required role(s) {missing_roles}."
                )

            missing = []
            if id_col not in cols:
                missing.append(f"id_column='{id_col}'")
            if attr_col not in cols:
                missing.append(f"attribute_column='{attr_col}'")
            if val_col not in cols:
                missing.append(f"value_column='{val_col}'")
            if time_col and time_col not in cols:
                missing.append(f"time_column='{time_col}'")

            if missing:
                raise ExtractionPlanValidationError(
                    f"추출 계획에 선언된 컬럼이 데이터셋에 존재하지 않습니다: {missing}"
                )

    def run_extraction(self, request: ExtractionRequest, request_id: Optional[str] = None) -> ExtractionResponse:
        """Execute end-to-end extraction and ontology mapping workflow."""
        req_id = request_id or f"req-{uuid.uuid4().hex[:12]}"
        run_id = f"extraction-{uuid.uuid4().hex[:12]}"

        dataset_path = self._resolve_dataset_path(request)
        ext = dataset_path.suffix.lower()

        try:
            preview_df = pd.read_csv(dataset_path, nrows=50) if ext == ".csv" else pd.read_excel(dataset_path, nrows=50)
        except Exception as exc:
            raise DatasetContractError(f"데이터셋을 읽는 중 오류가 발생했습니다: {exc}") from exc

        logger.info(f"[ExtractionService] Building extraction plan for '{dataset_path.name}'...")
        plan_dict = self.planner.build_plan(
            filepath=str(dataset_path),
            force_reanalyze=request.force_reanalyze,
            duplicate_policy=request.duplicate_policy,
            aggregation=request.aggregation,
        )
        self.validate_plan(preview_df, plan_dict)

        # Extract data using validated plan
        try:
            extracted_df = extract_with_plan(str(dataset_path), plan_dict)
        except Exception as exc:
            raise ExtractionPlanValidationError(f"추출 계획 실행 검증 실패: {exc}") from exc

        # Perform & Persist Ontology Mapping (Mandatory for /extraction)
        from systems.generator.ontology_mapping.mapping_cache import MappingStore
        from systems.generator.ontology_mapping.mapping_agent import map_all_sources

        dataset_store = MappingStore()
        source_key = os.path.splitext(dataset_path.name)[0]
        sources_dict = {source_key: extracted_df}
        try:
            map_all_sources(sources_dict, store=dataset_store)
        except Exception as exc:
            logger.exception(f"[ExtractionService] Ontology mapping generation failed: {exc}")
            raise ExtractionPlanPublishError(f"온톨로지 매핑 생성에 실패했습니다: {exc}") from exc

        mapping_dict = {
            k: {
                "target_ontology": v.target_ontology,
                "source": v.source,
                "confidence": v.confidence,
                "status": v.status,
            }
            for k, v in dataset_store.get_all().items()
        }

        # Publish content-addressed plan and mapping
        plan_version, plan_uri = self.repository.publish_plan(
            request.dataset_id,
            request.dataset_version,
            plan_dict,
        )
        mapping_version, mapping_uri = self.repository.publish_mapping(
            request.dataset_id,
            request.dataset_version,
            mapping_dict,
            extracted_columns=list(extracted_df.columns),
        )

        return ExtractionResponse(
            request_id=req_id,
            run_id=run_id,
            status="succeeded",
            dataset_id=request.dataset_id,
            dataset_version=request.dataset_version,
            extraction_plan_version=plan_version,
            result=ExtractionResultPayload(
                extraction_type=plan_dict.get("structure_type", "tabular_column_as_attribute"),
                id_column=plan_dict.get("id_column"),
                time_column=plan_dict.get("time_column"),
                attribute_column=plan_dict.get("attribute_column"),
                value_column=plan_dict.get("value_column"),
                duplicate_policy=plan_dict.get("duplicate_policy", "error"),
                aggregation=plan_dict.get("aggregation"),
                mapping_version=mapping_version,
                mapping_uri=mapping_uri,
            ),
        )
