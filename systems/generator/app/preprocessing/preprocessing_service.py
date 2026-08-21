"""Orchestration service for dataset resolution, planning, validation, and preprocessing."""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any, Optional
import pandas as pd

from systems.generator.generator_config import PATHS
from systems.generator.common.timestamp_canonicalizer import canonicalize_timestamp_series
from systems.generator.app.preprocessing.preprocessing_profiler import build_family_registry, load_family_registry
from systems.generator.app.preprocessing.preprocessing_schema import (
    PreprocessingRequest,
    PreprocessingResponse,
    PreprocessingResultPayload,
    PreprocessingPlanResponse,
)
from systems.generator.app.preprocessing.preprocessing_exception import (
    PreprocessingError,
    DatasetNotFoundError,
    DatasetContractError,
    PreprocessingRoleError,
    PreprocessingPlanValidationError,
    PreprocessingPlanningError,
)
from systems.generator.app.preprocessing.preprocessing_planner import PreprocessingPlanner
from systems.generator.app.preprocessing.preprocessing_repository import PreprocessingRepository

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = (".csv", ".xlsx", ".xls")
_last_plans: dict[str, Any] = {}


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


def preprocess_with_plan(filepath: str, plan: dict[str, Any]) -> pd.DataFrame:
    """Execute dataframe loading and transformation based on the validated preprocessing plan."""
    ext = os.path.splitext(filepath)[1].lower()
    logger.info(f"[Preprocessor] Reading file '{filepath}' (ext: {ext})...")

    if ext == ".csv":
        df = pd.read_csv(filepath)
    elif ext in (".xlsx", ".xls"):
        df = pd.read_excel(filepath)
    else:
        raise ValueError(f"Unsupported file extension: {ext}")

    structure_type = plan.get("structure_type", "tabular_column_as_attribute")
    selected_cols = plan.get("selected_columns", list(df.columns))

    if structure_type == "tabular_column_as_attribute":
        valid_cols = [c for c in selected_cols if c in df.columns]
        if not valid_cols:
            logger.warning(f"[Preprocessor] None of selected columns {selected_cols} exist in '{filepath}'. Keeping all.")
            valid_cols = list(df.columns)

        extracted_df = df[valid_cols].copy()

        id_col = plan.get("id_column")
        time_col = plan.get("time_column")
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

        logger.info(f"[Preprocessor] Successfully processed {len(valid_cols)} columns from '{filepath}'. Output shape: {extracted_df.shape}")
        return extracted_df

    elif structure_type == "tabular_row_as_attribute":
        logger.info(f"[Preprocessor] Performing contract-driven tabular_row_as_attribute transform for '{filepath}'...")
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
            raise PreprocessingRoleError(
                f"Long-format preprocessing for '{filepath}' failed: missing required role(s) {missing_roles}. "
                f"Specified roles: id_column={id_col!r}, attribute_column={attr_col!r}, value_column={val_col!r}, time_column={time_col!r}."
            )

        missing_cols = [c for c in [id_col, attr_col, val_col] if c not in df.columns]
        if time_col and time_col not in df.columns:
            missing_cols.append(time_col)

        if missing_cols:
            raise PreprocessingPlanValidationError(
                f"Long-format preprocessing for '{filepath}' failed: specified role columns {missing_cols} not found in DataFrame."
            )

        roles = [id_col, attr_col, val_col]
        if time_col:
            roles.append(time_col)
        if len(roles) != len(set(roles)):
            raise PreprocessingPlanValidationError(
                f"Long-format preprocessing for '{filepath}' failed: role columns must be unique and cannot overlap: {roles}."
            )

        if time_col and time_col in df.columns:
            df[time_col] = canonicalize_timestamp_series(df[time_col], col_name=time_col)
            index_cols = [id_col, time_col]
        else:
            index_cols = [id_col]

        check_cols = index_cols + [attr_col]
        has_duplicates = df.duplicated(subset=check_cols).any()

        dup_policy = plan.get("duplicate_policy", "error")
        aggfunc = plan.get("aggregation")

        if has_duplicates:
            if dup_policy == "aggregate" and aggfunc:
                logger.info(f"[Preprocessor] Duplicate entries found in long-format '{filepath}'. Aggregating using '{aggfunc}'...")
                pivoted = df.pivot_table(index=index_cols, columns=attr_col, values=val_col, aggfunc=aggfunc).reset_index()
                return pivoted
            else:
                raise ValueError(
                    f"Long-format dataset '{filepath}' contains duplicate observation entries for keys {check_cols} "
                    f"without an explicit aggregation policy (duplicate_policy='{dup_policy}')."
                )

        pivoted = df.pivot(index=index_cols, columns=attr_col, values=val_col).reset_index()
        pivoted.columns.name = None
        logger.info(f"[Preprocessor] Successfully pivoted long-format dataset '{filepath}'. Output shape: {pivoted.shape}")
        return pivoted

    elif structure_type == "wide_pivot":
        return df

    else:
        raise NotImplementedError(f"Preprocessing for structure type '{structure_type}' is not implemented.")


