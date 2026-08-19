"""
feature_label_service.py

담당 기능:
- 추출된 피처 데이터프레임과 고장 이력 데이터프레임을 조인하여 머신러닝 지도학습 라벨(label 0/1)을 생성하는 모듈.
- canonicalize_timestamp_series를 통해 시간 컬럼을 표준형(datetime64[ns])으로 정규화한 후, failure metadata에서 anchor(failure_point)와 exclusion_end(period_end/maintenance_end)를 분리해 단일 공식 positive = [anchor-horizon, anchor)으로 라벨링한다.
- anchor~exclusion_end 구간(active failure)은 label=0이 아니라 행 자체를 제거(drop)한다.
- degradation_start(period_start)는 failure metadata에서 라벨 계산에 사용하지 않으며 결과 DataFrame에 새로 추가하지 않는다. features_df에 존재하는 경우 1차로 제거(drop)한다.

예외/경계 상황 (Fail-Fast 정책):
- 필수 failure event 데이터, ID, timestamp 또는 anchor 계약을 충족하지 못하면 학습 데이터 오염 방지를 위해 조용한 fallback(전체 0 채움) 없이 명시적으로 실패한다:
  - failures_df 부재 또는 비어 있음: FailureDataNotReadyError
  - ID 또는 timestamp 컬럼 부재: LabelContractInvalidError
  - anchor(failure_point) 부재 또는 전체 NaT: LabelAnchorNotFoundError
  - 라벨 값이 {0, 1} 외 값: LabelContractInvalidError

설계 원칙과의 연결:
- docs/architecture.md 및 contracts/schemas/product-result-artifact.schema.json의 'prediction_task: binary_failure_within_horizon' 계약을 준수한다.
"""

import logging
import pandas as pd
import numpy as np
from systems.generator.common.timestamp_canonicalizer import canonicalize_timestamp_series
from systems.generator.app.feature.feature_exception import (
    FailureDataNotReadyError,
    LabelContractInvalidError,
    LabelAnchorNotFoundError,
)

logger = logging.getLogger(__name__)


