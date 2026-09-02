from __future__ import annotations

import uuid
import hashlib
import json
from datetime import datetime, timezone

from .system_operation_exception import SystemOperationError


class ModelOperationService:
    def __init__(self, repository, generator) -> None:
        self.repository=repository; self.generator=generator
    @staticmethod
    def _now(): return datetime.now(timezone.utc).isoformat()
    def list_models(self): return self.generator.list_models()
    def get_active(self): return self.generator.get_active()
    def history(self, model_id): return {"items": self.repository.selection_history(model_id)}
    def revisions(self): return {"items": self.repository.revisions()}
    def select(self, model_id, body, actor):
        previous=None
        try: previous=self.generator.get_selection(model_id)
        except Exception: pass
        try:
            result=self.generator.select(model_id,{**body.model_dump(),"actor":f"system-operator:{actor}"})
        except Exception as exc:
            raise SystemOperationError(422,"MODEL_SELECTION_FAILED",str(exc)) from exc
        if result.get("idempotent"):
            return result
        self.repository.record_selection({"selection_id":result["selection_id"],"model_id":model_id,"from_model_version":previous.get("model_version") if previous else None,"to_model_version":result["model_version"],"from_manifest_sha256":previous.get("model_artifact_manifest_sha256") if previous else None,"to_manifest_sha256":result["model_artifact_manifest_sha256"],"action":"select","reason":body.reason,"actor":actor,"status":"succeeded","created_at":self._now()})
        return result
    def clear(self, model_id, body, actor):
        try: previous=self.generator.get_selection(model_id); result=self.generator.clear(model_id,{**body.model_dump(),"actor":f"system-operator:{actor}"})
        except Exception as exc: raise SystemOperationError(422,"MODEL_SELECTION_CLEAR_FAILED",str(exc)) from exc
        self.repository.record_selection({"selection_id":str(uuid.uuid4()),"model_id":model_id,"from_model_version":previous.get("model_version"),"to_model_version":None,"from_manifest_sha256":previous.get("model_artifact_manifest_sha256"),"to_manifest_sha256":None,"action":"clear","reason":body.reason,"actor":actor,"status":"succeeded","created_at":self._now()})
        return result
    def validate(self, body, actor):
        try: return self.generator.validate_set({**body.model_dump(),"actor":f"system-operator:{actor}"})
        except Exception as exc: raise SystemOperationError(422,"ACTIVE_MODEL_SET_INVALID",str(exc)) from exc
    def activate(self, body, actor, action="activate"):
        request_payload=body.model_dump()
        previous=self.repository.revisions()[0]["revision_id"] if self.repository.revisions() else None
        operation = self.generator.rollback_set if action == "rollback" else self.generator.activate_set
        try: result=operation({**request_payload,"actor":f"system-operator:{actor}"})
        except Exception as exc:
            failed={"revision_id":str(uuid.uuid4()),"model_set_id":body.model_set_id,"model_set_version":body.model_set_version,"payload_sha256":hashlib.sha256(json.dumps(request_payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest(),"previous_revision_id":previous,"status":"failed","requested_by":actor,"reason":body.reason,"created_at":self._now(),"activated_at":None,"error_code":"ACTIVE_MODEL_SET_ACTIVATION_FAILED","error_message":str(exc),"payload":{"model_set_id":body.model_set_id,"model_set_version":body.model_set_version,"updated_at":self._now(),"models":{m["model_id"]:{"model_version":m.get("model_version") or "unresolved","required":m.get("required",True)} for m in body.models}}}
            self.repository.record_revision(failed)
            raise SystemOperationError(422,"ACTIVE_MODEL_SET_ACTIVATION_FAILED",str(exc)) from exc
        revision={"revision_id":str(uuid.uuid4()),"model_set_id":body.model_set_id,"model_set_version":body.model_set_version,"payload_sha256":result["payload_sha256"],"previous_revision_id":previous,"status":"active","requested_by":actor,"reason":body.reason,"created_at":self._now(),"activated_at":self._now(),"payload":result["payload"]}
        self.repository.record_revision(revision); return revision
    def rollback(self, body, actor):
        revision=self.repository.get_revision(body.revision_id)
        if not revision: raise SystemOperationError(404,"ACTIVE_MODEL_SET_ROLLBACK_UNAVAILABLE","대상 revision을 찾을 수 없습니다.")
        payload=revision["payload"]
        from .model_operation_schema import ModelSetOperationRequest
        request=ModelSetOperationRequest(model_set_id=payload["model_set_id"],model_set_version=f'{payload["model_set_version"]}-rollback',models=[{"model_id":key,"model_version":value["model_version"],"required":value["required"]} for key,value in payload["models"].items()],reason=body.reason)
        return self.activate(request,actor,"rollback")
