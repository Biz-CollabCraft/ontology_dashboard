"""
generator_main.py

담당 기능:
- Generator 도메인 백그라운드 FastAPI 데몬 서버 모듈.
- 서버 기동 시 모델 존재 여부를 자동 검사(has_any_trained_model)하여 모델이 없을 경우 자동 학습(train_all)을 최초 1회 구동한다.
- /health, /internal/train, /internal/retrain, /internal/predict, /internal/predict/file REST 엔트리포인트를 제공한다.

입력:
- TrainRequest: data_dir(str | None = None), force_reanalyze(bool)
- PredictRequest: rows(list[dict])
- PredictFileRequest: data_dir(str | None = None), n(int)

출력:
- JSON 응답: 시스템 헬스 상태, 재학습 버전 정보, 예측 결과 및 저장된 결과 파일 경로

의존 모듈:
- generator_config: load_config, PATHS
- model.model_registry: has_any_trained_model
- model.model_training: train_all
- prediction.prediction_service: run_prediction, get_current_snapshot
- prediction.prediction_repository: save_prediction_result
- fastapi, pydantic: REST 웹 프레임워크 및 라우팅

예외/경계 상황:
- 서버 기동 시 자동 학습(train_all) 실패 시에도 서버 다운을 막고 에러 로그만 남긴 후 구동을 계속한다 (FastAPI lifespan 세이프가드).
- /internal/predict/file 호출 시 파일 저장 단계에서 실패하더라도 500 에러를 내지 않고 save_error 항목을 채워 200 OK로 반환한다.

설계 원칙과의 연결:
- docs/architecture.md의 '자율 구동 데몬 및 단일 경로 제어' 원칙에 따라 모델 부재 시 스스로 파이프라인을 복구하고 에러를 격리한다.
"""

import os
import sys
import logging
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from systems.generator.generator_config import load_config, PATHS
load_config()

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from systems.generator.model.model_training import train_all
from systems.generator.model.model_registry import has_any_trained_model
from systems.generator.prediction.prediction_service import run_prediction, get_current_snapshot
from systems.generator.prediction.prediction_repository import save_prediction_result

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 기동 시 모델 존재 여부를 점검하여 자동 학습을 수행하는 마이크로 세이프가드 lifespan."""
    if not has_any_trained_model():
        logger.info("[GeneratorDaemon] 학습된 모델이 없습니다. 최초 자동 학습을 시작합니다...")
        try:
            train_all(data_dir=None, force_reanalyze=False)
            logger.info("[GeneratorDaemon] 최초 자동 학습 완료.")
        except Exception as e:
            logger.error(f"[GeneratorDaemon] 최초 자동 학습 실패: {e}. 서버는 계속 기동합니다.")
    else:
        logger.info("[GeneratorDaemon] 기존 학습된 모델이 존재합니다. 자동 학습을 생략합니다.")
    yield


app = FastAPI(title="Generator Daemon API", lifespan=lifespan)


@app.get("/health")
def health():
    """서버 구동 상태 및 시스템 식별자 반환."""
    return {"status": "ok", "system": "generator"}


class TrainRequest(BaseModel):
    data_dir: Optional[str] = None
    force_reanalyze: bool = False


@app.post("/internal/train")
def train(req: TrainRequest):
    """최초 학습(또는 데몬 자동 기동 시 호출)용 엔드포인트. /internal/retrain과 동일 로직."""
    try:
        result = train_all(data_dir=req.data_dir, force_reanalyze=req.force_reanalyze)
        return result
    except Exception as e:
        logger.error(f"[GeneratorDaemon] /internal/train 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/internal/retrain")
def retrain(req: TrainRequest):
    """명시적 재학습 요청용 엔드포인트. /internal/train과 동일 로직(용도 구분 목적)."""
    try:
        result = train_all(data_dir=req.data_dir, force_reanalyze=req.force_reanalyze)
        return result
    except Exception as e:
        logger.error(f"[GeneratorDaemon] /internal/retrain 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class PredictRequest(BaseModel):
    rows: list[dict]


@app.post("/internal/predict")
def predict(req: PredictRequest):
    """전달받은 텔레메트리 행들로 고장 예측을 수행한다 (파일 저장 안 함)."""
    try:
        return run_prediction(req.rows)
    except Exception as e:
        logger.error(f"[GeneratorDaemon] /internal/predict 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class PredictFileRequest(BaseModel):
    data_dir: Optional[str] = None
    n: int = 20


@app.post("/internal/predict/file")
def predict_and_save_file(req: PredictFileRequest):
    """현재 상태(가장 최근 데이터 스냅샷)를 스스로 조회하여 예측을 구동하고 결과를 파일에 영속 저장한다."""
    try:
        rows = get_current_snapshot(data_dir=req.data_dir, n=req.n)
        predictions = run_prediction(rows)

        saved_path = None
        save_error = None
        try:
            saved_path = save_prediction_result(predictions, rows)
        except Exception as e:
            logger.warning(f"[GeneratorDaemon] 예측 결과 파일 저장 실패(예측 결과는 계속 반환됨): {e}")
            save_error = str(e)

        return {
            "predictions": predictions,
            "saved_path": saved_path,
            "save_error": save_error,
        }
    except Exception as e:
        logger.error(f"[GeneratorDaemon] /internal/predict/file 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))
