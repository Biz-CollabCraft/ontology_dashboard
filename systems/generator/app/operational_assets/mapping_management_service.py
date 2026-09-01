from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from systems.generator.app.extraction.mapping_repository import MappingRepository
from systems.generator.app.extraction.mapping_validator import MappingValidator, compute_mapping_canonical_sha256
from systems.generator.generator_config import PATHS


class MappingManagementError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class MappingManagementService:
    def __init__(self) -> None:
        self.root = PATHS.mapping_root.resolve()
        self.validator = MappingValidator()
        self.reader = MappingRepository(mapping_root=self.root, search_roots=[self.root])

    def read(self, mapping_id: str, mapping_version: str) -> dict[str, Any]:
        try:
            data, _ = self.reader.load_mapping(mapping_id, mapping_version)
            return data
        except Exception as exc:
            raise MappingManagementError(404, "MAPPING_BASE_VERSION_NOT_FOUND", "요청한 Mapping 버전을 찾을 수 없습니다.") from exc

    def normalize_and_validate(self, mapping_id: str, mapping_version: str, payload: dict[str, Any], *, approved: bool) -> tuple[dict[str, Any], str]:
        normalized = json.loads(json.dumps(payload))
        normalized["mapping_id"] = mapping_id
        normalized["mapping_version"] = mapping_version
        normalized["status"] = "approved" if approved else "draft"
        normalized["mapping_sha256"] = compute_mapping_canonical_sha256(normalized)
        self.validator.validate_mapping(
            normalized,
            expected_mapping_id=mapping_id,
            expected_mapping_version=mapping_version,
            expected_mapping_sha256=normalized["mapping_sha256"],
            require_approved=approved,
        )
        return normalized, normalized["mapping_sha256"]

    def validate(self, mapping_id: str, mapping_version: str, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        # Validation returns the exact approved payload/checksum that publish will persist.
        return self.normalize_and_validate(mapping_id, mapping_version, payload, approved=True)

    def publish(self, mapping_id: str, mapping_version: str, payload: dict[str, Any], expected_sha256: str) -> dict[str, Any]:
        normalized, checksum = self.normalize_and_validate(mapping_id, mapping_version, payload, approved=True)
        if checksum != expected_sha256:
            raise MappingManagementError(422, "MAPPING_PUBLISH_CHECKSUM_MISMATCH", "검증된 Mapping checksum과 발행 요청이 일치하지 않습니다.")
        final_dir = (self.root / mapping_id / mapping_version).resolve()
        if self.root != final_dir and self.root not in final_dir.parents:
            raise MappingManagementError(422, "MAPPING_DRAFT_IDENTITY_INVALID", "Mapping 발행 경로가 허용 범위를 벗어났습니다.")
        final_file = final_dir / "mapping.json"
        lock_path = final_dir.parent / f".{mapping_version}.publish.lock"
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(lock_fd)
        except FileExistsError as exc:
            raise MappingManagementError(409, "MAPPING_PUBLISH_IN_PROGRESS", "동일 Mapping 버전이 현재 발행 중입니다.") from exc
        temp_dir = final_dir.parent / f".{mapping_version}.tmp-{uuid.uuid4().hex}"
        try:
            if final_file.is_file():
                existing = json.loads(final_file.read_text(encoding="utf-8"))
                existing_sha = compute_mapping_canonical_sha256(existing)
                if existing_sha == checksum:
                    return self._result(mapping_id, mapping_version, checksum, idempotent=True)
                raise MappingManagementError(409, "MAPPING_PUBLISH_CONFLICT", "동일 버전에 다른 Mapping이 이미 발행되어 있습니다.")
            if final_dir.exists():
                raise MappingManagementError(409, "MAPPING_PUBLISH_CONFLICT", "완전하지 않은 Mapping 발행 경로가 이미 존재합니다.")
            temp_dir.mkdir()
            temp_file = temp_dir / "mapping.json"
            temp_file.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            reread = json.loads(temp_file.read_text(encoding="utf-8"))
            self.normalize_and_validate(mapping_id, mapping_version, reread, approved=True)
            os.rename(temp_dir, final_dir)
            return self._result(mapping_id, mapping_version, checksum, idempotent=False)
        except FileExistsError as exc:
            raise MappingManagementError(409, "MAPPING_PUBLISH_CONFLICT", "동일 Mapping 버전이 동시에 발행되었습니다.") from exc
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            lock_path.unlink(missing_ok=True)

    def _result(self, mapping_id: str, mapping_version: str, checksum: str, *, idempotent: bool) -> dict[str, Any]:
        return {
            "mapping_id": mapping_id,
            "mapping_version": mapping_version,
            "mapping_sha256": checksum,
            "logical_uri": f"ontology/mappings/{mapping_id}/{mapping_version}/mapping.json",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "idempotent": idempotent,
        }

    def read_active(self, mapping_id: str) -> dict[str, Any]:
        pointer = (self.root / mapping_id / "active.json").resolve()
        if self.root not in pointer.parents or not pointer.is_file():
            raise MappingManagementError(404, "MAPPING_ACTIVE_VERSION_NOT_FOUND", "활성 Mapping 버전이 없습니다.")
        try:
            payload = json.loads(pointer.read_text(encoding="utf-8"))
            mapping = self.read(mapping_id, str(payload["mapping_version"]))
            checksum = compute_mapping_canonical_sha256(mapping)
            if checksum != payload.get("mapping_sha256"):
                raise ValueError("active pointer checksum mismatch")
            return payload
        except MappingManagementError:
            raise
        except Exception as exc:
            raise MappingManagementError(422, "MAPPING_ACTIVE_POINTER_INVALID", "활성 Mapping 포인터가 손상되었습니다.") from exc

    def activate(self, mapping_id: str, mapping_version: str, mapping_sha256: str, job_id: str) -> dict[str, Any]:
        mapping = self.read(mapping_id, mapping_version)
        actual = compute_mapping_canonical_sha256(mapping)
        if actual != mapping_sha256:
            raise MappingManagementError(422, "MAPPING_ACTIVATION_CHECKSUM_MISMATCH", "발행 Mapping checksum이 활성화 요청과 일치하지 않습니다.")
        mapping_dir = (self.root / mapping_id).resolve()
        mapping_dir.mkdir(parents=True, exist_ok=True)
        pointer = mapping_dir / "active.json"
        if pointer.is_file():
            current = self.read_active(mapping_id)
            if current.get("mapping_version") == mapping_version and current.get("mapping_sha256") == actual:
                return {**current, "idempotent": True}
        payload = {
            "mapping_id": mapping_id,
            "mapping_version": mapping_version,
            "mapping_sha256": actual,
            "activated_by_job_id": job_id,
            "activated_at": datetime.now(timezone.utc).isoformat(),
        }
        temp = mapping_dir / f".active.tmp-{uuid.uuid4().hex}"
        try:
            with temp.open("w", encoding="utf-8") as stream:
                stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, pointer)
            verified = self.read_active(mapping_id)
            return {**verified, "idempotent": False}
        except Exception as exc:
            raise MappingManagementError(500, "MAPPING_ACTIVATION_FAILED", "Mapping 활성 포인터를 원자적으로 갱신하지 못했습니다.") from exc
        finally:
            temp.unlink(missing_ok=True)
