"""Generator domain FastAPI background daemon server module."""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from systems.generator.generator_config import load_config
from systems.generator.model.model_registry import has_any_trained_model
from systems.generator.model.model_training import train_all

load_config()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Safeguard lifespan checking model presence and triggering startup training if needed."""
    if not has_any_trained_model():
        logger.info("[GeneratorDaemon] No trained models found. Starting initial automatic training...")
        try:
            train_all(force_reanalyze=False)
            logger.info("[GeneratorDaemon] Initial automatic training completed successfully.")
        except Exception as e:
            logger.error(f"[GeneratorDaemon] Initial automatic training failed: {e}. Daemon continues running.")
    else:
        logger.info("[GeneratorDaemon] Existing trained models detected. Skipping auto-training.")
    yield


app = FastAPI(title="Generator Daemon API", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    """Server health status and system identifier."""
    return {"status": "ok", "system": "generator"}


class TrainRequest(BaseModel):
    data_dir: str | None = None
    force_reanalyze: bool = False


@app.post("/internal/train")
def train(req: TrainRequest) -> dict:
    """Initial training execution endpoint. Runs train_all."""
    try:
        result = train_all(data_dir=req.data_dir, force_reanalyze=req.force_reanalyze)
        return result
    except Exception as e:
        logger.error(f"[GeneratorDaemon] /internal/train failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/internal/retrain")
def retrain(req: TrainRequest) -> dict:
    """Explicit re-training endpoint. Dispatches to train_all with new versioning."""
    try:
        result = train_all(data_dir=req.data_dir, force_reanalyze=req.force_reanalyze)
        return result
    except Exception as e:
        logger.error(f"[GeneratorDaemon] /internal/retrain failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class PredictRequest(BaseModel):
    rows: list[dict]


@app.post("/internal/predict")
def predict(req: PredictRequest) -> dict:
    """Execute prediction on provided telemetry rows without saving file."""
    try:
        from systems.generator.prediction.prediction_service import run_prediction

        return run_prediction(req.rows)
    except ModuleNotFoundError:
        raise HTTPException(status_code=501, detail="Prediction service is not installed in this stage.")
    except Exception as e:
        logger.error(f"[GeneratorDaemon] /internal/predict failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class PredictFileRequest(BaseModel):
    data_dir: str | None = None
    n: int = 20


@app.post("/internal/predict/file")
def predict_and_save_file(req: PredictFileRequest) -> dict:
    """Query recent snapshot and execute prediction, persisting results to disk."""
    try:
        from systems.generator.prediction.prediction_repository import save_prediction_result
        from systems.generator.prediction.prediction_service import get_current_snapshot, run_prediction

        rows = get_current_snapshot(data_dir=req.data_dir, n=req.n)
        predictions = run_prediction(rows)

        saved_path = None
        save_error = None
        try:
            saved_path = save_prediction_result(predictions, rows)
        except Exception as e:
            logger.warning(f"[GeneratorDaemon] Prediction file save warning (results still returned): {e}")
            save_error = str(e)

        return {
            "predictions": predictions,
            "saved_path": saved_path,
            "save_error": save_error,
        }
    except ModuleNotFoundError:
        raise HTTPException(status_code=501, detail="Prediction service is not installed in this stage.")
    except Exception as e:
        logger.error(f"[GeneratorDaemon] /internal/predict/file failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
