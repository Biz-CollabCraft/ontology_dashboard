"""
__init__.py (prediction package)

담당 기능:
- prediction 도메인 공개 서비스 파사드 패키지 초기화 모듈.
- PredictionOutput DTO, save_prediction_result 파일 저장 함수, run_prediction 추론 서비스, get_current_snapshot 스냅샷 조회를 파사드로 재노출한다.

입력:
- None

출력:
- export symbols: PredictionOutput, save_prediction_result, run_prediction, get_current_snapshot

의존 모듈:
- prediction_schema: PredictionOutput
- prediction_repository: save_prediction_result
- prediction_service: run_prediction, get_current_snapshot

예외/경계 상황:
- 하위 모듈 미존재 시 ImportError 예외 발생

설계 원칙과의 연결:
- docs/architecture.md의 '도메인 서비스 파사드' 원칙에 따라 외부에 일관된 진입점을 제공한다.
"""

import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parents[3])
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from systems.generator.prediction.prediction_schema import PredictionOutput
from systems.generator.prediction.prediction_repository import save_prediction_result
from systems.generator.prediction.prediction_service import run_prediction, get_current_snapshot

__all__ = ["PredictionOutput", "save_prediction_result", "run_prediction", "get_current_snapshot"]
