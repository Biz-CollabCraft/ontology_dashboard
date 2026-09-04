#!/usr/bin/env python3
"""Evaluate Agent Review reliability through real service and isolated SQLite paths."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "systems" / "backend"
for import_root in (ROOT, BACKEND):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from scripts.eval_support.agent_workflow_stability import (  # noqa: E402
    aggregate_stability_evaluation,
    stability_evaluation_row,
)
from app.dependencies import build_manufacturing_service  # noqa: E402
from app.operations.agent_review_summary import compose_deterministic_agent_review_summary  # noqa: E402
from app.operations.agent_review_summary_materialization import (  # noqa: E402
    summary_key,
    summary_key_payload,
)
from app.operations.agent_review_summary_workflow import AgentReviewSummaryWorkflow  # noqa: E402
from app.operations.operational_context_contract import OperationalRequestIdentity  # noqa: E402
from app.operations.operational_context_ports import (  # noqa: E402
    FixtureMaintenanceReadinessContextReadPort,
    FixtureProductionDecisionContextReadPort,
    FixtureQualityDeliveryContextReadPort,
)
from app.operations.operational_context_sqlite import (  # noqa: E402
    OPERATIONAL_CONTEXT_SNAPSHOT_DDL,
    SqliteOperationalContextReadPort,
)
from app.operations.operational_decision_agent import (  # noqa: E402
    BoundedOperationalDecisionAgent,
    OperationalAgentIntent,
    OperationalAgentRequest,
)
from app.operations.operational_impact_simulation import (  # noqa: E402
    ImpactOption,
    ImpactSimulationAssumptions,
)
from app.operations.service import AGENT_REVIEW_RUNNING_LEASE_SECONDS  # noqa: E402

ASSET_ID = "CNC-S04-L04-01"
PROJECT_ID = "manufacturing-demo-project"
ORGANIZATION_ID = "org-ontology-demo"
WORKSPACE_ID = "manufacturing-demo"
OPERATIONAL_ASSET_ID = "CNC-S04-L02-03"
FIXTURE_ROOT = ROOT / "data" / "fixtures" / "operation_context"
RETRIEVED_AT = datetime(2026, 9, 2, 2, tzinfo=timezone.utc)
VALIDATED_AT = RETRIEVED_AT + timedelta(seconds=3)
REQUIRED_SCENARIOS = {
    "normal_creation",
    "stored_reuse",
    "active_conflict",
    "provider_timeout",
    "external_context_timeout",
    "external_context_malformed",
    "external_context_not_connected",
    "invalid_output",
    "stale_recovery",
    "retry_exhausted",
    "snapshot_mismatch",
}


class SummaryProvider:
    name = "reliability-eval-provider"

    def __init__(self, behavior: str = "valid") -> None:
        self.behavior = behavior
        self.calls = 0

    def generate(self, packet: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if self.behavior == "timeout":
            raise TimeoutError("injected provider timeout")
        if self.behavior == "invalid":
            return {
                **compose_deterministic_agent_review_summary(packet),
                "mode": "llm",
                "create_work_order": True,
            }
        return {
            **compose_deterministic_agent_review_summary(packet),
            "mode": "llm",
            "title": "Reliability evaluation summary",
        }


class FailingPort:
    def __init__(self, owner_domain: str, exc: BaseException) -> None:
        self.owner_domain = owner_domain
        self.exc = exc
        self.calls = 0

    def lookup(self, *, identity: Any, retrieved_at: datetime) -> Any:
        self.calls += 1
        raise self.exc


class ChangingVersionPort:
    owner_domain = "production"

    def __init__(self, wrapped: Any) -> None:
        self.wrapped = wrapped
        self.calls = 0

    def lookup(self, *, identity: Any, retrieved_at: datetime) -> Any:
        self.calls += 1
        result = self.wrapped.lookup(identity=identity, retrieved_at=retrieved_at)
        if self.calls > 1:
            return result.model_copy(update={"source_version": "db-production-changed"})
        return result


def _service(database: Path, behavior: str = "valid") -> tuple[Any, SummaryProvider]:
    service = build_manufacturing_service(database, root=ROOT)
    provider = SummaryProvider(behavior)
    service.agent_review_summary_provider = provider
    return service, provider


def _counts(database: Path) -> dict[str, int]:
    with sqlite3.connect(database) as connection:
        return {
            "summaries": int(connection.execute("SELECT COUNT(*) FROM agent_review_summaries").fetchone()[0]),
            "workflow_runs": int(connection.execute("SELECT COUNT(*) FROM agent_review_workflow_runs").fetchone()[0]),
            "work_orders": int(connection.execute("SELECT COUNT(*) FROM closed_loop_work_orders").fetchone()[0]),
            "commands": int(connection.execute("SELECT COUNT(*) FROM ontology_action_invocations").fetchone()[0]),
        }


def _trace_ref(database: Path, *, summary_ids: list[str] | None = None, workflow_run_ids: list[str] | None = None, context_source_refs: list[str] | None = None) -> dict[str, Any]:
    return {
        "backend": "sqlite",
        "database": str(database),
        "summary_ids": summary_ids or [],
        "workflow_run_ids": workflow_run_ids or [],
        "context_source_refs": context_source_refs or [],
    }


def _summary_identity(service: Any) -> tuple[dict[str, Any], dict[str, Any], str]:
    packet = service.agent_review_packet(ASSET_ID)
    payload = summary_key_payload(
        packet=packet,
        organization_id=ORGANIZATION_ID,
        project_id=PROJECT_ID,
        workspace_id=WORKSPACE_ID,
        history_window="24h",
        provider=service.agent_review_summary_provider,
    )
    return packet, payload, summary_key(payload)


def _run_record(packet: dict[str, Any], payload: dict[str, Any], key: str, *, started_at: str | None = None) -> dict[str, Any]:
    record = {
        "trigger": "reliability_evaluation",
        "engine": "simple",
        "status": "running",
        "organization_id": ORGANIZATION_ID,
        "project_id": PROJECT_ID,
        "workspace_id": WORKSPACE_ID,
        "asset_id": packet["asset_id"],
        "event_id": payload["event_id"],
        "dataset_version_id": payload["dataset_version"],
        "history_window": "24h",
        "summary_key": key,
        "source_sha256": payload["source_sha256"],
        "context_sha256": payload["context_sha256"],
        "packet_schema_version": payload["packet_schema_version"],
        "prompt_version": payload["prompt_version"],
        "model_version": payload["model_version"],
        "trace": {"stage": "started", "evaluation": True},
    }
    if started_at is not None:
        record["started_at"] = started_at
    return record


def _row_from_summary(
    *,
    case_id: str,
    database: Path,
    before: dict[str, int],
    after: dict[str, int],
    trace: dict[str, Any],
    latency_ms: float,
    provider_mode: str,
    provider_calls: int,
    run_status: str | None = None,
    reused: bool | None = None,
    stale_recovered: bool = False,
) -> dict[str, Any]:
    materialization = trace["materialization"]
    workflow = trace.get("workflow_run") or {}
    status = run_status or (
        "fallback" if materialization["status"] == "fallback"
        else "reused" if materialization["reused"]
        else "created"
    )
    is_fallback = status == "fallback"
    return stability_evaluation_row(
        case_id=case_id,
        scenario=case_id,
        iteration=1,
        provider_mode=provider_mode,
        summary_key=materialization["summary_key"],
        workflow_run_id=workflow.get("workflow_run_id") or materialization.get("workflow_run_id"),
        run_status=status,
        reused=materialization["reused"] if reused is None else reused,
        fallback=is_fallback,
        fallback_reason=materialization.get("fallback_reason") if is_fallback else None,
        validation_errors=trace.get("validation_errors") or [],
        attempt_count=1,
        stale_recovered=stale_recovered,
        summary_count_before=before["summaries"],
        summary_count_after=after["summaries"],
        work_order_count_before=before["work_orders"],
        work_order_count_after=after["work_orders"],
        command_count_before=before["commands"],
        command_count_after=after["commands"],
        latency_ms=latency_ms,
        db_trace_ref=_trace_ref(
            database,
            summary_ids=[materialization["summary_id"]] if materialization.get("summary_id") else [],
            workflow_run_ids=[workflow.get("workflow_run_id") or materialization.get("workflow_run_id")] if (workflow.get("workflow_run_id") or materialization.get("workflow_run_id")) else [],
        ),
        evidence_identity_consistent=True,
        context_versions_consistent=True,
        provider_call_count=provider_calls,
    )


def _summary_scenarios(runtime_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    database = runtime_dir / "normal-and-reuse.sqlite3"
    service, provider = _service(database)
    before = _counts(database)
    started = time.perf_counter()
    _, first_trace = service.agent_review_summary(ASSET_ID)
    after = _counts(database)
    rows.append(_row_from_summary(
        case_id="normal_creation",
        database=database,
        before=before,
        after=after,
        trace=first_trace,
        latency_ms=(time.perf_counter() - started) * 1000,
        provider_mode="controlled_valid",
        provider_calls=provider.calls,
    ))
    reuse_before = _counts(database)
    started = time.perf_counter()
    _, reuse_trace = service.agent_review_summary(ASSET_ID)
    reuse_after = _counts(database)
    rows.append(_row_from_summary(
        case_id="stored_reuse",
        database=database,
        before=reuse_before,
        after=reuse_after,
        trace=reuse_trace,
        latency_ms=(time.perf_counter() - started) * 1000,
        provider_mode="controlled_valid",
        provider_calls=provider.calls,
        run_status="reused",
        reused=True,
    ))

    for case_id, behavior in (("provider_timeout", "timeout"), ("invalid_output", "invalid")):
        database = runtime_dir / f"{case_id}.sqlite3"
        service, provider = _service(database, behavior)
        before = _counts(database)
        started = time.perf_counter()
        _, trace = service.agent_review_summary(ASSET_ID)
        after = _counts(database)
        row = _row_from_summary(
            case_id=case_id,
            database=database,
            before=before,
            after=after,
            trace=trace,
            latency_ms=(time.perf_counter() - started) * 1000,
            provider_mode=f"controlled_{behavior}",
            provider_calls=provider.calls,
        )
        rows.append(row)

    database = runtime_dir / "active-conflict.sqlite3"
    service, _ = _service(database)
    packet, payload, key = _summary_identity(service)
    active = service.repository.create_agent_review_workflow_run(**_run_record(packet, payload, key))
    before = _counts(database)
    started = time.perf_counter()
    try:
        service.agent_review_summary(ASSET_ID)
        raise AssertionError("active conflict unexpectedly materialized")
    except RuntimeError as exc:
        if "materialization_in_progress" not in str(exc):
            raise
    after = _counts(database)
    preserved = service.repository.get_agent_review_workflow_run(active["workflow_run_id"])
    rows.append(stability_evaluation_row(
        case_id="active_conflict",
        iteration=1,
        provider_mode="controlled_valid",
        summary_key=key,
        workflow_run_id=active["workflow_run_id"],
        run_status="running_conflict",
        running_conflict=True,
        attempt_count=1,
        summary_count_before=before["summaries"],
        summary_count_after=after["summaries"],
        work_order_count_before=before["work_orders"],
        work_order_count_after=after["work_orders"],
        command_count_before=before["commands"],
        command_count_after=after["commands"],
        latency_ms=(time.perf_counter() - started) * 1000,
        db_trace_ref=_trace_ref(database, workflow_run_ids=[active["workflow_run_id"]]),
        evidence_identity_consistent=True,
        context_versions_consistent=True,
        validation_errors=[] if preserved and preserved["status"] == "running" else ["active_run_not_preserved"],
    ))

    database = runtime_dir / "stale-recovery.sqlite3"
    service, _ = _service(database)
    packet, payload, key = _summary_identity(service)
    old_started_at = (
        datetime.now(timezone.utc)
        - timedelta(seconds=AGENT_REVIEW_RUNNING_LEASE_SECONDS + 30)
    ).isoformat()
    stale = service.repository.create_agent_review_workflow_run(
        **_run_record(packet, payload, key, started_at=old_started_at)
    )
    before = _counts(database)
    started = time.perf_counter()
    _, trace = service.agent_review_summary(ASSET_ID)
    after = _counts(database)
    recovered = _row_from_summary(
        case_id="stale_recovery",
        database=database,
        before=before,
        after=after,
        trace=trace,
        latency_ms=(time.perf_counter() - started) * 1000,
        provider_mode="controlled_valid",
        provider_calls=1,
        stale_recovered=True,
    )
    recovered["db_trace_ref"]["workflow_run_ids"].insert(0, stale["workflow_run_id"])
    expired = service.repository.get_agent_review_workflow_run(stale["workflow_run_id"])
    if not expired or expired["error_type"] != "stale_running_lease_expired":
        recovered["validation_errors"].append("stale_run_not_expired")
    rows.append(recovered)

    database = runtime_dir / "retry-exhausted.sqlite3"
    service, _ = _service(database)
    before = _counts(database)

    def unavailable_repository(**record: Any) -> dict[str, Any]:
        raise OSError("injected repository outage")

    service.repository.create_agent_review_workflow_run = unavailable_repository
    started = time.perf_counter()
    result = AgentReviewSummaryWorkflow(service).run(
        limit=1,
        trigger="reliability_evaluation",
        max_attempts=2,
    )
    after = _counts(database)
    rows.append(stability_evaluation_row(
        case_id="retry_exhausted",
        iteration=1,
        provider_mode="controlled_valid",
        summary_key=None,
        workflow_run_id=None,
        run_status="failed",
        attempt_count=result["workflow"]["attempt_count"],
        retry_count=max(0, result["workflow"]["attempt_count"] - 1),
        retry_exhausted=True,
        validation_errors=[
            attempt["error_type"]
            for attempt in result["workflow"]["attempts"]
            if attempt["status"] == "failed"
        ],
        summary_count_before=before["summaries"],
        summary_count_after=after["summaries"],
        work_order_count_before=before["work_orders"],
        work_order_count_after=after["work_orders"],
        command_count_before=before["commands"],
        command_count_after=after["commands"],
        latency_ms=(time.perf_counter() - started) * 1000,
        db_trace_ref=_trace_ref(database),
        evidence_identity_consistent=True,
        context_versions_consistent=True,
    ))
    return rows


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _operational_identity() -> OperationalRequestIdentity:
    return OperationalRequestIdentity(
        organization_id="ORG-001",
        project_id=PROJECT_ID,
        workspace_id=WORKSPACE_ID,
        asset_id=OPERATIONAL_ASSET_ID,
        evidence_snapshot_id="ARTIFACT-GS-004",
        decision_as_of=datetime(2026, 9, 2, 1, tzinfo=timezone.utc),
    )


def _operational_request() -> OperationalAgentRequest:
    return OperationalAgentRequest(
        identity=_operational_identity(),
        actor_role="process_manager",
        intent=OperationalAgentIntent.MAINTENANCE_TIMING_DECISION,
        risk_status="critical",
    )


def _assumptions() -> ImpactSimulationAssumptions:
    return ImpactSimulationAssumptions(
        policy_version="operational-impact-demo-v1",
        primary_capacity_units={
            ImpactOption.STOP_NOW: 0,
            ImpactOption.PLANNED_MAINTENANCE: 120,
            ImpactOption.CONTINUE_OPERATION: 200,
        },
        alternative_capacity_allowed={
            ImpactOption.STOP_NOW: True,
            ImpactOption.PLANNED_MAINTENANCE: True,
            ImpactOption.CONTINUE_OPERATION: False,
        },
        source_refs=("policy:operational-impact-demo-v1",),
    )


def _insert_context(database: Path, *, owner_domain: str, source_version: str, payload: dict[str, Any]) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO operational_context_snapshot (
                owner_domain, organization_id, project_id, workspace_id,
                asset_id, source_version, source_updated_at, valid_from,
                valid_to, source_ref, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                owner_domain,
                "ORG-001",
                PROJECT_ID,
                WORKSPACE_ID,
                OPERATIONAL_ASSET_ID,
                source_version,
                (RETRIEVED_AT - timedelta(seconds=10)).isoformat(),
                datetime(2026, 9, 1, tzinfo=timezone.utc).isoformat(),
                datetime(2026, 9, 4, tzinfo=timezone.utc).isoformat(),
                f"sqlite:operational_context_snapshot/{source_version}",
                json.dumps(payload, ensure_ascii=False),
            ),
        )


def _operational_database(database: Path) -> dict[str, Any]:
    build_manufacturing_service(database, root=ROOT)
    with sqlite3.connect(database) as connection:
        connection.executescript(OPERATIONAL_CONTEXT_SNAPSHOT_DDL)

    maintenance = _load_fixture("maintenance-readiness-context-v1.json")
    maintenance["inventory_snapshots"][0]["reserved_quantity"] = 0
    maintenance["inventory_snapshots"][0]["available_quantity"] = 2
    quality = _load_fixture("quality-delivery-context-v1.json")
    quality["quality_lots"][1]["quality_state"] = "released"
    quality["quality_lots"][1]["release_required"] = False
    fixture_ports = {
        "production": FixtureProductionDecisionContextReadPort(
            context=_load_fixture("operational-decision-context-v1.json"),
            source_ref="fixture:production",
        ),
        "maintenance_readiness": FixtureMaintenanceReadinessContextReadPort(
            context=maintenance,
            source_ref="fixture:maintenance",
        ),
        "quality_delivery": FixtureQualityDeliveryContextReadPort(
            context=quality,
            source_ref="fixture:quality",
        ),
    }
    identity = _operational_identity()
    for domain, port in fixture_ports.items():
        envelope = port.lookup(identity=identity, retrieved_at=RETRIEVED_AT)
        _insert_context(
            database,
            owner_domain=domain,
            source_version=f"db-{domain}-1",
            payload=envelope.data,
        )
    return {
        domain: SqliteOperationalContextReadPort(
            database_path=database,
            owner_domain=domain,
            freshness_policy_version=f"{domain}-db-v1",
            max_age_seconds=3600,
        )
        for domain in fixture_ports
    }


def _operational_row(
    *,
    case_id: str,
    database: Path,
    ports: dict[str, Any],
    external_reason: str | None = None,
) -> dict[str, Any]:
    before = _counts(database)
    started = time.perf_counter()
    result = BoundedOperationalDecisionAgent(
        ports=ports,
        impact_assumptions=_assumptions(),
    ).run(
        request=_operational_request(),
        retrieved_at=RETRIEVED_AT,
        validated_at=VALIDATED_AT,
    )
    after = _counts(database)
    steps = [step.model_dump(mode="json") for step in result.trajectory]
    source_refs = [
        ref
        for envelope in result.contexts.values()
        for ref in envelope.source_refs
    ]
    relevant_gap = next(
        (
            gap for gap in result.gaps
            if external_reason and (
                gap.get("fallback_reason") == external_reason
                or gap.get("status") == "not_connected"
            )
        ),
        {},
    )
    mismatch = result.temporal_validation.get("valid") is False
    blocked = case_id == "snapshot_mismatch" and mismatch
    fallback = external_reason is not None
    return stability_evaluation_row(
        case_id=case_id,
        iteration=1,
        provider_mode="not_applicable",
        summary_key=None,
        workflow_run_id=None,
        run_status="blocked" if blocked else "fallback" if fallback else "created",
        fallback=fallback,
        fallback_reason=external_reason if fallback else None,
        external_api_status=(
            "not_connected"
            if external_reason == "external_api_not_connected"
            else "failed" if external_reason else None
        ),
        external_api_fallback_reason=external_reason,
        attempt_count=max(
            (int(step.get("attempt_count") or 0) for step in steps),
            default=0,
        ),
        retry_count=max(0, int(relevant_gap.get("attempt_count") or 1) - 1),
        blocked_side_effect=blocked,
        validation_errors=[
            str(item.get("reason") or item.get("domain") or "snapshot_mismatch")
            for item in result.temporal_validation.get("mismatches") or []
        ],
        summary_count_before=before["summaries"],
        summary_count_after=after["summaries"],
        work_order_count_before=before["work_orders"],
        work_order_count_after=after["work_orders"],
        command_count_before=before["commands"],
        command_count_after=after["commands"],
        latency_ms=(time.perf_counter() - started) * 1000,
        db_trace_ref=_trace_ref(database, context_source_refs=source_refs),
        evidence_identity_consistent=(
            result.identity.model_dump(mode="json")
            == _operational_request().identity.model_dump(mode="json")
        ),
        context_versions_consistent=bool(result.temporal_validation.get("valid")),
    )


def _operational_scenarios(runtime_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    database = runtime_dir / "external-timeout.sqlite3"
    ports = _operational_database(database)
    ports["production"] = FailingPort(
        "production",
        TimeoutError("injected external production timeout"),
    )
    rows.append(_operational_row(
        case_id="external_context_timeout",
        database=database,
        ports=ports,
        external_reason="external_api_timeout",
    ))

    database = runtime_dir / "external-malformed.sqlite3"
    ports = _operational_database(database)
    ports["quality_delivery"] = FailingPort(
        "quality_delivery",
        ValueError("missing source_version"),
    )
    rows.append(_operational_row(
        case_id="external_context_malformed",
        database=database,
        ports=ports,
        external_reason="external_api_malformed_response",
    ))

    database = runtime_dir / "external-not-connected.sqlite3"
    ports = _operational_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM operational_context_snapshot WHERE owner_domain=?",
            ("maintenance_readiness",),
        )
    rows.append(_operational_row(
        case_id="external_context_not_connected",
        database=database,
        ports=ports,
        external_reason="external_api_not_connected",
    ))

    database = runtime_dir / "snapshot-mismatch.sqlite3"
    ports = _operational_database(database)
    ports["production"] = ChangingVersionPort(ports["production"])
    rows.append(_operational_row(
        case_id="snapshot_mismatch",
        database=database,
        ports=ports,
    ))
    return rows


def run_evaluation(
    *,
    candidate_sha: str,
    run_id: str,
    runtime_dir: Path,
) -> dict[str, Any]:
    runtime_dir.mkdir(parents=True, exist_ok=False)
    rows = _summary_scenarios(runtime_dir) + _operational_scenarios(runtime_dir)
    aggregate = aggregate_stability_evaluation(rows)
    scenarios = {row["scenario"] for row in rows}
    external_reasons = {
        row["external_api_fallback_reason"]
        for row in rows
        if row["external_api_fallback_reason"]
    }
    acceptance = {
        "all_required_scenarios_measured": scenarios == REQUIRED_SCENARIOS,
        "real_service_and_sqlite_trace_present": all(
            row["db_trace_ref"].get("backend") == "sqlite"
            and row["db_trace_ref"].get("database")
            for row in rows
        ),
        "normal_summary_and_run_persisted": next(
            row for row in rows if row["case_id"] == "normal_creation"
        )["summary_count_after"] == 1,
        "stored_reuse_did_not_call_or_write": (
            next(row for row in rows if row["case_id"] == "stored_reuse")["summary_count_before"]
            == next(row for row in rows if row["case_id"] == "stored_reuse")["summary_count_after"]
            and next(row for row in rows if row["case_id"] == "normal_creation")["provider_call_count"]
            == next(row for row in rows if row["case_id"] == "stored_reuse")["provider_call_count"]
            == 1
        ),
        "active_conflict_isolated": aggregate["counts"]["active_running_conflict"] == 1,
        "stale_recovery_distinct": aggregate["counts"]["stale_recovered"] == 1,
        "provider_fallbacks_persisted": all(
            row["summary_count_after"] == 1
            for row in rows
            if row["case_id"] in {"provider_timeout", "invalid_output"}
        ),
        "retry_is_bounded": aggregate["counts"]["bounded_retry_exhausted"] == 1,
        "external_failures_distinguished": external_reasons == {
            "external_api_timeout",
            "external_api_malformed_response",
            "external_api_not_connected",
        },
        "snapshot_mismatch_blocked": next(
            row for row in rows if row["case_id"] == "snapshot_mismatch"
        )["blocked_side_effect"],
        "side_effect_counts_unchanged": aggregate["rates"]["side_effect_unchanged"] == 1.0,
        "identity_consistent": all(
            row["evidence_identity_consistent"] is not False for row in rows
        ),
        "unmeasured_token_and_cost_explicit": all(
            row["measurements"]["input_tokens"]["status"] == "not_measured"
            and row["measurements"]["cost_usd"]["status"] == "not_measured"
            for row in rows
        ),
    }
    return {
        "schema_version": "agent-workflow-reliability-evaluation-v1.0",
        "run_id": run_id,
        "candidate_sha": candidate_sha,
        "evaluation_mode": "integration",
        "database_backend": "isolated_sqlite",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scenario_count": len(rows),
        "rows": rows,
        "aggregate": aggregate,
        "acceptance": acceptance,
        "passed": all(acceptance.values()),
        "claim_boundary": {
            "production_reliability_proven": False,
            "live_llm_quality_measured": False,
            "statement": "Isolated SQLite service/repository integration evidence; not production load evidence.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run service/SQLite Agent Workflow reliability evaluation."
    )
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--run-id", default=f"agent-workflow-{uuid.uuid4().hex[:12]}")
    parser.add_argument("--runtime-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    runtime_dir = args.runtime_dir or (
        ROOT / "tests" / "eval" / "runtime" / args.run_id
    )
    result = run_evaluation(
        candidate_sha=args.candidate_sha,
        run_id=args.run_id,
        runtime_dir=runtime_dir,
    )
    output = args.output or (
        ROOT
        / "tests"
        / "eval"
        / "results"
        / f"agent_workflow_reliability_{args.run_id}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(output),
        "runtime_dir": str(runtime_dir),
        "run_id": result["run_id"],
        "candidate_sha": result["candidate_sha"],
        "scenario_count": result["scenario_count"],
        "acceptance": result["acceptance"],
        "passed": result["passed"],
    }, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
