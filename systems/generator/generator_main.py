"""Generator domain FastAPI background daemon server module."""

from __future__ import annotations

import asyncio
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

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Safeguard lifespan checking model presence and triggering startup training asynchronously if needed."""
    load_config()
    if not has_any_trained_model():
        logger.info("[GeneratorDaemon] No trained models found. Starting initial automatic training...")
        try:
            await asyncio.to_thread(train_all, force_reanalyze=False)
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
    if req.data_dir and not os.path.exists(req.data_dir):
        raise HTTPException(status_code=400, detail=f"지정한 data_dir가 존재하지 않습니다: {req.data_dir}")
    try:
        result = train_all(data_dir=req.data_dir, force_reanalyze=req.force_reanalyze)
        return result
    except Exception as e:
        logger.error(f"[GeneratorDaemon] /internal/train failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/internal/retrain")
def retrain(req: TrainRequest) -> dict:
    """Explicit re-training endpoint. Dispatches to train_all with new versioning."""
    if req.data_dir and not os.path.exists(req.data_dir):
        raise HTTPException(status_code=400, detail=f"지정한 data_dir가 존재하지 않습니다: {req.data_dir}")
    try:
        result = train_all(data_dir=req.data_dir, force_reanalyze=req.force_reanalyze)
        return result
    except Exception as e:
        logger.error(f"[GeneratorDaemon] /internal/retrain failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
