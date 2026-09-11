from __future__ import annotations
import argparse, copy, hashlib, json, os, re, sys, time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'systems/backend')]

from dotenv import dotenv_values
from app.operations.agent_review_summary import compose_deterministic_agent_review_summary, validate_agent_review_summary_contract
from app.operations.agent_review_summary_provider import (
    AGENT_REVIEW_SUMMARY_SYSTEM_PROMPT,
    AGENT_REVIEW_SUMMARY_PROMPT_VERSION,
    AgentReviewSummaryProvider,
    build_tool_selected_agent_review_summary_prompt_payload,
)
from scripts.run_pr167_extended_comparison import EvalProvider

MODEL = 'gpt-5.6-luna'
TOTAL_RUNS = 120
DEFAULT_INPUTS = None
FORBIDDEN_VISIBLE = re.compile(r'estimated_lost_units|production_impact|product_variant|product_type|제품 유형 M|maintenance_recommended|\boutcome\b|스냅샷|계획 가정|데모|합성 데이터')
RAW_UNIT = re.compile(r'\d[\d,]*(?:\.\d+)?\s*(?:min\b|N·m(?:·min)?)')
UNSUPPORTED_OPERATION = re.compile(r'도착 예정|재고 확보|착수 완료|실행 완료|완료(?:됐|되었습니다|됨| 상태)')
TRANSIENT_ERROR_TYPES = {'ConnectError', 'ReadTimeout', 'TimeoutException', 'RemoteProtocolError'}


def is_transient_transport_error(row: dict) -> bool:
    return str(row.get('error_type') or '') in TRANSIENT_ERROR_TYPES


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def load_env(env_file: Path | None) -> None:
    if env_file:
        for k, v in dotenv_values(env_file).items():
            if k in {'LLM_API_KEY', 'OPENAI_API_KEY', 'LLM_BASE_URL'} and v:
                os.environ[k] = v


def prepare(output_dir: Path, inputs_path: Path) -> None:
    if (output_dir / 'registration.json').exists():
        raise SystemExit('registration exists; remove output dir or resume runs')
    cases = json.loads(inputs_path.read_text())
    frozen = []
    for idx, case in enumerate(cases, 1):
        packet = case['packet']
        baseline = compose_deterministic_agent_review_summary(packet)
        prompt_payload = build_tool_selected_agent_review_summary_prompt_payload(packet=packet, baseline_summary=baseline)
        frozen.append({
            'input_index': idx,
            'label': case.get('label') or f'case-{idx}',
            'packet': packet,
            'prompt_payload_sha256': sha(prompt_payload),
            'packet_sha256': sha(packet),
        })
    schedule = []
    for run_index in range(TOTAL_RUNS):
        case = frozen[run_index % len(frozen)]
        schedule.append({
            'run_index': run_index,
            'input_index': case['input_index'],
            'label': case['label'],
            'iteration_for_input': run_index // len(frozen) + 1,
        })
    save(output_dir / 'inputs.json', frozen)
    save(output_dir / 'schedule.json', {'total_runs': TOTAL_RUNS, 'case_count': len(frozen), 'schedule': schedule})
    save(output_dir / 'registration.json', {
        'registered_at': datetime.now(UTC).isoformat(),
        'model': MODEL,
        'total_runs': TOTAL_RUNS,
        'case_count': len(frozen),
        'runs_per_case': TOTAL_RUNS // len(frozen),
        'remainder_runs': TOTAL_RUNS % len(frozen),
        'prompt_version': AGENT_REVIEW_SUMMARY_PROMPT_VERSION,
        'system_sha256': hashlib.sha256(AGENT_REVIEW_SUMMARY_SYSTEM_PROMPT.encode()).hexdigest(),
        'inputs_sha256': hashlib.sha256((output_dir / 'inputs.json').read_bytes()).hexdigest(),
        'schedule_sha256': hashlib.sha256((output_dir / 'schedule.json').read_bytes()).hexdigest(),
        'scope': '120 live Luna generations over 8 frozen owner-expanded local fixture inputs; no team DB write; no deployment verification',
        'checks': ['contract validation', 'provider content review', 'internal field/code leak regex', 'raw engineering unit leak regex', 'unsupported operation claim regex'],
    })
    print(json.dumps({'prepared': str(output_dir), 'total_runs': TOTAL_RUNS, 'case_count': len(frozen), 'prompt_version': AGENT_REVIEW_SUMMARY_PROMPT_VERSION}, ensure_ascii=False))


