"""
generator_llm_client.py

담당 기능:
- Generator 도메인 전역 LLM 호출 서비스(call_llm) 및 Pydantic 스키마 검증/다중 변환기(validate_or_transform_pydantic) 모듈.
- OpenAI Chat Completions API(gpt-4o-mini) 호출을 통해 RAW 텍스트 응답을 수신하며, Pydantic 검증 ➔ 실패 시 Multi-Format Transformer(JSON/YAML/KV/CSV) ➔ Pydantic 스키마 재검증 ➔ 실패 시 None(Fail-Fast) 4단계 파이프라인으로 동작한다.

입력:
- prompt(str): LLM에 전달할 사용자 프롬프트
- system(str, optional): system 역할 프롬프트. 기본값 "You are a helpful assistant."
- raw_text(str): LLM 수신 RAW 응답 텍스트
- pydantic_cls(type[T]): 검증 및 정제할 Pydantic 스키마 모델 클래스

출력:
- call_llm(): LLM RAW 응답 텍스트 (str)
- validate_or_transform_pydantic(): 스키마 검증이 완료된 Pydantic 모델 인스턴스 또는 실패 시 None

의존 모듈:
- generator_config.load_config: API 키 로딩 전 환경변수 세팅.
- openai.OpenAI: OpenAI 공식 API 클라이언트.
- pydantic.BaseModel, json, re, yaml, logging

예외/경계 상황:
- OPENAI_API_KEY 미설정 시 ValueError 발생.
- Pydantic 스키마 검증 및 파싱 실패 시 경고 로그 후 None을 안전하게 반환한다(Fail-Fast).

설계 원칙과의 연결:
- docs/architecture.md의 '타입 안전 스키마 검증' 및 '단일 책임 원칙'에 따라 스키마 검증과 포맷 변환을 캡슐화하여 제공한다.
"""

import os
import sys
import json
import re
import yaml
import logging
from typing import Any, TypeVar, Optional, Literal
from pydantic import BaseModel, Field

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from openai import OpenAI
from systems.generator.generator_config import load_config

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# --- Pydantic Response Schemas ---

class ExtractionStructureResponse(BaseModel):
    structure_type: str = "tabular_column_as_attribute"
    reason: Optional[str] = None


class ExtractionColumnsResponse(BaseModel):
    selected_columns: list[str] = Field(default_factory=list)


class ExtractionPlanResponse(BaseModel):
    structure_type: str = "tabular_column_as_attribute"
    selected_columns: list[str] = Field(default_factory=list)
    id_column: Optional[str] = None
    time_column: Optional[str] = None
    attribute_column: Optional[str] = None
    value_column: Optional[str] = None
    duplicate_policy: Literal["error", "aggregate"] = "error"
    aggregation: Optional[Literal["mean", "first", "sum"]] = None
    reason: Optional[str] = None


class ColumnMappingResponse(BaseModel):
    ontology_node: str = "Unknown"
    confidence: float = 0.5
    reason: Optional[str] = None


class FileProfileResponse(BaseModel):
    role: str = "unknown"
    description: str = ""
    id_columns: list[str] = Field(default_factory=list)
    time_columns: list[dict] = Field(default_factory=list)
    column_notes: dict[str, str] = Field(default_factory=dict)
    confidence: float = 0.9


def call_llm(prompt: str, system: str = "You are a helpful assistant.") -> str:
    """Generator 전용 LLM 호출 클라이언트 (RAW 텍스트 응답 수신 전용)."""
    load_config()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY environment variable is missing.")
        raise ValueError("OPENAI_API_KEY가 설정되어 있지 않습니다.")

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ],
        temperature=0.0
    )
    return response.choices[0].message.content.strip()


def transform_to_structured_data(raw_text: str, expected_type: type = dict) -> Any | None:
    """LLM 수신 응답 텍스트(raw_text)를 정규 JSON Dict/List 객체로 변환하는 변환기."""
    if not raw_text or not isinstance(raw_text, str):
        return None

    cleaned = raw_text.strip()

    # 1. 마크다운 코드 블록 태그 정제
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 2 and lines[-1].strip().startswith("```"):
            cleaned = "\n".join(lines[1:-1]).strip()

    # 2. 규격 JSON 파싱
    try:
        data = json.loads(cleaned)
        if isinstance(data, expected_type):
            return data
    except (json.JSONDecodeError, TypeError):
        pass

    # 3. YAML 파싱
    try:
        yaml_data = yaml.safe_load(cleaned)
        if isinstance(yaml_data, expected_type):
            logger.info("[Transformer] YAML 응답을 성공적으로 구조체로 변환함")
            return yaml_data
    except Exception:
        pass

    # 4. Key-Value / 화살표 (->, =>, :, =) 라인 파싱 (dict 전용)
    if expected_type is dict:
        kv_result = {}
        pattern = re.compile(r"^\s*[-*]?\s*[`'\"]?(\w+)[`'\"]?\s*(?:->|=>|:|=)\s*[`'\"]?(\w+)[`'\"]?", re.MULTILINE)
        matches = pattern.findall(cleaned)
        if matches:
            for k, v in matches:
                kv_result[k] = v
            logger.info(f"[Transformer] Key-Value/화살표 문장 {len(kv_result)}개를 성공적으로 Dict로 변환함")
            return kv_result

        # 5. CSV / Tab 구분 라인 파싱
        csv_result = {}
        for line in cleaned.splitlines():
            parts = re.split(r"[,;\t]+", line.strip())
            if len(parts) == 2:
                key, val = parts[0].strip(" -`'\""), parts[1].strip(" -`'\"")
                if key and val and key != val:
                    csv_result[key] = val
        if csv_result:
            logger.info(f"[Transformer] CSV/Tab 구분 라인 {len(csv_result)}개를 성공적으로 Dict로 변환함")
            return csv_result

    logger.warning("[Transformer] 모든 응답 형식(JSON/YAML/KV/CSV) 변환 실패 -> Rule-based 폴백 전달")
    return None


def validate_or_transform_pydantic(raw_text: str, pydantic_cls: type[T]) -> Optional[T]:
    """
    Pydantic 스키마 검증 ➔ 실패 시 Multi-Format Transformer ➔ Pydantic 스키마 재검증 4단계 파이프라인.
    """
    if not raw_text:
        return None

    # 1. Pydantic 직접 검증 시도
    try:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if len(lines) >= 2 and lines[-1].strip().startswith("```"):
                cleaned = "\n".join(lines[1:-1]).strip()
        return pydantic_cls.model_validate_json(cleaned)
    except Exception:
        pass

    # 2. 다중 변환기(JSON/YAML/KV/CSV) 시도
    transformed = transform_to_structured_data(raw_text, expected_type=dict)
    if transformed and isinstance(transformed, dict):
        try:
            return pydantic_cls.model_validate(transformed)
        except Exception as e:
            logger.warning(f"[PydanticValidator] Transformed dict validation failed for {pydantic_cls.__name__}: {e}")

    logger.warning(f"[PydanticValidator] Failed to validate or transform raw text for {pydantic_cls.__name__}")
    return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=== Generator LLM Client Standalone Self-Test ===")
    sample_raw = "```yaml\nstructure_type: wide_pivot\nreason: wide format\n```"
    res = validate_or_transform_pydantic(sample_raw, ExtractionStructureResponse)
    assert res is not None and res.structure_type == "wide_pivot", f"Failed: {res}"
    print("[SUCCESS] Pydantic validator & transformer self-test passed!")
