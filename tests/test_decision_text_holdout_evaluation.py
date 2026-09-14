import importlib
from pathlib import Path


def load(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    return importlib.import_module('evaluate_decision_text_holdout')


def test_evaluation_errors_are_not_counted_as_successful_negative_predictions(monkeypatch):
    module = load(monkeypatch)
    gold = dict.fromkeys(module.FLAGS, False)
    metrics = module.summarize([dict(gold=gold, actual=None, error='timeout', correct=False)])
    assert metrics['errors'] == 1
    assert metrics['exact_flags_correct'] == 0
    assert metrics['measurement_required']['false_positive_rate'] is None
    assert metrics['measurement_required']['negative_count'] == 0


def test_false_positives_and_false_negatives_have_separate_denominators(monkeypatch):
    module = load(monkeypatch)
    negative = dict.fromkeys(module.FLAGS, False)
    positive = {**negative, 'measurement_required': True}
    rows = [dict(gold=negative, actual=positive, error=None, correct=False),
            dict(gold=positive, actual=negative, error=None, correct=False),
            dict(gold=negative, actual=negative, error=None, correct=True)]
    score = module.summarize(rows)['measurement_required']
    assert score['false_positive_rate'] == 0.5
    assert score['false_negative_rate'] == 1


def test_human_review_counts_conflict_and_ambiguity_without_credit_for_errors(monkeypatch):
    module = load(monkeypatch)
    clear = dict.fromkeys(module.FLAGS, False)
    ambiguous = {**clear, 'uncertain': True}
    conflict = {**clear, 'unresolved_conflict': True}
    rows = [dict(gold=ambiguous, actual=clear, error=None, correct=False),
            dict(gold=conflict, actual=ambiguous, error=None, correct=False),
            dict(gold=clear, actual=conflict, error=None, correct=False),
            dict(gold=clear, actual=None, error='timeout', correct=False)]
    score = module.summarize(rows)
    assert score['errors'] == 1
    assert score['human_review'] == dict(missed=1, required_count=2, unnecessary=1, not_required_count=1)
