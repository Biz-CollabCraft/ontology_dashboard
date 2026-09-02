from types import SimpleNamespace


def build_service(tmp_path):
    from systems.backend.app.infra.db.migrations import migrate
    from systems.backend.app.infra.db.system_audit_repository import SystemAuditRepository
    from systems.backend.app.system_operations.audit_service import SystemAuditService
    database = tmp_path / "audit.db"; migrate(str(database))
    return SystemAuditService(SystemAuditRepository(database), tmp_path / "exports")


def test_audit_is_append_only_and_redacts_secrets(tmp_path):
    service = build_service(tmp_path)
    saved = service.record(actor_id="operator-1", action="model.select", resource_type="model_artifact",
        resource_id="lightgbm", resource_version="1.0.0", outcome="succeeded", request_id="request-1",
        metadata={"token": "secret", "nested": {"password": "secret"}})
    item = service.get_audit(saved["audit_id"])
    assert item["metadata"] == {"token": "[REDACTED]", "nested": {"password": "[REDACTED]"}}
    assert not hasattr(service.repository, "update_audit")
    assert not hasattr(service.repository, "delete_audit")


def test_jsonl_export_is_bounded_and_checksummed(tmp_path):
    service = build_service(tmp_path)
    for index in range(3):
        service.record(actor_id="operator-1", action="mapping.publish", resource_type="static_mapping",
            resource_id=f"map-{index}", resource_version="1", outcome="succeeded", request_id=f"request-{index}", metadata={})
    result = service.export(SimpleNamespace(source="audit", filters={}, limit=2), "operator-1", "request-export")
    assert result["record_count"] == 2 and result["truncated"] is True
    assert len(result["sha256"]) == 64
    assert (tmp_path / "exports" / f'{result["export_id"]}.jsonl').exists()
    assert service.list_audit({"action": "logs.export"}, 10)["count"] == 1


def test_recovery_guide_is_fail_closed_for_unknown_code():
    from systems.backend.app.system_operations.recovery_guide import recovery_guide
    result = recovery_guide("UNKNOWN_CODE")
    assert result["automatic_retry_allowed"] is False
    assert result["destructive_action_required"] is False
