"""Model Registry and Trainer base definitions for Generator."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol
import numpy as np

from systems.generator.app.training.training_exception import (
    TrainingDependencyError,
    TrainingExecutionError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrainedModelResult:
    """Internal contract returned by model trainer implementations."""
    base_model: str
    model: object
    metrics: dict[str, float]
    feature_importance: dict[str, float] | None
    training_duration_seconds: float


def compute_binary_metrics(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    threshold: float = 0.5,
) -> dict[str, float]:
    """Compute binary classification metrics safely."""
    from sklearn.metrics import (
        accuracy_score,
        precision_score,
        recall_score,
        f1_score,
        roc_auc_score,
        average_precision_score,
    )

    y_pred = (y_prob >= threshold).astype(int)
    metrics: dict[str, float] = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
    }

    try:
        if len(np.unique(y_true)) > 1:
            metrics["roc_auc"] = float(roc_auc_score(y_true, y_prob))
            metrics["pr_auc"] = float(average_precision_score(y_true, y_prob))
        else:
            metrics["roc_auc"] = 0.5
            metrics["pr_auc"] = 0.0
    except Exception:
        metrics["roc_auc"] = 0.5
        metrics["pr_auc"] = 0.0

    return metrics


class ModelTrainer(Protocol):
    """Protocol for model trainers."""

    base_model: str

    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
        feature_names: list[str],
        **kwargs: Any,
    ) -> TrainedModelResult:
        ...


class LightGBMTrainer:
    """LightGBM classifier trainer."""

    base_model: str = "lightgbm"

    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
        feature_names: list[str],
        **kwargs: Any,
    ) -> TrainedModelResult:
        start_time = time.perf_counter()
        try:
            import lightgbm as lgb
        except ImportError as exc:
            raise TrainingDependencyError(f"LightGBM 라이브러리를 임포트할 수 없습니다: {exc}") from exc

        try:
            clf = lgb.LGBMClassifier(
                random_state=42,
                verbosity=-1,
                n_estimators=100,
                **kwargs,
            )
            clf.fit(X_train, y_train)

            # Evaluate on validation set (or train if val empty)
            eval_X = X_val if len(X_val) > 0 else X_train
            eval_y = y_val if len(y_val) > 0 else y_train
            probs = clf.predict_proba(eval_X)[:, 1]
            metrics = compute_binary_metrics(eval_y, probs)

            # Feature importance
            importance_dict: dict[str, float] = {}
            if hasattr(clf, "feature_importances_"):
                importances = clf.feature_importances_
                for idx, feat_name in enumerate(feature_names):
                    if idx < len(importances):
                        importance_dict[feat_name] = float(importances[idx])

            duration = time.perf_counter() - start_time
            return TrainedModelResult(
                base_model=self.base_model,
                model=clf,
                metrics=metrics,
                feature_importance=importance_dict,
                training_duration_seconds=duration,
            )
        except Exception as exc:
            if isinstance(exc, TrainingDependencyError):
                raise
            raise TrainingExecutionError(f"LightGBM 학습 실행 실패: {exc}") from exc


class XGBoostTrainer:
    """XGBoost classifier trainer."""

    base_model: str = "xgboost"

    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
        feature_names: list[str],
        **kwargs: Any,
    ) -> TrainedModelResult:
        start_time = time.perf_counter()
        try:
            import xgboost as xgb
        except ImportError as exc:
            raise TrainingDependencyError(f"XGBoost 라이브러리를 임포트할 수 없습니다: {exc}") from exc

        try:
            clf = xgb.XGBClassifier(
                random_state=42,
                eval_metric="logloss",
                n_estimators=100,
                **kwargs,
            )
            clf.fit(X_train, y_train)

            eval_X = X_val if len(X_val) > 0 else X_train
            eval_y = y_val if len(y_val) > 0 else y_train
            probs = clf.predict_proba(eval_X)[:, 1]
            metrics = compute_binary_metrics(eval_y, probs)

            importance_dict: dict[str, float] = {}
            if hasattr(clf, "feature_importances_"):
                importances = clf.feature_importances_
                for idx, feat_name in enumerate(feature_names):
                    if idx < len(importances):
                        importance_dict[feat_name] = float(importances[idx])

            duration = time.perf_counter() - start_time
            return TrainedModelResult(
                base_model=self.base_model,
                model=clf,
                metrics=metrics,
                feature_importance=importance_dict,
                training_duration_seconds=duration,
            )
        except Exception as exc:
            if isinstance(exc, TrainingDependencyError):
                raise
            raise TrainingExecutionError(f"XGBoost 학습 실행 실패: {exc}") from exc


class RandomForestTrainer:
    """RandomForest classifier trainer."""

    base_model: str = "random_forest"

    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
        feature_names: list[str],
        **kwargs: Any,
    ) -> TrainedModelResult:
        start_time = time.perf_counter()
        try:
            from sklearn.ensemble import RandomForestClassifier
        except ImportError as exc:
            raise TrainingDependencyError(f"scikit-learn 라이브러리를 임포트할 수 없습니다: {exc}") from exc

        try:
            clf = RandomForestClassifier(
                random_state=42,
                n_estimators=100,
                n_jobs=2,
                **kwargs,
            )
            clf.fit(X_train, y_train)

            eval_X = X_val if len(X_val) > 0 else X_train
            eval_y = y_val if len(y_val) > 0 else y_train
            probs = clf.predict_proba(eval_X)[:, 1]
            metrics = compute_binary_metrics(eval_y, probs)

            importance_dict: dict[str, float] = {}
            if hasattr(clf, "feature_importances_"):
                importances = clf.feature_importances_
                for idx, feat_name in enumerate(feature_names):
                    if idx < len(importances):
                        importance_dict[feat_name] = float(importances[idx])

            duration = time.perf_counter() - start_time
            return TrainedModelResult(
                base_model=self.base_model,
                model=clf,
                metrics=metrics,
                feature_importance=importance_dict,
                training_duration_seconds=duration,
            )
        except Exception as exc:
            if isinstance(exc, TrainingDependencyError):
                raise
            raise TrainingExecutionError(f"RandomForest 학습 실행 실패: {exc}") from exc


REGISTERED_MODELS: dict[str, type[ModelTrainer]] = {
    "lightgbm": LightGBMTrainer,
    "xgboost": XGBoostTrainer,
    "random_forest": RandomForestTrainer,
}
