"""
extraction_service.py

담당 기능:
- 소스 데이터셋 변환 실행 및 전체 파일 순회 로딩 오케스트레이션 서비스 모듈.
- build_extraction_plan()이 만든 플랜에 맞춰 실제 데이터프레임 구조 변환(extract_with_plan)을 수행하고, 지정 디렉토리 내의 지원 데이터셋 파일들을 일괄 수집(load_all_sources)한다.

입력:
- data_dir(str): 소스 데이터셋 폴더 경로
- force_reanalyze(bool): 재분석 여부

출력:
- sources(dict): {file_key: pd.DataFrame} 구조의 파싱 완료 데이터셋 딕셔너리

의존 모듈:
- extraction_agent.build_extraction_plan: 파일별 추출 계획 수립.
- extraction_profiler.build_family_registry: Stage 0 프로파일링 메타데이터 생성.
- pandas: 데이터프레임 로드 및 피벗/선택 조작.

예외/경계 상황:
- 지원되지 않는 확장자의 파일은 건너뛴다.
- data_dir 미존재 시 ValueError 발생.

설계 원칙과의 연결:
- docs/architecture.md의 '추출 서비스 격리' 원칙에 따라 데이터 로딩 및 구조 정형화를 전담 처리한다.
"""

import os
import logging
import pandas as pd
from systems.generator.extraction.extraction_agent import build_extraction_plan
from systems.generator.extraction.extraction_profiler import build_family_registry

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = (".csv", ".xlsx", ".xls")
_last_plans: dict = {}


def extract_with_plan(filepath: str, plan: dict) -> pd.DataFrame:
    """build_extraction_plan()이 반환한 plan에 따라 실제 pandas 데이터프레임 로드 및 형태 변환을 수행한다."""
    ext = os.path.splitext(filepath)[1].lower()
    logger.info(f"[Extractor] Reading file '{filepath}' (ext: {ext})...")

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
            logger.warning(f"[Extractor] None of the selected columns {selected_cols} exist in '{filepath}'. Keeping all columns.")
            valid_cols = list(df.columns)

        extracted_df = df[valid_cols].copy()
        logger.info(f"[Extractor] Successfully extracted {len(valid_cols)} columns from '{filepath}'. Output shape: {extracted_df.shape}")
        return extracted_df

    elif structure_type == "tabular_row_as_attribute":
        logger.info(f"[Extractor] Performing contract-driven tabular_row_as_attribute transform for '{filepath}'...")
        id_col = plan.get("id_column") or (df.columns[0] if len(df.columns) >= 1 else None)
        time_col = plan.get("time_column") or next((c for c in df.columns if c in ("observed_at", "datetime", "timestamp")), None)
        attr_col = plan.get("attribute_column") or (df.columns[1] if len(df.columns) >= 2 else None)
        val_col = plan.get("value_column") or (df.columns[2] if len(df.columns) >= 3 else None)

        if not id_col or not attr_col or not val_col or id_col not in df.columns or attr_col not in df.columns or val_col not in df.columns:
            logger.warning(f"[Extractor] Required long-format contract columns ({id_col}, {attr_col}, {val_col}) missing in '{filepath}'. Keeping original df.")
            return df

        from systems.generator.common.timestamp_canonicalizer import canonicalize_timestamp_series
        if time_col and time_col in df.columns:
            df[time_col] = canonicalize_timestamp_series(df[time_col], col_name=time_col)
            index_cols = [id_col, time_col]
        else:
            index_cols = [id_col]

        # Check uniqueness of (index_cols + [attr_col])
        check_cols = index_cols + [attr_col]
        has_duplicates = df.duplicated(subset=check_cols).any()

        dup_policy = plan.get("duplicate_policy", "error")
        aggfunc = plan.get("aggregation")

        if has_duplicates:
            if dup_policy == "aggregate" and aggfunc:
                logger.info(f"[Extractor] Duplicate entries found in long-format '{filepath}'. Aggregating using '{aggfunc}'...")
                pivoted = df.pivot_table(index=index_cols, columns=attr_col, values=val_col, aggfunc=aggfunc).reset_index()
                return pivoted
            else:
                raise ValueError(
                    f"Long-format dataset '{filepath}' contains duplicate observation entries for keys {check_cols} "
                    f"without an explicit aggregation policy (duplicate_policy='{dup_policy}')."
                )

        pivoted = df.pivot(index=index_cols, columns=attr_col, values=val_col).reset_index()
        pivoted.columns.name = None
        logger.info(f"[Extractor] Successfully pivoted long-format dataset '{filepath}'. Output shape: {pivoted.shape}")
        return pivoted

    elif structure_type == "wide_pivot":
        logger.info(f"[Extractor] Performing wide_pivot transform for '{filepath}'...")
        return df

    else:
        raise NotImplementedError(f"Extraction for structure type '{structure_type}' is not implemented.")


def load_all_sources(data_dir: str, force_reanalyze: bool = False) -> dict:
    """data_dir 내의 파일들에 대해 Stage 0 프로파일링 ➔ 플랜 수립 ➔ 변환 추출을 순차 수행한다."""
    global _last_plans
    logger.info(f"[Loader] Loading all sources from data_dir: '{data_dir}' (force_reanalyze={force_reanalyze})")
    if not os.path.exists(data_dir):
        raise ValueError(f"Directory missing: {data_dir}")

    build_family_registry(data_dir)
    sources = {}
    plans = {}
    for filename in sorted(os.listdir(data_dir)):
        ext = os.path.splitext(filename)[1].lower()
        if ext in SUPPORTED_EXTENSIONS:
            filepath = os.path.join(data_dir, filename)
            key = os.path.splitext(filename)[0]
            logger.info(f"[Loader] Processing source file: '{filename}' (key: '{key}')...")

            plan = build_extraction_plan(filepath, force_reanalyze=force_reanalyze)
            df = extract_with_plan(filepath, plan)
            sources[key] = df
            plans[key] = plan

    _last_plans = plans
    logger.info(f"[Loader] Successfully loaded {len(sources)} source datasets from '{data_dir}'.")
    return sources


def get_last_plans() -> dict:
    """가장 최근 load_all_sources() 호출에서 만들어진 plan 정보를 조회한다."""
    return _last_plans
