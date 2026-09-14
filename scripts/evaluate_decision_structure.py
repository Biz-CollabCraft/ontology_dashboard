"""Evaluation-only orchestration ablation; no production runtime or policy rewrites."""
import argparse,copy,hashlib,json,os,statistics,time
from pathlib import Path
from dataclasses import dataclass
from collections import Counter
from dotenv import dotenv_values
from app.operations.decision_support_agent import ManufacturingDecisionAgent,DecisionAgentRequest,DecisionToolRuntime,DecisionAgentRunResult
from app.operations.decision_support_contract import DecisionSession,DecisionSessionStatus
from app.operations.decision_tools import DecisionToolName as T,DecisionToolFailure
from app.operations.decision_retry import RetryFailureKind as F
from app.operations.decision_evidence import relevant_tools,remaining_tools
from app.operations.decision_text_interpreter import StructuredTextEvidenceInterpreter,collect_excerpts,TextInterpretationError,TEXT_INTERPRETATION_PROMPT
from evaluate_decision_agent_ambiguous import make_case,build_tools,WARNING,IDENTITY,NOW
from evaluate_decision_agent_planner import RecordingProvider,usage_total
from evaluate_decision_model_comparison import ModelProvider
ROOT=Path(__file__).resolve().parents[1]
ARMS=('bulk','sequential','langgraph')
NORMAL='The existing log is present and its timestamp is verified.'
SECOND='No additional physical measurements are needed.'
CONFLICT='Two inspectors disagree about continued operation under the same current conditions; the disagreement remains unresolved.'
MEASURE='New vibration readings are required before assessment.'
CASES=[
 {'id':'normal','first':[NORMAL],'second':[SECOND],'expected':'REQUEST_INSPECTION','required':2},
 {'id':'early_conflict','first':[CONFLICT],'second':[SECOND],'expected':None,'required':1},
 {'id':'early_measurement','first':[MEASURE],'second':[SECOND],'expected':'REQUEST_ADDITIONAL_DIAGNOSIS','required':1},
 {'id':'timeout_recovered','first':[NORMAL],'second':[SECOND],'fault':'once','expected':'REQUEST_INSPECTION','required':2},
 {'id':'timeout_exhausted','first':[NORMAL],'second':[SECOND],'fault':'always','expected':None,'required':0,'recovery':True},
 {'id':'missing_context','first':[NORMAL],'second':[SECOND],'missing':True,'expected':None,'required':1,'recovery':True},
 {'id':'duplicate_sources','first':[f'Record {i} is present and verified.' for i in range(12)]+['Record 0 is present and verified.'],'expected':'REQUEST_INSPECTION','required':2},
 {'id':'stale_snapshot','first':[NORMAL],'second':[SECOND],'fault':'stale','expected':None,'required':0,'recovery':True},
 {'id':'tool_budget','first':[NORMAL],'second':[SECOND],'max_calls':1,'expected':None,'required':1,'recovery':True},
]
CASES[6]['second']=CASES[6]['first']

class FixtureTools:
 def __init__(self,case):self.case=case;self.base=build_tools(make_case(case['id']));self.attempts=Counter()
 def call(self,*,tool_name,identity,retrieved_at):
  c=self.case;self.attempts[tool_name]+=1
  if tool_name==T.GET_ASSET_CONDITION:
   if c.get('fault')=='stale':raise DecisionToolFailure(F.STALE_SNAPSHOT,'Injected stale snapshot')
   if c.get('fault')=='always' or c.get('fault')=='once' and self.attempts[tool_name]==1:raise DecisionToolFailure(F.TIMEOUT,'Injected timeout')
  r=self.base.call(tool_name=tool_name,identity=identity,retrieved_at=retrieved_at)
  return r.model_copy(update={'limitations':tuple(c['first'] if tool_name==T.GET_ASSET_CONDITION else c['second']),
    'status':'missing' if c.get('missing') and tool_name==T.GET_ASSET_CONDITION else 'available'})

class FixedResponseProvider:
 """Explicit simulated classifications; NOT model accuracy evidence."""
 def generate_json_with_metadata(self,prompt,payload,**kwargs):
  return {"payload":self.generate_json(prompt,payload,**kwargs),"provider_metadata":{}}
 def generate_json(self,prompt,payload,**kwargs):
  rows=[]
  for e in payload['excerpts']:
   text=e['text'];required=text==MEASURE
   rows.append({'evidence_id':e['evidence_id'],'unresolved_conflict':text==CONFLICT,'meaning':'new_measurement' if required else 'clear_other','information_missing':False,
    'measurement_status':'required' if required else 'not_required' if text==SECOND else 'not_stated','measurement_evidence':text if required else None,'rationale':'Predefined synthetic interpretation for structure control'})
  return {'assessments':rows}

