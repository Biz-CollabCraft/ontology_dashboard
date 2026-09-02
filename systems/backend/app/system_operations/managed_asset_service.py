from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from .managed_asset_diff import diff_payload
from .managed_asset_validator import create_template, validate_payload
from .system_operation_exception import SystemOperationError


def canonical_sha(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ManagedAssetService:
    def __init__(self, repository, generator=None, registry_service=None, audit=None) -> None:
        self.repository = repository
        self.generator = generator
        self.registry_service = registry_service
        self.audit = audit

    def get(self, draft_id: str) -> dict[str, Any]:
        draft = self.repository.get(draft_id)
        if draft is None:
            raise SystemOperationError(404, "SYSTEM_CONTRACT_DRAFT_NOT_FOUND", "계약 자산 Draft를 찾을 수 없습니다.")
        return draft

    def list(self, asset_type=None, status=None, asset_id=None) -> list[dict[str, Any]]:
        return self.repository.list(asset_type, status, asset_id)

    def create(self, body, actor: str) -> dict[str, Any]:
        if body.base_version:
            if self.generator is None:
                raise SystemOperationError(503, "SYSTEM_CONTRACT_GENERATOR_UNAVAILABLE", "Generator 계약 자산 API가 구성되지 않았습니다.")
            try:
                payload = self.generator.read(body.asset_type, body.asset_id, body.base_version)
            except Exception as exc:
                raise SystemOperationError(404, "SYSTEM_CONTRACT_BASE_VERSION_NOT_FOUND", "기준 버전을 찾을 수 없습니다.") from exc
            payload = json.loads(json.dumps(payload))
            from .managed_asset_validator import IDENTITY_FIELDS
            id_field, version_field = IDENTITY_FIELDS[body.asset_type]
            if id_field:
                payload[id_field] = body.asset_id
            payload[version_field] = body.target_version
        else:
            payload = create_template(body.asset_type, body.asset_id, body.target_version)
        now = datetime.now(timezone.utc).isoformat()
        item = {
            "draft_id": str(uuid.uuid4()), "asset_type": body.asset_type,
            "asset_id": body.asset_id, "target_version": body.target_version,
            "base_version": body.base_version, "payload": payload,
            "payload_sha256": canonical_sha(payload), "created_by": actor,
            "updated_by": actor, "created_at": now, "updated_at": now,
        }
        try:
            result = self.repository.create(item)
            if self.audit: self.audit.safe_record(actor_id=actor, action="contract_draft.create", resource_type=body.asset_type, resource_id=body.asset_id, resource_version=body.target_version, outcome="succeeded", request_id="contract-draft", metadata={"draft_id": item["draft_id"]})
            return result
        except sqlite3.IntegrityError as exc:
            raise SystemOperationError(409, "SYSTEM_CONTRACT_VERSION_EXISTS", "동일 자산 target version의 Draft가 이미 존재합니다.") from exc

    def update(self, draft_id: str, body, actor: str) -> dict[str, Any]:
        current = self.get(draft_id)
        errors, _ = validate_payload(current["asset_type"], current["asset_id"], current["target_version"], body.payload)
        if any(error["code"] == "SYSTEM_CONTRACT_IDENTITY_INVALID" for error in errors):
            raise SystemOperationError(422, "SYSTEM_CONTRACT_IDENTITY_INVALID", "자산 식별자는 변경할 수 없습니다.")
        saved = self.repository.update_payload(draft_id, body.expected_revision, body.payload, canonical_sha(body.payload), actor)
        if saved is None:
            if current["status"] == "published":
                raise SystemOperationError(409, "SYSTEM_CONTRACT_DRAFT_IMMUTABLE", "발행된 Draft는 수정할 수 없습니다.")
            raise SystemOperationError(409, "SYSTEM_CONTRACT_DRAFT_REVISION_CONFLICT", "Draft revision이 변경되었습니다.")
        if self.audit: self.audit.safe_record(actor_id=actor, action="contract_draft.update", resource_type=current["asset_type"], resource_id=current["asset_id"], resource_version=current["target_version"], outcome="succeeded", request_id="contract-draft", metadata={"draft_id": draft_id})
        return saved

    def validate(self, draft_id: str, actor: str) -> dict[str, Any]:
        current = self.get(draft_id)
        errors, warnings = validate_payload(current["asset_type"], current["asset_id"], current["target_version"], current["payload"])
        checksum = canonical_sha(current["payload"])
        saved = self.repository.record_validation(draft_id, current["revision"], checksum, errors, warnings, actor)
        if saved is None:
            raise SystemOperationError(409, "SYSTEM_CONTRACT_DRAFT_REVISION_CONFLICT", "검증 중 Draft가 변경되었습니다.")
        if self.audit: self.audit.safe_record(actor_id=actor, action="contract.validate", resource_type=current["asset_type"], resource_id=current["asset_id"], resource_version=current["target_version"], outcome="succeeded" if not errors else "failed", request_id="contract-draft", error_code=None if not errors else "SYSTEM_CONTRACT_VALIDATION_FAILED", metadata={"draft_id": draft_id})
        return {"draft_id": draft_id, "validation_status": "valid" if not errors else "invalid", "validated_revision": current["revision"], "payload_sha256": checksum, "errors": errors, "warnings": warnings}

    def diff(self, draft_id: str) -> dict[str, Any]:
        draft = self.get(draft_id)
        base: dict[str, Any] = {}
        if draft.get("base_version"):
            if self.generator is None:
                raise SystemOperationError(503, "SYSTEM_CONTRACT_GENERATOR_UNAVAILABLE", "Generator 계약 자산 API가 구성되지 않았습니다.")
            base = self.generator.read(draft["asset_type"], draft["asset_id"], draft["base_version"])
        changes = diff_payload(base, draft["payload"])
        return {
            "draft_id": draft_id, "base_version": draft.get("base_version"),
            "target_version": draft["target_version"],
            "summary": {
                "added": sum(change["change_type"] == "added" for change in changes),
                "removed": sum(change["change_type"] == "removed" for change in changes),
                "changed": sum(change["change_type"] == "changed" for change in changes),
            },
            "changes": changes,
        }

    def publish(self, draft_id: str, body, actor: str) -> dict[str, Any]:
        current = self.get(draft_id)
        if current["revision"] != body.expected_revision or current["payload_sha256"] != body.expected_payload_sha256:
            raise SystemOperationError(409, "SYSTEM_CONTRACT_VALIDATION_STALE", "검증 이후 Draft가 변경되었습니다.")
        if current["status"] != "validated" or current.get("validated_revision") != current["revision"]:
            raise SystemOperationError(422, "SYSTEM_CONTRACT_VALIDATION_FAILED", "현재 revision을 먼저 검증해야 합니다.")
        if self.generator is None:
            raise SystemOperationError(503, "SYSTEM_CONTRACT_GENERATOR_UNAVAILABLE", "Generator 계약 자산 API가 구성되지 않았습니다.")
        if self.repository.mark_publishing(draft_id, current["revision"], current["payload_sha256"], actor) is None:
            raise SystemOperationError(409, "SYSTEM_CONTRACT_PUBLISH_CONFLICT", "Draft 발행 상태가 변경되었습니다.")
        try:
            result = self.generator.publish(current["asset_type"], current["asset_id"], current["target_version"], current["payload_sha256"], current["payload"])
            if result.get("sha256") != current["payload_sha256"]:
                raise ValueError("Generator checksum mismatch")
        except Exception as exc:
            self.repository.mark_publish_failed(draft_id, type(exc).__name__, "Generator 계약 자산 발행에 실패했습니다.", actor)
            raise SystemOperationError(422, "SYSTEM_CONTRACT_PUBLISH_FAILED", "Generator 계약 자산 발행에 실패했습니다.") from exc
        published = self.repository.mark_published(draft_id, result["sha256"], actor)
        reconciled = True
        if self.registry_service is not None:
            try:
                self.registry_service.refresh()
            except Exception:
                reconciled = False
        if self.audit: self.audit.safe_record(actor_id=actor, action="contract.publish", resource_type=current["asset_type"], resource_id=current["asset_id"], resource_version=current["target_version"], outcome="succeeded", request_id="contract-draft", after_ref={"sha256": result["sha256"]}, metadata={"draft_id": draft_id})
        return {"draft": published, "publish": result, "registry_reconciled": reconciled, "impact_analysis_available": True}
