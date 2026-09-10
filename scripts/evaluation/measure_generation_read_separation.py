"""Offline controlled replay; never sends HTTP. Provider usage/time are historical."""
import argparse, ast, hashlib, json, os, statistics, subprocess, sys, time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'systems/backend'), str(ROOT / 'ml/src')]
os.environ['APP_ENV'] = 'test'
os.environ['ONTOLOGY_DASHBOARD_ALLOW_HEURISTIC_MODEL_FALLBACK'] = '1'
from app.dependencies import build_manufacturing_service
from app.operations.agent_review_summary import validate_agent_review_summary_contract, validated_agent_review_summary

BASE = '5126b4290eafc5e3855bc0c71618dae02d47aa40'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def dist(values):
    values = sorted(values)
    return {'n': len(values), 'p50': statistics.median(values),
            'p95': values[max(0, __import__('math').ceil(.95 * len(values)) - 1)], 'sum': sum(values)}

class RecordedProvider:
    name = 'historical-response-replay-no-network'
    provider = SimpleNamespace(model='gpt-5.6-luna')
    calls = 0
    def generate(self, packet):
        self.calls += 1
        return deepcopy(self.record['summary'])

def timed(fn):
    start = time.perf_counter()
    result = fn()
    return result, (time.perf_counter() - start) * 1000

