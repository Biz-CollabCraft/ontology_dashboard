"""
__init__.py (model package)

담당 기능:
- model 도메인 공개 모듈 초기화 및 서비스 함수 파사드.

입력:
- None

출력:
- export symbols: train_all, run_parsing_only, REGISTERED_MODELS, load_registry, get_latest_model_path, has_any_trained_model

의존 모듈:
- model_training: train_all, run_parsing_only
- model_registry: REGISTERED_MODELS, load_registry, get_latest_model_path, has_any_trained_model

예외/경계 상황:
- None

설계 원칙과의 연결:
- docs/architecture.md의 '도메인 서비스 파사드' 원칙에 따라 외부에 일관된 진입점을 제공한다.
"""

from systems.generator.model.model_training import train_all, run_parsing_only
from systems.generator.model.model_registry import (
    REGISTERED_MODELS,
    load_registry,
    get_latest_model_path,
    has_any_trained_model,
)

__all__ = [
    "train_all",
    "run_parsing_only",
    "REGISTERED_MODELS",
    "load_registry",
    "get_latest_model_path",
    "has_any_trained_model",
]
