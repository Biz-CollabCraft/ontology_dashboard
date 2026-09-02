from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .system_operation_exception import SystemOperationError


class PipelineJobService:
    def __init__(self, repository, generator, impact_repository=None, downstream_generator=None, audit=None) -> None:
        self.repository = repository
        self.generator = generator
        self.impact_repository = impact_repository
        self.downstream_generator = downstream_generator
        self.audit = audit

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
        result = self.repository.create_or_get({
            "job_id": str(uuid.uuid4()), "job_type": body.job_type, "request_id": request_id,
            "idempotency_key": body.idempotency_key, "run_id": str(uuid.uuid4()),
            "mapping_id": body.mapping_id, "mapping_version": body.mapping_version,
            "mapping_sha256": body.mapping_sha256, "source_uri": body.source_uri,
            "activate_on_success": body.activate_on_success, "created_by": actor, "created_at": now,
        })
        job = result[0] if isinstance(result, tuple) else result
        if self.audit: self.audit.safe_record(actor_id=actor, action="pipeline_job.create", resource_type="pipeline_job", resource_id=job["job_id"], resource_version=None, outcome="succeeded", request_id=request_id, job_id=job["job_id"], metadata={"job_type": body.job_type})
        return result

    def get(self, job_id: str) -> dict:
        job = self.repository.get(job_id)
        if job is None:
            raise SystemOperationError(404, "SYSTEM_JOB_NOT_FOUND", "Pipeline Job을 찾을 수 없습니다.")
        if job["job_type"] == "downstream_rebuild":
            job["steps"] = self.repository.list_steps(job_id)
        return job

    def create_downstream(self, analysis_id: str, body, actor: str, request_id: str) -> dict:
        if self.impact_repository is None:
            raise SystemOperationError(503, "SYSTEM_IMPACT_EXECUTOR_UNAVAILABLE", "영향 분석 실행기가 구성되지 않았습니다.")
        analysis = self.impact_repository.get(analysis_id)
        if analysis is None:
            raise SystemOperationError(404, "SYSTEM_IMPACT_ANALYSIS_NOT_FOUND", "영향 분석을 찾을 수 없습니다.")
        if body.expected_snapshot_sha256 != analysis["snapshot_sha256"]:
            raise SystemOperationError(409, "SYSTEM_IMPACT_SNAPSHOT_STALE", "영향 분석 snapshot이 변경되었습니다. 다시 분석해 주세요.")
        actions = {action["action_id"]: action for action in analysis["recommended_actions"]}
        missing = [action_id for action_id in body.selected_action_ids if action_id not in actions]
        if missing:
            raise SystemOperationError(422, "SYSTEM_IMPACT_ACTION_NOT_EXECUTABLE", "차단되었거나 존재하지 않는 작업은 실행할 수 없습니다.")
        selected = [actions[action_id] for action_id in body.selected_action_ids]
        selected.sort(key=lambda action: {"preprocessing": 0, "feature": 1, "training": 2}[action["stage"]])
        selected_ids = {action["action_id"] for action in selected}
        for action in selected:
            unmet = [dependency for dependency in action.get("depends_on_action_ids", []) if dependency not in selected_ids]
            if unmet:
                raise SystemOperationError(422, "SYSTEM_IMPACT_DEPENDENCY_MISSING", "선택 작업의 선행 단계가 누락되었습니다.")
        now = datetime.now(timezone.utc).isoformat()
        job_id = str(uuid.uuid4())
        steps = [
            {
                "step_id": str(uuid.uuid4()), "action_id": action["action_id"],
                "stage": action["stage"], "sequence": index,
                "input": dict(action.get("required_parameters") or {}),
            }
            for index, action in enumerate(selected)
        ]
        return self.repository.create_downstream(
            {
                "job_id": job_id, "request_id": request_id, "idempotency_key": f"impact:{analysis_id}:{body.expected_snapshot_sha256}:{','.join(body.selected_action_ids)}",
                "run_id": str(uuid.uuid4()), "analysis_id": analysis_id,
                "mapping_id": analysis["mapping_id"], "mapping_version": analysis["mapping_version"],
                "mapping_sha256": analysis["mapping_sha256"], "source_uri": f"system-impact-analyses/{analysis_id}",
                "created_by": actor, "created_at": now,
            },
            steps,
        )

    def list(self, status: str | None = None) -> list[dict]:
        return self.repository.list(status)

    def cancel(self, job_id: str) -> dict:
        before = self.get(job_id)
        if before["status"] not in {"queued", "running", "checkpointed"}:
            raise SystemOperationError(409, "SYSTEM_JOB_NOT_CANCELLABLE", "현재 상태에서는 Job을 취소할 수 없습니다.")
        result = self.repository.request_cancel(job_id)
        if self.audit: self.audit.safe_record(actor_id=before.get("created_by", "system"), actor_type="system", action="pipeline_job.cancel", resource_type="pipeline_job", resource_id=job_id, resource_version=None, outcome="succeeded", request_id=before.get("request_id") or "pipeline-job", job_id=job_id, metadata={})
        return result

    def execute(self, job_id: str, worker_id: str = "backend-worker") -> dict:
        claimed = self.repository.claim(job_id, worker_id)
        if claimed is None:
            return self.get(job_id)
        if claimed["job_type"] == "downstream_rebuild":
            return self._execute_downstream(claimed)
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

    def _execute_downstream(self, claimed: dict) -> dict:
        if self.downstream_generator is None:
            return self.repository.fail(
                claimed["job_id"], "SYSTEM_DOWNSTREAM_GENERATOR_UNAVAILABLE",
                "Generator downstream client is not configured",
            )
        outputs: list[dict] = []
        for step in self.repository.list_steps(claimed["job_id"]):
            current = self.get(claimed["job_id"])
            if current["cancel_requested"]:
                self.repository.block_remaining_steps(claimed["job_id"], step["sequence"] - 1)
                return self.repository.fail(claimed["job_id"], "SYSTEM_JOB_CANCELLED", "Job cancellation was requested")
            self.repository.start_step(step["step_id"])
            try:
                output = self.downstream_generator.execute(step["stage"], step["input"])
                self.repository.finish_step(step["step_id"], output)
                outputs.append({"action_id": step["action_id"], "stage": step["stage"], "output": output})
            except Exception as exc:
                self.repository.fail_step(step["step_id"], type(exc).__name__, str(exc))
                self.repository.block_remaining_steps(claimed["job_id"], step["sequence"])
                return self.repository.fail(claimed["job_id"], type(exc).__name__, str(exc))
        self.repository.finish(claimed["job_id"], {"steps": outputs})
        return self.get(claimed["job_id"])
