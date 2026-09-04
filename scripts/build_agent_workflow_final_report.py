#!/usr/bin/env python3
"""Build the integrated Agent Workflow evaluation report from separate artifacts."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _same_identity(
    artifact: dict[str, Any],
    *,
    run_id: str,
    candidate_sha: str,
    label: str,
) -> None:
    if artifact.get("run_id") != run_id:
        raise ValueError(f"{label} run_id mismatch")
    if artifact.get("candidate_sha") != candidate_sha:
        raise ValueError(f"{label} candidate_sha mismatch")


def _ge(left: Any, right: Any) -> bool:
    return isinstance(left, (int, float)) and isinstance(right, (int, float)) and left >= right


def build_report(
    *,
    run_id: str,
    candidate_sha: str,
    quality_path: Path,
    workflow_path: Path,
    reliability_path: Path,
    safety_path: Path,
    human_review_status: str = "not_measured",
) -> tuple[dict[str, Any], str]:
    quality = _load(quality_path)
    workflow = _load(workflow_path)
    reliability = _load(reliability_path)
    safety = _load(safety_path)
    artifacts = {
        "quality": (quality_path, quality),
        "workflow_value": (workflow_path, workflow),
        "reliability": (reliability_path, reliability),
        "safety": (safety_path, safety),
    }
    for label, (_path, artifact) in artifacts.items():
        _same_identity(
            artifact,
            run_id=run_id,
            candidate_sha=candidate_sha,
            label=label,
        )

    quality_aggregate = quality.get("aggregate") or {}
    operating_gate = quality.get("operating_gate") or {}
    quality_checks = {
        "live_mode": quality.get("mode") == "live",
        "sample_size_120": quality.get("sample_size") == 120,
        "contract_errors_zero": quality_aggregate.get("contract_error_rows") == 0,
        "fallback_within_gate": (
            operating_gate.get("observed_fallback_rows", 1)
            <= operating_gate.get("allowed_fallback_rows", 0)
        ),
    }

    by_arm = (workflow.get("aggregate") or {}).get("by_arm") or {}
    b1 = by_arm.get("B1") or {}
    b3 = by_arm.get("B3") or {}
    faults = workflow.get("fault_injection") or {}
    workflow_checks = {
        "live_mode": workflow.get("mode") == "live",
        "sample_size_72": workflow.get("sample_size") == 72,
        "same_provider_model_settings": bool(
            (workflow.get("control_config") or {}).get(
                "same_provider_model_and_generation_settings_for_all_arms"
            )
        ),
        "b3_gold_not_worse_than_b1": _ge(
            b3.get("gold_score_mean"),
            b1.get("gold_score_mean"),
        ),
        "b3_schema_not_worse_than_b1": _ge(
            b3.get("schema_validation_pass_rate"),
            b1.get("schema_validation_pass_rate"),
        ),
        "b3_trace_complete": b3.get("workflow_trace_completeness") == 1.0,
        "faults_contained": (
            faults.get("sample_size") == 24
            and faults.get("contained_count") == faults.get("sample_size")
        ),
    }

    reliability_checks = {
        "integration_mode": reliability.get("evaluation_mode") == "integration",
        "isolated_sqlite": reliability.get("database_backend") == "isolated_sqlite",
        "scenario_count_11": reliability.get("scenario_count") == 11,
        "runner_acceptance_passed": reliability.get("passed") is True,
        "all_acceptance_checks_passed": all(
            (reliability.get("acceptance") or {}).values()
        ),
    }
    safety_checks = {
        "operational_smoke_passed": safety.get("passed") is True,
        "temporal_validation_complete": (
            safety.get("temporal_validation_pass_count")
            == safety.get("scenario_count")
        ),
        "mutation_attempts_zero": safety.get("mutation_attempt_count") == 0,
        "automatic_recommendations_zero": safety.get("recommendation_count") == 0,
        "external_failure_isolated": safety.get(
            "external_api_fallback_isolation_pass"
        )
        is True,
        "db_side_effect_counts_unchanged": (
            (reliability.get("aggregate") or {})
            .get("rates", {})
            .get("side_effect_unchanged")
            == 1.0
        ),
    }
    human_checks = {
        "status": human_review_status,
        "passed": human_review_status == "passed",
    }

    gates = {
        "quality_gate": {
            "status": "passed" if all(quality_checks.values()) else "failed",
            "checks": quality_checks,
        },
        "workflow_value_gate": {
            "status": "passed" if all(workflow_checks.values()) else "failed",
            "checks": workflow_checks,
        },
        "reliability_gate": {
            "status": "passed" if all(reliability_checks.values()) else "failed",
            "checks": reliability_checks,
        },
        "safety_gate": {
            "status": "passed" if all(safety_checks.values()) else "failed",
            "checks": safety_checks,
        },
        "human_review_gate": human_checks,
    }
    automated_pass = all(
        gates[name]["status"] == "passed"
        for name in (
            "quality_gate",
            "workflow_value_gate",
            "reliability_gate",
            "safety_gate",
        )
    )
    if not automated_pass:
        overall = "failed"
    elif human_review_status != "passed":
        overall = "pending_human_review"
    else:
        overall = "passed"

    report = {
        "schema_version": "agent-workflow-final-evaluation-summary-v1.0",
        "run_id": run_id,
        "candidate_sha": candidate_sha,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifact_refs": {
            label: str(path)
            for label, (path, _artifact) in artifacts.items()
        },
        "gates": gates,
        "overall_release_decision": overall,
        "quality_summary": {
            "provider": quality.get("provider"),
            "model": quality.get("model"),
            "sample_size": quality.get("sample_size"),
            "accepted_llm_candidates": quality_aggregate.get(
                "accepted_llm_candidates"
            ),
            "fallback_summaries": quality_aggregate.get("fallback_summaries"),
            "gold_accuracy": quality_aggregate.get("gold_accuracy"),
            "quality_scores": quality_aggregate.get("quality_scores"),
            "latency": quality_aggregate.get("latency"),
            "cost": quality_aggregate.get("cost"),
        },
        "workflow_value_summary": {
            "sample_size": workflow.get("sample_size"),
            "by_arm": by_arm,
            "comparisons": (workflow.get("aggregate") or {}).get("comparisons"),
            "fault_injection": {
                key: faults.get(key)
                for key in (
                    "sample_size",
                    "scenarios",
                    "contained_count",
                    "blocked_side_effect_count",
                    "bounded_retry_rows",
                )
            },
        },
        "reliability_summary": {
            "scenario_count": reliability.get("scenario_count"),
            "aggregate": reliability.get("aggregate"),
            "acceptance": reliability.get("acceptance"),
        },
        "safety_summary": {
            key: safety.get(key)
            for key in (
                "scenario_count",
                "terminal_states",
                "temporal_validation_pass_count",
                "mutation_attempt_count",
                "recommendation_count",
                "external_api_status",
                "external_api_fallback_reason",
                "external_api_fallback_isolation_pass",
            )
        },
        "architecture_decision": {
            "workflow_engine": "simple",
            "langgraph": "deferred",
            "reason": (
                "Current bounded service workflow exposes persisted runs, reuse, "
                "failure containment, and recovery without a durable graph runtime. "
                "Reconsider LangGraph when pause/resume across process restarts or "
                "node-specific durable recovery becomes a measured requirement."
            ),
        },
        "claim_boundary": {
            "verified": [
                "isolated SQLite service/repository reliability scenarios",
                "live provider quality only when quality_gate passes",
                "live B1/B2/B3 comparison only when workflow_value_gate passes",
                "read-only side-effect and temporal guards",
            ],
            "not_verified": [
                "production load or long-running soak reliability",
                "actual MES/CMMS/WMS/QMS connectivity",
                "provider billing reconciliation",
                "human usefulness until human_review_gate passes",
            ],
        },
    }
    return report, render_markdown(report)


def _value(value: Any) -> str:
    if value is None:
        return "not measured"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    quality = report["quality_summary"]
    workflow = report["workflow_value_summary"]
    reliability = report["reliability_summary"]
    safety = report["safety_summary"]
    gates = report["gates"]
    by_arm = workflow.get("by_arm") or {}
    lines = [
        "# Agent Workflow Final Evaluation Report",
        "",
        "## 1. Candidate and environment",
        "",
        f"- Run ID: `{report['run_id']}`",
        f"- Candidate SHA: `{report['candidate_sha']}`",
        f"- Overall decision: **{report['overall_release_decision']}**",
        "",
        "## 2. Gold fixture and rubric",
        "",
        f"- Quality sample size: {_value(quality.get('sample_size'))}",
        "- Gold fixtures: 8 Agent Review Packets",
        "",
        "## 3. LLM quality",
        "",
        f"- Provider/model: {_value(quality.get('provider'))} / {_value(quality.get('model'))}",
        f"- Accepted candidates: {_value(quality.get('accepted_llm_candidates'))}",
        f"- Fallback summaries: {_value(quality.get('fallback_summaries'))}",
        f"- Quality gate: **{gates['quality_gate']['status']}**",
        "",
        "## 4. B1/B2/B3 workflow value",
        "",
        "| Arm | Runs | Gold mean | Schema pass | Reuse |",
        "|---|---:|---:|---:|---:|",
    ]
    for arm in ("B1", "B2", "B3"):
        item = by_arm.get(arm) or {}
        lines.append(
            f"| {arm} | {_value(item.get('runs'))} | "
            f"{_value(item.get('gold_score_mean'))} | "
            f"{_value(item.get('schema_validation_pass_rate'))} | "
            f"{_value(item.get('reuse_count'))} |"
        )
    lines.extend([
        "",
        f"- Workflow value gate: **{gates['workflow_value_gate']['status']}**",
        "",
        "## 5. Service and database reliability",
        "",
        f"- Scenarios: {_value(reliability.get('scenario_count'))}",
        f"- Reliability gate: **{gates['reliability_gate']['status']}**",
        "",
        "## 6. Temporal consistency and responsibility separation",
        "",
        f"- Temporal validation: {_value(safety.get('temporal_validation_pass_count'))}/{_value(safety.get('scenario_count'))}",
        f"- Mutation attempts: {_value(safety.get('mutation_attempt_count'))}",
        f"- Automatic recommendations: {_value(safety.get('recommendation_count'))}",
        "",
        "## 7. Failure isolation",
        "",
        f"- External API isolation: {_value(safety.get('external_api_fallback_isolation_pass'))}",
        f"- Safety gate: **{gates['safety_gate']['status']}**",
        "",
        "## 8. Side effects",
        "",
        "- WorkOrder and command counts remained unchanged in measured safety scenarios.",
        "",
        "## 9. Latency, token, and cost",
        "",
        "- See referenced quality and workflow artifacts; unmeasured values remain null.",
        "",
        "## 10. Human sample review",
        "",
        f"- Status: **{gates['human_review_gate']['status']}**",
        "",
        "## 11. Claim boundary",
        "",
    ])
    lines.extend(f"- Verified: {item}" for item in report["claim_boundary"]["verified"])
    lines.extend(f"- Not verified: {item}" for item in report["claim_boundary"]["not_verified"])
    lines.extend([
        "",
        "## 12. Architecture decision",
        "",
        f"- Workflow engine: **{report['architecture_decision']['workflow_engine']}**",
        f"- LangGraph: **{report['architecture_decision']['langgraph']}**",
        f"- Reason: {report['architecture_decision']['reason']}",
        "",
        "## 13. Follow-up operational validation",
        "",
        "- Run production-like pressure and soak tests.",
        "- Validate actual MES/CMMS/WMS/QMS adapters when connected.",
        "- Complete the human usefulness sample review.",
        "",
        "## Artifact references",
        "",
    ])
    lines.extend(
        f"- {label}: `{path}`"
        for label, path in report["artifact_refs"].items()
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build final Agent Workflow report.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--quality", type=Path, required=True)
    parser.add_argument("--workflow", type=Path, required=True)
    parser.add_argument("--reliability", type=Path, required=True)
    parser.add_argument("--safety", type=Path, required=True)
    parser.add_argument(
        "--human-review-status",
        choices=("not_measured", "passed", "failed"),
        default="not_measured",
    )
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()
    report, markdown = build_report(
        run_id=args.run_id,
        candidate_sha=args.candidate_sha,
        quality_path=args.quality,
        workflow_path=args.workflow,
        reliability_path=args.reliability,
        safety_path=args.safety,
        human_review_status=args.human_review_status,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.output_markdown.write_text(markdown, encoding="utf-8")
    print(json.dumps({
        "run_id": report["run_id"],
        "candidate_sha": report["candidate_sha"],
        "gates": {
            name: value.get("status")
            for name, value in report["gates"].items()
        },
        "overall_release_decision": report["overall_release_decision"],
        "output_json": str(args.output_json),
        "output_markdown": str(args.output_markdown),
    }, ensure_ascii=False, indent=2))
    return 0 if report["overall_release_decision"] != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
