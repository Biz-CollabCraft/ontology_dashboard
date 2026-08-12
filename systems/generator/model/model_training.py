"""
model_training.py

담당 기능:
- 엔드투엔드 모델 학습 파이프라인(train_all) 및 파싱 전용 시험 함수(run_parsing_only) 오케스트레이터 모듈.
- extraction ➔ ontology_mapping ➔ capability_detection ➔ feature_extraction ➔ labeling ➔ run_version_issue ➔ model_training(model_v{N}.joblib) ➔ shared_run_artifacts(runs/v{N}) 순서로 구동하며, 실행별 전역 버전(run_version)을 기준으로 모델 아티팩트와 전체 공유 아티팩트를 소유권별로 분리 저장한다.

입력:
- data_dir(str): 원본 소스 데이터셋 폴더 경로. 기본값 "data".
- store_dir(str): 모델 및 레지스트리 영속화 디렉토리. 기본값 "models_store".
- force_reanalyze(bool): 캐시 무시 재분석 여부. 기본값 False.

출력:
- dict: capabilities, mappings, registry (각 모델별 최신 버전 정보 및 파일 경로 포함)

의존 모듈:
- extraction.extraction_loader: load_all_sources 데이터 로딩
- ontology_mapping.mapping_agent: map_all_sources 온톨로지 매핑
- ontology_mapping_capability_service: detect_capabilities 도메인 역량 판별
- feature.feature_builder: build_features 피처 추출
- feature.feature_label_service: build_labels 라벨링
- model_registry: REGISTERED_MODELS, get_next_run_version, save_run_result

예외/경계 상황:
- telemetry 또는 failure 소스 역할을 찾지 못하거나 조인 키가 없을 경우 ValueError 발생.
- 모든 모델의 학습이 실패한 경우 ValueError 발생. 단일 모델 실패 시 해당 모델만 skip되고 나머지 성공 모델은 등록된다.

설계 원칙과의 연결:
- docs/architecture.md의 '소유권 기준 버전 관리' 원칙에 따라 실행 단위(run) 공유 산출물과 모델 개별 아티팩트를 구별하여 영속화한다.
"""

import os
import json
import logging
from datetime import datetime, timezone

from systems.generator.extraction.extraction_service import load_all_sources
from systems.generator.extraction.extraction_profiler import load_family_registry
from systems.generator.ontology_mapping.mapping_cache import get_mapping_store, reload_mapping_store
from systems.generator.ontology_mapping.mapping_agent import map_all_sources
from systems.generator.ontology_mapping.ontology_mapping_capability_service import detect_capabilities
from systems.generator.feature.feature_catalog import load_catalog
from systems.generator.feature.feature_builder import build_features, save_features_npy
from systems.generator.feature.feature_label_service import build_labels
from systems.generator.model.model_registry import (
    REGISTERED_MODELS,
    get_next_run_version,
    save_run_result,
)

logger = logging.getLogger(__name__)


def _get_file_meta(sources_key: str, registry: dict) -> dict:
    """sources_key와 매칭되는 Stage 0 파일 메타데이터를 반환한다."""
    matched = next(
        (fname for fname in registry if os.path.splitext(fname)[0] == sources_key), None
    )
    return registry.get(matched, {}) if matched else {}


