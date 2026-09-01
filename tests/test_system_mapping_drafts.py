import json
from pathlib import Path

import pytest

from app.infra.db.mapping_draft_repository import MappingDraftRepository
from app.infra.db.migrations import migrate
from app.system_operations.mapping_draft_exception import MappingDraftConflict, MappingDraftInvalid
from app.system_operations.mapping_draft_service import MappingDraftService, canonical_sha


class FakeGenerator:
    def __init__(self):
        root = Path(__file__).resolve().parents[1]
        self.mapping = json.loads((root / "contracts/examples/generator-protocol-extraction/static-mapping-table.json").read_text(encoding="utf-8"))

    def read_mapping(self, mapping_id, version):
        return dict(self.mapping)

    def validate_mapping(self, mapping_id, version, mapping):
        approved = dict(mapping)
        approved.update(mapping_id=mapping_id, mapping_version=version, status="approved")
        checksum = canonical_sha(approved)
        approved["mapping_sha256"] = checksum
        return {"status": "valid", "mapping_sha256": checksum, "normalized_mapping": approved, "errors": []}

    def publish_mapping(self, request_id, mapping_id, version, checksum, mapping):
        return {"mapping_id": mapping_id, "mapping_version": version, "mapping_sha256": checksum, "logical_uri": f"ontology/mappings/{mapping_id}/{version}/mapping.json", "published_at": "2026-09-01T00:00:00Z", "idempotent": False}


class FakeRegistry:
    def refresh(self):
        return {"status": "succeeded"}


def _service(tmp_path: Path):
    database = tmp_path / "mapping.db"
    migrate(str(database))
    return MappingDraftService(MappingDraftRepository(database), FakeGenerator(), FakeRegistry())


def test_draft_revision_invalidates_validation(tmp_path: Path):
    service = _service(tmp_path)
    draft = service.create("mapping-a", "v2", "v1", "operator")
    validated = service.validate(draft["draft_id"], "operator")
    assert validated["status"] == "validated"
    payload = dict(validated["payload"])
    payload["description"] = "edited"
    updated = service.update(draft["draft_id"], validated["revision"], payload, "operator")
    assert updated["revision"] == 2
    assert updated["validation_status"] == "not_validated"
    with pytest.raises(MappingDraftInvalid):
        service.publish(draft["draft_id"], updated["revision"], "operator")


def test_stale_revision_is_rejected(tmp_path: Path):
    service = _service(tmp_path)
    draft = service.create("mapping-a", "v2", "v1", "operator")
    service.update(draft["draft_id"], 1, draft["payload"], "operator")
    with pytest.raises(MappingDraftConflict):
        service.update(draft["draft_id"], 1, draft["payload"], "operator")


def test_validated_draft_publishes_and_refreshes_registry(tmp_path: Path):
    service = _service(tmp_path)
    draft = service.create("mapping-a", "v2", "v1", "operator")
    validated = service.validate(draft["draft_id"], "operator")
    result = service.publish(draft["draft_id"], validated["revision"], "operator")
    assert result["draft"]["status"] == "published"
    assert result["registry_reconciled"] is True
