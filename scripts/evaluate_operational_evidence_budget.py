#!/usr/bin/env python3
"""Offline budget sweep; synthetic evidence preservation, not LLM quality."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "systems/backend")]

from scripts.evaluate_operational_evidence_selection import (
    ASSET_ID, DECISION_AS_OF, PROJECT_ID, REQUIRED_EVIDENCE_IDS, RETRIEVED_AT,
)
from app.operations.operational_context_contract import (
    FreshnessMetadata, FreshnessState, OperationalContextStatus, OperationalRequestIdentity,
)
from app.operations.operational_context_ports import (
    FixtureMaintenanceReadinessContextReadPort, FixtureProductionDecisionContextReadPort,
    FixtureQualityDeliveryContextReadPort,
)
from app.operations.operational_evidence_selection import (
    EvidenceSelectionStrategy, evaluate_evidence_selection,
    project_evidence_candidates, select_evidence_candidates,
)
from app.operations.operational_relation_resolver import resolve_operational_relations


def evaluate():
    identity = OperationalRequestIdentity(
        organization_id="ORG-001", project_id=PROJECT_ID, workspace_id="manufacturing-demo",
        asset_id=ASSET_ID, evidence_snapshot_id="ARTIFACT-GS-004", decision_as_of=DECISION_AS_OF,
    )
    supplied = {}
    inputs = {}
    for domain, port, filename in [
        ("production", FixtureProductionDecisionContextReadPort, "operational-decision-context-v1.json"),
        ("maintenance_readiness", FixtureMaintenanceReadinessContextReadPort, "maintenance-readiness-context-v1.json"),
        ("quality_delivery", FixtureQualityDeliveryContextReadPort, "quality-delivery-context-v1.json"),
    ]:
        path = ROOT / "data/fixtures/operation_context" / filename
        inputs[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        supplied[domain] = port(context=json.loads(path.read_text()), source_ref=f"fixture:{domain}").lookup(
            identity=identity, retrieved_at=RETRIEVED_AT,
        )
    scenarios = {"base": supplied}
    for name, limitations in [
        ("production_stale", ("Production snapshot is stale.",)),
        ("production_stale_two_limitations_same_source", (
            "Production snapshot is stale.", "Production order completeness cannot be established.",
        )),
    ]:
        scenarios[name] = {**supplied, "production": supplied["production"].model_copy(update={
            "status": OperationalContextStatus.STALE, "data": {},
            "freshness": FreshnessMetadata(policy_version="budget-stress-v1", max_age_seconds=0, state=FreshnessState.STALE),
            "limitations": limitations,
        })}
    for relative in (
        "systems/backend/app/operations/operational_evidence_selection.py",
        "systems/backend/app/operations/operational_relation_resolver.py",
        "scripts/evaluate_operational_evidence_budget.py",
    ):
        inputs[relative] = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
    results = []
    for name, contexts in scenarios.items():
        relations = resolve_operational_relations(identity=identity, contexts=contexts)
        candidates = project_evidence_candidates(identity=identity, contexts=contexts, relation_resolution=relations)
        full = select_evidence_candidates(candidates, strategy=EvidenceSelectionStrategy.FULL_CONTEXT)
        available_refs = set(full.selected_source_refs)
        required = REQUIRED_EVIDENCE_IDS & available_refs
        boundary_ids = {c.candidate_id for c in full.selected if c.required_for_boundary}
        limitation_ids = {c.candidate_id for c in full.selected if c.candidate_type == "limitation"}
        rows = []
        for role in ("process_manager", "field_operator", "system_admin"):
            for budget in [*range(1, len(full.selected) + 1), None]:
                selected = select_evidence_candidates(candidates, strategy=EvidenceSelectionStrategy.DETERMINISTIC,
                    role=role, max_candidates=budget)
                metrics = evaluate_evidence_selection(full_context=full, selected=selected,
                    required_evidence_ids=required, required_limitation_ids=limitation_ids)
                ids = {c.candidate_id for c in selected.selected}
                repeat = select_evidence_candidates(candidates, strategy=EvidenceSelectionStrategy.DETERMINISTIC,
                    role=role, max_candidates=budget)
                assert selected == repeat
                rows.append({"role": role, "budget": budget, **metrics.model_dump(mode="json"),
                    "missing_boundary_candidate_ids": sorted(boundary_ids - ids),
                    "selected_candidate_ids": [c.candidate_id for c in selected.selected],
                    "selected_source_refs": list(selected.selected_source_refs),
                    "candidate_json_utf8_bytes": len(json.dumps([c.model_dump(mode="json") for c in selected.selected],
                        ensure_ascii=False, sort_keys=True).encode()),
                })
        results.append({"scenario": name, "full_candidate_count": len(full.selected),
            "required_evidence_ids": sorted(required), "unavailable_original_required_refs": sorted(REQUIRED_EVIDENCE_IDS - available_refs),
            "required_limitation_ids": sorted(limitation_ids), "boundary_candidate_ids": sorted(boundary_ids),
            "candidates": [c.model_dump(mode="json") for c in full.selected], "rows": rows})
    return {"mode": "offline_synthetic_budget_sweep", "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "working_tree_status": subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True),
        "input_sha256": inputs, "live_llm": False, "tokens": "not_measured", "llm_latency": "not_measured",
        "human_usefulness": "not_measured", "rubric_scope": "Original process-manager five-reference rubric; other roles are sensitivity checks, not role-specific gold.",
        "scenarios": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    for scenario in result["scenarios"]:
        print(scenario["scenario"], "full=", scenario["full_candidate_count"], "limitations=", len(scenario["required_limitation_ids"]))
        for role in ("process_manager", "field_operator", "system_admin"):
            rows = [r for r in scenario["rows"] if r["role"] == role]
            passing = [r["budget"] for r in rows if r["budget"] is not None and r["required_evidence_recall"] == 1 and not r["missing_boundary_candidate_ids"]]
            print(role, "minimum all-reference/all-boundary budget:", min(passing) if passing else None)
            if role == "process_manager":
                for row in rows:
                    if row["budget"] in (4, 6, 7, 8, 10, 12, None):
                        print({k: row[k] for k in ("budget", "selected_candidate_count", "required_evidence_recall", "required_limitation_preservation", "missing_boundary_candidate_ids", "missing_required_evidence_ids")})
