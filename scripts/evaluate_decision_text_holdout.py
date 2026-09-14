#!/usr/bin/env python3
"""Frozen text evaluation; gold never enters provider payloads."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import time
from urllib.parse import urlparse

from dotenv import load_dotenv
from evaluate_decision_agent_planner import RecordingProvider, usage_total, NOW
from evaluate_decision_agent_ambiguous import HTTPRecordingProvider
import app.operations.decision_text_interpreter as text_module
from app.operations.decision_text_interpreter import StructuredTextEvidenceInterpreter, collect_excerpts, TextInterpretationError
from app.operations.decision_tools import DecisionToolName as T, DecisionToolResult

FLAGS = ('unresolved_conflict', 'measurement_required', 'uncertain')


def summarize(rows):
    metrics = {'total': len(rows), 'exact_flags_correct': sum(r['correct'] for r in rows),
               'errors': sum(r['error'] is not None for r in rows)}
    for flag in FLAGS:
        valid = [r for r in rows if r['actual'] is not None]
        negatives = [r for r in valid if not r['gold'][flag]]
        positives = [r for r in valid if r['gold'][flag]]
        fp = sum(r['actual'][flag] for r in negatives)
        fn = sum(not r['actual'][flag] for r in positives)
        metrics[flag] = {'false_positives': fp, 'negative_count': len(negatives),
            'false_positive_rate': fp / len(negatives) if negatives else None,
            'false_negatives': fn, 'positive_count': len(positives),
            'false_negative_rate': fn / len(positives) if positives else None}
    for field in ('information_missing', 'measurement_status'):
        available = [r for r in rows if r['actual'] is not None and r['actual'].get(field) is not None and field in r['gold']]
        metrics[field] = {'correct': sum(r['actual'][field] == r['gold'][field] for r in available),
                          'measured': len(available)}
    valid = [r for r in rows if r['actual'] is not None]
    needs_review = lambda x: x['uncertain'] or x['unresolved_conflict']
    positives = [r for r in valid if needs_review(r['gold'])]
    negatives = [r for r in valid if not needs_review(r['gold'])]
    metrics['human_review'] = {
        'missed': sum(not needs_review(r['actual']) for r in positives),
        'required_count': len(positives),
        'unnecessary': sum(needs_review(r['actual']) for r in negatives),
        'not_required_count': len(negatives),
    }
    return metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--iterations', type=int, default=3)
    parser.add_argument('--batch-size', type=int, default=8)
    parser.add_argument('--label', required=True)
    parser.add_argument('--prompt-file', type=Path, help='Evaluation-only frozen prompt override')
    args = parser.parse_args()
    if args.iterations < 1 or not 1 <= args.batch_size <= 8:
        parser.error('iterations must be positive and batch-size must be between 1 and 8')
    load_dotenv(args.env_file, override=True)
    if (os.getenv('LLM_MODEL') != 'gpt-4o-mini' or
        urlparse(os.getenv('LLM_BASE_URL', 'https://api.openai.com/v1')).hostname != 'api.openai.com' or
        os.getenv('LLM_PROVIDER') not in {'openai', 'openai-compatible', 'openai_compatible'}):
        parser.error('Only the authorized synthetic OpenAI gpt-4o-mini evaluation is supported')
    if args.prompt_file:
        text_module.TEXT_INTERPRETATION_PROMPT = args.prompt_file.read_text()
    raw = args.manifest.read_bytes()
    cases = json.loads(raw)['cases']
    artifact = {'label': args.label, 'recorded_at': datetime.now(timezone.utc).isoformat(),
        'manifest_sha256': sha256(raw).hexdigest(), 'cases': cases,
        'prompt_sha256': sha256(text_module.TEXT_INTERPRETATION_PROMPT.encode()).hexdigest(),
        'prompt': text_module.TEXT_INTERPRETATION_PROMPT, 'interpreter': StructuredTextEvidenceInterpreter.name,
        'scope': 'Synthetic text fixtures with real model calls; no live backend or factory performance',
        'batch_size': args.batch_size, 'rows': [], 'batches': []}
    for iteration in range(args.iterations):
        for offset in range(0, len(cases), args.batch_size):
            chunk = cases[offset:offset + args.batch_size]
            source = DecisionToolResult(tool_name=T.GET_ASSET_CONDITION, status='available',
                source_refs=('fixture:text-holdout-v1',), as_of=NOW,
                limitations=tuple(c['text'] for c in chunk))
            provider = HTTPRecordingProvider()
            recording = RecordingProvider(provider)
            interpreter = StructuredTextEvidenceInterpreter(recording)
            started = time.perf_counter()
            error = None
            try:
                predictions = interpreter.interpret(collect_excerpts({T.GET_ASSET_CONDITION: source}), cache={})
            except TextInterpretationError as exc:
                error = str(exc)
                predictions = ()
            by_text = {p.source_text: p.model_dump(mode='json') for p in predictions}
            for case in chunk:
                actual = by_text.get(case['text'])
                artifact['rows'].append({'id': case['id'], 'category': case['category'],
                    'iteration': iteration + 1, 'gold': case['gold'], 'actual': actual, 'error': error,
                    'correct': actual is not None and all(actual[f] == case['gold'][f] for f in FLAGS)})
            artifact['batches'].append({'api_calls': len(recording.calls), 'http_attempts': provider.http_attempts,
                'latency_seconds': time.perf_counter() - started,
                'total_tokens': usage_total(recording.calls, 'total_tokens'), 'error': error})
            artifact['summary'] = summarize(artifact['rows'])
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'label': args.label, 'manifest_sha256': artifact['manifest_sha256'],
                      'summary': artifact['summary']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
