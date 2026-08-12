"""
test_generator_feature_isolation.py

담당 기능:
- systems/generator/feature/feature_builder.py의 설비별 시계열 계산 격리(Groupby), 명시적 시간 정렬 및 독립 윈도우 초기화 검증 테스트 모듈.

입력:
- 복수 설비(ASSET_A, ASSET_B)가 섞인 텔레메트리 데이터프레임
- 셔플된 행 순서의 데이터프레임

출력:
- pytest 아서션 성공 여부

의존 모듈:
- pytest, pandas, numpy
- systems.generator.feature.feature_builder: build_features
- systems.generator.ontology_mapping.mapping_cache: MappingStore, ColumnMapping
- systems.generator.feature.feature_catalog: load_catalog

설계 원칙과의 연결:
- docs/architecture.md의 '설비 단위 시간격리 및 결정론적 피처 연산' 원칙을 검증한다.
"""

import pytest
import pandas as pd
import numpy as np
from pandas.testing import assert_frame_equal
from systems.generator.feature.feature_builder import build_features
from systems.generator.ontology_mapping.mapping_cache import MappingStore, MappingRecord
from systems.generator.feature.feature_catalog import load_catalog


class DummyMappingStore:
    """테스트용 Mock MappingStore."""
    def get_mapping(self, col: str):
        if col in ("voltage", "voltage_raw", "Voltage"):
            return MappingRecord(source_field=col, target_ontology="Voltage", source="llm_agent", confidence=1.0, status="confirmed")
        if col in ("rotation", "rotation_raw", "Rotation"):
            return MappingRecord(source_field=col, target_ontology="Rotation", source="llm_agent", confidence=1.0, status="confirmed")
        return None


@pytest.fixture
def dummy_store():
    return DummyMappingStore()


@pytest.fixture
def catalog():
    return load_catalog()


def test_multi_asset_feature_isolation(dummy_store, catalog):
    """테스트 1: 설비 2개가 섞인 DataFrame 입력 시 설비 경계에서 diff/shift/rolling 값이 오염되지 않음."""
    dates_a = pd.date_range("2026-01-01", periods=5, freq="1h")
    dates_b = pd.date_range("2026-01-01", periods=5, freq="1h")

    df_a = pd.DataFrame({
        "asset_id": ["ASSET_A"] * 5,
        "observed_at": dates_a,
        "voltage": [10.0, 20.0, 30.0, 40.0, 50.0]
    })
    df_b = pd.DataFrame({
        "asset_id": ["ASSET_B"] * 5,
        "observed_at": dates_b,
        "voltage": [100.0, 200.0, 300.0, 400.0, 500.0]
    })

    # 설비 A와 B를 하나의 DataFrame으로 병합
    mixed_df = pd.concat([df_a, df_b], ignore_index=True)
    plan = {"id_column": "asset_id", "time_column": "observed_at"}

    res = build_features(mixed_df, dummy_store, catalog, plan=plan)

    # ASSET_B의 첫 행(voltage=100.0)에서의 Voltage_rolling_mean 검증
    asset_b_res = res[res["asset_id"] == "ASSET_B"].reset_index(drop=True)

    # dropna()로 인해 std가 NaN인 ASSET_B의 첫 행이 제거되고, 2번째 행(100.0, 200.0)부터 보존됨
    # 오염 누설 시 rolling_mean은 (30 + 40 + 50 + 100 + 200) / 5 = 84.0이 되나,
    # 설비 격리에 의해 ASSET_B 2번째 행의 rolling_mean은 (100 + 200) / 2 = 150.0이어야 함
    asset_b_mean = asset_b_res["Voltage_rolling_mean"].iloc[0]
    assert asset_b_mean == 150.0, f"Expected ASSET_B rolling_mean to be 150.0 within ASSET_B stream, but got {asset_b_mean}"


def test_row_order_independence(dummy_store, catalog):
    """테스트 2: 입력 행 순서를 섞어도 (내부 정렬 후) 동일한 피처 결과가 나옴."""
    dates = pd.date_range("2026-01-01", periods=10, freq="1h")
    df_orig = pd.DataFrame({
        "asset_id": ["ASSET_A"] * 5 + ["ASSET_B"] * 5,
        "observed_at": list(dates[:5]) + list(dates[:5]),
        "voltage": [10.0, 20.0, 30.0, 40.0, 50.0, 100.0, 110.0, 120.0, 130.0, 140.0]
    })

    plan = {"id_column": "asset_id", "time_column": "observed_at"}

    res_orig = build_features(df_orig, dummy_store, catalog, plan=plan)

    # 무작위 셔플
    df_shuffled = df_orig.sample(frac=1, random_state=42).reset_index(drop=True)
    res_shuffled = build_features(df_shuffled, dummy_store, catalog, plan=plan)

    assert_frame_equal(
        res_orig.reset_index(drop=True),
        res_shuffled.reset_index(drop=True),
        check_dtype=False
    )


def test_independent_window_initialization(dummy_store, catalog):
    """테스트 3: 설비별 rolling window가 서로 독립적으로 초기화됨."""
    dates = pd.date_range("2026-01-01", periods=5, freq="1h")
    df = pd.DataFrame({
        "asset_id": ["ASSET_A"] * 5 + ["ASSET_B"] * 5,
        "observed_at": list(dates) + list(dates),
        "voltage": [10.0, 10.0, 10.0, 10.0, 10.0, 50.0, 50.0, 50.0, 50.0, 50.0]
    })
    plan = {"id_column": "asset_id", "time_column": "observed_at"}

    res = build_features(df, dummy_store, catalog, plan=plan)

    # ASSET_A rolling_mean은 항상 10.0, ASSET_B rolling_mean은 항상 50.0이어야 함
    mean_a = res[res["asset_id"] == "ASSET_A"]["Voltage_rolling_mean"]
    mean_b = res[res["asset_id"] == "ASSET_B"]["Voltage_rolling_mean"]

    assert (mean_a == 10.0).all(), f"ASSET_A rolling mean contaminated: {mean_a.tolist()}"
    assert (mean_b == 50.0).all(), f"ASSET_B rolling mean contaminated: {mean_b.tolist()}"


def test_horizon_labeling_lead_window():
    """테스트 4: 단일 고장 시점 기반 prediction_horizon_hours(24h) 사전 라벨링 매칭 검증."""
    from systems.generator.feature.feature_label_service import build_labels

    dates = pd.date_range("2026-01-01 00:00:00", periods=48, freq="1h")
    features_df = pd.DataFrame({
        "asset_id": ["ASSET_A"] * 48,
        "observed_at": dates,
        "voltage": [10.0] * 48
    })

    failures_df = pd.DataFrame({
        "asset_id": ["ASSET_A"],
        "observed_at": [pd.Timestamp("2026-01-02 12:00:00")]
    })

    labeled_df = build_labels(features_df, failures_df, prediction_horizon_hours=24)

    pos_mask = labeled_df["label"] == 1
    pos_times = labeled_df.loc[pos_mask, "observed_at"]

    assert len(pos_times) == 25, f"Expected 25 hourly points in 24h horizon window, got {len(pos_times)}"
    assert pos_times.min() == pd.Timestamp("2026-01-01 12:00:00")
    assert pos_times.max() == pd.Timestamp("2026-01-02 12:00:00")