@dataclass
class ImperativeAgent(ManufacturingDecisionAgent):
 bulk: bool=False
 def run(self,request):
  policy=self.policy_guard.evaluate(request.policy_facts);results={};calls=[];failures=[];errors=[];cache={};interpretations=();budget=request.retry_budget;proposal=None;reason=None;stale=False
  runtime=DecisionToolRuntime(self.tools,self.retry_policy,self.sleep,self.now)
  def interpret():
   nonlocal interpretations
   if self.text_interpreter is not None and self._evidence_gate_reason(results) is None:
    try:interpretations=self.text_interpreter.interpret(collect_excerpts(results),cache=cache)
    except TextInterpretationError as e:errors.append(str(e))
  if policy.recommendation_blocked:proposal=self._abstain('deterministic policy blocked recommendation')
  fixed=list(relevant_tools(request.policy_facts))
  while proposal is None:
   if not self.bulk:
    proposal,reason=self._text_interpretation_proposal(interpretations,errors,results,policy.allowed_actions)
    if proposal is not None:break
   pending=tuple(t for t in fixed if t not in results) if self.bulk else remaining_tools(request.policy_facts,results)
   if failures:break
   if pending and len(calls)>=request.max_tool_calls:
    proposal=self._abstain('required context unavailable within tool budget');break
   if not pending:break
   tool=pending[0];effective=min(budget,request.max_tool_calls-len(calls)-1)
   result,trace,left,failure=runtime.execute(tool_name=tool,identity=request.identity,retry_budget_remaining=effective)
   calls.extend(trace);budget-=effective-left
   if result is not None:
    results[tool]=result
    if not self.bulk:interpret()
   if failure is not None:
    failures.append((tool,failure));stale=failure==F.STALE_SNAPSHOT;break
   # Bulk still honors authoritative source/unavailability gates before further reads.
   if self.bulk and self._evidence_gate_reason(results):break
  if self.bulk and not failures and proposal is None:
   interpret();proposal,reason=self._text_interpretation_proposal(interpretations,errors,results,policy.allowed_actions)
  if stale:proposal=self._abstain('snapshot changed; start a new DecisionSession')
  if proposal is None:proposal=self._planned_proposal(request=request,allowed=policy.allowed_actions,results=results,failures=failures,planner_errors=[])
  session=DecisionSession(decision_session_id='EVAL-'+os.urandom(8).hex(),identity=request.identity,actor_role=request.actor_role,
   status=DecisionSessionStatus.STALE if stale else DecisionSessionStatus.ABSTAINED if proposal.recommended_action is None else DecisionSessionStatus.READY_FOR_REVIEW,
   allowed_actions=policy.allowed_actions,proposal=proposal,created_at=self.now(),updated_at=self.now(),tool_calls=tuple(calls),retry_budget_remaining=budget,
   text_interpretations=interpretations,text_interpretation_errors=tuple(errors),recommendation_gate_reason=self._evidence_gate_reason(results) or reason)
  return DecisionAgentRunResult(engine='eval-bulk' if self.bulk else 'eval-sequential',session=session,policy=policy,tool_results={k.value:v for k,v in results.items()})

def run(case,arm,live):
 provider=ModelProvider('gpt-5.6-luna') if live else FixedResponseProvider();recording=RecordingProvider(provider);delays=[]
 args=dict(tools=FixtureTools(case),text_interpreter=StructuredTextEvidenceInterpreter(recording),sleep=delays.append,now=lambda:NOW)
 agent=ManufacturingDecisionAgent(**args) if arm=='langgraph' else ImperativeAgent(**args,bulk=arm=='bulk')
 request=DecisionAgentRequest(identity=IDENTITY,actor_role='process_engineer',policy_facts=WARNING,max_tool_calls=case.get('max_calls',5))
 start=time.perf_counter();result=agent.run(request);elapsed=time.perf_counter()-start;s=result.session
 actual=s.proposal.recommended_action;trace=s.tool_calls
 successful={c.tool_name for c in trace if c.status=='available'}
 required=set(t.value for t in relevant_tools(WARNING)[:case['required']])
 observed={c.tool_name for c in trace}
 # Expected failure/missing cases require attempts, not fabricated successful data.
 missing=len(required-(observed if case.get('recovery') else successful))
 unnecessary=len(observed-required) if not case.get('recovery') else 0
 expected_status='stale' if case.get('fault')=='stale' else 'abstained' if case['expected'] is None else 'ready_for_review'
 return {'case':case['id'],'arm':arm,'action':actual,'expected':case['expected'],'status':s.status,'outcome_match':actual==case['expected'] and s.status==expected_status and not s.text_interpretation_errors,
  'tool_attempts':len(trace),'tool_path':[c.tool_name for c in trace],'unnecessary_distinct_tools':unnecessary,'missing_required_tools':missing,
  'retry_attempts':sum(c.status=='failed' and c.retryable for c in trace),'scheduled_backoff_seconds':sum(delays),'latency_seconds':elapsed,
  'api_calls':len(recording.calls) if live else 0,'simulated_interpretation_batches':len(recording.calls) if not live else 0,'tokens':usage_total(recording.calls,'total_tokens') if live else None,
  'http_events':provider.events if live else [],'interpretation_count':len(s.text_interpretations),'unique_interpreted_texts':len({i.source_text for i in s.text_interpretations}),
  'policy_contained':actual is None or actual in result.policy.allowed_actions,'human_approval_required':s.proposal.human_approval_required,'mutation_attempted':s.mutation_attempted,
  'session':s.model_dump(mode='json'),'tool_results':{k:v.model_dump(mode='json') for k,v in result.tool_results.items()}}

