"""Test-only bridge to the real local prediction / workflow / API chain."""
from pathlib import Path
import os,sys,tempfile,threading
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'systems/backend'),str(ROOT/'tests'),str(ROOT)]
os.environ['APP_ENV']='test';os.environ['ONTOLOGY_DASHBOARD_ALLOW_HEURISTIC_MODEL_FALLBACK']='1'
os.environ.pop('CNC_MODEL_ARTIFACT_URI',None);os.environ.pop('MODEL_ARTIFACT_URI',None)
from fastapi import FastAPI,HTTPException
from pydantic import BaseModel
from typing import Literal
from briefing_chain_support import IntegrationChain

app=FastAPI(docs_url=None,redoc_url=None)
folder=tempfile.TemporaryDirectory(prefix='briefing-full-chain-')
chain=IntegrationChain(Path(folder.name)/'integration.sqlite')
lock=threading.RLock()
results=[]
@app.get('/api/demo-briefing/cases')
def cases():return chain.cases
@app.get('/api/demo-briefing/cases/{case_id}')
def delivery(case_id:int):
    if case_id not in range(1,9):raise HTTPException(404)
    with lock:return chain.delivery(case_id)
class Request(BaseModel):
    variant:Literal['recorded','rejected']='recorded'
@app.post('/api/demo-briefing/cases/{case_id}/validate')
def validate(case_id:int,request:Request):
    if case_id not in range(1,9):raise HTTPException(404)
    with lock:
        result=chain.validate(case_id,request.variant=='rejected')
        results.append({'case_id':case_id,'variant':request.variant,**result['chain']})
        return result
@app.get('/proof')
def proof():
    with lock:return {'scope':'local_heuristic_prediction_real_pipeline_workflow_sqlite_api_controlled_llm_transport',
                     'predictions':chain.predictions,'workflow_runs':chain.rows('agent_review_workflow_runs'),
                     'summaries':chain.rows('agent_review_summaries'),'checks':results}
if __name__=='__main__':
    import uvicorn
    try:uvicorn.run(app,host='127.0.0.1',port=8338)
    finally:chain.close();folder.cleanup()
