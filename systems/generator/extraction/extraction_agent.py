"""
extraction_agent.py

담당 기능:
- 원본 파일의 헤더와 샘플 행(최대 5행)을 LLM에 전달해 구조를 2단계로 판별한다.
  1단계는 tabular_column_as_attribute / tabular_row_as_attribute / wide_pivot / unsupported 중 하나로 구조를 분류하고,
  2단계는 실제로 추출할 컬럼 목록을 선정한다. 두 판단은 서로 다른 LLM 호출로 분리되어 있다.

입력:
- filepath(str): 원본 데이터셋 파일 경로
- force_reanalyze(bool): True 설정 시 캐시를 무시하고 무조건 재분석 구동. 기본값 False.

출력:
- dict: {"filepath": str, "filename": str, "fingerprint": str, "structure_type": str, "selected_columns": list[str]}

의존 모듈:
- systems.generator.generator_llm_client.call_llm: LLM 호환 클라이언트.
- extraction_cache.py: fingerprint 기반 캐시 로드/저장.
- pandas: 엑셀 및 CSV 샘플 프리뷰 파싱.

예외/경계 상황:
- unsupported 구조 타입 감지 시 NotImplementedError 발생.
- LLM 호출 실패 시 기본값(tabular_column_as_attribute 및 전체 컬럼)으로 안전하게 폴백한다.

설계 원칙과의 연결:
- docs/architecture.md의 '판단 단계 분리' 원칙에 따라 구조 판별과 컬럼 선택을 개별 프롬프트 단계로 구별한다.
"""

import os
import json
import logging
import pandas as pd
from systems.generator.generator_llm_client import call_llm
from systems.generator.extraction.extraction_cache import (
    load_plan_cache,
    save_plan_cache,
    compute_fingerprint,
)

logger = logging.getLogger(__name__)


def classify_structure(filepath: str, df_preview: pd.DataFrame) -> str:
    """Stage 1: 오직 파일 구조 타입만 판별한다."""
    system_prompt = (
        "You are a manufacturing data structure classifier.\n"
        "Classify the input table format into EXACTLY ONE of the following structure types:\n"
        "- tabular_column_as_attribute: Standard table where each column is an attribute/sensor feature.\n"
        "- tabular_row_as_attribute: Long format table where rows contain sensor attribute names and values.\n"
        "- wide_pivot: Wide format matrix requiring reshaping.\n"
        "- unsupported: Unparseable unstructured text or binary.\n\n"
        "Respond ONLY with a JSON object: {\"structure_type\": \"...\", \"reason\": \"...\"}"
    )
    prompt = f"File: {os.path.basename(filepath)}\nColumns: {list(df_preview.columns)}\nSample:\n{df_preview.head(3).to_string()}"

    try:
        res = call_llm(prompt, system=system_prompt)
        parsed = json.loads(res)
        st_type = parsed.get("structure_type", "tabular_column_as_attribute")
        logger.info(f"[ExtractionPlanner] Stage 1 structure classification for '{filepath}': {st_type}")
        return st_type
    except Exception as e:
        logger.warning(f"[ExtractionPlanner] Stage 1 classification failed: {e}. Defaulting to tabular_column_as_attribute.")
        return "tabular_column_as_attribute"


def plan_extraction(filepath: str, structure_type: str, df_preview: pd.DataFrame) -> list[str]:
    """Stage 2: 오직 추출할 컬럼 목록만 선택한다."""
    system_prompt = (
        "You are a dataset column selector for manufacturing predictive maintenance.\n"
        "Select all relevant telemetry sensors, time/date fields, and asset identifiers for model analysis.\n"
        "Respond ONLY with a JSON object: {\"selected_columns\": [\"col1\", \"col2\", ...]}"
    )
    prompt = (
        f"File: {os.path.basename(filepath)}\n"
        f"Structure Type: {structure_type}\n"
        f"Available Columns: {list(df_preview.columns)}\n"
        f"Sample:\n{df_preview.head(3).to_string()}"
    )

    try:
        res = call_llm(prompt, system=system_prompt)
        parsed = json.loads(res)
        cols = parsed.get("selected_columns", list(df_preview.columns))
        logger.info(f"[ExtractionPlanner] Stage 2 column selection for '{filepath}': {cols}")
        return cols
    except Exception as e:
        logger.warning(f"[ExtractionPlanner] Stage 2 column selection failed: {e}. Fallback to all columns.")
        return list(df_preview.columns)


def enforce_key_columns(selected_columns: list[str], available_columns: list[str]) -> list[str]:
    """machineID/asset_id, datetime/observed_at 등의 주요 키가 누락되었을 시 강제로 보존한다."""
    result = list(selected_columns)

    id_candidates = ["asset_id", "machineID", "equipment_id", "device_id", "asset", "machine"]
    time_candidates = ["observed_at", "datetime", "timestamp", "time", "date"]

    has_id = any(c in result for c in id_candidates)
    if not has_id:
        found_id = next((c for c in available_columns if c in id_candidates), None)
        if found_id and found_id not in result:
            result.append(found_id)
            logger.info(f"[ExtractionPlanner] Enforced key column ID: '{found_id}'")

    has_time = any(c in result for c in time_candidates)
    if not has_time:
        found_time = next((c for c in available_columns if c in time_candidates), None)
        if found_time and found_time not in result:
            result.append(found_time)
            logger.info(f"[ExtractionPlanner] Enforced key column Time: '{found_time}'")

    return result


def build_extraction_plan(filepath: str, force_reanalyze: bool = False) -> dict:
    """오케스트레이션 함수: 캐시 확인 ➔ LLM 2단계 분석 ➔ 주요 키 보존 ➔ 캐시 저장."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".csv":
        df_preview = pd.read_csv(filepath, nrows=5)
    elif ext in (".xlsx", ".xls"):
        df_preview = pd.read_excel(filepath, nrows=5)
    else:
        raise ValueError(f"Unsupported file format: {ext}")

    fingerprint = compute_fingerprint(df_preview)
    cache = load_plan_cache()

    file_key = os.path.basename(filepath)
    if not force_reanalyze and file_key in cache:
        cached_plan = cache[file_key]
        if cached_plan.get("fingerprint") == fingerprint:
            logger.info(f"[ExtractionPlanner] Cache HIT for '{file_key}'. Reusing plan without LLM calls.")
            return cached_plan

    logger.info(f"[ExtractionPlanner] Cache MISS for '{file_key}'. Executing 2-stage LLM plan analysis...")
    structure_type = classify_structure(filepath, df_preview)
    if structure_type == "unsupported":
        raise NotImplementedError(f"File '{filepath}' classified as unsupported format.")

    raw_selected = plan_extraction(filepath, structure_type, df_preview)
    final_selected = enforce_key_columns(raw_selected, list(df_preview.columns))

    plan = {
        "filepath": filepath,
        "filename": file_key,
        "fingerprint": fingerprint,
        "structure_type": structure_type,
        "selected_columns": final_selected
    }

    cache[file_key] = plan
    save_plan_cache(cache)
    logger.info(f"[ExtractionPlanner] Saved new extraction plan for '{file_key}' into cache.")
    return plan
