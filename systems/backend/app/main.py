"""
systems/backend/app/main.py

FastAPI 애플리케이션 진입점 파일.
4개 도메인(equipment, diagnosis, report, dashboard)의 라우터를 실제로 등록하고
기동 가능한 애플리케이션 및 헬스체크(/health) 엔드포인트를 제공한다.
"""

from fastapi import FastAPI
from app.equipment import router as equipment_router
from app.diagnosis import router as diagnosis_router
from app.report import router as report_router
from app.dashboard import router as dashboard_router

app = FastAPI(
    title="CodeMap Backend API",
    description="PdM 설비 예지보전 백엔드 API 서비스",
    version="1.0.0",
)

# 4개 도메인 라우터 등록
app.include_router(equipment_router, prefix="/api/v1")
app.include_router(diagnosis_router, prefix="/api/v1")
app.include_router(report_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")


@app.get("/health", tags=["Health"])
def health_check():
    """헬스체크 엔드포인트"""
    return {"status": "ok", "system": "backend", "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