class Capture(EvalProvider):
    def __init__(self, model: str, expected_system_sha: str):
        super().__init__(model)
        self.expected_system_sha = expected_system_sha
        self.raw = None
        self.attempts = []

    def generate_json_with_metadata(self, *args, **kwargs):
        assert hashlib.sha256(args[0].encode()).hexdigest() == self.expected_system_sha
        result = super().generate_json_with_metadata(*args, **kwargs)
        self.raw = result
        self.attempts.append(result)
        return result


def run_one(output_dir: Path, run_index: int) -> dict:
    reg = json.loads((output_dir / 'registration.json').read_text())
    assert reg['system_sha256'] == hashlib.sha256(AGENT_REVIEW_SUMMARY_SYSTEM_PROMPT.encode()).hexdigest()
    assert reg['inputs_sha256'] == hashlib.sha256((output_dir / 'inputs.json').read_bytes()).hexdigest()
    schedule = json.loads((output_dir / 'schedule.json').read_text())['schedule']
    inputs = json.loads((output_dir / 'inputs.json').read_text())
    item = schedule[run_index]
    case = inputs[item['input_index'] - 1]
    packet = case['packet']
    baseline = compose_deterministic_agent_review_summary(packet)
    prompt_payload = build_tool_selected_agent_review_summary_prompt_payload(packet=packet, baseline_summary=baseline)
    assert sha(prompt_payload) == case['prompt_payload_sha256']
    path = output_dir / 'runs' / f'run-{run_index:03}.json'
    if path.exists():
        existing = json.loads(path.read_text())
        if not is_transient_transport_error(existing):
            return existing
    provider = Capture(MODEL, reg['system_sha256'])
    started = datetime.now(UTC).isoformat()
    start = time.monotonic()
    try:
        summary, meta = AgentReviewSummaryProvider(provider).generate_with_metadata(packet)
        contract_errors = validate_agent_review_summary_contract(summary, packet=packet)
        prose_parts = [summary.get('title', ''), summary.get('summary', '')]
        prose_parts.extend(role.get('quote', '') for role in summary.get('role_summaries', []) if isinstance(role, dict))
        text = '\n'.join(str(part) for part in prose_parts)
        extra_errors = []
        if FORBIDDEN_VISIBLE.search(text):
            extra_errors.append('internal_field_or_code_visible')
        if RAW_UNIT.search(text):
            extra_errors.append('raw_unit_visible')
        operation_text = re.sub(r'(?:시작|착수|완료|실행)[·\s]*(?:기록|상태)[^.!?\n]{0,40}(?:없|미확인|확인되지|제공되지|제공 자료에 없)', '', text)
        if UNSUPPORTED_OPERATION.search(operation_text):
            extra_errors.append('unsupported_operation_claim_candidate')
        result = {
            **item,
            'model': MODEL,
            'accepted': not contract_errors and not extra_errors,
            'contract_errors': contract_errors,
            'extra_errors': extra_errors,
            'summary': summary,
            'metadata': meta,
        }
    except Exception as exc:
        error_type = type(exc).__name__
        result = {
            **item,
            'model': MODEL,
            'accepted': None if error_type in TRANSIENT_ERROR_TYPES else False,
            'error_type': error_type,
            'error': str(exc),
            'review_attempts': getattr(exc, 'review_attempts', []),
        }
    result.update({
        'started_at': started,
        'finished_at': datetime.now(UTC).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'transport': provider.http_events,
        'raw': provider.raw,
        'attempt_count': len(provider.attempts),
    })
    save(path, result)
    return result