def build_labels(
    features_df: pd.DataFrame,
    failures_df: pd.DataFrame,
    failure_meta: dict | None = None,
    prediction_horizon_hours: int = 24,
    plan: dict | None = None,
) -> pd.DataFrame:
    """
    features_df와 failures_df를 매칭하여 prediction_horizon 기반 label(0/1) 컬럼을 생성하고,
    active failure 구간(다운타임) 행을 제거(drop)하며, features_df에 존재하는 degradation_start 누수 컬럼을 1차 제거한다.

    Positive 구간 공식:
        positive = [failure_point - prediction_horizon, failure_point)

    Active Failure 제거 구간:
        [failure_point, exclusion_end] (exclusion_end: period_end 또는 maintenance_end)
    """
    if failures_df is None or failures_df.empty:
        raise FailureDataNotReadyError("고장 이력 데이터(failures_df)가 비어 있거나 존재하지 않습니다.")

    df = features_df.copy()
    f_df = failures_df.copy()

    # 0. Remove pre-existing degradation_start leakage columns if present in features_df
    time_cols_meta = (failure_meta or {}).get("time_columns", [])
    degradation_cols = [c["name"] for c in time_cols_meta if c.get("semantic") == "period_start"]
    leaked_cols = [c for c in degradation_cols if c in df.columns]
    if leaked_cols:
        logger.warning(f"[LabelBuilder] Removing leaked degradation_start columns from features_df: {leaked_cols}")
        df = df.drop(columns=leaked_cols)

    id_col = None
    if plan and isinstance(plan, dict):
        id_col = plan.get("id_column")
    if not id_col or id_col not in df.columns:
        for candidate in ("asset_id", "machineID", "equipment_id", "machine_id", "device_id", "UDI", "Product ID", "id"):
            if candidate in df.columns:
                id_col = candidate
                break

    time_col = None
    if plan and isinstance(plan, dict):
        time_col = plan.get("time_column")
    if not time_col or time_col not in df.columns:
        for candidate in ("observed_at", "datetime", "timestamp", "time", "ts", "date"):
            if candidate in df.columns:
                time_col = candidate
                break

    fail_id_col = None
    if plan and isinstance(plan, dict):
        fail_id_col = plan.get("id_column")
    if not fail_id_col or fail_id_col not in f_df.columns:
        for candidate in ("asset_id", "machineID", "equipment_id", "machine_id", "device_id", "UDI", "Product ID", "id"):
            if candidate in f_df.columns:
                fail_id_col = candidate
                break

    if not id_col or id_col not in df.columns:
        raise LabelContractInvalidError("Feature 데이터프레임에서 ID 컬럼을 찾을 수 없습니다.")
    if not time_col or time_col not in df.columns:
        raise LabelContractInvalidError("Feature 데이터프레임에서 timestamp 컬럼을 찾을 수 없습니다.")
    if not fail_id_col or fail_id_col not in f_df.columns:
        raise LabelContractInvalidError("고장 데이터프레임에서 ID 컬럼을 찾을 수 없습니다.")

    df[time_col] = canonicalize_timestamp_series(df[time_col], col_name=time_col)
    df["label"] = 0

    # anchor_col (failure_point) 및 exclusion_end_col (period_end / maintenance_end) 탐지
    anchor_col = next((c["name"] for c in time_cols_meta if c.get("semantic") == "failure_point"), None)
    if not anchor_col or anchor_col not in f_df.columns:
        anchor_col = None
        for candidate in ("observed_at", "datetime", "timestamp", "time", "ts", "date", "failure_point"):
            if candidate in f_df.columns:
                anchor_col = candidate
                break

    if not anchor_col or anchor_col not in f_df.columns:
        raise LabelAnchorNotFoundError("고장 데이터프레임에서 anchor(failure_point) 컬럼을 찾을 수 없습니다.")

    f_df[anchor_col] = canonicalize_timestamp_series(f_df[anchor_col], col_name=anchor_col)
    if f_df[anchor_col].isna().all():
        raise LabelAnchorNotFoundError("고장 데이터프레임의 모든 anchor(failure_point) 값이 NaT/결측치입니다.")

    exclusion_end_col = next((c["name"] for c in time_cols_meta if c.get("semantic") in ("period_end", "maintenance_end")), None)
    if exclusion_end_col and exclusion_end_col not in f_df.columns:
        exclusion_end_col = None
    if exclusion_end_col and exclusion_end_col in f_df.columns:
        f_df[exclusion_end_col] = canonicalize_timestamp_series(f_df[exclusion_end_col], col_name=exclusion_end_col)

    horizon_delta = pd.Timedelta(hours=prediction_horizon_hours)
    rows_to_drop_mask = pd.Series(False, index=df.index)

    for _, row in f_df.iterrows():
        if pd.isna(row[anchor_col]):
            continue

        f_time = row[anchor_col]
        h_start = f_time - horizon_delta

        # 1. Positive Labeling: [f_time - horizon, f_time)
        pos_mask = (
            (df[id_col] == row[fail_id_col])
            & (df[time_col] >= h_start)
            & (df[time_col] < f_time)
        )
        df.loc[pos_mask, "label"] = 1

        # 2. Active Failure Dropping: [f_time, exclusion_end]
        ex_end = row[exclusion_end_col] if exclusion_end_col and not pd.isna(row[exclusion_end_col]) else f_time
        drop_mask = (
            (df[id_col] == row[fail_id_col])
            & (df[time_col] >= f_time)
            & (df[time_col] <= ex_end)
        )
        rows_to_drop_mask = rows_to_drop_mask | drop_mask

    # Active failure 구간 행 제거
    if rows_to_drop_mask.any():
        logger.info(f"[LabelBuilder] Dropping {rows_to_drop_mask.sum()} active failure rows.")
        df = df[~rows_to_drop_mask].reset_index(drop=True)

    # Final label sanity check
    if not set(pd.unique(df["label"])).issubset({0, 1}):
        raise LabelContractInvalidError(f"생성된 라벨 값이 {{0, 1}} 범위를 벗어납니다: {pd.unique(df['label'])}")

    logger.info(f"[LabelBuilder] Labeling complete: shape={df.shape}, positive_labels={(df['label'] == 1).sum()}")
    return df