def main():
    args = argparse.ArgumentParser()
    args.add_argument('--records', type=Path, required=True)
    args.add_argument('--output', type=Path, required=True)
    args = args.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    old_source = subprocess.check_output(['git', 'show', f'{BASE}:systems/backend/app/mvp/service.py'], cwd=ROOT, text=True)
    tree = ast.parse(old_source)
    method = next(n for cls in tree.body if isinstance(cls, ast.ClassDef)
                  for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'agent_review_summary')
    code = ast.get_source_segment(old_source, method)
    namespace = {'Any': __import__('typing').Any,
                 'validate_agent_review_summary_contract': validate_agent_review_summary_contract,
                 'validated_agent_review_summary': validated_agent_review_summary}
    exec(compile(code, '<historical-service-method>', 'exec'), namespace)
    legacy = namespace['agent_review_summary']
    (args.output / 'historical-method.py.txt').write_text(code)
    rows = []
    manifest = {'baseline_commit': BASE, 'current_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'scope': 'historical method with current contract helpers vs current SQLite materialize/read; prebuilt identical packet; replay provider; no network',
                'historical_model_prompt': 'gpt-5.6-luna / v3.4-next-decision-emphasis',
                'repeated_reads_per_window': 15, 'windows': 120, 'fresh_http_calls': 0,
                'latency': 'local timings measured; provider durations added arithmetically from historical HTTP records; not wall-clock E2E',
                'source_hashes': {str(p.relative_to(ROOT)): digest(p) for p in [Path(__file__), ROOT/'systems/backend/app/operations/service.py',ROOT/'systems/backend/app/operations/agent_review_summary_materialization.py']},
                'record_hashes': {}, 'packet_hashes': {}}
    for case in range(1, 9):
        name = f'GS-{case:03}'
        packet_path = ROOT/f'tests/fixtures/agent_review_packets/{name}.json'
        packet = json.loads(packet_path.read_text())
        manifest['packet_hashes'][name] = digest(packet_path)
        # Check exact inputs match those used in the real provider run.
        original = json.loads((args.records/'manifest.json').read_text())
        assert hashlib.sha256(json.dumps(packet, sort_keys=True).encode()).hexdigest() == original['packet_hashes'][name]
        service = build_manufacturing_service(args.output/f'{name}.db', root=ROOT)
        provider = RecordedProvider()
        service.agent_review_summary_provider = provider
        old_self = SimpleNamespace(agent_review_summary_provider=provider, agent_review_packet=lambda *a, **kw: packet)
        for repeat in range(1, 16):
            path = args.records/f'{name}-{repeat:02}.json'
            manifest['record_hashes'][path.name] = digest(path)
            record = json.loads(path.read_text())
            provider.record = record
            http = record['row']['http']
            usage = {key: sum(h['usage'].get(key, 0) for h in http) for key in ('prompt_tokens','completion_tokens','total_tokens')}
            assert all(h['status'] == 200 and h.get('usage') for h in http)
            provider_ms = sum(h['seconds'] for h in http) * 1000
            start_calls = provider.calls
            old_times = []
            for _ in range(15):
                (summary, _), elapsed = timed(lambda: legacy(old_self, packet['asset_id'], packet['project_id']))
                assert not validate_agent_review_summary_contract(summary, packet=packet)
                old_times.append(elapsed)
            before_calls = provider.calls - start_calls
            start_calls = provider.calls
            (generated, trace), gen_ms = timed(lambda: service._materialize_agent_review_packet(
                packet=packet, project_id=packet['project_id'], organization_id='org-ontology-demo',
                workspace_id='manufacturing-demo', history_window='24h', trigger='ui_manual_regeneration',
                engine='simple', generation_policy='always', packet_loader=lambda: packet))
            assert not validate_agent_review_summary_contract(generated, packet=packet)
            assert (generated['mode'] == 'llm') == record['row']['ready']
            warm_times = []
            for _ in range(14):
                (cached, _), elapsed = timed(lambda: service.cached_agent_review_summary_for_packet(packet=packet))
                assert cached == generated
                warm_times.append(elapsed)
            after_calls = provider.calls - start_calls
            changed = deepcopy(packet)
            changed['snapshot_basis']['source_sha256'] = 'changed-evidence-replay'
            mark = provider.calls
            (miss, _), miss_ms = timed(lambda: service.cached_agent_review_summary_for_packet(packet=changed))
            assert miss is None and provider.calls == mark
            assert before_calls == 15 and after_calls == 1
            rows.append({'case': name, 'repeat': repeat, 'historical_ready': record['row']['ready'],
                         'http_per_generation': len(http), 'historical_usage': usage, 'historical_provider_ms': provider_ms,
                         'before_provider_calls': before_calls, 'after_provider_calls': after_calls,
                         'before_local_ms': old_times, 'after_generation_local_ms': gen_ms,
                         'after_warm_read_local_ms': warm_times, 'miss_local_ms': miss_ms,
                         'cached_equal': True, 'changed_evidence_blocked': True})
        print(f'{name}: {len(rows)} windows verified', flush=True)
    summary = {'scope': manifest['scope'], 'windows': len(rows), 'reads_per_arm': 15*len(rows),
               'fresh_http_calls': 0, 'fresh_tokens': 0, 'provider_record_count': sum(r['http_per_generation'] for r in rows),
               'before_modeled_http': sum(r['http_per_generation']*15 for r in rows),
               'after_modeled_http': sum(r['http_per_generation'] for r in rows),
               'before_modeled_tokens': {k:sum(r['historical_usage'][k]*15 for r in rows) for k in usage},
               'after_modeled_tokens': {k:sum(r['historical_usage'][k] for r in rows) for k in usage},
               'before_query_modeled_ms': dist([t+r['historical_provider_ms'] for r in rows for t in r['before_local_ms']]),
               'after_all_query_modeled_ms': dist([t for r in rows for t in [r['after_generation_local_ms']+r['historical_provider_ms'], *r['after_warm_read_local_ms']]]),
               'after_cold_query_modeled_ms': dist([r['after_generation_local_ms']+r['historical_provider_ms'] for r in rows]),
               'after_warm_read_measured_ms': dist([t for r in rows for t in r['after_warm_read_local_ms']]),
               'after_miss_measured_ms': dist([r['miss_local_ms'] for r in rows]),
               'after_generation_local_measured_ms': dist([r['after_generation_local_ms'] for r in rows]),
               'before_local_measured_ms': dist([t for r in rows for t in r['before_local_ms']]),
               'cached_equal_windows': sum(r['cached_equal'] for r in rows),
               'changed_evidence_blocked_windows': sum(r['changed_evidence_blocked'] for r in rows),
               'historical_ready_windows':sum(r['historical_ready'] for r in rows),
               'sensitivity': [{'reads_per_evidence': n,'modeled_token_saving_percent':100*(1-1/n)} for n in [1,2,5,15]],
               'limitations': ['Not whole historical checkout A/B: old method/current contract helpers to isolate read generation behavior.',
                              'Recorded responses reused, no new prompt quality measurement or live bill.',
                              'No packet building, HTTP API/auth, browser rendering, production DB, network contention included.',
                              '15 stable reads and one explicit generation per window; no evidence changes inside window.',
                              'Fallback windows remain fallback; background fallback retries not scheduled.',
                              'Total time is summed request service time, not concurrent elapsed wall time.']}
    (args.output/'rows.json').write_text(json.dumps(rows, indent=2))
    (args.output/'manifest.json').write_text(json.dumps(manifest, indent=2))
    (args.output/'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))

if __name__ == '__main__': main()
