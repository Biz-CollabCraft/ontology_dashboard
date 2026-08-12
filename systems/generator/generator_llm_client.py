"""
generator_llm_client.py

담당 기능:
- Generator 도메인 전역 LLM 호출 서비스 모듈.
- GeneratorConfig를 자동으로 로드한 뒤 OpenAI Chat Completions API(gpt-4o-mini)를 호출하여 답변 텍스트를 반환한다.

입력:
- prompt(str): LLM에 전달할 사용자 프롬프트
- system(str, optional): system 역할 프롬프트. 기본값 "You are a helpful assistant."

출력:
- response_text(str): LLM 응답 텍스트 (strip 처리됨)

의존 모듈:
- generator_config.load_config: API 키 로딩 전 환경변수 세팅.
- openai.OpenAI: OpenAI 공식 API 클라이언트.

예외/경계 상황:
- OPENAI_API_KEY 환경변수가 미설정된 경우 ValueError 예외를 발생시킨다.
- API 호출 타임아웃 또는 네트워크 오류 발생 시 OpenAI 예외를 전파한다.

설계 원칙과의 연결:
- docs/architecture.md의 'LLM 호출 단일 창구' 원칙에 따라 추론 및 분류 모듈이 동일 클라이언트를 사용한다.
"""

import os
import sys
import logging

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from openai import OpenAI
from systems.generator.generator_config import load_config

logger = logging.getLogger(__name__)


def call_llm(prompt: str, system: str = "You are a helpful assistant.") -> str:
    """Generator 전용 LLM 호출 클라이언트."""
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=== Generator LLM Client Standalone Self-Test ===")
    try:
        res = call_llm("Ping! Reply with 'PONG' only.", system="You are a test assistant.")
        print(f"[SUCCESS] Response: '{res}'")
    except Exception as e:
        print(f"[FAIL] Error during LLM call: {e}")
