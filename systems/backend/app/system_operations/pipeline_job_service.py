from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .system_operation_exception import SystemOperationError


class PipelineJobService:
    def __init__(self, repository, generator) -> None:
        self.repository = repository
        self.generator = generator

    def create(self, body, actor: str, request_id: str) -> tuple[dict, bool]:
        existing = self.repository.get_by_idempotency_key(body.idempotency_key)
        if existing:
            return existing, False
        active = self.repository.find_active(body.source_uri, body.mapping_sha256)
        if active:
            raise SystemOperationError(409, "SYSTEM_JOB_ALREADY_RUNNING", "동일 source와 Mapping의 Rebuild Job이 이미 실행 중입니다.")
        try:
            published = self.generator.read_mapping(body.mapping_id, body.mapping_version)
        except Exception as exc:
            raise SystemOperationError(422, "SYSTEM_MAPPING_NOT_PUBLISHED", "발행된 Mapping 버전을 확인할 수 없습니다.") from exc
        if published.get("mapping_sha256") != body.mapping_sha256:
            raise SystemOperationError(422, "SYSTEM_MAPPING_INTEGRITY_ERROR", "발행 Mapping checksum이 Job 요청과 일치하지 않습니다.")
        now = datetime.now(timezone.utc).isoformat()
        return self.repository.create_or_get({
            "job_id": str(uuid.uuid4()), "job_type": body.job_type, "request_id": request_id,
            "idempotency_key": body.idempotency_key, "run_id": str(uuid.uuid4()),
            "mapping_id": body.mapping_id, "mapping_version": body.mapping_version,
            "mapping_sha256": body.mapping_sha256, "source_uri": body.source_uri,
            "activate_on_success": body.activate_on_success, "created_by": actor, "created_at": now,
        })

    def get(self, job_id: str) -> dict:
        job = self.repository.get(job_id)
        if job is None:
            raise SystemOperationError(404, "SYSTEM_JOB_NOT_FOUND", "Pipeline Job을 찾을 수 없습니다.")
        return job

    def list(self, status: str | None = None) -> list[dict]:
        return self.repository.list(status)

    def cancel(self, job_id: str) -> dict:
        before = self.get(job_id)
        if before["status"] not in {"queued", "running", "checkpointed"}:
            raise SystemOperationError(409, "SYSTEM_JOB_NOT_CANCELLABLE", "현재 상태에서는 Job을 취소할 수 없습니다.")
        return self.repository.request_cancel(job_id)

    def execute(self, job_id: str, worker_id: str = "backend-worker") -> dict:
        claimed = self.repository.claim(job_id, worker_id)
        if claimed is None:
            return self.get(job_id)
        try:
            result = self.generator.rebuild({
                "job_id": claimed["job_id"], "run_id": claimed["run_id"],
                "idempotency_key": claimed["idempotency_key"], "source_uri": claimed["source_uri"],
                "mapping_id": claimed["mapping_id"], "mapping_version": claimed["mapping_version"],
                "mapping_sha256": claimed["mapping_sha256"], "replay_scope": "full_source",
            })
            activation = None
            if claimed["activate_on_success"]:
                activation = self.generator.activate(claimed["mapping_id"], {
                    "mapping_version": claimed["mapping_version"], "mapping_sha256": claimed["mapping_sha256"],
                    "activated_by_job_id": claimed["job_id"],
                })
            return self.repository.finish(job_id, {"rebuild": result, "activation": activation})
        except Exception as exc:
            return self.repository.fail(job_id, type(exc).__name__, str(exc))
