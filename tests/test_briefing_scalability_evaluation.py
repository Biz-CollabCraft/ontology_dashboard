from __future__ import annotations

from scripts.evaluate_briefing_scalability import (
    CHANGE_PROFILES,
    load_provider_reference,
    run_matrix,
    evaluate_scenario,
)


def test_provider_reference_preserves_recorded_measurement_boundary() -> None:
    provider = load_provider_reference()

    assert provider.provider
    assert provider.model
    assert len(provider.latency_samples_ms) == 120
    assert len(provider.prompt_token_samples) == 120
    assert len(provider.completion_token_samples) == 120
    assert "recorded live-provider" in provider.latency_basis
    assert "not provider billing usage" in provider.token_basis
    assert provider.cost_status == "not_configured"


def test_scale_matrix_covers_required_assets_profiles_and_repeats() -> None:
    result = run_matrix(repeats=3, challenger_cycles=3)

    assert result["method"]["new_external_provider_calls"] == 0
    assert result["method"]["repeats"] == 3
    assert result["summary"]["scenario_count"] == 9

    covered = {
        (item["asset_count"], item["profile"])
        for item in result["scenarios"]
    }
    assert covered == {
        (asset_count, profile)
        for asset_count in (100, 500, 1000)
        for profile in CHANGE_PROFILES
    }
    assert all(
        item["detection"]["repeat_count"] == 3
        for item in result["scenarios"]
    )


def test_recorded_provider_replay_identifies_serial_provider_bottleneck() -> None:
    provider = load_provider_reference()
    scenario = evaluate_scenario(
        asset_count=1000,
        profile_name="burst_change",
        change_rate=0.50,
        provider=provider,
        repeats=1,
        poll_interval_ms=10_000,
        challenger_workers=8,
        challenger_cycles=6,
    )

    detection = scenario["detection"]
    baseline = scenario["baseline"]
    challenger = scenario["challenger"]

    assert detection["important_event_detection_recall"] == 1.0
    assert detection["generated_count"] == 500
    assert detection["reused_count"] == 500
    assert baseline["poll_deadline_missed"] is True
    assert baseline["projected_backlog_at_deadline"] > 0
    assert (
        challenger["end_to_end_ms"]["p95"]
        < baseline["end_to_end_ms"]["p95"]
    )
    assert challenger["coalesced_candidate_count"] > 0
    assert challenger["dropped_candidate_count"] == 0
    assert challenger["provider_concurrency"] <= 8
    assert (
        challenger["correctness"]["important_event_detection_recall"]
        == 1.0
    )
    assert (
        challenger["correctness"]["snapshot_consistency_rate"]
        == 1.0
    )
    assert (
        challenger["correctness"]["latest_changed_asset_materialized_rate"]
        == 1.0
    )


def test_matrix_does_not_claim_kubernetes_from_provider_queue_projection() -> None:
    result = run_matrix(repeats=1, challenger_cycles=2)

    assert result["summary"]["baseline_poll_deadline_miss_scenarios"] > 0
    assert result["summary"]["primary_bottleneck"] == "provider_queue"
    assert result["summary"]["bounded_queue_worker_split_justified"] is True
    assert result["summary"]["kubernetes_hpa_justified"] is False
