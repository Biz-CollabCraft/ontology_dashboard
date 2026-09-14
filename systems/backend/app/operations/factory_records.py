"""Immutable scoped source records and deterministic as-of aggregates."""
import json
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Status(Strict):
    recorded_at: datetime
    valid_until: datetime
    state: Literal['running','stopped','maintenance','unknown']

class Incident(Strict):
    incident_id: str
    occurred_at: datetime
    failure_type: str

class AssetRecords(Strict):
    asset_id: str
    evidence_snapshot_id: str
    model_version: str
    asset_type: str
    failure_type: str
    history_from: datetime
    history_through: datetime
    statuses: list[Status]
    incidents: list[Incident]
    attention_threshold: float = Field(ge=0, le=1)
    action_threshold: float = Field(ge=0, le=1)
    policy_version: str

class RecordBundle(Strict):
    bundle_id: str
    organization_id: str
    project_id: str
    workspace_id: str
    dataset_version_id: str
    source_classification: Literal['synthetic_demo_context','owner_system']
    source_ref: str
    generated_at: datetime
    valid_from: datetime
    valid_to: datetime
    assets: list[AssetRecords] = Field(min_length=1)

    @model_validator(mode='after')
    def validate_records(self):
        times=[self.generated_at,self.valid_from,self.valid_to]
        ids=set()
        for a in self.assets:
            if a.asset_id in ids: raise ValueError('duplicate asset')
            ids.add(a.asset_id)
            if a.attention_threshold >= a.action_threshold: raise ValueError('threshold order')
            if a.history_from > a.history_through or a.history_through > self.generated_at: raise ValueError('history coverage')
            if len({i.incident_id for i in a.incidents}) != len(a.incidents): raise ValueError('duplicate incident')
            times += [a.history_from,a.history_through]
            previous=None
            for s in sorted(a.statuses,key=lambda s:s.recorded_at):
                times += [s.recorded_at,s.valid_until]
                if s.recorded_at>=s.valid_until or s.recorded_at>self.generated_at: raise ValueError('status time')
                if previous and s.recorded_at<previous: raise ValueError('overlapping status')
                previous=s.valid_until
            for i in a.incidents:
                times.append(i.occurred_at)
                if not a.history_from<=i.occurred_at<=a.history_through: raise ValueError('incident outside coverage')
        if any(t.tzinfo is None for t in times): raise ValueError('timezone required')
        if not self.valid_from<=self.generated_at<self.valid_to: raise ValueError('bundle time')
        return self

def import_bundle(repository, bundle):
    payload=json.dumps(bundle.model_dump(mode='json'),sort_keys=True,ensure_ascii=False,separators=(',',':'))
    sha=hashlib.sha256(payload.encode()).hexdigest()
    with repository.connection(bundle.organization_id,bundle.project_id) as c:
        existing=repository.execute(c,'SELECT content_sha256 FROM factory_record_bundles WHERE organization_id=? AND project_id=? AND workspace_id=? AND bundle_id=?',(bundle.organization_id,bundle.project_id,bundle.workspace_id,bundle.bundle_id)).fetchone()
        if existing:
            if existing['content_sha256']!=sha: raise ValueError('immutable bundle conflict')
            return {'inserted':0,'unchanged':1}
        repository.execute(c,'INSERT INTO factory_record_bundles (organization_id,project_id,workspace_id,bundle_id,dataset_version_id,payload_json,content_sha256) VALUES (?,?,?,?,?,?,?)',(bundle.organization_id,bundle.project_id,bundle.workspace_id,bundle.bundle_id,bundle.dataset_version_id,payload,sha))
    return {'inserted':1,'unchanged':0}

def read_records(repository, *, identity, dataset_version_id, model_version, asset_ids):
    with repository.connection(identity.organization_id,identity.project_id) as c:
        rows=repository.execute(c,'SELECT payload_json FROM factory_record_bundles WHERE organization_id=? AND project_id=? AND workspace_id=? AND dataset_version_id=?',(identity.organization_id,identity.project_id,identity.workspace_id,dataset_version_id)).fetchall()
    at=identity.decision_as_of
    bundles=[RecordBundle.model_validate_json(r['payload_json']) for r in rows]
    bundles=[b for b in bundles if b.valid_from<=at<b.valid_to and b.generated_at<=at]
    for b in sorted(bundles,key=lambda b:(b.generated_at,b.bundle_id),reverse=True):
        a=next((a for a in b.assets if a.asset_id==identity.asset_id and a.evidence_snapshot_id==identity.evidence_snapshot_id and a.model_version==model_version),None)
        if a is None: continue
        selected=[a for a in b.assets if a.asset_id in asset_ids]
        counts=dict(running=0,stopped=0,maintenance=0,unknown=len(set(asset_ids)-{a.asset_id for a in selected}))
        for item in selected:
            valid=[s for s in item.statuses if s.recorded_at<=at<s.valid_until]
            counts[valid[-1].state if valid else 'unknown']+=1
        start=at-timedelta(days=30)
        incidents=[i for i in a.incidents if start<i.occurred_at<=at and i.failure_type==a.failure_type]
        complete=a.history_from<=start and a.history_through>=at
        return dict(status='available',identity=identity.model_dump(mode='json'),counts=counts,total=len(set(asset_ids)),similar_events_30d=len(incidents) if complete else None,incident_refs=[i.incident_id for i in incidents],history_coverage_complete=complete,policy=dict(attention_threshold=a.attention_threshold,action_threshold=a.action_threshold,version=a.policy_version,model_version=a.model_version,asset_type=a.asset_type),provenance=dict(bundle_id=b.bundle_id,source_classification=b.source_classification,source_ref=b.source_ref,dataset_version_id=b.dataset_version_id,generated_at=b.generated_at.isoformat()),limitations=['같은 설비·같은 고장 유형의 사건을 (기준 시각-30일, 기준 시각] 구간에서 집계합니다.','상태 집계와 조치 정책은 기존 예측 위험 등급·작업 승인을 변경하지 않습니다.'])
    return dict(status='not_connected',reason='NO_MATCHING_FACTORY_RECORDS',identity=identity.model_dump(mode='json'))
