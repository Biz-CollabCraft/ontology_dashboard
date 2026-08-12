"""
prediction_schema.py

담당 기능:
- 예측 결과 출력 DTO 스키마 클래스 (PredictionOutput).
- 고장 확률(failure_probability), 확신도(confidence), 상태 등급(status_grade), 타임스탬프(prediction_timestamp), 피처 중요도(feature_importance), SHAP 기여도 수치(shap_values)를 정의한다.

입력:
- failure_probability(float): 고장 발생 확률 (0.0 ~ 1.0)
- confidence(float): 확신도 수치
- feature_importance(dict): 피처별 상대 중요도 맵
- shap_values(dict): 피처별 SHAP 기여 수치 맵

출력:
- PredictionOutput Pydantic 데이터 모델

의존 모듈:
- pydantic.BaseModel: 데이터 검증 및 직렬화

예외/경계 상황:
- 선택적 입력 필드가 None으로 전달되어도 기본값(빈 딕셔너리/None)으로 정상 세팅된다.

설계 원칙과의 연결:
- docs/architecture.md의 '도메인 소유권 분리' 원칙에 따라 backend 역참조를 막고 prediction 도메인 소유로 정의한다.
"""

from pydantic import BaseModel
from typing import Dict, Optional


class PredictionOutput(BaseModel):
    failure_probability: float
    confidence: float
    status_grade: Optional[str] = None
    predicted_failure_type: Optional[str] = None
    prediction_timestamp: str = ""
    feature_importance: Dict[str, float] = {}
    shap_values: Optional[Dict[str, float]] = None