def _select_training_pair(sources: dict) -> tuple[str, str, dict, dict]:
    """Stage 0 메타데이터의 role/id_columns를 기준으로 telemetry와 failure 파일을 짝짓는다."""
    registry = load_family_registry()

    telemetry_candidates = [
        k for k in sources if _get_file_meta(k, registry).get("role") == "telemetry_sensor"
    ]
    failure_candidates = [
        k for k in sources if _get_file_meta(k, registry).get("role") in ("failure_event", "evaluation_truth")
    ]

    if not telemetry_candidates:
        raise ValueError("role='telemetry_sensor'로 판별된 파일이 없습니다. Stage 0 메타데이터를 확인해주세요.")
    if not failure_candidates:
        raise ValueError("role='failure_event'로 판별된 파일이 없습니다. Stage 0 메타데이터를 확인해주세요.")

    for t_key in telemetry_candidates:
        t_meta = _get_file_meta(t_key, registry)
        t_ids = set(t_meta.get("id_columns", []))
        for f_key in failure_candidates:
            f_meta = _get_file_meta(f_key, registry)
            f_ids = set(f_meta.get("id_columns", []))
            if t_ids & f_ids:
                logger.info(
                    f"[TrainAll] Stage 0 메타데이터 기준 매칭 성공: telemetry='{t_key}'(role={t_meta.get('role')}), "
                    f"failure='{f_key}'(role={f_meta.get('role')}), 공통 id_columns={t_ids & f_ids}"
                )
                return t_key, f_key, t_meta, f_meta

    raise ValueError(
        "telemetry_sensor와 failure_event 역할을 가진 파일들 중 id_columns가 겹치는 "
        "조합을 찾지 못했습니다. Stage 0 메타데이터(source_family_registry.json)를 확인해주세요."
    )


def train_all(data_dir: str = "data", store_dir: str = "models_store", force_reanalyze: bool = False) -> dict:
    """전체 학습 파이프라인을 수행하고 전역 실행 버전(run_version) 단위로 산출물을 저장한다."""
    logger.info("========================================")
    logger.info(f"🚀 RUNNING TRAINING PIPELINE (v3): Data Directory = '{data_dir}', force_reanalyze = {force_reanalyze}")
    logger.info("========================================")

    logger.info(">>> STEP 1: PARSE & EXTRACT SOURCES (Extraction Agent)")
    sources = load_all_sources(data_dir, force_reanalyze=force_reanalyze)

    try:
        from systems.generator.extraction.extraction_writer import persist_raw_extracted
        from systems.generator.extraction.extraction_service import get_last_plans
        persist_raw_extracted(sources, get_last_plans(), force_reanalyze)
    except Exception as e:
        logger.warning(f"[TrainAll] raw_extracted 저장 단계 전체 실패(학습은 계속 진행): {e}")

    logger.info(">>> STEP 2: ONTOLOGY MAPPING")
    store = get_mapping_store()
    map_all_sources(sources, store)
    reload_mapping_store()

    logger.info(">>> STEP 3: CAPABILITY DETECTION")
    try:
        capabilities = detect_capabilities(store)
    except Exception as e:
        logger.warning(f"[TrainAll] Capability 판별 실패(학습은 계속 진행, 빈 값으로 대체): {e}")
        capabilities = {}

    logger.info(">>> STEP 4: STAGE 0 METADATA PAIR SELECTION & FEATURE EXTRACTION")
    telemetry_key, failures_key, telemetry_meta, failure_meta = _select_training_pair(sources)
    family_id = telemetry_meta.get("family_id", "unknown")
    id_col = telemetry_meta.get("id_col") or "asset_id"
    time_col = telemetry_meta.get("time_col") or "observed_at"

    catalog = load_catalog()
    features = build_features(sources[telemetry_key], store, catalog)

    try:
        save_features_npy(features, "data_preprocessed/features", telemetry_key)
    except Exception as e:
        logger.warning(f"[TrainAll] Feature npy 저장 실패(학습은 계속 진행, 참고용 산출물만 없음): {e}")

    logger.info(">>> STEP 5: LABELING (with Stage 0 time_columns semantics)")
    labeled = build_labels(features, sources[failures_key], failure_meta=failure_meta)
    train_positive_rate = float(labeled["label"].mean())
    logger.info(f"Training dataset positive rate for telemetry='{telemetry_key}' & failure='{failures_key}': {train_positive_rate:.4f}")

    # STEP 6 시작 전 미리 feature_cols 산출
    exclude = set(filter(None, ["datetime", "observed_at", "machineID", "asset_id", "label", id_col, time_col]))
    feature_cols = [c for c in labeled.columns if c not in exclude]

    logger.info(">>> STEP 6: TRAIN & SAVE MODELS (전역 실행 버전 v{N})")
    run_version = get_next_run_version(store_dir=store_dir)

    results = {}
    failed_models = {}
    for name, cls in REGISTERED_MODELS.items():
        try:
            logger.info(f"Training model: {name} (run v{run_version})")
            model = cls()
            model.train(labeled, target_col="label", id_col=id_col, time_col=time_col)

            model_dir = os.path.join(store_dir, name)
            os.makedirs(model_dir, exist_ok=True)
            model_path = os.path.join(model_dir, f"model_v{run_version}.joblib")
            model.save(model_path)

            results[name] = {"path": model_path, "train_positive_rate": train_positive_rate}
            logger.info(f"Saved {name} to {model_path}")
        except Exception as e:
            logger.error(f"[TrainAll] 모델 '{name}' 학습/저장 실패, 다른 모델은 계속 진행: {e}")
            failed_models[name] = str(e)
            results[name] = None

    if all(v is None for v in results.values()):
        raise ValueError(f"모든 모델 학습이 실패했습니다: {failed_models}")

    # 학습 실행 전체 공유 산출물을 runs/v{N}/에 저장
    run_artifacts_dir = os.path.join(store_dir, "runs", f"v{run_version}")
    os.makedirs(run_artifacts_dir, exist_ok=True)
    run_artifacts_meta = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "feature_cols": feature_cols,
        "family_id": family_id,
        "source_telemetry_key": telemetry_key,
        "source_failures_key": failures_key,
    }
    with open(os.path.join(run_artifacts_dir, "run_meta.json"), "w", encoding="utf-8") as f:
        json.dump(run_artifacts_meta, f, ensure_ascii=False, indent=2)

    save_run_result(run_version, results, run_artifacts_meta, store_dir=store_dir)

    logger.info(">>> STEP 7: ASSEMBLE SUMMARY RESPONSE")
    summary = {
        "run_version": run_version,
        "trained_at": run_artifacts_meta["trained_at"],
        "models": {k: v for k, v in results.items() if v is not None},
        "failed_models": failed_models if failed_models else None,
    }

    logger.info("========================================")
    logger.info("✅ TRAINING PIPELINE COMPLETED SUCCESSFULLY")
    logger.info("========================================")

    return {
        "capabilities": capabilities,
        "mappings": {
            k: {
                "source_field": v.source_field,
                "target_ontology": v.target_ontology,
                "source": v.source,
                "confidence": v.confidence,
                "status": v.status
            } for k, v in store.get_all().items()
        },
        "registry": summary
    }


