"""
generator_llm_client.py

담당 기능:
- Generator 도메인 전역 LLM 호출 서비스(call_llm) 및 다중 응답 형식 다각도 구조 변환기(transform_to_structured_data) 모듈.
- OpenAI Chat Completions API(gpt-4o-mini) 호출을 통해 RAW 텍스트 응답을 수신하고, 이를 JSON/YAML/Key-Value/CSV 다중 변환기를 통해 정규 JSON Dict/List 객체로 안전하게 변환한다.

입력:
- prompt(str): LLM에 전달할 사용자 프롬프트
- system(str, optional): system 역할 프롬프트. 기본값 "You are a helpful assistant."
- raw_text(str): LLM 수신 RAW 응답 텍스트
- expected_type(type, optional): 기대 데이터 구조 타입 (dict 또는 list). 기본값 dict.

출력:
- call_llm(): LLM RAW 응답 텍스트 (str)
- transform_to_structured_data(): 정규화된 Dict/List 객체 또는 변환 실패 시 None

의존 모듈:
- generator_config.load_config: API 키 로딩 전 환경변수 세팅.
- openai.OpenAI: OpenAI 공식 API 클라이언트.
- json, re, yaml, logging

예외/경계 상황:
- OPENAI_API_KEY 미설정 시 ValueError 발생.
- JSON 문법 파싱 및 YAML/KV/CSV 모든 변환 시도가 실패한 경우 경고 로그 후 None을 안전하게 반환한다(Fail-Fast).

설계 원칙과의 연결:
- docs/architecture.md의 '단일 마이그레이션 파사드' 및 '단일 책임 원칙'에 따라 LLM호출(작업1)과 다중 형식 JSON 변환(작업2)을 독립된 기능으로 명확히 분리 관리한다.
"""

import os
import sys
import json
import re
import yaml
import logging
from typing import Any

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from openai import OpenAI
from systems.generator.generator_config import load_config

logger = logging.getLogger(__name__)


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
    """
    LLM 수신 응답 텍스트(raw_text)를 수용하여 정규 JSON Dict/List 객체로 변환하는 전용 변환기(Multi-Format Transformer).
    JSON ➔ YAML ➔ Key-Value/화살표 ➔ CSV 순으로 다각도 구조 변환을 시도하며, 스키마 검증 실패 시 None을 반환한다.
    """
    if not raw_text or not isinstance(raw_text, str):
        return None

    cleaned = raw_text.strip()

    # 1. 마크다운 코드 블록(```json ... ``` 또는 ``` ... ```) 정제
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 2 and lines[-1].strip().startswith("```"):
            cleaned = "\n".join(lines[1:-1]).strip()

    # 2. 규격 JSON 파싱 시도
    try:
        data = json.loads(cleaned)
        if isinstance(data, expected_type):
            return data
    except (json.JSONDecodeError, TypeError):
        pass

    # 3. YAML 변환 시도 (LLM이 인덴트/목록 형태로 응답한 경우)
    try:
        yaml_data = yaml.safe_load(cleaned)
        if isinstance(yaml_data, expected_type):
            logger.info("[Transformer] YAML 응답 텍스트를 성공적으로 구조체로 변환함")
            return yaml_data
    except Exception:
        pass

    # 4. Key-Value / 화살표 (->, =>, :, =) 라인 정규식 파싱 시도 (dict 전용)
    if expected_type is dict:
        kv_result = {}
        pattern = re.compile(r"^\s*[-*]?\s*[`'\"]?(\w+)[`'\"]?\s*(?:->|=>|:|=)\s*[`'\"]?(\w+)[`'\"]?", re.MULTILINE)
        matches = pattern.findall(cleaned)
        if matches:
            for k, v in matches:
                kv_result[k] = v
            logger.info(f"[Transformer] Key-Value/화살표 문장 {len(kv_result)}개를 성공적으로 Dict로 변환함")
            return kv_result

        # 5. CSV / Tab 구분 라인 파싱 시도
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=== Generator LLM Client Standalone Self-Test ===")
    sample_markdown_json = "```json\n{\"test_key\": \"test_val\"}\n```"
    res = transform_to_structured_data(sample_markdown_json)
    assert res == {"test_key": "test_val"}, f"Expected dict, got {res}"
    print("[SUCCESS] Transformer self-test passed!")
