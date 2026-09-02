from __future__ import annotations
import hashlib,json,uuid
from datetime import datetime,timezone
from .system_operation_exception import SystemOperationError

def _sha(value): return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()

class ImpactAnalysisService:
    def __init__(self, repository, jobs, audit=None): self.repository=repository; self.jobs=jobs; self.audit=audit
    def _record(self, item, actor):
        if self.audit: self.audit.safe_record(actor_id=actor, action="impact_analysis.create", resource_type="impact_analysis", resource_id=item["analysis_id"], resource_version=None, outcome="succeeded", request_id="impact-analysis", metadata={"snapshot_sha256": item["snapshot_sha256"]})
        return item
    def get(self,analysis_id):
        value=self.repository.get(analysis_id)
        if value is None: raise SystemOperationError(404,"SYSTEM_IMPACT_ANALYSIS_NOT_FOUND","영향 분석을 찾을 수 없습니다.")
        return value
    def list(self): return self.repository.list()
    def create(self,body,actor):
        if body.source_asset_type:
            return self._create_managed_asset_analysis(body, actor)
        job=self.jobs.get(body.rebuild_job_id)
        if job["status"]!="succeeded": raise SystemOperationError(409,"SYSTEM_IMPACT_SOURCE_JOB_INCOMPLETE","성공한 Mapping Rebuild Job만 분석할 수 있습니다.")
        if (job["mapping_id"],job["mapping_version"],job["mapping_sha256"])!=(body.mapping_id,body.mapping_version,body.mapping_sha256):
            raise SystemOperationError(409,"SYSTEM_IMPACT_SOURCE_MISMATCH","분석 Mapping과 Rebuild Job의 Mapping identity가 일치하지 않습니다.")
        rebuild=(job.get("result") or {}).get("rebuild") or {}
        datasets=rebuild.get("published_datasets") or []
        nodes=[]; edges=[]; actions=[]
        for index,dataset in enumerate(datasets):
            dataset_id=str(dataset.get("dataset_id") or ""); version=str(dataset.get("dataset_version") or "")
            if not dataset_id or not version: continue
            node_id=f"observation_dataset:{dataset_id}:{version}"
            nodes.append({"node_id":node_id,"asset_type":"observation_dataset","asset_key":dataset_id,"version":version,"logical_uri":dataset.get("manifest_uri"),"change_status":"created","rebuild_eligibility":"eligible","blocked_reasons":[]})
            pp_id=f"preprocessing:{dataset_id}:{version}"
            if "preprocessing" in body.include_stages:
                actions.append({"action_id":pp_id,"stage":"preprocessing","status":"recommended","input_node_ids":[node_id],"required_parameters":{"dataset_id":dataset_id,"dataset_version":version},"missing_parameters":[],"depends_on_action_ids":[]})
            feature_id=f"feature:{dataset_id}:{version}"
            if "feature" in body.include_stages:
                missing=["failure_source","preprocessing_plan_id","preprocessing_plan_version","feature_schema_version","label_schema_version","prediction_horizon_hours"]
                actions.append({"action_id":feature_id,"stage":"feature","status":"blocked","input_node_ids":[node_id],"required_parameters":{},"missing_parameters":missing,"depends_on_action_ids":[pp_id] if "preprocessing" in body.include_stages else []})
            if "training" in body.include_stages:
                actions.append({"action_id":f"training:{dataset_id}:{version}","stage":"training","status":"blocked","input_node_ids":[],"required_parameters":{},"missing_parameters":["feature_dataset_version","training_config_version","base_models"],"depends_on_action_ids":[feature_id]})
        source={"mapping_id":body.mapping_id,"mapping_version":body.mapping_version,"mapping_sha256":body.mapping_sha256,"rebuild_job_id":body.rebuild_job_id}
        canonical={"source":source,"nodes":nodes,"edges":edges,"actions":actions}
        now=datetime.now(timezone.utc).isoformat()
        return self._record(self.repository.create({"analysis_id":str(uuid.uuid4()),"status":"completed","mapping_id":body.mapping_id,"mapping_version":body.mapping_version,"mapping_sha256":body.mapping_sha256,"rebuild_job_id":body.rebuild_job_id,"include_stages":body.include_stages,"source":source,"nodes":nodes,"edges":edges,"actions":actions,"snapshot_sha256":_sha(canonical),"created_by":actor,"created_at":now,"source_asset_type":"static_mapping","source_asset_id":body.mapping_id,"source_version":body.mapping_version,"source_sha256":body.mapping_sha256,"source_job_id":body.rebuild_job_id}), actor)

    def _create_managed_asset_analysis(self, body, actor):
        source = {
            "source_asset_type": body.source_asset_type,
            "source_asset_id": body.source_asset_id,
            "source_version": body.source_version,
            "source_sha256": body.source_sha256,
            "source_job_id": body.source_job_id,
        }
        node_id = f"{body.source_asset_type}:{body.source_asset_id}:{body.source_version}"
        nodes = [{
            "node_id": node_id, "asset_type": body.source_asset_type,
            "asset_key": body.source_asset_id, "version": body.source_version,
            "logical_uri": None, "change_status": "created",
            "rebuild_eligibility": "requires_inputs", "blocked_reasons": [],
        }]
        requirements = {
            "preprocessing_plan": {
                "feature": ["dataset_id", "dataset_version", "failure_source", "feature_schema_version", "label_schema_version"],
                "training": ["feature_dataset_version", "training_config_version", "base_models"],
            },
            "feature_schema": {
                "feature": ["dataset_id", "dataset_version", "failure_source", "preprocessing_plan_id", "label_schema_version"],
                "training": ["feature_dataset_version", "training_config_version", "base_models"],
            },
            "label_schema": {
                "feature": ["dataset_id", "dataset_version", "failure_source", "preprocessing_plan_id", "feature_schema_version"],
                "training": ["feature_dataset_version", "training_config_version", "base_models"],
            },
            "history_requirement": {
                "training": ["feature_dataset_version", "training_config_version", "base_models"],
            },
            "training_config": {
                "training": ["dataset_id", "dataset_version", "feature_dataset_version", "base_models"],
            },
        }
        actions = []
        for stage, missing in requirements[body.source_asset_type].items():
            if stage in body.include_stages:
                actions.append({
                    "action_id": f"{stage}:{body.source_asset_id}:{body.source_version}",
                    "stage": stage, "status": "blocked", "input_node_ids": [node_id],
                    "required_parameters": {}, "missing_parameters": missing,
                    "depends_on_action_ids": [],
                })
        canonical = {"source": source, "nodes": nodes, "edges": [], "actions": actions}
        now = datetime.now(timezone.utc).isoformat()
        # Legacy NOT NULL columns mirror the generic identity until the storage
        # compatibility columns can become the sole source in a later migration.
        legacy_job = body.source_job_id or f"managed-asset:{body.source_asset_type}"
        return self._record(self.repository.create({
            "analysis_id": str(uuid.uuid4()), "status": "completed",
            "mapping_id": body.source_asset_id, "mapping_version": body.source_version,
            "mapping_sha256": body.source_sha256, "rebuild_job_id": legacy_job,
            "include_stages": body.include_stages, "source": source, "nodes": nodes,
            "edges": [], "actions": actions, "snapshot_sha256": _sha(canonical),
            "created_by": actor, "created_at": now,
            "source_asset_type": body.source_asset_type,
            "source_asset_id": body.source_asset_id, "source_version": body.source_version,
            "source_sha256": body.source_sha256, "source_job_id": body.source_job_id,
        }), actor)
