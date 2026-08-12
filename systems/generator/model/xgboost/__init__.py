"""
__init__.py (XGBoostModel)

담당 기능:
- XGBoost 기반 예지보전 고장 확률 예측 모델 클래스.
- train()을 통해 시계열 피처 데이터셋으로 학습하고, predict()를 통해 최근 1행에 대한 고장 확률 및 SHAP 기여도/기능 중요도를 계산한다.

입력:
- df(pd.DataFrame): 피처 및 라벨 데이터프레임 (train) / 최근 센서 피처 데이터프레임 (predict)

출력:
- PredictionOutput: 고장 확률(failure_probability), 확신도(confidence), feature_importance, shap_values

의존 모듈:
- xgboost: XGBClassifier 모델
- shap: TreeExplainer 기반 SHAP 수치 산출
- joblib: 모델 직렬화/복원
- systems.generator.prediction.prediction_schema.PredictionOutput: 결과 스키마

예외/경계 상황:
- SHAP 계산 시 차원에 따른 배열 형태 차이를 안전하게 플래튼 처리한다.

설계 원칙과의 연결:
- docs/architecture.md의 '독립 모델 캡슐화' 원칙에 따라 상속 없이 독립 클래스로 구현한다.
"""

import logging
import joblib
import pandas as pd
import xgboost as xgb
import shap
from systems.generator.prediction.prediction_schema import PredictionOutput

logger = logging.getLogger(__name__)


class XGBoostModel:
    name = "xgboost"

    def __init__(self):
        self.model = None
        self.feature_cols = None

    def train(self, df: pd.DataFrame, target_col: str = "label", id_col: str = None, time_col: str = None):
        """XGBoost 분류기를 학습한다."""
        exclude = set(filter(None, ["datetime", "observed_at", "machineID", "asset_id", target_col, id_col, time_col]))
        self.feature_cols = [c for c in df.columns if c not in exclude]
        X, y = df[self.feature_cols], df[target_col]
        self.model = xgb.XGBClassifier(eval_metric="logloss")
        self.model.fit(X, y)

    def predict(self, df: pd.DataFrame) -> PredictionOutput:
        """최근 1행 피처에 대한 고장 확률 및 SHAP 수치를 추론한다."""
        last_row = df[self.feature_cols].iloc[[-1]]
        proba = self.model.predict_proba(last_row)[0][1]

        explainer = shap.TreeExplainer(self.model)
        shap_values = explainer.shap_values(last_row)

        import numpy as np
        if isinstance(shap_values, list):
            sv = np.array(shap_values[1])[0]
        elif isinstance(shap_values, np.ndarray):
            if len(shap_values.shape) == 3:
                sv = shap_values[0, :, 1]
            else:
                sv = shap_values[0]
        else:
            sv = np.array(shap_values)[0]

        sv = np.array(sv).flatten()
        shap_dict = dict(zip(self.feature_cols, [float(v) for v in sv]))
        importance = dict(zip(self.feature_cols, [float(v) for v in self.model.feature_importances_]))

        return PredictionOutput(
            failure_probability=float(proba),
            confidence=float(max(proba, 1 - proba)),
            feature_importance=importance,
            shap_values=shap_dict
        )

    def save(self, path: str):
        """모델 및 피처 컬럼 정보를 디스크 파일에 저장한다."""
        joblib.dump({"model": self.model, "feature_cols": self.feature_cols}, path)

    def load(self, path: str):
        """디스크 파일에서 모델 및 피처 컬럼 정보를 로드한다."""
        data = joblib.load(path)
        self.model = data["model"]
        self.feature_cols = data["feature_cols"]
