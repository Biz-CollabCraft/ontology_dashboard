"""
prediction_service.py

담당 기능:
- 추론 실행 오케스트레이션(run_prediction) 및 최근 센서 데이터 스냅샷 조회(get_current_snapshot) 서비스 모듈.
- 입력된 텔레메트리 행 딕셔너리로 온톨로지 피처를 즉시 생성하고 최신 등록 모델들을 호출하여 SHAP/확률 결과를 반환한다.

입력:
- new_rows(list[dict]): 최근 텔레메트리 센서 레코드 딕셔너리 리스트
- store_dir(str | Path, optional): 모델 저장소 경로. 기본값 PATHS.models_store.
- data_dir(str | Path, optional): 소스 데이터셋 폴더 경로. 기본값 PATHS.data_dir.
- n(int): 스냅샷으로 가져올 최근 행 수. 기본값 20.

출력:
- predictions(dict): {model_name: prediction_output_dict}
- snapshot_rows(list[dict]): 최근 n행 텔레메트리 레코드

의존 모듈:
- prediction_repository._get_or_load_model: 최신 모델 인스턴스 로딩
- ontology_mapping.mapping_cache.get_mapping_store: 온톨로지 매핑 참조
- feature.feature_builder.build_features: 온톨로지 피처 변환
- extraction.extraction_service.load_all_sources: 스냅샷 조회용 데이터셋 로딩
- systems.generator.generator_config.PATHS: 전역 경로 레지스트리

예외/경계 상황:
- models_store/registry.json 미존재 시 ValueError 발생.
- 입력 행 수가 피처 계산 윈도우 미만으로 dropna() 후 empty가 되면 ValueError 발생.

설계 원칙과의 연결:
- docs/architecture.md의 '독립 예측 파이프라인' 및 '단일 경로 제어' 원칙에 따라 동적 경로 기반 조회를 제공한다.
"""

import os
import json
import logging
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

from systems.generator.generator_config import PATHS
from systems.generator.ontology_mapping.mapping_cache import get_mapping_store
from systems.generator.feature.feature_catalog import load_catalog
from systems.generator.feature.feature_builder import build_features
from systems.generator.prediction.prediction_repository import _get_or_load_model
from systems.generator.extraction.extraction_service import load_all_sources
from systems.generator.extraction.extraction_profiler import load_family_registry

logger = logging.getLogger(__name__)


def run_prediction(new_rows: list[dict], store_dir: str | Path | None = None) -> dict:
    """최근 N건의 telemetry 레코드로 피처를 구성하여 최신 모델들로 고장 예측을 수행한다."""
    target_store = Path(store_dir).resolve() if store_dir else PATHS.models_store
    registry_path = target_store / "registry.json"
    if not registry_path.exists():
        raise ValueError("모델 레지스트리를 찾을 수 없습니다. 먼저 학습(/internal/retrain)을 진행해주세요.")

    with open(registry_path, "r", encoding="utf-8") as f:
        registry_meta = json.load(f)

    store = get_mapping_store()
    catalog = load_catalog()
    df = pd.DataFrame(new_rows)

    features = build_features(df, store, catalog)
    if features.empty:
        raise ValueError(f"Feature 계산에 필요한 최소 행 수가 부족합니다 (입력 {len(df)}건). 더 많은 과거 데이터를 함께 전달해주세요.")

    now_iso = datetime.now(timezone.utc).isoformat()
    predictions = {}

    models_entry = registry_meta.get("models", {})
    for name in models_entry.keys():
        model = _get_or_load_model(name, store_dir=target_store)
        if not model:
            continue

        pred_output = model.predict(features)
        pred_output.prediction_timestamp = now_iso
        predictions[name] = pred_output.model_dump()

    return predictions


def find_latest_telemetry_key(sources: dict) -> str:
    """Stage 0 메타데이터를 사용하여 telemetry_sensor 역할을 가진 데이터셋 키를 찾는다."""
    registry = load_family_registry()
    for key in sources:
        matched = next((fname for fname in registry if os.path.splitext(fname)[0] == key), None)
        meta = registry.get(matched, {}) if matched else {}
        if meta.get("role") == "telemetry_sensor":
            return key

    # 폴백: telemetry 키워드가 포함된 키 또는 첫번째 키
    for key in sources:
        if any(k in key.lower() for k in ("telemetry", "sensor", "observation")):
            return key

    if sources:
        return list(sources.keys())[0]

    raise ValueError("사용 가능한 소스 데이터셋이 존재하지 않습니다.")


def get_current_snapshot(data_dir: str | Path | None = None, n: int = 20) -> list[dict]:
    """telemetry_sensor 데이터셋 파일에서 가장 최근 n행을 스냅샷으로 조회한다."""
    target_data_dir = str(Path(data_dir).resolve()) if data_dir else str(PATHS.data_dir)
    sources = load_all_sources(target_data_dir, force_reanalyze=False)
    telemetry_key = find_latest_telemetry_key(sources)
    df = sources[telemetry_key]
    logger.info(f"[PredictionService] Fetched snapshot from '{telemetry_key}' (total rows: {len(df)}, returning last {n} rows)")
    return df.tail(n).to_dict(orient="records")