def run_parsing_only(data_dir: str = "data", force_reanalyze: bool = False) -> dict:
    """학습 파이프라인과 완전히 분리된 파싱 시험 전용 함수."""
    logger.info("========================================")
    logger.info(f"🔍 PARSING TEST ONLY (no training): data_dir='{data_dir}', force_reanalyze={force_reanalyze}")
    logger.info("========================================")

    sources = load_all_sources(data_dir, force_reanalyze=force_reanalyze)

    try:
        from systems.generator.extraction.extraction_writer import persist_raw_extracted
        from systems.generator.extraction.extraction_service import get_last_plans
        persist_raw_extracted(sources, get_last_plans(), force_reanalyze)
    except Exception as e:
        logger.warning(f"[RunParsingOnly] raw_extracted 저장 단계 예외(파싱 시험은 계속 진행): {e}")

    store = get_mapping_store()
    map_all_sources(sources, store)
    reload_mapping_store()

    family_registry = load_family_registry()

    file_summaries = []
    for key, df in sources.items():
        matched_filename = next((f for f in family_registry if os.path.splitext(f)[0] == key), None)
        meta = family_registry.get(matched_filename, {}) if matched_filename else {}
        file_summaries.append({
            "filename": matched_filename or key,
            "shape": list(df.shape),
            "columns": list(df.columns),
            "role": meta.get("role", "unknown"),
            "confidence": meta.get("confidence"),
            "status": meta.get("status"),
            "id_columns": meta.get("id_columns", []),
            "time_columns": meta.get("time_columns", []),
        })

    return {
        "parsed_files": file_summaries,
        "mappings": {
            k: {
                "source_field": v.source_field,
                "target_ontology": v.target_ontology,
                "source": v.source,
                "confidence": v.confidence,
                "status": v.status,
            } for k, v in store.get_all().items()
        },
    }
