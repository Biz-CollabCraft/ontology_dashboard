"""Frozen, offline structural comparison. Fixed text classifications are not LLM accuracy."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import statistics
import tempfile
import time
from threading import Lock

from app.infra.db.decision_run_repository import DecisionRunRepository
from app.operations.decision_durable_runner import DurableDecisionRunner
from app.operations.decision_support_agent import ManufacturingDecisionAgent, DecisionAgentRequest
from app.operations.decision_text_interpreter import StructuredTextEvidenceInterpreter
from evaluate_decision_structure import CASES, FixtureTools, FixedResponseProvider, NORMAL, CONFLICT, MEASURE
from evaluate_decision_agent_ambiguous import make_case, build_tools, WARNING, MAINTENANCE, IDENTITY
from evaluate_decision_agent_planner import RecordingProvider

ROOT=Path(__file__).resolve().parents[1]
CASES_FROZEN=[dict(c) for c in CASES if c['id']!='early_measurement']+[
    {'id':'late_explicit_conflict','first':[MEASURE],'second':[CONFLICT],'expected':None},
    {'id':'three_independent_reads','maintenance':True,'expected':'REVIEW_PLANNED_MAINTENANCE'}]


def run(case,workers,delay):
    provider=RecordingProvider(FixedResponseProvider())
    base=build_tools(make_case(case['id'],maintenance=True)) if case.get('maintenance') else FixtureTools(case)
    active=0;peak=0;lock=Lock()
    class TimedTools:
        def call(self,**kwargs):
            nonlocal active,peak
            with lock:
                active+=1;peak=max(peak,active)
            try:
                time.sleep(delay)
                return base.call(**kwargs)
            finally:
                with lock:active-=1
    agent=ManufacturingDecisionAgent(tools=TimedTools(),text_interpreter=StructuredTextEvidenceInterpreter(provider))
    request=DecisionAgentRequest(identity=IDENTITY,actor_role='process_engineer',policy_facts=MAINTENANCE if case.get('maintenance') else WARNING,max_tool_calls=case.get('max_calls',5))
    with tempfile.TemporaryDirectory() as temp:
        db=Path(temp)/'runs.db'
        with sqlite3.connect(db) as c:c.executescript((ROOT/'systems/backend/migrations/sqlite/0052_decision_agent_runs.sql').read_text())
        store=DecisionRunRepository(db)
        start=time.perf_counter()
        result=DurableDecisionRunner(agent,store,max_workers=workers).run(request,'DS-evaluation')
        elapsed=time.perf_counter()-start
        # New runner + repository demonstrate persisted completion reuse for each case.
        replay=DurableDecisionRunner(agent,DecisionRunRepository(db),max_workers=workers).run(request,'DS-evaluation')
        assert replay==result
    s=result.session
    return {'case':case['id'],'workers':workers,'latency_seconds':elapsed,'peak_concurrent_reads':peak,
        'action':s.proposal.recommended_action,'expected':case['expected'],'outcome_match':s.proposal.recommended_action==case['expected'],
        'status':s.status,'tool_attempts':len(s.tool_calls),'remaining_retry_budget':s.retry_budget_remaining,
        'simulated_interpretation_batches':len(provider.calls),'external_api_calls':0,'tokens':None,
        'text_errors':s.text_interpretation_errors,'all_available_source_fields_interpreted':len(s.text_interpretations),
        'completion_reused':True,'policy_contained':s.proposal.recommended_action is None or s.proposal.recommended_action in result.policy.allowed_actions,
        'human_approval_required':s.proposal.human_approval_required,'mutation_attempted':s.mutation_attempted}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output-dir',type=Path,required=True);parser.add_argument('--prepare',action='store_true');args=parser.parse_args()
    sources=[Path(__file__),ROOT/'scripts/evaluate_decision_structure.py',ROOT/'scripts/evaluate_decision_agent_ambiguous.py',*sorted((ROOT/'systems/backend/app/operations').glob('decision_*.py')),ROOT/'systems/backend/app/infra/db/decision_run_repository.py']
    protocol={'cases':CASES_FROZEN,'workers':[1,3],'iterations':3,'warmup':'one unscored normal run per arm before measurements','injected_read_delay_seconds':.1,'scope':'Actual SQLite durable runner; synthetic tool values/faults and predefined text labels. No external LLM, no production latency claim.',
        'source_hashes':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        'excluded':'Prior early_measurement case has contradictory later evidence and invalid action gold; it is not used as accuracy evidence.'}
    binding=hashlib.sha256(json.dumps(protocol,sort_keys=True).encode()).hexdigest()
    out=args.output_dir
    if args.prepare:
        out.mkdir(parents=True,exist_ok=True)
        path=out/'registration.json'
        if path.exists():raise SystemExit('registration exists')
        path.write_text(json.dumps({'binding':binding,'protocol':protocol},ensure_ascii=False,indent=2));return
    assert json.loads((out/'registration.json').read_text())['binding']==binding,'Frozen inputs changed'
    for workers in (1,3):
        run(CASES_FROZEN[0],workers,.1)
    rows=[]
    for iteration in range(3):
        for case in CASES_FROZEN:
            for workers in ([1,3] if iteration%2==0 else [3,1]):
                row=run(case,workers,.1);row['iteration']=iteration;rows.append(row)
    summary={}
    for workers in (1,3):
        selected=[r for r in rows if r['workers']==workers]
        summary[str(workers)]={'runs':len(selected),'outcome_matches':sum(r['outcome_match'] for r in selected),
            'policy_violations':sum(not r['policy_contained'] or not r['human_approval_required'] or r['mutation_attempted'] for r in selected),
            'simulated_interpretation_batches':sum(r['simulated_interpretation_batches'] for r in selected),
            'mean_normal_seconds':statistics.mean(r['latency_seconds'] for r in selected if r['case']=='normal'),
            'mean_three_reads_seconds':statistics.mean(r['latency_seconds'] for r in selected if r['case']=='three_independent_reads')}
    (out/'results.json').write_text(json.dumps({'binding':binding,'summary':summary,'rows':rows},ensure_ascii=False,indent=2))
    print(json.dumps(summary))
    assert all(r['outcome_match'] and r['policy_contained'] and r['human_approval_required'] and not r['mutation_attempted'] for r in rows)

if __name__=='__main__':main()
