from __future__ import annotations

import copy
import json
import os
import subprocess
import sys

import pytest

from scripts import compare_agent_review_summary_models as runner


@pytest.fixture
def packets():
    manifest = runner.evaluation._load_json(runner.evaluation.GOLD_ROOT / "manifest.json")
    return [runner.evaluation._load_json(runner.evaluation.ROOT / c["fixture_path"])
            for c in manifest["cases"]]


class RecordingProvider:
    def __init__(self, change=None, usage=None):
        self.calls = []
        self.change = change
        self.usage = usage

    def generate_json_with_metadata(self, system, payload, **kwargs):
        self.calls.append(copy.deepcopy((system, payload, kwargs)))
        packet = next(p for p in packets.__wrapped__() if p["asset_id"] == payload["summary_context"]["asset_id"])
        from app.operations.agent_review_summary import compose_deterministic_agent_review_summary
        raw = runner.evaluation._editable_candidate_payload(compose_deterministic_agent_review_summary(packet))
        if self.change:
            self.change(raw)
        payload.clear()  # A provider must not contaminate the next candidate's input.
        return {"payload": raw, "provider_metadata": {"usage": self.usage}}


def test_rotating_order_identical_frozen_context_and_prompt(packets):
    before = copy.deepcopy(packets)
    models = ["test-a", "test-b", "test-c"]
    providers = {m: RecordingProvider() for m in models}
    report = runner.run_comparison(packets=packets[:2], models=models, providers=providers,
                                   iterations=2, mode="live")
    assert [r["model"] for r in report["rows"]] == [
        "test-a", "test-b", "test-c", "test-b", "test-c", "test-a",
        "test-c", "test-a", "test-b", "test-a", "test-b", "test-c"]
    assert providers["test-a"].calls == providers["test-b"].calls == providers["test-c"].calls
    assert packets == before
    for start in range(0, 12, 3):
        assert len({r["input_sha256"] for r in report["rows"][start:start + 3]}) == 1
    assert all(r["accepted"] and r["prose_equals_baseline"] for r in report["rows"])


@pytest.mark.parametrize("change", [
    lambda raw: raw.clear(),
    lambda raw: raw.update(summary=" "),
    lambda raw: raw.update(work_order_id="invented"),
    lambda raw: raw["role_summaries"].pop(),
    lambda raw: raw["role_summaries"].__setitem__(1, raw["role_summaries"][0]),
])
def test_raw_response_cannot_be_repaired_into_acceptance(packets, change):
    report = runner.run_comparison(packets=packets[:1], models=["test"], mode="live",
                                   providers={"test": RecordingProvider(change)})
    row = report["rows"][0]
    assert not row["accepted"] and row["fallback"]
    assert row["candidate_gold"] is None
    assert row["fallback_gold"] is not None
    assert report["aggregate"]["test"]["candidate_gold_score"] is None


def test_forbidden_candidate_is_scored_separately_from_fallback(packets):
    usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
    provider = RecordingProvider(lambda raw: raw.update(summary="수리 완료되었습니다."), usage=usage)
    report = runner.run_comparison(packets=packets[:1], models=["test"],
                                   mode="live", providers={"test": provider})
    row = report["rows"][0]
    assert row["fallback"] and row["validation_errors"]
    assert row["candidate_gold"]["unsupported_claim_count"] > 0
    assert row["fallback_gold"]["unsupported_claim_count"] == 0
    assert report["aggregate"]["test"]["hard_gate_pass_rate"] == 0
    assert row["usage"] == usage  # Rejected output still consumed reported tokens.


def test_provider_failure_does_not_score_baseline_as_candidate_or_leak_message(packets):
    class FailingProvider:
        def generate_json_with_metadata(self, *args, **kwargs):
            raise RuntimeError("sensitive upstream response")
    report = runner.run_comparison(packets=packets[:1], models=["test"], mode="live",
                                   providers={"test": FailingProvider()})
    assert "sensitive" not in json.dumps(report)
    assert report["rows"][0]["provider_error"] == "RuntimeError"
    assert report["rows"][0]["candidate_gold"] is None
    assert report["aggregate"]["test"]["latency_ms"]["samples"] == 1
    assert report["aggregate"]["test"]["cost"]["status"] == "not_measured"


