#!/usr/bin/env python3
"""Explicit, paired model comparison over frozen synthetic text; no runtime config writes."""
import argparse
import copy
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import statistics
import time

from dotenv import dotenv_values
from app.infra.llm.provider import OpenAICompatibleProvider
from app.operations.decision_text_interpreter import StructuredTextEvidenceInterpreter, collect_excerpts, TextInterpretationError, TEXT_INTERPRETATION_PROMPT
from app.operations.decision_tools import DecisionToolName as T, DecisionToolResult
from evaluate_decision_agent_planner import RecordingProvider, NOW, usage_total
from evaluate_decision_text_holdout import FLAGS, summarize
from evaluate_decision_text_interpreter import CASES as REGRESSION

ROOT = Path(__file__).resolve().parents[1]
MODELS = ('gpt-4o-mini', 'gpt-5.6-luna')


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class ModelProvider(OpenAICompatibleProvider):
    def __init__(self, model):
        if model not in MODELS:
            raise ValueError('Explicit supported comparison model required')
        super().__init__()
        self.model = model
        self.timeout_seconds = 90
        self.events = []
        if self.base_url != 'https://api.openai.com/v1' or not self.api_key:
            raise ValueError('Expected OpenAI endpoint and configured credentials')

    def _post_chat_completion(self, request_body):
        body = copy.deepcopy(request_body)
        body['model'] = self.model
        body['max_completion_tokens'] = 4096
        if self.model == 'gpt-5.6-luna':
            body.pop('temperature', None)
            body['reasoning_effort'] = 'low'
        else:
            body['temperature'] = 0
        event = {'requested_model': self.model, 'status': None, 'returned_model': None,
                 'format': body['response_format']['type'], 'input_sha256': fingerprint(body['messages']),
                 'schema_sha256': fingerprint(body['response_format']),
                 'reasoning_effort': body.get('reasoning_effort'), 'temperature': body.get('temperature')}
        self.events.append(event)
        response = super()._post_chat_completion(body)
        event['status'] = response.status_code
        if response.is_success:
            data = response.json()
            event.update(returned_model=data.get('model'), usage=data.get('usage'),
                         finish_reasons=[c.get('finish_reason') for c in data.get('choices', [])])
            returned = event['returned_model'] or ''
            if returned != self.model and not returned.startswith(self.model + '-'):
                raise ValueError('Provider response model does not match requested model')
        return response


def inputs(gold_dataset=None, *, allow_draft=False):
    if allow_draft and gold_dataset is None:
        raise ValueError("Draft evaluation requires --gold-dataset")
    if gold_dataset is not None:
        from validate_decision_gold import validate
        data = json.loads(gold_dataset.read_text())
        errors = validate(data, require_review=not allow_draft)
        if errors:
            raise ValueError("Gold dataset requires completed human review: " + "; ".join(errors[:3]))
        return [{'id': c['id'], 'text': c['source']['text'], 'category': c['family_id'],
                 'suite': 'draft_evaluation' if allow_draft else 'reviewed_evaluation', 'gold': c['annotation']['labels'],
                 'context': c['context'], 'action_constraint': c['annotation']['action_constraint']}
                for c in data['cases'] if c['split'] == 'evaluation' and c['annotation']['status'] == 'proposed']
    data = json.loads((ROOT / 'tests/fixtures/decision_text_ambiguity_holdout_v1.json').read_text())['cases']
    cases = [{**c, 'suite': 'ambiguity'} for c in data]
    for id, text, flags in REGRESSION:
        cases.append({'id': id, 'text': text, 'category': 'regression', 'suite': 'regression',
                      'gold': dict(zip(FLAGS, flags))})
    return cases


