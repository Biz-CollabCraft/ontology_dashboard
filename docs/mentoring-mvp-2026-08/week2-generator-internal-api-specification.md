# Week 2 Generator 내부 API 명세서

## 1. 기준과 상태

이 문서는 `systems/generator`가 노출하는 **내부 전용 API**의 계약이다. [Week 2 API 명세서](./week2-api-specification.md)가 `backend`의 제품 API(사용자·프론트엔드가 소비)를 다루는 것과 달리, 이 문서는 `backend`(또는 운영자)가 `generator` 데몬을 제어하기 위한 API를 다룬다. **외부(프론트엔드)에는 노출되지 않는다.**

- Base path: (별도 접두사 없음, `generator` 프로세스가 단독으로 사용)
- 책임: `generator` 파이프라인(추출/매핑/feature/학습/예측) 구현 담당자

## 2. Endpoint

| Method | Path | 목적 |
|---|---|---|
| GET | `/health` | 데몬 상태 확인 |
| POST | `/internal/train` | 파이프라인 최초 학습 실행(모델이 없을 때 데몬 기동 시 자동 호출도 동일 로직) |
| POST | `/internal/retrain` | 재학습 실행, 기존 모델을 덮어쓰지 않고 새 버전으로 저장 |
| POST | `/internal/predict` | 호출자가 넘긴 데이터로 즉시 예측(파일 저장 없음) |
| POST | `/internal/predict/file` | 현재 시점 최신 데이터로 예측을 자체 실행하고 결과를 파일로 저장 |

## 3. 요청/응답 계약

### 3.1 `GET /health`

```json
{
  "status": "ok",
  "system": "generator"
}
```

### 3.2 `POST /internal/train`, `POST /internal/retrain`

요청:

```json
{
  "data_dir": "data",
  "force_reanalyze": false
}
```

응답:

```json
{
  "capabilities": {
    "EquipmentMonitoring": true,
    "SensorAnalytics": true,
    "MaintenanceHistory": false,
    "FailurePrediction": true,
    "ErrorTracking": false
  },
  "mappings": {
    "voltage_raw": {
      "source_field": "voltage_raw",
      "target_ontology": "Voltage",
      "source": "mapping_agent",
      "confidence": 0.8,
      "status": "auto_mapped"
    }
  },
  "registry": {
    "run_version": 3,
    "trained_at": "2026-08-12T01:15:08.477637+00:00",
    "models": {
      "lightgbm": {
        "path": "models_store/lightgbm/model_v3.joblib",
        "train_positive_rate": 0.0507
      },
      "xgboost": {
        "path": "models_store/xgboost/model_v3.joblib",
        "train_positive_rate": 0.0507
      },
      "random_forest": {
        "path": "models_store/random_forest/model_v3.joblib",
        "train_positive_rate": 0.0507
      }
    },
    "failed_models": null
  }
}
```

`failed_models`는 일부 모델 학습이 실패했을 때만 채워지며, 채워져도 나머지 모델의 성공한 버전 정보는 `models`에 그대로 반환된다(부분 실패가 전체 응답 실패로 이어지지 않는다).

### 3.3 `POST /internal/predict`

요청:

```json
{
  "rows": [
    {
      "asset_id": "CMP-S01-L01-01",
      "observed_at": "2026-08-12T09:00:00Z",
      "voltage_raw": 220.5
    }
  ]
}
```

응답: `Dict[str, PredictionOutput]` — 모델명을 key로 하는 예측 결과 객체.
스키마는 `systems/generator/prediction/prediction_schema.py` 참조.

예시:

```json
{
  "lightgbm": {
    "failure_probability": 0.02,
    "confidence": 0.98,
    "status_grade": null,
    "predicted_failure_type": null,
    "prediction_timestamp": "2026-08-12T09:00:00Z",
    "feature_importance": {
      "Voltage_rolling_mean": 0.15
    },
    "shap_values": {
      "Voltage_rolling_mean": -0.36
    }
  },
  "xgboost": {
    "failure_probability": 0.03,
    "confidence": 0.97,
    "status_grade": null,
    "predicted_failure_type": null,
    "prediction_timestamp": "2026-08-12T09:00:00Z",
    "feature_importance": {},
    "shap_values": {}
  },
  "random_forest": {
    "failure_probability": 0.02,
    "confidence": 0.98,
    "status_grade": null,
    "predicted_failure_type": null,
    "prediction_timestamp": "2026-08-12T09:00:00Z",
    "feature_importance": {},
    "shap_values": {}
  }
}
```