def test_reported_usage_timestamped_prices_and_latency(packets):
    usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
    # Explicit test-only rates; these do not describe a real model's pricing.
    price = {"input_per_1m": 2, "output_per_1m": 3, "currency": "TEST",
             "as_of": "2026-09-07T00:00:00+00:00", "source": "unit-test"}
    ticks = iter([0, .1, 1, 1.3])
    report = runner.run_comparison(packets=packets[:2], models=["test"], mode="live",
                                   providers={"test": RecordingProvider(usage=usage)},
                                   prices={"test": price}, clock=lambda: next(ticks))
    aggregate = report["aggregate"]["test"]
    assert aggregate["latency_ms"] == {"status": "measured", "samples": 2, "p50": 100, "p95": 300}
    assert aggregate["tokens"]["reported_subtotal"]["total_tokens"] == 240
    assert aggregate["cost"]["estimated_total_cost"] == pytest.approx(.00052)
    assert report["rows"][0]["cost"]["price"] == price


@pytest.mark.parametrize("usage", [None, {}, {"prompt_tokens": True, "completion_tokens": 1, "total_tokens": 2},
                                   {"prompt_tokens": -1, "completion_tokens": 2, "total_tokens": 1},
                                   {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 4}])
def test_missing_or_invalid_usage_is_not_estimated(usage):
    assert runner.reported_usage({"usage": usage}) is None
    assert runner.cost_for(None, None)["status"] == "not_measured"


def test_partial_measurements_do_not_become_complete_totals(packets):
    report = runner.run_comparison(packets=packets[:2], models=["test"])
    rows = report["rows"]
    rows[0]["usage"] = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}
    rows[0]["cost"] = {"estimated_total_cost": .001}
    result = runner.aggregate(rows, "live")
    assert result["tokens"]["status"] == "not_measured"
    assert result["tokens"]["reported_rows"] == 1
    assert result["cost"]["estimated_total_cost"] is None


@pytest.mark.parametrize("models,iterations", [([], 1), (["a"] * 2, 1),
    (["a", "b", "c", "d"], 1), (["a"], 0), (["a", "b", "c"], 16)])
def test_bounds_fail_before_any_provider_call(packets, models, iterations):
    with pytest.raises(ValueError):
        runner.run_comparison(packets=packets, models=models, iterations=iterations)


@pytest.mark.parametrize("patch", [{"as_of": "2026-09-07"}, {"source": ""},
                                  {"input_per_1m": float("nan")}, {"output_per_1m": -1}])
def test_invalid_prices_rejected(patch):
    price = {"input_per_1m": 1, "output_per_1m": 2, "currency": "TEST",
             "as_of": "2026-09-07T00:00:00Z", "source": "unit-test", **patch}
    with pytest.raises(ValueError):
        runner.validate_prices({"test": price}, ["test"])


def test_cli_offline_holdout_and_live_configuration_guard(tmp_path):
    output = tmp_path / "comparison.json"
    command = [sys.executable, str(runner.evaluation.ROOT / "scripts/compare_agent_review_summary_models.py"),
               "--model", "offline-test", "--manifest", "tests/fixtures/agent_review_packets_holdout/manifest.json",
               "--gold-answers", "tests/fixtures/agent_review_packets_holdout/gold_answers.json",
               "--output", str(output)]
    env = {k: v for k, v in os.environ.items() if k not in ("LLM_API_KEY", "OPENAI_API_KEY")}
    env["PYTHONPATH"] = "systems/backend"
    subprocess.run(command, env=env, cwd=runner.evaluation.ROOT, check=True, capture_output=True)
    report = json.loads(output.read_text())
    assert len(report["rows"]) == 8
    assert report["evidence_level"] == "offline_test_double"
    assert report["aggregate"]["offline-test"]["latency_ms"]["p50"] is None
    assert report["aggregate"]["offline-test"]["tokens"]["status"] == "not_measured"
    assert report["rows"][0]["candidate_gold"]["answer_set_id"] == "agent-review-summary-holdout-gold-answers-v1"
    result = subprocess.run(command + ["--mode", "live", "--run-id", "test", "--candidate-sha", "test"],
                            env=env, cwd=runner.evaluation.ROOT, capture_output=True, text=True)
    assert result.returncode != 0
    assert "credentials already configured" in result.stderr


