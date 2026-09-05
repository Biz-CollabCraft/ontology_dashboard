from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "evaluate_agent_review_summary_llm.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("agent_summary_llm_eval", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mock_120_run_harness_aggregates_all_gold_packets(monkeypatch) -> None:
    monkeypatch.setenv("LLM_INPUT_PRICE_PER_1M_TOKENS", "0.15")
    monkeypatch.setenv("LLM_OUTPUT_PRICE_PER_1M_TOKENS", "0.60")
    monkeypatch.setenv("LLM_PRICE_CURRENCY", "USD")
    monkeypatch.setenv("LLM_PRICING_VERSION", "configured-gpt-4o-mini-2026-09-01")
    harness = _load_harness()
    manifest = harness._load_json(harness.GOLD_ROOT / "manifest.json")
    packets = [
        harness._load_json(harness.ROOT / case["fixture_path"])
        for case in manifest["cases"]
    ]
    rows = [
        harness._run_mock_candidate(
            packet=packet,
            iteration=iteration,
            provider="mock-openai-compatible",
            model="gpt-4o-mini",
        )
        for packet in packets
        for iteration in range(1, 16)
    ]

    aggregate = harness._aggregate(rows)

    assert len(packets) == 8
    assert len(rows) == 120
    assert aggregate["sample_size"] == 120
    assert aggregate["accepted_llm_candidates"] == 120
    assert aggregate["fallback_summaries"] == 0
    assert aggregate["acceptance_rate"] == 1.0
    assert aggregate["grounding"]["grounding_rate"] == 1.0
    assert aggregate["quality_scores"]["coverage_candidate"] is not None
    assert aggregate["quality_scores"]["usefulness_candidate"] is not None
    assert aggregate["quality_scores"]["korean_quality_candidate"] is not None
    assert aggregate["quality_scores"]["overall_candidate"] is not None
    assert aggregate["gold_accuracy"]["accuracy_goldset_score"] is not None
    assert aggregate["gold_accuracy"]["missing_required_points"] == 0
    assert aggregate["gold_accuracy"]["must_not_claim_violations"] == 0
    assert aggregate["cost"]["status"] == "estimated"
    assert aggregate["cost"]["estimated_total_cost"] > 0
    assert all(row["editable_output"] for row in rows)
    assert all(row["quality_scores"]["checks"]["coverage"] for row in rows)
    assert all(row["gold_accuracy"]["accuracy_goldset_score"] == 1.0 for row in rows)


def test_mock_holdout_run_uses_custom_manifest_and_gold_answers() -> None:
    harness = _load_harness()
    harness.GOLD_ANSWERS_PATH = (
        harness.ROOT / "tests/fixtures/agent_review_packets_holdout/gold_answers.json"
    )
    harness._GOLD_ANSWERS_CACHE = None
    manifest = harness._load_json(
        harness.ROOT / "tests/fixtures/agent_review_packets_holdout/manifest.json"
    )
    packets = [
        harness._load_json(harness.ROOT / case["fixture_path"])
        for case in manifest["cases"]
    ]

    rows = [
        harness._run_mock_candidate(
            packet=packet,
            iteration=1,
            provider="mock-openai-compatible",
            model="gpt-4o-mini",
        )
        for packet in packets
    ]
    aggregate = harness._aggregate(rows)

    assert len(packets) == 8
    assert rows[0]["gold_accuracy"]["answer_set_id"] == (
        "agent-review-summary-holdout-gold-answers-v1"
    )
    assert aggregate["gold_accuracy"]["accuracy_goldset_score"] == 1.0
    assert all(
        row["gold_accuracy"]["role_scores"]["process_manager"]["score"] == 1.0
        for row in rows
    )
    assert aggregate["gold_accuracy"]["missing_required_points"] == 0


