"""Run only the isolated local replay API: python scripts/serve_final_briefing_demo.py."""
from pathlib import Path
import sys
from typing import Literal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "systems/backend"))
sys.path.insert(0, str(ROOT / "tests"))
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from briefing_demo_replay_support import load_cases, read_case, replay_delivery, validate_replay

app = FastAPI(title="Local briefing replay", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:3318", "http://localhost:3318"], allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

def case(case_id):
    try:
        return read_case(case_id)
    except StopIteration:
        raise HTTPException(404, "시연 입력을 찾을 수 없습니다.")

@app.get("/health")
def health():
    return {"status": "ok", "scope": "local_replay"}

@app.get("/api/demo-briefing/cases")
def cases():
    return [{"case_id": c["case_id"], "label": c["label"]} for c in load_cases()]

@app.get("/api/demo-briefing/cases/{case_id}")
def delivery(case_id: int):
    return replay_delivery(case(case_id))

class CheckRequest(BaseModel):
    variant: Literal["recorded", "rejected"] = "recorded"

@app.post("/api/demo-briefing/cases/{case_id}/validate")
def validate(case_id: int, request: CheckRequest):
    return validate_replay(case(case_id), request.variant)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8328)
