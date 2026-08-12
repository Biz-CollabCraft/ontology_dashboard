"""
model_registry.py

담당 기능:
- 등록된 예측 모델 클래스 매핑(REGISTERED_MODELS) 관리 및 경로 레지스트리(PATHS.models_store) 기준 모델 버전 관리 레지스트리 서비스.
- models_store/registry.json 파일에 전역 학습 실행 버전(latest_run_version), 실행별 공유 메타데이터(runs/v{N}), 모델별 최신 성공 버전 정보(models/{model_name})를 기록 관리한다.

입력:
- model_name(str): 모델 식별 키 ("lightgbm", "xgboost", "random_forest")
- run_version(int): 전역 1-indexed 학습 실행 버전 번호
- model_results(dict): 모델별 성공 결과 딕셔너리 (실패한 모델은 None)
- run_artifacts_meta(dict): 학습 실행 공유 메타데이터 (feature_cols, trained_at 등)
- store_dir(str | Path, optional): 모델 저장소 디렉토리 경로. 미지정 시 PATHS.models_store 사용.

출력:
- REGISTERED_MODELS(dict): {model_name: ModelClass}
- get_next_run_version(): 다음 학습 실행 버전 번호 (int)
- get_latest_model_path(): 해당 모델이 마지막으로 성공한 버전의 model_v{N}.joblib 파일 경로 (str | None)
- has_any_trained_model(): 성공한 모델 존재 여부 (bool)

의존 모듈:
- systems.generator.model.lightgbm.LightGBMModel
- systems.generator.model.xgboost.XGBoostModel
- systems.generator.model.random_forest.RandomForestModel
- systems.generator.generator_config.PATHS
- os, json, logging

예외/경계 상황:
- registry.json 파일이 없으면 기본 딕셔너리({"latest_run_version": 0, "runs": {}, "models": {}})로 자동 초기화한다.

설계 원칙과의 연결:
- docs/architecture.md의 '소유권 기준 버전 관리' 원칙에 따라 학습 실행(run) 전체 공유 산출물과 모델 개별 아티팩트를 명확히 구별하여 보존한다.
"""

import os
import json
import logging
from pathlib import Path
from systems.generator.model.lightgbm import LightGBMModel
from systems.generator.model.xgboost import XGBoostModel
from systems.generator.model.random_forest import RandomForestModel
from systems.generator.generator_config import PATHS

logger = logging.getLogger(__name__)

REGISTERED_MODELS = {
    "lightgbm": LightGBMModel,
    "xgboost": XGBoostModel,
    "random_forest": RandomForestModel,
}

REGISTRY_PATH = str(PATHS.registry_json)


def _resolve_store_dir(store_dir: str | Path | None = None) -> Path:
    if store_dir is None:
        return PATHS.models_store
    return Path(store_dir).resolve()


def load_registry(store_dir: str | Path | None = None) -> dict:
    """models_store/registry.json 파일에서 전체 레지스트리를 읽어 반환한다."""
    resolved_dir = _resolve_store_dir(store_dir)
    path = resolved_dir / "registry.json"
    if not path.exists():
        return {"latest_run_version": 0, "runs": {}, "models": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[ModelRegistry] Failed to load registry from '{path}': {e}")
        return {"latest_run_version": 0, "runs": {}, "models": {}}


def get_next_run_version(store_dir: str | Path | None = None) -> int:
    """전역 학습 실행 버전 번호를 하나 발급한다(모델별이 아니라 실행 전체 기준)."""
    registry = load_registry(store_dir)
    return registry.get("latest_run_version", 0) + 1


def save_run_result(
    run_version: int,
    model_results: dict,
    run_artifacts_meta: dict,
    store_dir: str | Path | None = None,
) -> None:
    """
    학습 실행 1회의 결과를 registry.json에 기록한다.
    - runs[str(run_version)]에 이번 실행의 공유 메타데이터를 기록
    - models[name]는 성공한 모델만 latest_version을 이번 run_version으로 갱신
    """
    resolved_dir = _resolve_store_dir(store_dir)
    path = resolved_dir / "registry.json"
    registry = load_registry(store_dir)

    registry["latest_run_version"] = run_version
    registry.setdefault("runs", {})[str(run_version)] = run_artifacts_meta

    registry.setdefault("models", {})
    for name, result in model_results.items():
        if result is None:
            continue
        registry["models"][name] = {
            "latest_version": run_version,
            "path": result["path"],
            "train_positive_rate": result.get("train_positive_rate"),
        }

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)
    logger.info(f"[ModelRegistry] Saved run v{run_version} result to '{path}'")


def get_latest_model_path(model_name: str, store_dir: str | Path | None = None) -> str | None:
    """해당 모델이 마지막으로 성공한 버전의 파일 경로(폴더 없이 파일명 버전)."""
    registry = load_registry(store_dir)
    model_entry = registry.get("models", {}).get(model_name)
    if not model_entry:
        return None
    return model_entry["path"]


def has_any_trained_model(store_dir: str | Path | None = None) -> bool:
    """학습에 성공하여 등록된 모델이 하나라도 존재하는지 확인한다."""
    registry = load_registry(store_dir)
    return len(registry.get("models", {})) > 0
