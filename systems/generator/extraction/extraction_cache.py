"""
extraction_cache.py

담당 기능:
- 추출 계획(Extraction Plan) 캐시 관리 모듈.
- 소스 파일 샘플 데이터프레임의 md5 fingerprint 해시값을 기반으로 기존 추출 계획을 캐싱하고 조회/저장한다.

입력:
- df_preview(pd.DataFrame): 파일의 프리뷰 데이터프레임 (fingerprint 계산용)
- cache(dict): 저장할 캐시 객체 (save_plan_cache)

출력:
- compute_fingerprint: md5 32자리 해시 문자열
- load_plan_cache: 캐시 딕셔너리 객체

의존 모듈:
- pandas: 데이터프레임 프리뷰 파싱 및 json 변환
- hashlib: md5 해시 산출

예외/경계 상황:
- 캐시 파일(data_preprocessed/extraction_plan_cache.json)이 없거나 파싱 실패 시 빈 딕셔너리를 반환하며 새로 생성한다.

설계 원칙과의 연결:
- docs/architecture.md의 '결과 재사용 및 LLM 비용 최적화' 원칙에 따라 동일 구조 파일의 불필요한 재분석을 방지한다.
"""

import os
import json
import logging
import hashlib
import pandas as pd

logger = logging.getLogger(__name__)

EXTRACTION_PLAN_CACHE_PATH = "data_preprocessed/extraction_plan_cache.json"

_plan_cache: dict = {}
_cache_mtime: float = 0.0


def load_plan_cache() -> dict:
    """캐시 파일에서 추출 계획 캐시를 읽어 반환한다."""
    global _plan_cache, _cache_mtime
    if os.path.exists(EXTRACTION_PLAN_CACHE_PATH):
        mtime = os.path.getmtime(EXTRACTION_PLAN_CACHE_PATH)
        if _cache_mtime == mtime and _plan_cache:
            return _plan_cache
        try:
            with open(EXTRACTION_PLAN_CACHE_PATH, "r", encoding="utf-8") as f:
                _plan_cache = json.load(f)
                _cache_mtime = mtime
                return _plan_cache
        except Exception as e:
            logger.warning(f"[ExtractionPlanner] Failed to load plan cache: {e}")
    _plan_cache = {}
    return _plan_cache


def save_plan_cache(cache: dict) -> None:
    """추출 계획 캐시를 파일에 영속화한다."""
    global _plan_cache, _cache_mtime
    os.makedirs(os.path.dirname(os.path.abspath(EXTRACTION_PLAN_CACHE_PATH)), exist_ok=True)
    with open(EXTRACTION_PLAN_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    _plan_cache = cache
    if os.path.exists(EXTRACTION_PLAN_CACHE_PATH):
        _cache_mtime = os.path.getmtime(EXTRACTION_PLAN_CACHE_PATH)


def compute_fingerprint(df_preview: pd.DataFrame) -> str:
    """df_preview의 컬럼명과 헤더 샘플 텍스트를 기반으로 md5 해시를 생성한다."""
    raw_str = f"cols:{list(df_preview.columns)}|head:{df_preview.head(3).to_json()}"
    return hashlib.md5(raw_str.encode("utf-8")).hexdigest()