def test_quality_scores_detect_internal_language_and_missing_role_focus() -> None:
    harness = _load_harness()
    packet = harness._load_json(harness.ROOT / "tests/fixtures/agent_review_packets/GS-004.json")
    candidate = harness.compose_deterministic_agent_review_summary(packet)
    candidate["summary"] = "packet source_ref only"
    candidate["role_summaries"] = [
        {"role": "field_operator", "quote": "대상 설명 없음"},
        {"role": "process_manager", "quote": "대상 설명 없음"},
    ]

    scores = harness._quality_scores(candidate, packet=packet)

    assert scores["coverage_candidate"] < 1.0
    assert scores["usefulness_candidate"] < 1.0
    assert scores["korean_quality_candidate"] < 1.0
    assert scores["checks"]["korean_quality"]["avoids_internal_terms"] is False


def test_gold_accuracy_scores_reference_answer_misses_and_forbidden_claims() -> None:
    harness = _load_harness()
    packet = harness._load_json(harness.ROOT / "tests/fixtures/agent_review_packets/GS-004.json")
    candidate = harness.compose_deterministic_agent_review_summary(packet)
    candidate["summary"] = "critical 상태지만 수리 완료되었습니다."
    candidate["role_summaries"] = [
        {"role": "field_operator", "quote": "주축 모터 확인"},
        {"role": "process_manager", "quote": "생산 영향 확인"},
    ]

    score = harness._gold_accuracy(candidate, packet=packet)

    assert score["accuracy_goldset_score"] < 1.0
    assert "수리 완료" in score["must_not_claim_violations"]
    assert score["unsupported_claim_count"] == 1
    assert score["missing_required_points"]


def test_gold_accuracy_accepts_observed_process_manager_surface_variants() -> None:
    harness = _load_harness()
    packet = harness._load_json(harness.ROOT / "tests/fixtures/agent_review_packets/GS-002.json")
    candidate = harness.compose_deterministic_agent_review_summary(packet)
    candidate["summary"] = (
        "CNC-S04-L04-01는 현재 warning 상태이며 예측 위험도는 82.5%입니다. "
        "공구/마모 계통과 동력 전달 계통을 함께 확인해야 합니다."
    )
    candidate["role_summaries"] = [
        {
            "role": "field_operator",
            "quote": (
                "공구 매거진 및 스핀들 공구 체결부와 주축 모터를 점검하고, 관측값을 "
                "기록한 후 정비팀 또는 생산 관리자에게 인계해야 합니다."
            ),
        },
        {
            "role": "process_manager",
            "quote": (
                "현재 상태는 중간 정도의 생산 영향을 미치며, 예상되는 다운타임은 120분, "
                "손실 예상 유닛은 25개입니다. 정비 우선순위 및 승인 검토가 필요합니다."
            ),
        },
    ]

    score = harness._gold_accuracy(candidate, packet=packet)

    assert score["role_scores"]["process_manager"]["score"] == 1.0
    assert score["role_scores"]["process_manager"]["missing_points"] == []
    assert "생산 영향이 중간" in score["matched_required_points"]
    assert "25건" in score["matched_required_points"]


def test_gold_accuracy_does_not_match_inventory_counts_as_lost_units() -> None:
    harness = _load_harness()

    assert harness._contains_point("손실 예상 유닛은 25개입니다.", "25건")
    assert not harness._contains_point("25개 부품 재고 확보를 검토합니다.", "25건")
    assert not harness._contains_point("공구 25개를 점검합니다.", "25건")