def summarize(rows):
 return {a:{'runs':len(r:=[x for x in rows if x['arm']==a]),'outcome_matches':sum(x['outcome_match'] for x in r),'tool_attempts':sum(x['tool_attempts'] for x in r),
  'unnecessary_distinct_tools':sum(x['unnecessary_distinct_tools'] for x in r),'missing_required_tools':sum(x['missing_required_tools'] for x in r),'api_calls':sum(x['api_calls'] for x in r),
  'simulated_interpretation_batches':sum(x['simulated_interpretation_batches'] for x in r),'tokens':sum(x['tokens'] or 0 for x in r) if any(x['tokens'] is not None for x in r) else None,'mean_latency_seconds':statistics.mean(x['latency_seconds'] for x in r) if r else None,
  'unsafe_results':sum(not x['policy_contained'] or not x['human_approval_required'] or x['mutation_attempted'] for x in r)} for a in ARMS}

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--output-dir',type=Path,required=True);parser.add_argument('--prepare',action='store_true');parser.add_argument('--live',action='store_true');parser.add_argument('--env-file',type=Path);parser.add_argument('--iterations',type=int,default=3);args=parser.parse_args()
 if args.iterations<1:parser.error('iterations must be positive')
 sources=[Path(__file__),*sorted((ROOT/'systems/backend/app/operations').glob('decision_*.py')),ROOT/'systems/backend/app/infra/llm/provider.py',ROOT/'scripts/evaluate_decision_model_comparison.py',ROOT/'scripts/evaluate_decision_agent_ambiguous.py',ROOT/'scripts/evaluate_decision_agent_planner.py']
 protocol={'cases':CASES,'arms':ARMS,'iterations':args.iterations,'prompt':TEXT_INTERPRETATION_PROMPT,'model':'gpt-5.6-luna','reasoning_effort':'low','max_completion_tokens':4096,'temperature':'omitted',
  'source_hashes':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},'scope':'Synthetic tool responses and injected faults; live Luna or explicitly simulated text outputs. Shared deterministic policy/retry/finalization. No deployed performance claim.',
  'backoff':'recorded but not slept in all arms; tool latency not simulated','order':'rotate arm order per iteration and case','bulk':'policy-relevant tools fetched before one combined interpretation; source gates/failures still stop reads','sequential':'evaluation-only imperative implementation with early text gate','langgraph':'current production run method; deterministic planner, no checkpoint/resume claim'}
 binding=hashlib.sha256(json.dumps(protocol,sort_keys=True).encode()).hexdigest();out=args.output_dir
 if args.prepare:
  out.mkdir(parents=True,exist_ok=True)
  if (out/'registration.json').exists():raise SystemExit('Registration exists')
  (out/'registration.json').write_text(json.dumps({'binding':binding,'protocol':protocol},ensure_ascii=False,indent=2)+'\n');print(binding);return
 registered=json.loads((out/'registration.json').read_text());assert registered['binding']==binding,'Frozen protocol changed'
 if args.live:
  if not args.env_file:parser.error('--live requires --env-file')
  v=dotenv_values(args.env_file)
  for k in ['LLM_API_KEY','OPENAI_API_KEY','LLM_BASE_URL']:
   if v.get(k):os.environ[k]=v[k]
 path=out/('live.json' if args.live else 'offline.json');data=json.loads(path.read_text()) if path.exists() else {'binding':binding,'live':args.live,'rows':[]}
 assert data['binding']==binding
 done={(r['case'],r['arm'],r['iteration']) for r in data['rows']}
 for iteration in range(args.iterations):
  for i,case in enumerate(CASES):
   offset=(iteration+i)%len(ARMS)
   for arm in ARMS[offset:]+ARMS[:offset]:
    if (case['id'],arm,iteration+1) in done:continue
    row=run(case,arm,args.live);row['iteration']=iteration+1;data['rows'].append(row);data['summary']=summarize(data['rows'])
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');temp.replace(path)
    print(f'{iteration+1} {case["id"]} {arm} match={row["outcome_match"]}',flush=True)
 print(json.dumps(data['summary']))
if __name__=='__main__':main()
