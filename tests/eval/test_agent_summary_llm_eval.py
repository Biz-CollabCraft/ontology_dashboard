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
    assert aggregate["cost"]["status"] == "estimated"
    assert aggregate["cost"]["estimated_total_cost"] > 0


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
    assert artifact["sample_size"] == 120
    assert artifact["case_count"] == 8
    assert artifact["iterations_per_case"] == 15
    assert artifact["pre_harness_gate"]["ready_for_120_run"] is True
    assert artifact["ready_for_live_120_run"] is True
    assert artifact["aggregate"]["contract_error_rows"] == 0
