"""Isolated integration harness. Only external LLM transport is substituted."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
from app.main import app as product_app
from app.dependencies import build_manufacturing_service, get_service, get_identity_service
from app.operations.agent_review_summary_provider import AgentReviewSummaryProvider
from app.operations.agent_review_summary_workflow import AgentReviewSummaryWorkflow
from app.operations.agent_briefing_review import decision_facts
from app.diagnosis.predictor import HeuristicPredictor
from identity_test_support import build_identity_service

ROOT=Path(__file__).resolve().parents[1]

def digest(value):
    return sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

class ControlledLLMTransport:
    name='integration-controlled-llm-transport'
    def __init__(self):
        self.calls=[]
        self.reject=False
    def generate_json(self, system, payload, **kwargs):
        self.calls.append(deepcopy(payload))
        label=payload['summary_context']['asset_label']
        quote=f'**{label}의 관측값**을 점검 근거로 확인합니다.\n작업요청·승인·착수·완료 기록은 제공 범위에서 확인할 수 있습니다.\n실제 재고·작업 가능 시간은 미확인이므로 **현장 확인 결과**가 다음 판단의 조건입니다.'
        return {'title':'선택 설비 근거 검토','summary':'AI가 자동 승인과 정비 완료를 실행했습니다.' if self.reject else '선택 설비의 관측 근거를 확인합니다.',
                'role_summaries':[{'role':role,'quote':quote} for role in ('process_engineer','maintenance_technician','process_manager')]}

class IntegrationChain:
    def __init__(self, db_path):
        self.db_path=Path(db_path)
        self.predictions={};self.inputs={};self.artifacts={};self.packets={}
        self.original_predict=HeuristicPredictor.predict
        def record_predict(predictor, fixture):
            result=self.original_predict(predictor,fixture)
            self.predictions[fixture['event_id']]=result.to_dict()
            self.inputs[fixture['event_id']]=deepcopy(fixture)
            return result
        HeuristicPredictor.predict=record_predict
        self.service=build_manufacturing_service(self.db_path,root=ROOT)
        original_artifact=self.service._product_result_artifact
        def artifact(fixture):
            result=original_artifact(fixture);self.artifacts[fixture['event_id']]=deepcopy(result);return result
        self.service._product_result_artifact=artifact
        original_packet=self.service.agent_review_packet
        def packet(*args,**kwargs):
            result=original_packet(*args,**kwargs);self.packets[result['snapshot_basis']['event_id']]=deepcopy(result);return result
        self.service.agent_review_packet=packet
        self.transport=ControlledLLMTransport()
        self.service.agent_review_summary_provider=AgentReviewSummaryProvider(self.transport)
        self.workflow=AgentReviewSummaryWorkflow(self.service)
        identity=build_identity_service(self.db_path,app_env='test',seed_demo=True)
        product_app.dependency_overrides[get_service]=lambda:self.service
        product_app.dependency_overrides[get_identity_service]=lambda:identity
        self.client=TestClient(product_app)
        login=self.client.post('/api/auth/login',json={'email':'manager@ontology.local','password':'Manager!2026'})
        assert login.status_code==200
        self.cases=[{'case_id':i,'label':f'입력 {i} · {f["equipment"]["equipment_id"]}', 'event_id':f['event_id'],'asset_id':f['equipment']['equipment_id']} for i,f in enumerate(sorted(self.service.fixtures.values(),key=lambda f:f['scenario_id']),1)]
    def close(self):
        self.client.close();product_app.dependency_overrides.clear();HeuristicPredictor.predict=self.original_predict
    def read(self,asset):
        return self.client.get(f'/api/objects/{asset}/agent-review-summary')
    def rows(self,table):
        assert table in ('agent_review_summaries','agent_review_workflow_runs')
        with sqlite3.connect(self.db_path) as db:
            db.row_factory=sqlite3.Row
            return [dict(r) for r in db.execute('SELECT * FROM '+table)]
    def activity(self):
        return {c['event_id']:self.client.get('/api/events/'+c['event_id']+'/activity').json() for c in self.cases}
    def delivery(self,case_id):
        case=self.cases[case_id-1];asset=case['asset_id'];event=case['event_id']
        detail=self.client.get(f'/api/objects/{asset}/detail-view');assert detail.status_code==200
        vm=detail.json();packet=self.service.agent_review_packet(asset);facts=decision_facts(packet)
        artifact=self.artifacts[event];prediction=self.predictions[event]
        checks={
            'input_hash':digest(self.inputs[event])==digest(self.service.fixtures[event]),
            'asset_event_time':all(vm['snapshot_basis'][k]==packet['snapshot_basis'][k] for k in ('asset_id','event_id','observed_at')),
            'selected_evidence_only':set(packet['source_refs']).issuperset(ref for r in packet.get('evidence_context',{}).get('selected_basis',[]) if (ref:=r.get('source_ref'))),
            'screen_context':vm['risk']['current']==artifact['failure_probability']==prediction['probability'],
        }
        assert all(checks.values()),checks
        return {**case,'view_model':vm,'packet':packet,'facts':facts,'checks':checks,'input_sha256':digest(self.inputs[event]),
                'evidence_count':len(packet.get('source_refs',[])),'excluded_record_count':len(facts['excluded_records']),
                'response':{'summary':None,'trace':{'fallback':False,'materialization':{'status':'pending'}}},
                'chain':{'prediction':prediction,'artifact_sha256':digest(artifact),'api_status':detail.status_code}}
    def run(self):
        return self.workflow.run(limit=8)
    def validate(self,case_id,rejected=False):
        case=self.cases[case_id-1];before=self.activity();delivery=self.delivery(case_id)
        self.transport.reject=rejected
        # Changing the test transport identity isolates accepted/rejected candidate caches.
        self.service.agent_review_summary_provider.name='integration-rejected-transport' if rejected else self.transport.name
        workflow=self.run();wire=self.read(case['asset_id']);response=wire.json()
        assert self.activity()==before
        trace=response['trace'];material=trace['materialization']
        rows=self.rows('agent_review_summaries');row=next(r for r in rows if r['summary_id']==material['summary_id'])
        assert row['summary_key']==material['summary_key']
        assert json.loads(row['summary_json'])==response['summary']
        if trace.get('fallback') or material['status']!='ready':
            # Adapter hides stored deterministic fallback from the natural prose surface.
            response={**response,'summary':None,'trace':{**trace,'fallback':True,'materialization':{**material,'status':'fallback'}}}
        return {**response,'replay':{'case_id':case_id,'input_sha256':delivery['input_sha256']},
                'chain':{'workflow':workflow,'api_status':wire.status_code,'stored_status':row['status'],'summary_id':row['summary_id'],
                         'workflow_run_id':row['workflow_run_id'],'transport_calls':len(self.transport.calls),'business_state_unchanged':True}}
