from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from .mapping_draft_exception import MappingDraftConflict, MappingDraftInvalid, MappingDraftNotFound


def canonical_sha(payload: dict[str, Any]) -> str:
    value = dict(payload)
    value.pop("mapping_sha256", None)
    value.pop("$schema", None)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class MappingDraftService:
    def __init__(self, repository, generator, registry_service) -> None:
        self.repository = repository
        self.generator = generator
        self.registry_service = registry_service

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def create(self, mapping_id: str, target_version: str, base_version: str | None, actor: str) -> dict[str, Any]:
        if base_version:
            payload = self.generator.read_mapping(mapping_id, base_version)
        else:
            payload = {
                "$schema": "https://ontology-dashboard.local/schemas/generator-static-mapping-table.schema.json",
                "mapping_id": mapping_id,
                "mapping_version": target_version,
                "mapping_sha256": "0" * 64,
                "status": "draft",
                "source_schema_version": "",
                "source_schema_fingerprint": "0" * 64,
                "fingerprint_algorithm_version": "v1",
                "field_mappings": [],
            }
        payload["mapping_id"] = mapping_id
        payload["mapping_version"] = target_version
        payload["status"] = "draft"
        payload["mapping_sha256"] = canonical_sha(payload)
        now = self._now()
        item = {
            "draft_id": str(uuid.uuid4()), "mapping_id": mapping_id, "target_version": target_version,
            "base_version": base_version, "revision": 1, "status": "draft", "payload": payload,
            "payload_sha256": payload["mapping_sha256"], "validation_status": "not_validated",
            "validation_errors": [], "validated_revision": None, "created_by": actor, "updated_by": actor,
            "created_at": now, "updated_at": now,
        }
        try:
            return self.repository.create(item)
        except sqlite3.IntegrityError as exc:
            raise MappingDraftConflict("MAPPING_DRAFT_VERSION_EXISTS", "동일 Mapping target version의 Draft가 이미 존재합니다.") from exc

    def get(self, draft_id: str) -> dict[str, Any]:
        item = self.repository.get(draft_id)
        if item is None:
            raise MappingDraftNotFound()
        return item

    def list(self) -> list[dict[str, Any]]:
        return self.repository.list()

    def update(self, draft_id: str, expected_revision: int, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        current = self.get(draft_id)
        if payload.get("mapping_id") != current["mapping_id"] or str(payload.get("mapping_version")) != current["target_version"]:
            raise MappingDraftInvalid("MAPPING_DRAFT_IDENTITY_INVALID", "Draft Mapping 식별자는 변경할 수 없습니다.")
        normalized = json.loads(json.dumps(payload))
        normalized["status"] = "draft"
        normalized["mapping_sha256"] = canonical_sha(normalized)
        updated = self.repository.update_payload(draft_id, expected_revision, normalized, normalized["mapping_sha256"], actor)
        if updated is None:
            raise MappingDraftConflict()
        return updated

    def validate(self, draft_id: str, actor: str) -> dict[str, Any]:
        current = self.get(draft_id)
        result = self.generator.validate_mapping(current["mapping_id"], current["target_version"], current["payload"])
        valid = result.get("status") == "valid"
        checksum = str(result.get("mapping_sha256") or current["payload_sha256"])
        errors = list(result.get("errors") or [])
        saved = self.repository.record_validation(draft_id, current["revision"], valid=valid, checksum=checksum, errors=errors, actor=actor)
        if saved is None:
            raise MappingDraftConflict("MAPPING_DRAFT_REVISION_CONFLICT", "검증 중 Draft가 변경되어 결과를 폐기했습니다.")
        return saved

    def publish(self, draft_id: str, expected_revision: int, actor: str) -> dict[str, Any]:
        current = self.get(draft_id)
        if current["revision"] != expected_revision:
            raise MappingDraftConflict()
        if current["status"] not in {"validated", "publishing"} or current.get("validated_revision") != expected_revision:
            raise MappingDraftInvalid("MAPPING_DRAFT_NOT_VALIDATED", "현재 revision의 검증을 먼저 완료해야 합니다.")
        if current["status"] == "validated":
            publishing = self.repository.mark_publishing(draft_id, expected_revision, actor)
            if publishing is None:
                raise MappingDraftConflict("MAPPING_PUBLISH_IN_PROGRESS", "Mapping이 이미 발행 중이거나 상태가 변경되었습니다.")
        try:
            result = self.generator.publish_mapping(
                draft_id, current["mapping_id"], current["target_version"], current["payload_sha256"], current["payload"]
            )
        except Exception as exc:
            self.repository.mark_publish_failed(draft_id, type(exc).__name__, "Generator Mapping 발행에 실패했습니다.", actor)
            raise MappingDraftInvalid("MAPPING_PUBLISH_FAILED", "Generator Mapping 발행에 실패했습니다.") from exc
        try:
            published = self.repository.mark_published(draft_id, result["mapping_sha256"], actor)
        except Exception as exc:
            raise MappingDraftInvalid(
                "MAPPING_PUBLISH_RESULT_UNCONFIRMED",
                "Generator 발행은 성공했지만 Backend 결과 기록을 확인하지 못했습니다. 동일 요청으로 복구해야 합니다.",
            ) from exc
        registry_reconciled = True
        try:
            self.registry_service.refresh()
        except Exception:
            registry_reconciled = False
        return {"draft": published, "publish": result, "registry_reconciled": registry_reconciled}

    def diff(self, draft_id: str) -> dict[str, Any]:
        draft = self.get(draft_id)
        base = self.generator.read_mapping(draft["mapping_id"], draft["base_version"]) if draft.get("base_version") else {"field_mappings": []}
        old = {item.get("source_field"): item for item in base.get("field_mappings", [])}
        new = {item.get("source_field"): item for item in draft["payload"].get("field_mappings", [])}
        added = [{"source_field": key, "after": new[key]} for key in sorted(new.keys() - old.keys())]
        removed = [{"source_field": key, "before": old[key]} for key in sorted(old.keys() - new.keys())]
        changed = [{"source_field": key, "before": old[key], "after": new[key]} for key in sorted(old.keys() & new.keys()) if old[key] != new[key]]
        return {
            "draft_id": draft_id, "base_version": draft.get("base_version"), "target_version": draft["target_version"],
            "summary": {"added": len(added), "removed": len(removed), "changed": len(changed)},
            "changes": [*added, *removed, *changed],
        }
