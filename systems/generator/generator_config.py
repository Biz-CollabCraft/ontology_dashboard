"""
generator_config.py

담당 기능:
- 시스템 전역 환경변수(.env) 싱글톤 로더 모듈.
- 실행 시 루트 디렉토리의 .env 파일을 찾아 os.environ으로 로드하며 중복 로드를 방지한다.

입력:
- force(bool, optional): True 설정 시 기존 로딩 여부와 관계없이 강제로 .env 재로드. 기본값 False.

출력:
- None: 환경변수가 os.environ에 주입된다.

의존 모듈:
- dotenv.load_dotenv: .env 파일 파싱 모듈.
- logging: 환경변수 로딩 결과 로그 기록.

예외/경계 상황:
- .env 파일이 지정 위치에 존재하지 않는 경우 경고 로그를 남기고 기본 환경변수를 유지한다.
- 파일 접근 권한 문제 발생 시 예외를 포착하고 경고 로그를 남긴다.

설계 원칙과의 연결:
- docs/architecture.md의 '단일 설정 관리' 원칙에 따라 모든 서비스 모듈이 동일한 설정 로더를 공유한다.
"""

import os
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
_config_loaded = False


def load_config(force: bool = False) -> None:
    """.env 파일에서 전역 환경변수를 읽어 설정한다."""
    global _config_loaded
    if _config_loaded and not force:
        return
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env_path = os.path.join(root_dir, ".env")
    if os.path.exists(env_path):
        try:
            load_dotenv(dotenv_path=env_path)
            logger.info(f"[GeneratorConfig] Loaded '{env_path}'")
        except Exception as e:
            logger.warning(f"[GeneratorConfig] Failed to load .env at '{env_path}': {e}")
    else:
        logger.warning(f"[GeneratorConfig] .env not found at '{env_path}'.")
    _config_loaded = True
