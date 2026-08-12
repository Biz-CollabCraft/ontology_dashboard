"""
feature_label_service.py

담당 기능:
- 추출된 피처 데이터프레임과 고장 이력 데이터프레임을 조인하여 머신러닝 지도학습 라벨(label 0/1)을 생성하는 모듈.
- canonicalize_timestamp_series를 통해 시간 컬럼을 표준형(datetime64[ns])으로 정규화한 후 구간 매칭(Interval-based) 또는 prediction_horizon_hours 기반 사전 예측 구간(Lead Window) 매칭을 수행한다.

입력:
- features_df(pd.DataFrame): 피처 데이터프레임
- failures_df(pd.DataFrame): 고장 데이터프레임
- failure_meta(dict, optional): Stage 0 고장 데이터셋 메타데이터
- prediction_horizon_hours(int): 예측 호라이즌시간 (기본값 24시간)

출력:
- df(pd.DataFrame): label 컬럼이 추가된 데이터프레임

의존 모듈:
- pandas, numpy
- systems.generator.common.timestamp_canonicalizer.canonicalize_timestamp_series

예외/경계 상황:
- id/time 컬럼을 찾지 못하거나 조인 매칭 대상이 없는 경우 label을 0으로 채우고 경고 로그를 남긴다.

설계 원칙과의 연결:
- docs/architecture.md 및 schemas/product-result-artifact.schema.json의 'prediction_task: binary_failure_within_horizon' 계약을 준수한다.
"""

import logging
import pandas as pd
import numpy as np
from systems.generator.common.timestamp_canonicalizer import canonicalize_timestamp_series

logger = logging.getLogger(__name__)


def build_labels(
    features_df: pd.DataFrame,
    failures_df: pd.DataFrame,
    failure_meta: dict | None = None,
    prediction_horizon_hours: int = 24
) -> pd.DataFrame:
    """features_df와 failures_df를 매칭하여 prediction_horizon 기반 label(0/1) 컬럼을 생성한다."""
    df = features_df.copy()
    f_df = failures_df.copy()

    id_col = "asset_id" if "asset_id" in df.columns else ("machineID" if "machineID" in df.columns else None)
    time_col = "observed_at" if "observed_at" in df.columns else ("datetime" if "datetime" in df.columns else None)

    fail_id_col = "asset_id" if "asset_id" in f_df.columns else ("machineID" if "machineID" in f_df.columns else None)

    if time_col and time_col in df.columns:
        df[time_col] = canonicalize_timestamp_series(df[time_col], col_name=time_col)

    time_cols_meta = (failure_meta or {}).get("time_columns", [])
    start_col = next((c["name"] for c in time_cols_meta if c.get("semantic") == "period_start"), None)
    end_col = next((c["name"] for c in time_cols_meta if c.get("semantic") in ("failure_point", "period_end", "maintenance_end")), None)

    df["label"] = 0

    # 1. 구간 매칭 (start_col ~ end_col)
    if id_col and fail_id_col and time_col and start_col and end_col \
            and start_col in f_df.columns and end_col in f_df.columns:
        logger.info(f"[LabelBuilder] 열화/고장 구간 매칭 사용: start='{start_col}', end='{end_col}' (id_col='{id_col}')")
        f_df[start_col] = canonicalize_timestamp_series(f_df[start_col], col_name=start_col)
        f_df[end_col] = canonicalize_timestamp_series(f_df[end_col], col_name=end_col)

        valid_fdf = f_df[[fail_id_col, start_col, end_col]].dropna()
        for _, row in valid_fdf.iterrows():
            mask = (
                (df[id_col] == row[fail_id_col]) &
                (df[time_col] >= row[start_col]) &
                (df[time_col] <= row[end_col])
            )
            df.loc[mask, "label"] = 1
        pos_count = (df["label"] == 1).sum()
        logger.info(f"[LabelBuilder] 구간 매칭 완료. 총 {len(df)}행 중 positive label: {pos_count}행 ({pos_count/len(df):.4f})")
        return df

    # 2. 호라이즌 기반 매칭 (Lead Window: failure_time - horizon ~ failure_time)
    fail_time_col = next((c["name"] for c in time_cols_meta if c.get("semantic") == "failure_point"), None)
    if not fail_time_col:
        fail_time_col = "observed_at" if "observed_at" in f_df.columns else ("datetime" if "datetime" in f_df.columns else None)

    if id_col and fail_id_col and time_col and fail_time_col and fail_time_col in f_df.columns:
        logger.info(f"[LabelBuilder] Horizon ({prediction_horizon_hours}h) 기반 매칭 사용: fail_time='{fail_time_col}', id='{id_col}'")
        f_df[fail_time_col] = canonicalize_timestamp_series(f_df[fail_time_col], col_name=fail_time_col)
        horizon_delta = pd.Timedelta(hours=prediction_horizon_hours)

        valid_fdf = f_df[[fail_id_col, fail_time_col]].dropna()
        for _, row in valid_fdf.iterrows():
            f_time = row[fail_time_col]
            h_start = f_time - horizon_delta
            mask = (
                (df[id_col] == row[fail_id_col]) &
                (df[time_col] >= h_start) &
                (df[time_col] <= f_time)
            )
            df.loc[mask, "label"] = 1
        pos_count = (df["label"] == 1).sum()
        logger.info(f"[LabelBuilder] Horizon 매칭 완료. 총 {len(df)}행 중 positive label: {pos_count}행 ({pos_count/len(df):.4f})")
    else:
        logger.warning("[LabelBuilder] id/time 컬럼을 찾지 못해 label을 전부 0으로 채웁니다.")

    return df
