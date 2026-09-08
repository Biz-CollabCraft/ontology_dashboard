#!/usr/bin/env python3
"""Evaluate whether AI briefings preserve enough grounded facts for operator judgment.

This is a preliminary usefulness evaluator. It does not measure live operational
benefit or human decision quality. It checks whether a briefing gives a reader
enough grounded cues to identify the current state, the next action, the
supporting evidence, and unsupported claims that should remain absent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_AB_DIR = Path('/private/tmp/pipeline-ab-20260908')
DEFAULT_OUTPUT_DIR = Path('/private/tmp/agent-briefing-usefulness-20260908')

DECISION_TASKS = [
    '현재 설비 상태와 우선순위를 판단할 수 있는가',
    '먼저 확인해야 할 점검 대상이 드러나는가',
    '점검 결과, 작업요청, 승인, 착수 상태가 구분되는가',
    '생산 영향과 아직 확정할 수 없는 항목이 구분되는가',
    '근거 없는 정비 완료, 재고 확보, 자동 승인 주장을 피하는가',
]

RISKY_CLAIM_PATTERNS = [
    r'정비\s*(?:완료|종료|마무리)',
    r'수리\s*(?:완료|종료|마무리)',
    r'정상\s*(?:복귀|운전\s*가능|가동\s*가능)',
    r'재고\s*(?:확보|충분|있음|가용)',
    r'부품\s*(?:확보|충분|있음|가용)',
    r'자동\s*(?:승인|생성|실행)',
    r'작업요청을\s*생성(?:하|했|함)',
    r'승인(?:하|했|함|되었습니다)',
]

INTERNAL_TERM_PATTERNS = [
    r'\bmaintenance_recommended\b',
    r'\bmonitor_only\b',
    r'\bdata_quality_hold\b',
    r'\bfixture\b',
    r'데모',
    r'스냅샷',
]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _text(summary: dict[str, Any]) -> str:
    parts = [str(summary.get('title') or ''), str(summary.get('summary') or '')]
    for item in summary.get('role_summaries') or []:
        if isinstance(item, dict):
            parts.append(str(item.get('quote') or ''))
    return '\n'.join(parts)


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    return any(term and term in text for term in terms)


def _regex_any(text: str, patterns: Iterable[str]) -> list[str]:
    return [pattern for pattern in patterns if re.search(pattern, text, flags=re.IGNORECASE)]


def _top_factor_labels(packet: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for item in packet.get('model_expression_context', {}).get('top_factors') or []:
        label = item.get('label') or item.get('display_label') or item.get('factor_key')
        if label:
            labels.append(str(label))
    return labels[:2]


def _inspection_terms(packet: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for target in packet.get('inspection_targets') or []:
        for key in ('component_label', 'location_label'):
            value = target.get(key)
            if value:
                terms.append(str(value))
    return list(dict.fromkeys(terms))[:4]


def _expected_status_terms(expected_facts: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    inspection = expected_facts.get('inspection')
    work_order = expected_facts.get('work_order')
    if inspection == 'maintenance_recommended':
        terms.extend(['점검', '편심'])
    if work_order == 'requested':
        terms.extend(['작업요청', '요청'])
    elif work_order == 'approved':
        terms.extend(['작업요청', '승인'])
        approval_time = expected_facts.get('approval_time')
        if approval_time:
            terms.append(str(approval_time))
    elif work_order in {'not_supplied', 'after_basis_excluded', 'other_asset_excluded'}:
        terms.extend(['작업요청', '확정'])
    return terms


def _required_evidence_terms(packet: dict[str, Any], expected_facts: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    risk = packet.get('risk_summary') or {}
    grade = risk.get('status_grade')
    if grade:
        terms.append(str(grade))
    probability = risk.get('failure_probability')
    if isinstance(probability, (int, float)):
        terms.append(str(round(probability * 100, 1)))
    terms.extend(_top_factor_labels(packet))
    terms.extend(_inspection_terms(packet)[:2])
    terms.extend(_expected_status_terms(expected_facts))
    return list(dict.fromkeys(term for term in terms if term))


def _next_action_terms(packet: dict[str, Any], expected_facts: dict[str, Any]) -> list[str]:
    terms = ['확인', '점검', '검토']
    terms.extend(_inspection_terms(packet)[:2])
    work_order = expected_facts.get('work_order')
    if work_order == 'requested':
        terms.extend(['승인', '일정'])
    elif work_order == 'approved':
        terms.extend(['착수', '재고', '작업 가능'])
    elif expected_facts.get('inspection') == 'maintenance_recommended':
        terms.extend(['작업요청', '조치 범위'])
    return list(dict.fromkeys(term for term in terms if term))


def _status_is_correct(text: str, expected_facts: dict[str, Any]) -> bool:
    work_order = expected_facts.get('work_order')
    inspection = expected_facts.get('inspection')
    if inspection == 'maintenance_recommended' and not ('점검' in text and ('편심' in text or '정비 필요' in text or '조치' in text)):
        return False
    if work_order == 'requested':
        return '작업요청' in text and '요청' in text and not re.search(r'승인\s*(?:완료|됨|되었습니다|상태)', text)
    if work_order == 'approved':
        return '작업요청' in text and '승인' in text and not re.search(r'(정비|수리|작업)\s*(?:완료|종료)', text)
    if work_order in {'after_basis_excluded', 'other_asset_excluded'}:
        return not re.search(r'작업요청\s*승인\s*(?:완료|됨|되었습니다|상태)', text)
    if work_order == 'not_supplied':
        return not re.search(r'작업요청\s*승인\s*(?:완료|됨|되었습니다|상태)', text)
    return True


def _uncertainty_boundary_is_clear(text: str, packet: dict[str, Any], expected_facts: dict[str, Any]) -> bool:
    has_gap = bool(packet.get('evidence_gaps')) or expected_facts.get('work_order') in {
        'not_supplied', 'after_basis_excluded', 'other_asset_excluded', 'approved'
    }
    if not has_gap:
        return True
    uncertainty_terms = ['확정되지', '확인 필요', '미확인', '제공되지', '기록되지', '판단할 수 없']
    return _contains_any(text, uncertainty_terms)


def score_summary(summary: dict[str, Any], *, packet: dict[str, Any], expected_facts: dict[str, Any]) -> dict[str, Any]:
    text = _text(summary)
    required_terms = _required_evidence_terms(packet, expected_facts)
    matched_required = [term for term in required_terms if term in text]
    risky_claims = _regex_any(text, RISKY_CLAIM_PATTERNS)
    internal_terms = _regex_any(text, INTERNAL_TERM_PATTERNS)
    next_action_terms = _next_action_terms(packet, expected_facts)
    matched_next_action = [term for term in next_action_terms if term in text]

    checks = {
        'status_accuracy': _status_is_correct(text, expected_facts),
        'required_evidence_recall': len(matched_required) >= max(2, min(5, len(required_terms) // 2)),
        'next_action_identifiable': len(matched_next_action) >= 2,
        'uncertainty_boundary': _uncertainty_boundary_is_clear(text, packet, expected_facts),
        'risky_claims_avoided': not risky_claims,
        'reader_language': not internal_terms,
    }
    score = sum(1 for passed in checks.values() if passed)
    return {
        'score': score,
        'total': len(checks),
        'pass': score == len(checks),
        'checks': checks,
        'matched_required_terms': matched_required,
        'required_terms': required_terms,
        'matched_next_action_terms': matched_next_action,
        'next_action_terms': next_action_terms,
        'risky_claims': risky_claims,
        'internal_terms': internal_terms,
    }


def _load_a_runs(ab_dir: Path) -> dict[tuple[int, int], dict[str, Any]]:
    runs: dict[tuple[int, int], dict[str, Any]] = {}
    for path in sorted((ab_dir / 'historical-A' / 'runs').glob('run-*.json')):
        row = _read_json(path)
        runs[(int(row['input_index']), int(row['iteration_for_input']))] = row.get('summary')
    return runs


def _load_b_runs(ab_dir: Path) -> dict[tuple[int, int], dict[str, Any]]:
    runs: dict[tuple[int, int], dict[str, Any]] = {}
    for path in sorted((ab_dir / 'runs').glob('*-B.json')):
        row = _read_json(path)
        runs[(int(row['case_id']), int(row['iteration']))] = row['visible']
    return runs


def _case_map(ab_dir: Path) -> dict[int, dict[str, Any]]:
    return {int(row['case_id']): row for row in _read_json(ab_dir / 'source-inputs.json')}


def _evaluate(ab_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cases = _case_map(ab_dir)
    a_runs = _load_a_runs(ab_dir)
    b_runs = _load_b_runs(ab_dir)
    rows: list[dict[str, Any]] = []
    for case_id, source in cases.items():
        for iteration in range(1, 16):
            for condition, runs in [('pipeline', a_runs), ('direct', b_runs)]:
                summary = runs[(case_id, iteration)]
                if summary is None:
                    scored = {
                        'score': 0,
                        'total': 6,
                        'pass': False,
                        'checks': {
                            'status_accuracy': False,
                            'required_evidence_recall': False,
                            'next_action_identifiable': False,
                            'uncertainty_boundary': False,
                            'risky_claims_avoided': False,
                            'reader_language': False,
                        },
                        'matched_required_terms': [],
                        'required_terms': _required_evidence_terms(source['packet'], source.get('expected_facts') or {}),
                        'matched_next_action_terms': [],
                        'next_action_terms': _next_action_terms(source['packet'], source.get('expected_facts') or {}),
                        'risky_claims': ['missing_returned_briefing'],
                        'internal_terms': [],
                    }
                else:
                    scored = score_summary(
                        summary,
                        packet=source['packet'],
                        expected_facts=source.get('expected_facts') or {},
                    )
                rows.append({
                    'case_id': case_id,
                    'case_label': source.get('label'),
                    'iteration': iteration,
                    'condition': condition,
                    **scored,
                })
    aggregate: dict[str, Any] = {
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'scope': 'preliminary automatic usefulness rubric over 8 local A/B fixture cases x 15 iterations; not a human or live operations outcome measurement',
        'decision_tasks': DECISION_TASKS,
        'conditions': {},
        'by_case': {},
    }
    for condition in ['pipeline', 'direct']:
        subset = [row for row in rows if row['condition'] == condition]
        total = len(subset)
        pass_count = sum(1 for row in subset if row['pass'])
        aggregate['conditions'][condition] = {
            'runs': total,
            'pass_count': pass_count,
            'pass_rate': pass_count / total if total else 0,
            'average_score': sum(row['score'] for row in subset) / total if total else 0,
            'check_pass_rates': {
                check: sum(1 for row in subset if row['checks'][check]) / total
                for check in subset[0]['checks']
            } if subset else {},
        }
    for case_id in sorted(cases):
        aggregate['by_case'][str(case_id)] = {}
        for condition in ['pipeline', 'direct']:
            subset = [row for row in rows if row['case_id'] == case_id and row['condition'] == condition]
            aggregate['by_case'][str(case_id)][condition] = {
                'pass_count': sum(1 for row in subset if row['pass']),
                'runs': len(subset),
                'average_score': sum(row['score'] for row in subset) / len(subset),
            }
    p = aggregate['conditions']['pipeline']['pass_rate']
    d = aggregate['conditions']['direct']['pass_rate']
    aggregate['lift_pp'] = round((p - d) * 100, 1)
    return rows, aggregate


def _summary_as_markdown(aggregate: dict[str, Any]) -> str:
    pipe = aggregate['conditions']['pipeline']
    direct = aggregate['conditions']['direct']
    lines = [
        '# AI 브리핑 판단 유용성 예비 자동평가',
        '',
        aggregate['scope'],
        '',
        '| 조건 | 통과 | 평균 점수 |',
        '|---|---:|---:|',
        f"| Pipeline | {pipe['pass_count']}/{pipe['runs']} ({pipe['pass_rate']*100:.1f}%) | {pipe['average_score']:.2f}/6 |",
        f"| Direct | {direct['pass_count']}/{direct['runs']} ({direct['pass_rate']*100:.1f}%) | {direct['average_score']:.2f}/6 |",
        '',
        f"Pipeline의 예비 자동 유용성 통과율 차이는 {aggregate['lift_pp']:+.1f}%p다.",
        '',
        '## 검사 항목별 통과율',
        '',
        '| 검사 항목 | Pipeline | Direct |',
        '|---|---:|---:|',
    ]
    for check in pipe['check_pass_rates']:
        lines.append(
            f"| {check} | {pipe['check_pass_rates'][check]*100:.1f}% | {direct['check_pass_rates'][check]*100:.1f}% |"
        )
    lines.extend([
        '',
        '이 수치는 사람 평가가 아니라 정답 판단 과제에 필요한 근거, 상태 구분, 다음 액션, 불확실성 경계, 위험 단정 회피, 독자용 표현을 자동 규칙으로 본 예비 평가다.',
    ])
    return '\n'.join(lines) + '\n'


def _blind_records(rows: list[dict[str, Any]], ab_dir: Path, *, seed: int, per_case: int) -> list[dict[str, Any]]:
    cases = _case_map(ab_dir)
    a_runs = _load_a_runs(ab_dir)
    b_runs = _load_b_runs(ab_dir)
    rng = random.Random(seed)
    records: list[dict[str, Any]] = []
    for case_id, source in cases.items():
        iterations = [
            iteration
            for iteration in range(1, 16)
            if a_runs.get((case_id, iteration)) is not None and b_runs.get((case_id, iteration)) is not None
        ]
        rng.shuffle(iterations)
        for iteration in iterations[:per_case]:
            left_is_pipeline = rng.choice([True, False])
            pair = [
                ('X', 'pipeline' if left_is_pipeline else 'direct'),
                ('Y', 'direct' if left_is_pipeline else 'pipeline'),
            ]
            summaries = {'pipeline': a_runs[(case_id, iteration)], 'direct': b_runs[(case_id, iteration)]}
            record = {
                'blind_id': f'case-{case_id:02d}-iter-{iteration:02d}',
                'case_id': case_id,
                'case_label': source.get('label'),
                'decision_tasks': DECISION_TASKS,
                'case_context': {
                    'asset_label': source['packet'].get('asset_label'),
                    'risk_summary': source['packet'].get('risk_summary'),
                    'review_priority': source['packet'].get('review_priority'),
                    'expected_facts': source.get('expected_facts'),
                },
                'briefings': {label: summaries[condition] for label, condition in pair},
                'answer_key': {label: condition for label, condition in pair},
            }
            records.append(record)
    return records


def _write_blind_package(records: list[dict[str, Any]], output_dir: Path) -> None:
    public_records = []
    key_records = []
    for record in records:
        public = {k: v for k, v in record.items() if k != 'answer_key'}
        public_records.append(public)
        key_records.append({
            'blind_id': record['blind_id'],
            'case_id': record['case_id'],
            'answer_key': record['answer_key'],
        })
    (output_dir / 'blind-agent-eval-input.json').write_text(json.dumps(public_records, ensure_ascii=False, indent=2))
    (output_dir / 'blind-agent-eval-key.json').write_text(json.dumps(key_records, ensure_ascii=False, indent=2))

    lines = [
        '# 블라인드 에이전트 평가 입력',
        '',
        '각 케이스에서 X/Y 중 어느 브리핑이 다음 조치 판단에 더 유용한지 고르세요. Pipeline/Direct 여부는 보지 말고, 아래 판단 과제만 기준으로 평가하세요.',
        '',
    ]
    for record in public_records:
        lines.extend([
            f"## {record['blind_id']} — {record['case_label']}",
            '',
            f"설비: {record['case_context']['asset_label']}",
            f"위험: {record['case_context']['risk_summary']}",
            f"기대 상태: {record['case_context']['expected_facts']}",
            '',
            '판단 과제:',
        ])
        lines.extend([f"- {task}" for task in record['decision_tasks']])
        for label in ['X', 'Y']:
            summary = record['briefings'][label]
            lines.extend(['', f"### 브리핑 {label}", '', f"제목: {summary.get('title', '')}", '', str(summary.get('summary', ''))])
            for role in summary.get('role_summaries') or []:
                lines.extend(['', f"{role.get('role', '')}: {role.get('quote', '')}"])
        lines.append('')
    (output_dir / 'blind-agent-eval-input.md').write_text('\n'.join(lines))


def _manifest(ab_dir: Path, output_dir: Path, aggregate: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    files = ['aggregate.json', 'summary-ko.md', 'scored-runs.json', 'blind-agent-eval-input.json', 'blind-agent-eval-input.md', 'blind-agent-eval-key.json']
    manifest = {
        'result_id': 'agent-briefing-usefulness-prelim-20260908',
        'source_ab_dir': str(ab_dir),
        'output_dir': str(output_dir),
        'scope': aggregate['scope'],
        'blind_records': len(records),
        'files': {},
    }
    for name in files:
        path = output_dir / name
        if path.exists():
            manifest['files'][name] = {
                'path': str(path),
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'bytes': path.stat().st_size,
            }
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--ab-dir', type=Path, default=DEFAULT_AB_DIR)
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument('--blind-per-case', type=int, default=1)
    parser.add_argument('--seed', type=int, default=20260908)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows, aggregate = _evaluate(args.ab_dir)
    records = _blind_records(rows, args.ab_dir, seed=args.seed, per_case=args.blind_per_case)
    (args.output_dir / 'scored-runs.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    (args.output_dir / 'aggregate.json').write_text(json.dumps(aggregate, ensure_ascii=False, indent=2))
    (args.output_dir / 'summary-ko.md').write_text(_summary_as_markdown(aggregate))
    _write_blind_package(records, args.output_dir)
    manifest = _manifest(args.ab_dir, args.output_dir, aggregate, records)
    (args.output_dir / 'artifact-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps({
        'output_dir': str(args.output_dir),
        'pipeline_pass_rate': aggregate['conditions']['pipeline']['pass_rate'],
        'direct_pass_rate': aggregate['conditions']['direct']['pass_rate'],
        'lift_pp': aggregate['lift_pp'],
        'blind_records': len(records),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
