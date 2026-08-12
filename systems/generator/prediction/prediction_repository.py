"""
prediction_repository.py

담당 기능:
- 최신 버전 모델 인스턴스 인메모리 로딩 및 캐싱(_get_or_load_model)과 예측 결과 파일 영속화(save_prediction_result) 모듈.
- model_registry.get_latest_model_path를 사용해 항상 최신 재학습 버전(v{N}) 모델을 동적으로 로드하며, 예측 결과 및 텔레메트리 행을 data_preprocessed/predictions/ 디렉토리에 JSON 파일로 보존한다.

입력:
- name(str): 모델명 ("lightgbm", "xgboost", "random_forest")
- store_dir(str): 모델 저장소 경로
- predictions(dict): 추론 결과 딕셔너리
- rows(list[dict]): 추론에 사용된 텔레메트리 입력 행 목록
- out_dir(str): 예측 결과 저장 디렉토리 경로

출력:
- model: 로드된 모델 인스턴스
- saved_path(str): 생성된 예측 결과 파일 경로

의존 모듈:
- systems.generator.model.model_registry.get_latest_model_path: 최신 버전 모델 경로 조회
- systems.generator.model.model_registry.REGISTERED_MODELS: 모델 클래스 매핑

예외/경계 상황:
- 최신 버전 모델 파일이 존재하지 않는 경우 None을 반환하며 로그를 기록한다.
- 파일 저장 실패 시 예외를 발생시켜 상위 호출부에 전달하며, 상위 파이프라인에서 저장 오류만 기록하도록 격리한다.

설계 원칙과의 연결:
- docs/architecture.md의 '격리된 파일 저장소' 원칙에 따라 학습 경로와 독립적으로 예측 결과 파일 저장을 수행한다.
"""

import os
import json
import logging
from datetime import datetime, timezone
logger = logging.getLogger(__name__)

_model_cache: dict[str, tuple[float, object]] = {}


def _get_or_load_model(name: str, store_dir: str = "models_store"):
    """최신 버전(latest_version)의 모델 인스턴스를 인메모리 로드/캐시한다."""
    from systems.generator.model.model_registry import REGISTERED_MODELS, get_latest_model_path

    path = get_latest_model_path(name, store_dir=store_dir)
    if not path or not os.path.exists(path):
        logger.warning(f"[PredictionRepository] Latest model file path '{path}' for '{name}' does not exist.")
        return None

    mtime = os.path.getmtime(path)
    cached = _model_cache.get(name)
    if cached and cached[0] == mtime:
        logger.debug(f"[PredictionRepository] Reusing in-memory instance for model '{name}' (path: {path}, mtime: {mtime})")
        return cached[1]

    cls = REGISTERED_MODELS.get(name)
    if not cls:
        logger.warning(f"[PredictionRepository] Model '{name}' is not in REGISTERED_MODELS.")
        return None

    logger.info(f"[PredictionRepository] Loading latest model '{name}' from disk path '{path}' (mtime: {mtime})...")
    model = cls()
    model.load(path)
    _model_cache[name] = (mtime, model)
    return model


def save_prediction_result(predictions: dict, rows: list[dict], out_dir: str = "data_preprocessed/predictions") -> str:
    """예측 결과 및 입력 텔레메트리 행을 JSON 파일로 디스크에 영속화한다."""
    os.makedirs(out_dir, exist_ok=True)
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    out_filename = f"{timestamp_str}_prediction.json"
    out_path = os.path.join(out_dir, out_filename)

    data_payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_rows_count": len(rows),
        "predictions": predictions,
        "sample_input_rows": rows[-5:] if len(rows) > 5 else rows
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data_payload, f, ensure_ascii=False, indent=2)

    logger.info(f"[PredictionRepository] Prediction result saved successfully to: '{out_path}'")
    return out_path
