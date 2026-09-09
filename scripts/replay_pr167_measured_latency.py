"""Replay temporal scheduling using measured fixture response delays; projections only."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from scripts.evaluate_agent_review_generation_policy import temporal_snapshots, simulate_scenario, aggregate

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    comparison = json.loads(args.comparison.read_text())
    root = Path(__file__).resolve().parents[1]
    fixture_path = root / "tests/fixtures/agent_review_packets/temporal_policy.json"
    fixture = json.loads(fixture_path.read_text())
    snapshots = list(temporal_snapshots())
    results = {}
    for model in comparison["models"]:
        measured = comparison["aggregate"][model]
        if model not in comparison["selection_gate"]["eligible_models"]:
            results[model] = {"status": "excluded_quality_gate", "direct_pass_rate": measured["hard_gate_pass_rate"]}
            continue
        profiles = {}
        for scenario in fixture["scenarios"]:
            delays = [r["provider_duration_ms"] for r in comparison["rows"]
                      if r["model"] == model and r["case_id"] == "EVT-"+scenario]
            profiles[scenario] = {**fixture["profiles"][scenario],
                "completion_latency_seconds": math.ceil(max(delays)/1000)}
        policies = {}
        for policy in ("click", "always", "hybrid"):
            runs = [simulate_scenario(policy, [s for s in snapshots if s[0]==scenario],
                       fixture["timing"], profiles[scenario]) for scenario in fixture["scenarios"]]
            metrics = aggregate(runs)
            starts = metrics["simulated_background_generations"] + metrics["simulated_refresh_generations"]
            metrics["projected_uncached_list_cost_usd"] = starts * measured["cost"]["estimated_total_cost"] / measured["attempts"]
            metrics["generation_starts"] = starts
            policies[policy] = metrics
        results[model] = {"status": "modeled_with_measured_latency", "profiles": profiles, "policies": policies}
    report = {"evidence_level": "simulation_with_measured_fixture_latency",
              "comparison_sha256": hashlib.sha256(args.comparison.read_bytes()).hexdigest(),
              "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
              "results": results,
              "limits": ["Uses each original fixture case maximum of two measured response delays, rounded up to seconds.",
                         "Changed synthetic packets are not sent to providers; successful validation is assumed.",
                         "Injected failures/backoff remain the fixed temporal fixture model.",
                         "Costs project mean measured usage at uncached list prices to each generation start, including failed starts.",
                         "No production availability or billing savings measurement."]}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(results, ensure_ascii=False))
if __name__=="__main__":
    main()
