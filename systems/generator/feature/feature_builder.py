"""
feature_builder.py

담당 기능:
- 온톨로지 매핑 정보 및 카탈로그 규칙 기반 시계열 피처 추출(rolling mean, rolling std, gradient, ema, lag, moving average) 및 NPY 파일 영속화 모듈.

입력:
- telemetry_df(pd.DataFrame): 텔레메트리 원본 데이터프레임
- store(MappingStore): 컬럼별 온톨로지 매핑 정보
- catalog(dict): 온톨로지 노드별 피처 변환 규칙 딕셔너리
- features_df(pd.DataFrame): 생성된 피처 데이터프레임 (save_features_npy)
- out_dir(str): NPY 파일 저장 디렉토리
- name(str): 데이터셋 식별키

출력:
- final_df(pd.DataFrame): 피처 변환이 완료된 데이터프레임 (build_features)
- load_features_npy: 저장된 NPY 및 JSON 메타데이터에서 복원한 데이터프레임

의존 모듈:
- pandas, numpy: 시계열 연산 (rolling, diff, ewm, shift) 및 NPY 저장/복원
- ontology_mapping.mapping_cache.MappingStore: 온톨로지 매핑 정보 참조
- feature_catalog.load_catalog: 카탈로그 로더

예외/경계 상황:
- 컬럼에 온톨로지 매핑이 없거나 카탈로그에 해당 노드가 없는 경우 피처 생성을 건너뛰고 경고 로그를 기록한다.
- rolling 연산 등으로 발생하는 NaN 행은 dropna()로 처리한다.

설계 원칙과의 연결:
- docs/architecture.md의 '온톨로지 규격 피처 자동 생성' 원칙에 따라 매핑된 노드에 기반하여 모델 입력 피처를 표준화한다.
"""

import os
import json
import logging
import numpy as np
import pandas as pd
from systems.generator.ontology_mapping.mapping_cache import MappingStore
from systems.generator.feature.feature_catalog import load_catalog

logger = logging.getLogger(__name__)


def build_features(telemetry_df: pd.DataFrame, store: MappingStore, catalog: dict) -> pd.DataFrame:
    """온톨로지 매핑 및 카탈로그 룰에 따라 시계열 피처를 추출한다."""
    logger.info(f"[FeatureBuilder] Starting feature extraction on dataset shape: {telemetry_df.shape}")
    df = telemetry_df.copy()

    time_col = "observed_at" if "observed_at" in df.columns else ("datetime" if "datetime" in df.columns else df.columns[0])
    id_col = "asset_id" if "asset_id" in df.columns else ("machineID" if "machineID" in df.columns else None)

    meta_cols = [time_col]
    if id_col and id_col in df.columns:
        meta_cols.append(id_col)

    result = df[meta_cols].copy()

    for col in df.columns:
        if col in meta_cols:
            continue
        mapping = store.get_mapping(col)
        if not mapping:
            logger.warning(f"[FeatureBuilder] Column '{col}' has no ontology mapping. Skipping feature extraction.")
            continue
        if mapping.target_ontology not in catalog:
            logger.warning(f"[FeatureBuilder] Column '{col}' mapped to '{mapping.target_ontology}', but node is not in catalog. Skipping.")
            continue
        node = mapping.target_ontology
        if not pd.api.types.is_numeric_dtype(df[col]):
            logger.warning(f"[FeatureBuilder] Column '{col}' mapped to '{node}' is non-numeric ({df[col].dtype}). Skipping feature extraction.")
            continue

        logger.info(f"[FeatureBuilder] Applying features for column '{col}' mapped to '{node}'...")

        for rule in catalog[node]:
            name = rule["name"]
            feat_name = f"{node}_{name}"
            if name == "rolling_mean":
                result[feat_name] = df[col].rolling(rule.get("window", 5)).mean()
            elif name == "rolling_std":
                result[feat_name] = df[col].rolling(rule.get("window", 5)).std()
            elif name == "gradient":
                result[feat_name] = df[col].diff()
            elif name == "ema":
                result[feat_name] = df[col].ewm(span=rule.get("span", 10)).mean()
            elif name == "lag":
                result[feat_name] = df[col].shift(rule.get("periods", 1))
            elif name == "moving_average":
                result[feat_name] = df[col].rolling(rule.get("window", 10)).mean()

            logger.debug(f"[FeatureBuilder] Generated feature '{feat_name}'")

    final_df = result.dropna()
    logger.info(f"[FeatureBuilder] Completed feature extraction. Output shape (after dropna): {final_df.shape}")
    return final_df


def save_features_npy(features_df: pd.DataFrame, out_dir: str, name: str) -> None:
    """생성된 피처 데이터프레임을 NPY 및 JSON 컬럼 메타데이터로 저장한다."""
    os.makedirs(out_dir, exist_ok=True)
    meta_cols = {"datetime", "observed_at", "machineID", "asset_id"}
    feature_cols = [c for c in features_df.columns if c not in meta_cols]

    np.save(os.path.join(out_dir, f"{name}_X.npy"), features_df[feature_cols].to_numpy())

    id_col = "asset_id" if "asset_id" in features_df.columns else ("machineID" if "machineID" in features_df.columns else None)
    if id_col:
        np.save(os.path.join(out_dir, f"{name}_machineID.npy"), features_df[id_col].to_numpy())

    time_col = "observed_at" if "observed_at" in features_df.columns else ("datetime" if "datetime" in features_df.columns else None)
    if time_col:
        np.save(os.path.join(out_dir, f"{name}_datetime.npy"), features_df[time_col].to_numpy(dtype="datetime64[ns]"))

    with open(os.path.join(out_dir, f"{name}_columns.json"), "w", encoding="utf-8") as f:
        json.dump(feature_cols, f, ensure_ascii=False, indent=2)
    logger.info(f"[FeatureBuilder] Saved NPY features to: {out_dir}/{name}_*.npy")


def load_features_npy(out_dir: str, name: str) -> pd.DataFrame:
    """NPY 파일 및 JSON 메타데이터에서 피처 데이터프레임을 복원한다."""
    X = np.load(os.path.join(out_dir, f"{name}_X.npy"))
    machine_id = np.load(os.path.join(out_dir, f"{name}_machineID.npy"))
    dt = np.load(os.path.join(out_dir, f"{name}_datetime.npy"))
    with open(os.path.join(out_dir, f"{name}_columns.json"), "r", encoding="utf-8") as f:
        columns = json.load(f)

    df = pd.DataFrame(X, columns=columns)
    df["machineID"] = machine_id
    df["datetime"] = dt
    return df