def test_changed_output_roles_are_explicitly_unscored(packets, monkeypatch):
    original = runner.evaluation._gold_answer_for

    def legacy_answer(packet):
        answer = copy.deepcopy(original(packet))
        answer["role_points"] = {"legacy-test-role": ["점검"]}
        return answer

    monkeypatch.setattr(runner.evaluation, "_gold_answer_for", legacy_answer)
    report = runner.run_comparison(packets=packets[:1], models=["offline-test"])
    coverage = report["role_gold_coverage"]
    assert coverage["missing_output_roles"] == ["legacy-test-role"]
    assert coverage["unscored_output_roles"] == coverage["output_roles"]


def test_cli_rejects_unequal_temperature_policies_without_calling_provider(tmp_path):
    # These strings exercise existing provider routing, not configured real candidates.
    env = {**os.environ, "LLM_API_KEY": "offline-test-placeholder", "PYTHONPATH": "systems/backend"}
    command = [sys.executable, str(runner.evaluation.ROOT / "scripts/compare_agent_review_summary_models.py"),
               "--mode", "live", "--model", "gpt-5-test-placeholder", "--model", "other-test-placeholder",
               "--run-id", "test", "--candidate-sha", "test", "--output", str(tmp_path / "unused.json")]
    result = subprocess.run(command, env=env, cwd=runner.evaluation.ROOT, capture_output=True, text=True)
    assert result.returncode != 0
    assert "unequal provider temperature policies" in result.stderr
    assert not (tmp_path / "unused.json").exists()


def test_rejected_raw_prose_and_delivered_fallback_are_archived_separately(packets):
    def reject(raw):
        raw["summary"] = "수리 완료되었습니다."
        raw["unexpected_provider_field"] = "do-not-archive-this-field"

    report = runner.run_comparison(packets=packets[:1], models=["test"], mode="live",
                                   providers={"test": RecordingProvider(reject)})
    row = report["rows"][0]
    assert row["raw_candidate_prose"]["summary"] == "수리 완료되었습니다."
    assert "do-not-archive-this-field" not in json.dumps(report)
    assert row["raw_candidate_gold"]["unsupported_claim_count"] > 0
    assert row["candidate_gold"] is None  # Raw schema failed before merge.
    assert not row["accepted"] and row["editable_output"] is None
    assert row["delivered_kind"] == "deterministic_fallback"
    assert row["delivered_gold"] == row["fallback_gold"]
    assert row["delivered_gold"]["unsupported_claim_count"] == 0
    assert report["aggregate"]["test"]["raw_gold_scored_candidates"] == 1
    assert report["aggregate"]["test"]["fallback_gold_score"] is not None
    assert row["delivered_output"] != row["raw_candidate_prose"]


def test_archive_manifest_binds_inputs_settings_usage_and_reject_reasons(packets):
    usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
    report = runner.run_comparison(packets=packets[:1], models=["test"], mode="live",
        providers={"test": RecordingProvider(lambda raw: raw.update(summary=" "), usage=usage)},
        model_settings={"temperature": 0, "provider": "test-provider", "api_key": "not-public"})
    archive = report["archive_manifest"]
    assert "not-public" not in json.dumps(report)
    assert archive["model_settings"]["test"] == {"model": "test", "temperature": 0, "provider": "test-provider"}
    for key in ("system_prompt_sha256", "scorer_sha256", "response_schema_sha256"):
        assert archive[key] == report[key]
    row = report["rows"][0]
    attempt = archive["attempts"][0]
    assert archive["packets"][0]["packet_sha256"] == runner.fingerprint(packets[0])
    assert archive["packets"][0]["prompt_payload_sha256"] == row["input_sha256"]
    assert attempt["row_ref"] == "#/rows/0"
    assert attempt["row_sha256"] == runner.fingerprint(row)
    assert attempt["usage"] == usage
    assert attempt["reject_reasons"] == ["incomplete_role_prose"]
    assert archive["started_at"] <= attempt["started_at"] <= attempt["finished_at"] <= archive["finished_at"]


@pytest.fixture
def selection_example(packets):
    """All values are test doubles; no real model or price is configured."""
    usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
    price = {"input_per_1m": 2, "output_per_1m": 3, "currency": "TEST",
             "as_of": "2026-09-07T00:00:00Z", "source": "unit-test"}
    models = ["test-reference", "test-candidate"]
    report = runner.run_comparison(packets=packets[:1], models=models, iterations=2, mode="live",
        providers={m: RecordingProvider(usage=usage) for m in models}, prices={m: price for m in models},
        model_settings={"temperature": 0, "provider": "test-provider"})
    config = {"registered_at": "2000-01-01T00:00:00Z", "quality_floor": .5, "max_regression": .1,
              "repeat_count": 2, "baseline_model": models[0], "models": models,
              "input_binding_sha256": report["archive_manifest"]["input_binding_sha256"]}
    return report, config