def test_gold_accuracy_keeps_data_quality_hold_process_manager_miss_visible() -> None:
    harness = _load_harness()
    packet = harness._load_json(harness.ROOT / "tests/fixtures/agent_review_packets/GS-007.json")
    candidate = harness.compose_deterministic_agent_review_summary(packet)
    candidate["summary"] = (
        "CNC-S04-L05-01는 데이터 품질 보류 상태라 위험 등급과 예측 위험도를 "
        "확정하지 않습니다. 근거 공백이 있습니다."
    )
    candidate["role_summaries"] = [
        {
            "role": "field_operator",
            "quote": "데이터 품질 보류 상태에 대한 증거를 기록하십시오.",
        },
        {
            "role": "process_manager",
            "quote": (
                "현재 CNC-S04-L05-01의 생산 영향은 낮으며, 예상 다운타임은 40분입니다. 정비 "
                "이력이 부족하여 생산 계획에 미치는 영향이 불확실합니다."
            ),
        },
    ]

    score = harness._gold_accuracy(candidate, packet=packet)

    assert score["role_scores"]["process_manager"]["score"] == 0.0
    assert score["role_scores"]["process_manager"]["missing_points"] == [
        "추정 물량 손실",
        "유사 이력은 아직",
        "점검 승인",
    ]


def test_mock_120_run_harness_writes_result_artifact(tmp_path: Path) -> None:
    output = tmp_path / "agent-summary-llm-eval.json"
    env = {
        **os.environ,
        "PYTHONPATH": "systems/backend",
        "LLM_INPUT_PRICE_PER_1M_TOKENS": "0.15",
        "LLM_OUTPUT_PRICE_PER_1M_TOKENS": "0.60",
        "LLM_PRICE_CURRENCY": "USD",
        "LLM_PRICING_VERSION": "configured-gpt-4o-mini-2026-09-01",
    }
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--iterations",
            "15",
            "--run-id",
            "quality-test-run",
            "--candidate-sha",
            "quality-test-sha",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    summary = json.loads(result.stdout)
    artifact = json.loads(output.read_text(encoding="utf-8"))

    assert summary["sample_size"] == 120
    assert summary["accepted_llm_candidates"] == 120
    assert artifact["run_id"] == summary["run_id"] == "quality-test-run"
    assert artifact["candidate_sha"] == summary["candidate_sha"] == "quality-test-sha"
    assert artifact["sample_size"] == 120
    assert artifact["case_count"] == 8
    assert artifact["iterations_per_case"] == 15
    assert artifact["pre_harness_gate"]["ready_for_120_run"] is True
    assert artifact["ready_for_live_120_run"] is True
    assert artifact["aggregate"]["contract_error_rows"] == 0
    assert artifact["aggregate"]["quality_scores"]["overall_candidate"] is not None
    assert artifact["aggregate"]["gold_accuracy"]["accuracy_goldset_score"] == 1.0
    assert artifact["rows"][0]["editable_output"]["role_summaries"]
    assert artifact["rows"][0]["quality_scores"]["limits"]
    assert artifact["rows"][0]["gold_accuracy"]["answer_set_id"] == (
        "agent-review-summary-gold-answers-v1"
    )


def test_mock_harness_records_concurrency_metrics(tmp_path: Path) -> None:
    output = tmp_path / "agent-summary-llm-eval-c4.json"
    env = {
        **os.environ,
        "PYTHONPATH": "systems/backend",
        "LLM_INPUT_PRICE_PER_1M_TOKENS": "0.15",
        "LLM_OUTPUT_PRICE_PER_1M_TOKENS": "0.60",
        "LLM_PRICE_CURRENCY": "USD",
        "LLM_PRICING_VERSION": "configured-gpt-4o-mini-2026-09-01",
    }
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--iterations",
            "1",
            "--concurrency",
            "4",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    summary = json.loads(result.stdout)
    artifact = json.loads(output.read_text(encoding="utf-8"))

    assert summary["sample_size"] == 8
    assert summary["concurrency"] == 4
    assert summary["batch_wall_clock_ms"] > 0
    assert artifact["concurrency"] == 4
    assert artifact["aggregate"]["batch"]["wall_clock_ms"] > 0
    assert artifact["aggregate"]["batch"]["throughput_per_minute"] > 0
    assert artifact["aggregate"]["queue_wait_ms"]["p95"] is not None
    assert all(row["attempt"] == 1 for row in artifact["rows"])
    assert all(row["llm"]["queue_wait_ms"] is not None for row in artifact["rows"])
