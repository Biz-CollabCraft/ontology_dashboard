#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from app.diagnosis.contracts import load_fixture
from app.diagnosis.evidence import build_product_result_artifact
from app.diagnosis.recommendation_policy import (
    POLICY_VERSION,
    RecommendationPolicyInput,
    evaluate_recommendation_policy,
)
from app.diagnosis.predictor import HeuristicPredictor
from app.maintenance import ProducerRecommendation


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _producer_for_fixture(root: Path, scenario: dict[str, Any], *, policy_version: str) -> ProducerRecommendation:
    fixture_path = root / scenario["fixture_path"]
    fixture = load_fixture(fixture_path)
    artifact = build_product_result_artifact(fixture, predictor=HeuristicPredictor())
    evidence_payload = artifact["evidence_payload"]
    action = evidence_payload["recommended_actions"][0]
    policy_input = RecommendationPolicyInput(
        source_product_result_id=str(artifact["artifact_id"]),
        source_evidence_id=str(artifact["provenance"]["evidence_payload_reference"]["reference"]),
        source_schema_version=str(artifact["schema_version"]),
        status=str(artifact["status_grade"]),
        equipment=dict(fixture["equipment"]),
        basis=tuple(action["basis"]),
        source_fields=tuple(field["field_id"] for field in evidence_payload["source_fields"]),
        data_quality_hold=str(artifact["status_grade"]) == "data_quality_hold"
        or bool(artifact["data_quality_warnings"]),
        policy_version=policy_version,
    )
    producer = evaluate_recommendation_policy(policy_input)
    return producer.model_copy(
        update={
            "source_product_result_id": f"{producer.source_product_result_id}#{scenario['id']}",
            "source_evidence_id": f"{producer.source_evidence_id}#{scenario['id']}",
        }
    )


def seed_gold_recommendations(
    root: Path,
    *,
    output: Path,
    policy_version: str = POLICY_VERSION,
) -> dict[str, Any]:
    suite_path = root / "evaluation" / "gold_scenarios.yml"
    suite = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
    existing = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
    existing_rows = existing.get("fixture_recommendations") or []
    by_key = {
        (
            row["source_product_result_id"],
            row["source_action_id"],
            row["source_policy_version"],
        ): row
        for row in existing_rows
    }
    rows = list(existing_rows)
    inserted = 0
    replayed = 0
    for scenario in suite["scenarios"]:
        producer = _producer_for_fixture(root, scenario, policy_version=policy_version)
        key = (
            producer.source_product_result_id,
            producer.source_action_id,
            producer.source_policy_version,
        )
        if key in by_key:
            replayed += 1
            continue
        fixture_path = root / scenario["fixture_path"]
        row = {
            "scenario_id": scenario["id"],
            "fixture_path": scenario["fixture_path"],
            "fixture_checksum_sha256": _checksum(fixture_path),
            "status": "proposed",
            "store": "evaluation_demo_fixture",
            "do_not_operationalize": True,
            **producer.model_dump(mode="json"),
        }
        rows.append(row)
        by_key[key] = row
        inserted += 1
    result = {
        "artifact_type": "recommendation_policy_gold_fixture_store",
        "suite_id": suite["suite_id"],
        "gold_version": "gold-v1",
        "policy_version": policy_version,
        "fixture_count": len(suite["scenarios"]),
        "fixture_checksum_sha256": _checksum(suite_path),
        "inserted": inserted,
        "replayed": replayed,
        "operational_side_effect_counts": {
            "recommendations": 0,
            "decisions": 0,
            "work_orders": 0,
            "maintenance_actions": 0,
            "maintenance_events": 0,
        },
        "claim_boundary": "Gold 8/8 is engineering acceptance evidence only, not field or business impact validation.",
        "fixture_recommendations": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output", default="evaluation/results/recommendation-policy-v1.json")
    parser.add_argument("--policy-version", default=POLICY_VERSION)
    args = parser.parse_args()
    root = Path(args.root)
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    result = seed_gold_recommendations(root, output=output, policy_version=args.policy_version)
    print(json.dumps({k: v for k, v in result.items() if k != "fixture_recommendations"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