def test_historical_scorer_always_blocks_three_role_selection(selection_example):
    report, config = selection_example
    gate = runner.selection_gate(report, config)
    assert gate["status"] == "blocked"
    assert "complete_three_role_rubric_missing" in gate["reasons"]
    assert gate["selected_model"] is None and gate["eligible_models"] == []
    assert report["selection_gate"]["reasons"] == ["preregistration_missing"]


@pytest.mark.parametrize("key,value,reason", [
    ("quality_floor", None, "invalid_or_missing_quality_floor"),
    ("max_regression", float("nan"), "invalid_or_missing_max_regression"),
    ("repeat_count", None, "invalid_or_missing_repeat_count"),
    ("repeat_count", 3, "preregistered_repeat_count_not_met"),
    ("registered_at", "2999-01-01T00:00:00Z", "registration_not_before_run"),
    ("registered_at", "2020-01-01", "registration_not_before_run"),
    ("models", ["other"], "preregistered_models_mismatch"),
    ("input_binding_sha256", "other", "preregistered_inputs_or_settings_mismatch"),
    ("baseline_model", "other", "comparison_baseline_missing"),
])
def test_selection_requires_preregistered_criteria(selection_example, key, value, reason):
    report, config = selection_example
    config[key] = value
    gate = runner.selection_gate(report, config)
    assert gate["status"] == "blocked" and reason in gate["reasons"]
    assert gate["selected_model"] is None


def test_selection_requires_live_complete_measurements(selection_example):
    report, config = selection_example
    report["mode"] = "offline"
    report["rows"][0]["usage"] = None
    gate = runner.selection_gate(report, config)
    assert "live_measurements_missing" in gate["reasons"]
    assert "complete_latency_usage_and_priced_cost_required" in gate["reasons"]


def test_gate_uses_raw_floor_regression_and_direct_acceptance_never_fallback(selection_example):
    report, config = selection_example
    # Exercise the generic gate's future rubric-ready branch using a synthetic
    # report. The current production runner NEVER labels its rubric complete.
    report["selection_rubric"] = {"complete": True, "roles": sorted(runner.PRODUCT_ROLES)}
    reference = report["aggregate"]["test-reference"]
    candidate = report["aggregate"]["test-candidate"]
    reference["raw_candidate_gold_score"] = .9
    candidate["raw_candidate_gold_score"] = .4
    candidate["delivered_gold_score"] = 1.0
    candidate["hard_gate_pass_rate"] = .5
    gate = runner.selection_gate(report, config)
    assert gate["model_reasons"]["test-candidate"] == [
        "below_quality_floor", "exceeds_max_regression", "direct_acceptance_failed"]
    assert gate["eligible_models"] == ["test-reference"]
    assert gate["selected_model"] is None  # Eligibility does not invent a winner.


def test_selection_config_is_frozen_before_provider_generation(packets):
    config = {"quality_floor": .9}
    provider = RecordingProvider(lambda raw: config.update(quality_floor=0))
    report = runner.run_comparison(packets=packets[:1], models=["test"], mode="live",
                                   providers={"test": provider}, selection_config=config)
    assert report["selection_config"] == {"quality_floor": .9}
    assert report["archive_manifest"]["selection_config_sha256"] == runner.fingerprint({"quality_floor": .9})


def test_non_object_candidate_text_is_preserved_and_scored_without_acceptance(packets):
    class TextProvider:
        def generate_json_with_metadata(self, *args, **kwargs):
            return {"payload": "수리 완료되었습니다.", "provider_metadata": {}}

    report = runner.run_comparison(packets=packets[:1], models=["test"], mode="live",
                                   providers={"test": TextProvider()})
    row = report["rows"][0]
    assert row["raw_candidate_prose"] == {"unstructured_text": "수리 완료되었습니다."}
    assert row["raw_candidate_gold"]["unsupported_claim_count"] > 0
    assert not row["accepted"] and row["delivered_kind"] == "deterministic_fallback"
