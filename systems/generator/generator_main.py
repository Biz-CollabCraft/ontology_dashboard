"""Generator domain FastAPI background daemon server module."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from systems.generator.generator_config import load_config
from systems.generator.model.model_registry import has_any_trained_model
from systems.generator.model.model_training import train_all

logger = logging.getLogger(__name__)

_training_lock = asyncio.Lock()


def _validate_data_dir(data_dir: str | None) -> None:
    """Validate data directory: must exist, be a directory, and not be empty."""
    if not data_dir:
        return
    path = Path(data_dir)
    if not path.exists():
        raise HTTPException(status_code=400, detail=f"지정한 data_dir가 존재하지 않습니다: {data_dir}")
    if not path.is_dir():
        raise HTTPException(status_code=400, detail=f"지정한 data_dir가 디렉터리가 아닙니다: {data_dir}")
    if not any(path.iterdir()):
        raise HTTPException(status_code=400, detail=f"지정한 data_dir가 비어 있습니다: {data_dir}")


async def _execute_training(*, data_dir: str | None, force_reanalyze: bool) -> dict:
    """Execute model training under process-wide concurrency lock."""
    _validate_data_dir(data_dir)
    if _training_lock.locked():
        raise HTTPException(status_code=409, detail="모델 학습이 이미 진행 중입니다.")
    async with _training_lock:
        try:
            return await asyncio.to_thread(train_all, data_dir=data_dir, force_reanalyze=force_reanalyze)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("[GeneratorDaemon] Training failed")
            raise HTTPException(status_code=500, detail="모델 학습에 실패했습니다.") from exc


async def _run_initial_training() -> None:
    """Background startup training worker."""
    try:
        await _execute_training(data_dir=None, force_reanalyze=False)
        logger.info("[GeneratorDaemon] Initial automatic training completed successfully.")
    except Exception:
        logger.exception("[GeneratorDaemon] Initial automatic training failed. Daemon remains available.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan managing configuration loading and non-blocking background initial training."""
    load_config()
    app.state.initial_training_task = None

    if not has_any_trained_model():
        logger.info("[GeneratorDaemon] No trained models found. Scheduling initial automatic training...")
        app.state.initial_training_task = asyncio.create_task(_run_initial_training())
    else:
        logger.info("[GeneratorDaemon] Existing trained models detected. Skipping auto-training.")

    yield

    task = getattr(app.state, "initial_training_task", None)
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Generator Daemon API", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    """Server health status and system identifier."""
    return {"status": "ok", "system": "generator"}


class TrainRequest(BaseModel):
    data_dir: str | None = None
    force_reanalyze: bool = False


@app.post("/internal/train")
async def train(req: TrainRequest) -> dict:
    """Initial training execution endpoint. Runs train_all under concurrency lock."""
    return await _execute_training(data_dir=req.data_dir, force_reanalyze=req.force_reanalyze)


@app.post("/internal/retrain")
async def retrain(req: TrainRequest) -> dict:
    """Explicit re-training endpoint. Dispatches to train_all under concurrency lock."""
    return await _execute_training(data_dir=req.data_dir, force_reanalyze=req.force_reanalyze)
