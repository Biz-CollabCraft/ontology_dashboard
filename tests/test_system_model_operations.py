from __future__ import annotations

from types import SimpleNamespace


class FakeRepository:
    def __init__(self): self.selections=[]; self._revisions=[]
    def record_selection(self,item): self.selections.append(item); return item
    def selection_history(self,model_id): return [item for item in self.selections if item["model_id"] == model_id]
    def record_revision(self,item): self._revisions.insert(0,item); return item
    def revisions(self): return self._revisions
    def get_revision(self,revision_id): return next((item for item in self._revisions if item["revision_id"] == revision_id),None)


class FakeGenerator:
    def __init__(self): self.selection=None; self.active=None
    def list_models(self): return {"items":[]}
    def get_selection(self,_):
        if self.selection is None: raise RuntimeError("not found")
        return self.selection
    def select(self,model_id,body):
        self.selection={"selection_id":"selection-1","model_id":model_id,"model_version":body["model_version"],"model_artifact_manifest_sha256":body["model_artifact_manifest_sha256"]}; return self.selection
    def clear(self,model_id,body): self.selection=None; return {"model_id":model_id,"fallback_version":"1.1.0"}
    def validate_set(self,body): return {"status":"validated"}
    def activate_set(self,body):
        self.active={"model_set_id":body["model_set_id"],"model_set_version":body["model_set_version"],"updated_at":"2026-09-02T00:00:00Z","models":{m["model_id"]:{"model_version":m.get("model_version") or "1.2.0","required":m["required"]} for m in body["models"]}}
        return {"payload":self.active,"payload_sha256":"3"*64}
    def rollback_set(self,body): return self.activate_set(body)
    def get_active(self): return self.active


def test_selection_and_activation_are_separate():
    from systems.backend.app.system_operations.model_operation_schema import ModelSelectRequest, ModelSetOperationRequest
    from systems.backend.app.system_operations.model_operation_service import ModelOperationService
    repo=FakeRepository(); generator=FakeGenerator(); service=ModelOperationService(repo,generator)
    service.select("pdm-lightgbm",ModelSelectRequest(model_version="1.2.0",model_artifact_manifest_sha256="1"*64,reason="검증"),"operator-1")
    assert generator.active is None
    service.activate(ModelSetOperationRequest(model_set_id="production",model_set_version="v2",models=[{"model_id":"pdm-lightgbm","model_version":None,"required":True}],reason="운영 반영"),"operator-1")
    assert generator.active["models"]["pdm-lightgbm"]["model_version"] == "1.2.0"
    assert len(repo._revisions) == 1


def test_system_operator_has_model_permissions_only():
    from systems.backend.app.identity.identity_schema import ROLE_PERMISSIONS
    expected={"system.models.read","system.models.select","system.models.activate","system.models.rollback"}
    assert expected <= ROLE_PERMISSIONS["system_operator"]
    assert expected.isdisjoint(ROLE_PERMISSIONS["tenant_admin"])
