from __future__ import annotations
import hashlib,json,uuid
from datetime import datetime,timezone
from .system_operation_exception import SystemOperationError

def _sha(value): return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()

class ImpactAnalysisService:
    def __init__(self, repository, jobs): self.repository=repository; self.jobs=jobs
    def get(self,analysis_id):
        value=self.repository.get(analysis_id)
        if value is None: raise SystemOperationError(404,"SYSTEM_IMPACT_ANALYSIS_NOT_FOUND","영향 분석을 찾을 수 없습니다.")
        return value
    def list(self): return self.repository.list()
    def create(self,body,actor):
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
        return self.repository.create({"analysis_id":str(uuid.uuid4()),"status":"completed","mapping_id":body.mapping_id,"mapping_version":body.mapping_version,"mapping_sha256":body.mapping_sha256,"rebuild_job_id":body.rebuild_job_id,"include_stages":body.include_stages,"source":source,"nodes":nodes,"edges":edges,"actions":actions,"snapshot_sha256":_sha(canonical),"created_by":actor,"created_at":now})