def aggregate(output_dir: Path) -> dict:
    reg = json.loads((output_dir / 'registration.json').read_text())
    rows = [json.loads(p.read_text()) for p in sorted((output_dir / 'runs').glob('run-*.json'))]
    valid_rows = [row for row in rows if not is_transient_transport_error(row)]
    transport_rows = [row for row in rows if is_transient_transport_error(row)]
    by_case = {}
    for row in valid_rows:
        bucket = by_case.setdefault(str(row['input_index']), {'label': row['label'], 'runs': 0, 'accepted': 0, 'failures': {}})
        bucket['runs'] += 1
        bucket['accepted'] += int(row.get('accepted') is True)
        for e in row.get('contract_errors') or []:
            bucket['failures'][e] = bucket['failures'].get(e, 0) + 1
        for e in row.get('extra_errors') or []:
            bucket['failures'][e] = bucket['failures'].get(e, 0) + 1
        if row.get('error_type'):
            bucket['failures'][row['error_type']] = bucket['failures'].get(row['error_type'], 0) + 1
    failure_counts = {}
    for row in valid_rows:
        for e in (row.get('contract_errors') or []) + (row.get('extra_errors') or []):
            failure_counts[e] = failure_counts.get(e, 0) + 1
        if row.get('error_type'):
            failure_counts[row['error_type']] = failure_counts.get(row['error_type'], 0) + 1
    report = {
        'result_id': 'luna-120-stability-20260908',
        'recorded_at': datetime.now(UTC).isoformat(),
        'registration': reg,
        'completed_runs': len(rows),
        'valid_model_runs': len(valid_rows),
        'transport_error_runs': len(transport_rows),
        'accepted_runs': sum(1 for r in valid_rows if r.get('accepted') is True),
        'pass_rate': round(sum(1 for r in valid_rows if r.get('accepted') is True) / len(valid_rows), 6) if valid_rows else 0,
        'failure_counts': failure_counts,
        'by_case': by_case,
        'duration_seconds_total': round(sum(r.get('duration_seconds') or 0 for r in rows), 3),
        'rows_index': [{'run_index': r['run_index'], 'input_index': r['input_index'], 'label': r['label'], 'accepted': r.get('accepted'), 'duration_seconds': r.get('duration_seconds'), 'contract_errors': r.get('contract_errors'), 'extra_errors': r.get('extra_errors'), 'error_type': r.get('error_type')} for r in rows],
    }
    save(output_dir / 'aggregate.json', report)
    lines = ['# Luna 120-run stability', '', f"prompt_version: `{reg['prompt_version']}`", f"scope: {reg['scope']}", '', f"completed_runs: {report['completed_runs']}", f"valid_model_runs: {report['valid_model_runs']}", f"transport_error_runs: {report['transport_error_runs']}", f"accepted_runs: {report['accepted_runs']}", f"pass_rate: {report['pass_rate']}", f"duration_seconds_total: {report['duration_seconds_total']}", '', '## Failure counts', '']
    if failure_counts:
        for k, v in sorted(failure_counts.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f'- {k}: {v}')
    else:
        lines.append('- none')
    lines.extend(['', '## By case', ''])
    for key, value in sorted(by_case.items(), key=lambda kv: int(kv[0])):
        lines.append(f"- case {key} {value['label']}: {value['accepted']}/{value['runs']} accepted; failures={value['failures']}")
    (output_dir / 'aggregate.md').write_text('\n'.join(lines) + '\n')
    return report


def run_all(output_dir: Path) -> None:
    for i in range(TOTAL_RUNS):
        row = run_one(output_dir, i)
        print(json.dumps({'run_index': i, 'input_index': row['input_index'], 'label': row['label'], 'accepted': row.get('accepted'), 'duration_seconds': row.get('duration_seconds'), 'errors': (row.get('contract_errors') or []) + (row.get('extra_errors') or []) + ([row.get('error_type')] if row.get('error_type') else [])}, ensure_ascii=False), flush=True)
    report = aggregate(output_dir)
    print(json.dumps({'completed_runs': report['completed_runs'], 'valid_model_runs': report['valid_model_runs'], 'transport_error_runs': report['transport_error_runs'], 'accepted_runs': report['accepted_runs'], 'pass_rate': report['pass_rate'], 'failure_counts': report['failure_counts']}, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, default=DEFAULT_INPUTS)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--run-all', action='store_true')
    parser.add_argument('--run-index', type=int)
    parser.add_argument('--aggregate', action='store_true')
    parser.add_argument('--compact', action='store_true')
    args = parser.parse_args()
    if args.prepare and args.inputs is None:
        parser.error("--prepare requires --inputs for explicitly supplied frozen packets")
    if args.env_file:
        load_env(args.env_file)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.prepare:
        prepare(args.output_dir, args.inputs)
    elif args.run_all:
        run_all(args.output_dir)
    elif args.run_index is not None:
        row = run_one(args.output_dir, args.run_index)
        if args.compact:
            print(json.dumps({'run_index': row['run_index'], 'input_index': row['input_index'], 'label': row['label'], 'accepted': row.get('accepted'), 'duration_seconds': row.get('duration_seconds'), 'errors': (row.get('contract_errors') or []) + (row.get('extra_errors') or []) + ([row.get('error_type')] if row.get('error_type') else []), 'attempt_count': row.get('attempt_count')}, ensure_ascii=False))
        else:
            print(json.dumps(row, ensure_ascii=False))
    elif args.aggregate:
        print(json.dumps(aggregate(args.output_dir), ensure_ascii=False, indent=2))
    else:
        raise SystemExit('choose --prepare, --run-all, --run-index, or --aggregate')

if __name__ == '__main__':
    main()