extract_with_plan = preprocess_with_plan


def load_all_sources(data_dir: str, force_reanalyze: bool = False) -> dict[str, pd.DataFrame]:
    """Legacy helper: profile, plan, and load all files in data_dir."""
    global _last_plans
    if not os.path.exists(data_dir):
        raise ValueError(f"Directory missing: {data_dir}")

    build_family_registry(data_dir)
    planner = PreprocessingPlanner()
    sources = {}
    plans = {}
    for filename in sorted(os.listdir(data_dir)):
        ext = os.path.splitext(filename)[1].lower()
        if ext in SUPPORTED_EXTENSIONS:
            filepath = os.path.join(data_dir, filename)
            key = os.path.splitext(filename)[0]
            plan = planner.build_plan(filepath, force_reanalyze=force_reanalyze)
            df = preprocess_with_plan(filepath, plan)
            sources[key] = df
            plans[key] = plan

    _last_plans = plans
    return sources


def get_last_plans() -> dict[str, Any]:
    return _last_plans


class PreprocessingService:
    """Orchestrates preprocessing requests end-to-end."""

    def __init__(
        self,
        planner: Optional[PreprocessingPlanner] = None,
        repository: Optional[PreprocessingRepository] = None,
    ) -> None:
        self.planner = planner or PreprocessingPlanner()
        self.repository = repository or PreprocessingRepository()

    def _resolve_dataset_path(self, request: PreprocessingRequest) -> Path:
        """Resolve dataset_id / dataset_version / source_uri to a concrete readable file path."""
        allowed_roots = [PATHS.data_dir.resolve(), PATHS.data_preprocessed.resolve()]

        # 1. Direct source_uri if provided
        if request.source_uri:
            raw_uri = str(request.source_uri).strip()
            p = Path(raw_uri)
            # Security checks: relative path only, no directory traversal
            if p.is_absolute() or ".." in p.parts:
                raise DatasetContractError(
                    "source_uri는 허용된 데이터 루트(data_dir, data_preprocessed) 내 상대경로 파일이어야 하며 절대경로/상위경로(..)는 허용되지 않습니다."
                )

            found_path: Optional[Path] = None
            for base in allowed_roots:
                candidate = (base / raw_uri).resolve()
                if _is_within_allowed_root(candidate, allowed_roots) and candidate.is_file():
                    found_path = candidate
                    break

            if not found_path:
                repo_root = PATHS.models_store.parent.resolve()
                repo_candidate = (repo_root / raw_uri).resolve()
                if _is_within_allowed_root(repo_candidate, allowed_roots) and repo_candidate.is_file():
                    found_path = repo_candidate

            if found_path:
                return found_path

            # Check if file exists outside allowed roots (e.g. repository root files)
            repo_root = PATHS.models_store.parent.resolve()
            outside_candidate = (repo_root / raw_uri).resolve()
            if outside_candidate.is_file():
                raise DatasetContractError(
                    f"source_uri '{request.source_uri}'는 허용된 데이터 루트 외부의 파일입니다. 데이터 루트 내부 상대경로만 허용됩니다."
                )

            raise DatasetNotFoundError(
                f"지정한 source_uri 파일을 허용된 데이터 루트에서 찾을 수 없습니다: '{request.source_uri}'"
            )

        # 2. Lookup by dataset_id and dataset_version
        id_path = Path(str(request.dataset_id).strip())
        ver_path = Path(str(request.dataset_version).strip())
        if id_path.is_absolute() or ".." in id_path.parts or ver_path.is_absolute() or ".." in ver_path.parts:
            raise DatasetContractError(
                "dataset_id 및 dataset_version에 절대경로나 상위경로(..)는 허용되지 않습니다."
            )

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
            resolved_cand = cand.resolve()
            if not _is_within_allowed_root(resolved_cand, allowed_roots):
                continue

            if resolved_cand.is_file():
                return resolved_cand
            if resolved_cand.is_dir():
                for child in sorted(resolved_cand.iterdir()):
                    resolved_child = child.resolve()
                    if _is_within_allowed_root(resolved_child, allowed_roots):
                        if resolved_child.is_file() and resolved_child.suffix.lower() in SUPPORTED_EXTENSIONS:
                            return resolved_child

        raise DatasetNotFoundError(
            f"데이터셋을 찾을 수 없습니다: dataset_id='{request.dataset_id}', "
            f"version='{request.dataset_version}'"
        )

    def validate_plan(self, df_preview: pd.DataFrame, plan: dict[str, Any]) -> None:
        """Validate preprocessing plan against actual dataframe preview."""
        cols = list(df_preview.columns)
        st_type = plan.get("structure_type", "tabular_column_as_attribute")

        if st_type == "tabular_row_as_attribute":
            id_col = plan.get("id_column")
            attr_col = plan.get("attribute_column")
            val_col = plan.get("value_column")
            time_col = plan.get("time_column")

            if not id_col or not attr_col or not val_col:
                raise PreprocessingRoleError(
                    "Long-format preprocessing requires explicit id_column, attribute_column, and value_column."
                )

            roles = [id_col, attr_col, val_col]
            if time_col:
                roles.append(time_col)

            if len(roles) != len(set(roles)):
                raise PreprocessingPlanValidationError(
                    f"Long-format role columns must be unique and cannot overlap: {roles}"
                )

            missing = [r for r in roles if r not in cols]
            if missing:
                raise PreprocessingPlanValidationError(
                    f"Declared role columns {missing} not found in dataset columns: {cols}"
                )

        selected = plan.get("selected_columns")
        if selected:
            valid_selected = [c for c in selected if c in cols]
            if not valid_selected:
                raise PreprocessingPlanValidationError(
                    f"None of the selected columns {selected} exist in dataset: {cols}"
                )

    def run_preprocessing(self, request: PreprocessingRequest, request_id: Optional[str] = None) -> PreprocessingResponse:
        """Execute full preprocessing workflow and return structured PreprocessingResponse."""
        req_id = request_id or f"req-{uuid.uuid4().hex[:12]}"
        run_id = f"preprocessing-{uuid.uuid4().hex[:12]}"

        # 1. Resolve dataset
        dataset_path = self._resolve_dataset_path(request)
        logger.info(f"[PreprocessingService] Resolved dataset path: '{dataset_path.name}' for {request.dataset_id}")

        # 2. Preview dataset
        ext = dataset_path.suffix.lower()
        if ext == ".csv":
            df_preview = pd.read_csv(dataset_path, nrows=5)
        elif ext in (".xlsx", ".xls"):
            df_preview = pd.read_excel(dataset_path, nrows=5)
        else:
            raise DatasetContractError(f"지원하지 않는 파일 형식입니다: {ext}")

        if df_preview.empty or len(df_preview.columns) == 0:
            raise DatasetContractError("데이터셋이 비어 있거나 컬럼이 존재하지 않습니다.")

        # 3. Check existing plan or generate new plan
        existing_plan = None if request.force_reanalyze else self.repository.find_plan(request.dataset_id, request.dataset_version)
        if existing_plan:
            logger.info(f"[PreprocessingService] Reusing existing plan for {request.dataset_id}:{request.dataset_version}")
            plan = existing_plan
        else:
            logger.info(f"[PreprocessingService] Generating new preprocessing plan for {request.dataset_id}:{request.dataset_version}")
            plan = self.planner.build_plan(
                str(dataset_path),
                force_reanalyze=request.force_reanalyze,
                duplicate_policy=request.duplicate_policy,
                aggregation=request.aggregation,
            )

        # 4. Validate plan
        self.validate_plan(df_preview, plan)

        # 5. Execute full dataset preprocessing with plan to verify full transform success
        try:
            preprocess_with_plan(str(dataset_path), plan)
        except PreprocessingError:
            raise
        except Exception as exc:
            logger.warning(f"[PreprocessingService] Preprocessing execution failed with plan: {exc}")
            raise PreprocessingPlanningError(
                f"전처리 계획 적용 실행에 실패했습니다: {exc}",
                details=[{"stage": "execution", "error": str(exc)}],
            ) from exc

        # 6. Atomically persist plan only after full execution succeeds
        mapping_uri = self.repository.publish_plan(
            request.dataset_id,
            request.dataset_version,
            plan,
            overwrite=request.force_reanalyze,
        )

        plan_version = f"preprocessing-plan-{request.dataset_id}-{request.dataset_version}"

        return PreprocessingResponse(
            request_id=req_id,
            run_id=run_id,
            status="succeeded",
            dataset_id=request.dataset_id,
            dataset_version=request.dataset_version,
            preprocessing_plan_version=plan_version,
            result=PreprocessingResultPayload(
                extraction_type=plan.get("structure_type", "tabular_column_as_attribute"),
                structure_type=plan.get("structure_type", "tabular_column_as_attribute"),
                id_column=plan.get("id_column"),
                time_column=plan.get("time_column"),
                attribute_column=plan.get("attribute_column"),
                value_column=plan.get("value_column"),
                duplicate_policy=plan.get("duplicate_policy", request.duplicate_policy),
                aggregation=plan.get("aggregation", request.aggregation),
                mapping_uri=mapping_uri,
            ),
        )


ExtractionService = PreprocessingService