### 3.4 `POST /internal/predict/file`

요청:

```json
{
  "data_dir": "data",
  "n": 20
}
```

응답:

```json
{
  "predictions": {
    "lightgbm": {
      "failure_probability": 0.0,
      "confidence": 1.0,
      "status_grade": null,
      "predicted_failure_type": null,
      "prediction_timestamp": "2026-08-12T09:00:00Z",
      "feature_importance": {},
      "shap_values": {}
    },
    "xgboost": {
      "failure_probability": 0.0,
      "confidence": 1.0,
      "status_grade": null,
      "predicted_failure_type": null,
      "prediction_timestamp": "2026-08-12T09:00:00Z",
      "feature_importance": {},
      "shap_values": {}
    },
    "random_forest": {
      "failure_probability": 0.0,
      "confidence": 1.0,
      "status_grade": null,
      "predicted_failure_type": null,
      "prediction_timestamp": "2026-08-12T09:00:00Z",
      "feature_importance": {},
      "shap_values": {}
    }
  },
  "saved_path": "data_preprocessed/predictions/20260812_090000_prediction.json",
  "save_error": null
}
```

`save_error`가 채워지면 파일 저장은 실패했지만 `predictions`는 정상 반환된 것이다(저장 실패가 예측 응답 자체를 막지 않는다).

## 4. 오류 envelope

`generator`는 내부 전용 API이므로, [Week 2 API 명세서](./week2-api-specification.md)의 제품 API 오류 형식(`{"error": {...}}`)을 따르지 않고 FastAPI 기본 형식을 그대로 사용한다:

```json
{
  "detail": "모든 모델 학습이 실패했습니다: {...}"
}
```

| HTTP | 조건 |
|---:|---|
| 500 | 모든 모델 학습이 실패(부분 실패는 200 응답에 `failed_models`로 표기) |
| 500 | 모델 로드 또는 추론 실행 자체가 실패 |
| 400 | 지정한 `data_dir`가 존재하지 않거나 비어 있음 |

**`backend`가 이 API를 나중에 HTTP로 호출하게 되면, 이 형식과 제품 API 오류 형식이 다르다는 것을 감안해서 별도로 파싱해야 한다** — 이 차이를 없애고 싶다면 후속 작업으로 통일을 재검토한다.

## 5. 모델 버전 관리 계약

- 모든 모델 학습 결과는 `models_store/{model_name}/v{N}/model.joblib` 형태로 버전별로 보존한다. 기존 버전은 재학습으로 삭제되지 않는다.
- `models_store/registry.json`에 모델별 `latest_version`과 버전별 메타데이터(`trained_at`, `train_positive_rate`, `path`)를 기록한다.
- `/internal/predict`, `/internal/predict/file`은 항상 `latest_version` 모델을 사용한다 — 재학습 직후 예측부터 자동으로 새 버전이 반영된다.
- 데몬 최초 기동 시, `registry.json`에 학습된 모델이 하나도 없으면 자동으로 `/internal/train`과 동일한 로직을 실행한다(자동 학습 실패 시에도 데몬 기동 자체는 막지 않는다).

## 6. 결정 반영과 후속 확인

### Week 2 결정 완료

- `generator` 내부 API는 프론트엔드에 직접 노출하지 않는다.
- 모델은 덮어쓰기가 아니라 버전 관리 방식으로 보존한다.

### 후속 확인

- `backend`가 이 API를 직접 함수 호출 대신 HTTP로 전환할 시점
- 예측 결과 파일(`data_preprocessed/predictions/`)의 보관 기간·정리 정책
- 인증/네트워크 격리 방식(현재는 내부망 전제, 별도 인증 없음)