def save(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def score(rows, batches):
    result = {}
    for model in MODELS:
        selected = [r for r in rows if r['model'] == model]
        calls = [b for b in batches if b['model'] == model]
        result[model] = {'all': summarize(selected), 'by_suite': {
            suite: summarize([r for r in selected if r['suite'] == suite])
            for suite in sorted({r['suite'] for r in selected})},
            'api_calls': sum(b['api_calls'] for b in calls),
            'http_requests': sum(len(b['http_events']) for b in calls),
            'json_object_retries': sum(e['format'] == 'json_object' for b in calls for e in b['http_events']),
            'total_tokens': sum(b['total_tokens'] or 0 for b in calls),
            'token_measured_batches': sum(b['total_tokens'] is not None for b in calls),
            'mean_batch_latency_seconds': statistics.mean(b['latency_seconds'] for b in calls) if calls else None,
            'returned_models': sorted({e['returned_model'] for b in calls for e in b['http_events'] if e['returned_model']})}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--iterations', type=int, default=3)
    parser.add_argument('--gold-dataset', type=Path, help='Reviewed candidate dataset; evaluation split only')
    parser.add_argument("--allow-draft", action="store_true", help="Explicit exploratory evaluation of proposed labels; never approves or exports gold")
    args = parser.parse_args()
    if args.prepare == args.run or args.iterations < 1:
        parser.error('Choose exactly one of --prepare and --run; iterations must be positive')
    cases = inputs(args.gold_dataset, allow_draft=args.allow_draft)
    if not cases: raise SystemExit("Empty evaluation input")
    # Keep suites separate and preserve their existing order; no gold is sent to providers.
    chunks = []
    for suite in dict.fromkeys(c['suite'] for c in cases):
        selected = [c for c in cases if c['suite'] == suite]
        chunks.extend(selected[i:i+8] for i in range(0, len(selected), 8))
    sources = [Path(__file__), ROOT/'systems/backend/app/operations/decision_text_interpreter.py',
        ROOT/'systems/backend/app/operations/decision_support_contract.py',
        ROOT/'systems/backend/app/infra/llm/provider.py', ROOT/'scripts/evaluate_decision_text_holdout.py']
    if args.gold_dataset:
        sources.extend([args.gold_dataset.resolve(), ROOT/'scripts/validate_decision_gold.py'])
    protocol = {'allow_draft': args.allow_draft,
        'excluded_unresolved_ids': [c['id'] for c in json.loads(args.gold_dataset.read_text())['cases'] if c['split'] == 'evaluation' and c['annotation']['status'] == 'unresolved'] if args.gold_dataset else [],
        'gold_dataset_sha256': sha256(args.gold_dataset.read_bytes()).hexdigest() if args.gold_dataset else None,
        'models': MODELS, 'iterations': args.iterations, 'cases': cases,
        'prompt': TEXT_INTERPRETATION_PROMPT, 'prompt_sha256': sha256(TEXT_INTERPRETATION_PROMPT.encode()).hexdigest(),
        'source_sha256': {str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p): sha256(p.read_bytes()).hexdigest() for p in sources},
        'settings': {'gpt-4o-mini': {'temperature': 0, 'reasoning_effort': None},
                     'gpt-5.6-luna': {'temperature': 'omitted', 'reasoning_effort': 'low'}},
        'max_completion_tokens': 4096, 'endpoint': 'https://api.openai.com/v1/chat/completions',
        'scope': 'UNREVIEWED synthetic draft: agreement with proposed labels only; not validated gold accuracy' if args.allow_draft else 'Human-reviewed synthetic evaluation split; not field accuracy' if args.gold_dataset else 'Existing synthetic text cases, tuned before comparison; not unseen holdout, live backend, or production accuracy',
        'order': 'paired batches, rotate model order by iteration and chunk; unchanged gold/prompt across models'}
    binding = fingerprint(protocol)
    out = args.output_dir
    if args.prepare:
        out.mkdir(parents=True, exist_ok=True)
        if (out/'registration.json').exists():
            raise SystemExit('Registration exists; refusing overwrite')
        save(out/'registration.json', {'registered_at': datetime.now(timezone.utc).isoformat(), 'binding': binding, 'protocol': protocol})
        print(json.dumps({'binding': binding, 'models': MODELS, 'cases_per_model': len(cases)*args.iterations}))
        return
    registered = json.loads((out/'registration.json').read_text())
    if binding != registered['binding']:
        raise SystemExit('Frozen protocol or source changed; refusing model calls')
    if not args.env_file:
        parser.error('--run requires --env-file for credentials; its model value is ignored')
    values = dotenv_values(args.env_file)
    for key in ('LLM_API_KEY', 'OPENAI_API_KEY', 'LLM_BASE_URL'):
        if values.get(key): os.environ[key] = values[key]
    path = out/'comparison.json'
    artifact = json.loads(path.read_text()) if path.exists() else {
        'binding': binding, 'registered': registered, 'rows': [], 'batches': []}
    if artifact['binding'] != binding: raise SystemExit('Result binding mismatch')
    done = {(b['iteration'],b['chunk'],b['model']) for b in artifact['batches']}
    for iteration in range(args.iterations):
        for index, chunk in enumerate(chunks):
            order = MODELS if (iteration+index)%2 == 0 else tuple(reversed(MODELS))
            for model in order:
                if (iteration+1,index,model) in done: continue
                source = DecisionToolResult(tool_name=T.GET_ASSET_CONDITION, status='available',
                    source_refs=('fixture:paired-model-comparison',), as_of=NOW,
                    limitations=tuple(c['text'] for c in chunk))
                provider = ModelProvider(model)
                recording = RecordingProvider(provider)
                started = time.perf_counter()
                error = None
                try:
                    parsed = StructuredTextEvidenceInterpreter(recording).interpret(
                        collect_excerpts({T.GET_ASSET_CONDITION: source}), cache={})
                except TextInterpretationError as exc:
                    error = str(exc); parsed = ()
                by_text = {p.source_text: p.model_dump(mode='json') for p in parsed}
                for case in chunk:
                    actual = by_text.get(case['text'])
                    artifact['rows'].append({'id': case['id'], 'suite': case['suite'], 'model': model,
                        'iteration': iteration+1, 'gold': case['gold'], 'actual': actual, 'error': error,
                        'correct': actual is not None and all(actual[f] == case['gold'][f] for f in FLAGS)})
                artifact['batches'].append({'iteration': iteration+1, 'chunk': index, 'model': model,
                    'latency_seconds': time.perf_counter()-started, 'api_calls': len(recording.calls),
                    'total_tokens': usage_total(recording.calls,'total_tokens'), 'http_events': provider.events, 'error': error})
                artifact['summary'] = score(artifact['rows'], artifact['batches'])
                save(path, artifact)
                print(f'{model}: iteration {iteration+1}, chunk {index+1}, error={error}', flush=True)
    print(json.dumps(artifact['summary'], ensure_ascii=False))


if __name__ == '__main__': main()
