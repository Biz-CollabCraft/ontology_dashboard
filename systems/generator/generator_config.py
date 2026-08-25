"""
generator_config.py

담당 기능:
- 시스템 전역 환경변수(.env) 싱글톤 로더 및 경로 레지스트리(GeneratorPaths) 모듈.
- PROJECT_ROOT(프로젝트 최상위 디렉토리)를 기준으로 경로를 동적 계산하되, .env에 DATA_DIR, DATA_PREPROCESSED_DIR, MODELS_STORE_DIR, ONTOLOGY_DIR이 설정되어 있으면 해당 외부 경로를 최우선으로 적용한다.

입력:
- force(bool, optional): True 설정 시 기존 로딩 여부와 관계없이 강제로 .env 재로드. 기본값 False.

출력:
- load_config(): 환경변수를 os.environ에 주입
- PROJECT_ROOT(Path): 프로젝트 최상위 루트 디렉토리 Path 객체
- PATHS(GeneratorPaths): 전역 디렉토리 및 영속 파일 경로 레지스트리

의존 모듈:
- dotenv.load_dotenv: .env 파일 파싱 모듈.
- pathlib.Path, os, logging

예외/경계 상황:
- .env 파일 미존재 시 기본 디렉토리(data, data_preprocessed 등)로 안전하게 폴백한다.

설계 원칙과의 연결:
- docs/architecture.md의 '단일 경로 제어 및 이기종 데이터 위치 수용' 원칙에 따라 마이그레이션 없이 환경변수로 원본 데이터 디렉토리를 제어한다.
"""

import os
import logging
from pathlib import Path
logger = logging.getLogger(__name__)
_config_loaded = False

# 프로젝트 최상위 루트 디렉토리 (systems/generator/generator_config.py 이므로 parents[2])
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_config(force: bool = False) -> None:
    """.env 파일에서 전역 환경변수를 읽어 설정한다."""
    global _config_loaded
    if _config_loaded and not force:
        return
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(dotenv_path=env_path)
            logger.info(f"[GeneratorConfig] Loaded '{env_path}'")
        except ImportError:
            logger.warning("[GeneratorConfig] dotenv package not installed; skipping .env load")
        except Exception as e:
            logger.warning(f"[GeneratorConfig] Failed to load .env at '{env_path}': {e}")
    else:
        logger.warning(f"[GeneratorConfig] .env not found at '{env_path}'.")
    _config_loaded = True


class GeneratorPaths:
    """Generator 시스템 전역 디렉토리 및 영속 파일 경로 레지스트리 (.env 오버라이드 지원)"""
    def __init__(self):
        load_config()

        # 1. 디렉토리 경로 (.env 설정 우선, 미설정 시 PROJECT_ROOT 하위 기본 디렉토리)
        data_env = os.getenv("DATA_DIR")
        self.data_dir: Path = Path(data_env).resolve() if data_env else PROJECT_ROOT / "data"

        preprocessed_env = os.getenv("DATA_PREPROCESSED_DIR")
        self.data_preprocessed: Path = Path(preprocessed_env).resolve() if preprocessed_env else PROJECT_ROOT / "data_preprocessed"

        models_env = os.getenv("MODELS_STORE_DIR")
        self.models_store: Path = Path(models_env).resolve() if models_env else PROJECT_ROOT / "models_store"

        ontology_env = os.getenv("ONTOLOGY_DIR")
        self.ontology: Path = Path(ontology_env).resolve() if ontology_env else PROJECT_ROOT / "ontology"

        # 2. 핵심 영속 파일 전용 경로
        self.extraction_plan_cache: Path = self.data_preprocessed / "extraction_plan_cache.json"
        self.source_family_registry: Path = self.data_preprocessed / "source_family_registry.json"
        self.mapping_cache: Path = self.ontology / "mapping_cache.json"
        self.feature_catalog: Path = PROJECT_ROOT / "systems" / "generator" / "feature" / "feature_catalog.yaml"
        self.registry_json: Path = self.models_store / "registry.json"
        self.predictions_dir: Path = self.data_preprocessed / "predictions"

    def ensure_directories(self) -> None:
        """필요 디렉토리가 존재하는지 검사하고 자동 생성한다."""
        for path in (self.data_preprocessed, self.models_store, self.ontology, self.predictions_dir):
            path.mkdir(parents=True, exist_ok=True)


PATHS = GeneratorPaths()
PATHS.ensure_directories()
