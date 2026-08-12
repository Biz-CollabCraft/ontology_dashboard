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
    """
    features_df와 failures_df를 매칭하여 prediction_horizon 기반 label(0/1) 컬럼을 생성하고 다운타임 구간을 제외한다.

    계약 규격 (binary_failure_within_horizon):
    1. anchor_col(failure_point): 필수 고장 시점.
       - Positive 구간: [failure_point - prediction_horizon, failure_point)
       - failure_point 시점 자체는 positive에서 제외.
    2. exclusion_end_col(period_end / maintenance_end): 선택적 다운타임 완료 시점.
       - Active failure 구간: [failure_point, exclusion_end] 은 label=0이 아니라 행 자체를 제거(Drop).
    3. anchor_col 부재 시: period_end나 maintenance_end를 anchor로 대신 쓰지 않으며, 라벨링 대상에서 제외하고 경고 로그를 기록한다.
    4. Target Leakage 방지: degradation_start(period_start) 등 고장 메타데이터 컬럼은 Label DataFrame 피처로 유입되지 않는다.
    """
    df = features_df.copy()
    f_df = failures_df.copy()

    id_col = "asset_id" if "asset_id" in df.columns else ("machineID" if "machineID" in df.columns else None)
    time_col = "observed_at" if "observed_at" in df.columns else ("datetime" if "datetime" in df.columns else None)

    fail_id_col = "asset_id" if "asset_id" in f_df.columns else ("machineID" if "machineID" in f_df.columns else None)

    if time_col and time_col in df.columns:
        df[time_col] = canonicalize_timestamp_series(df[time_col], col_name=time_col)

    df["label"] = 0

    time_cols_meta = (failure_meta or {}).get("time_columns", [])
    anchor_col = next((c["name"] for c in time_cols_meta if c.get("semantic") == "failure_point"), None)
    if not anchor_col:
        anchor_col = "observed_at" if "observed_at" in f_df.columns else ("datetime" if "datetime" in f_df.columns else None)

    exclusion_end_col = next((c["name"] for c in time_cols_meta if c.get("semantic") in ("period_end", "maintenance_end")), None)
    if not exclusion_end_col:
        for c_cand in ("maintenance_end", "period_end"):
            if c_cand in f_df.columns and c_cand != anchor_col:
                exclusion_end_col = c_cand
                break

    if not id_col or not fail_id_col or not time_col or not anchor_col or anchor_col not in f_df.columns:
        logger.warning("[LabelBuilder] 필수 id/time/anchor_col(failure_point)을 찾지 못해 라벨링을 수행할 수 없습니다.")
        return df

    logger.info(f"[LabelBuilder] Horizon ({prediction_horizon_hours}h) 라벨링 시작: anchor='{anchor_col}', exclusion_end='{exclusion_end_col}'")
    f_df[anchor_col] = canonicalize_timestamp_series(f_df[anchor_col], col_name=anchor_col)
    if exclusion_end_col and exclusion_end_col in f_df.columns:
        f_df[exclusion_end_col] = canonicalize_timestamp_series(f_df[exclusion_end_col], col_name=exclusion_end_col)

    horizon_delta = pd.Timedelta(hours=prediction_horizon_hours)
    rows_to_drop_mask = pd.Series(False, index=df.index)

    valid_fdf = f_df.dropna(subset=[fail_id_col, anchor_col])
    for _, row in valid_fdf.iterrows():
        f_time = row[anchor_col]
        h_start = f_time - horizon_delta

        # 1. Positive interval: [f_time - horizon, f_time)
        pos_mask = (
            (df[id_col] == row[fail_id_col]) &
            (df[time_col] >= h_start) &
            (df[time_col] < f_time)
        )
        df.loc[pos_mask, "label"] = 1

        # 2. Active failure exclusion: [f_time, exclusion_end] 또는 [f_time, f_time]
        if exclusion_end_col and exclusion_end_col in row and pd.notna(row[exclusion_end_col]):
            ex_end = row[exclusion_end_col]
            ex_mask = (
                (df[id_col] == row[fail_id_col]) &
                (df[time_col] >= f_time) &
                (df[time_col] <= ex_end)
            )
        else:
            ex_mask = (
                (df[id_col] == row[fail_id_col]) &
                (df[time_col] == f_time)
            )
        rows_to_drop_mask |= ex_mask

    # Active failure 구간 행 제거 (Drop)
    df = df[~rows_to_drop_mask].reset_index(drop=True)

    pos_count = (df["label"] == 1).sum()
    logger.info(f"[LabelBuilder] 라벨링 완료. 최종 {len(df)}행 중 positive: {pos_count}행")
    return df
