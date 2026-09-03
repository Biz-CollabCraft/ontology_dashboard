#!/usr/bin/env python3
"""Evaluate S0/S1 operational evidence selection on synthetic context."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "systems" / "backend"
for import_root in (ROOT, BACKEND):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from app.dependencies import build_manufacturing_service  # noqa: E402


ASSET_ID = "CNC-S04-L02-03"
PROJECT_ID = "manufacturing-demo-project"
DECISION_AS_OF = datetime(2026, 9, 2, 1, tzinfo=timezone.utc)
RETRIEVED_AT = datetime(2026, 9, 2, 2, tzinfo=timezone.utc)
REQUIRED_EVIDENCE_IDS = {
    "operational-decision-context-demo-v1#/production_orders/0",
    "operational-decision-context-demo-v1#/wip/0",
    "maintenance-readiness-context-demo-v1#/part_requirements/0",
    "quality-delivery-context-demo-v1#/quality_lots/1",
    "quality-delivery-context-demo-v1#/delivery_commitments/0",
}


def evaluate(candidate_sha: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="operational-selection-") as directory:
        service = build_manufacturing_service(
            Path(directory) / "selection-eval.db",
            root=ROOT,
        )
        selection = service.agent_review_evidence_selection(
            ASSET_ID,
            PROJECT_ID,
            decision_as_of=DECISION_AS_OF,
            retrieved_at=RETRIEVED_AT,
            role="process_manager",
            max_candidates=8,
            required_evidence_ids=REQUIRED_EVIDENCE_IDS,
        )
    metrics = selection["metrics"]
    passed = all(
        [
            metrics["required_evidence_recall"] == 1.0,
            metrics["required_limitation_preservation"] == 1.0,
            metrics["context_reduction"] > 0,
            selection["mutation_allowed"] is False,
            selection["strategies"]["S1"]["selected_candidate_count"]
            < selection["strategies"]["S0"]["selected_candidate_count"],
        ]
    )
    return {
        "evaluation_schema_version": "operational-evidence-selection-eval-v1.0",
        "evaluation_mode": "deterministic_synthetic_smoke",
        "candidate_sha": candidate_sha,
        "asset_id": ASSET_ID,
        "project_id": PROJECT_ID,
        "strategy_under_test": "S1_DETERMINISTIC_SELECTION",
        "baseline_strategy": "S0_FULL_CONTEXT",
        "live_llm_evaluation": False,
        "actual_mes_cmms_wms_qms_evaluation": False,
        "passed": passed,
        "metrics": metrics,
        "selected_source_refs": selection["strategies"]["S1"]["selected_source_refs"],
        "full_candidate_count": selection["strategies"]["S0"]["selected_candidate_count"],
        "selected_candidate_count": selection["strategies"]["S1"]["selected_candidate_count"],
        "limitations": [
            "Synthetic deterministic smoke; not final live LLM quality evidence.",
            "Prompt token reduction is represented by candidate reduction until LLM prompt measurement is wired.",
            "Does not claim actual MES/CMMS/WMS/QMS connectivity.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-sha", default="working-tree")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT
        / "tests"
        / "eval"
        / "results"
        / "operational_evidence_selection_working-tree.json",
    )
    args = parser.parse_args()

    result = evaluate(args.candidate_sha)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
