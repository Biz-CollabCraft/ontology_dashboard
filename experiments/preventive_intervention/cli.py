"""CLI for deterministic preventive-intervention experiment outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .risk_rise import (
    detect_risk_rise_events,
    load_prediction_timeline,
    load_risk_rise_policy,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("experiments/preventive_intervention/policies/risk-rise-detection-v1.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    timeline = args.timeline.resolve()
    output = args.output.resolve()
    if timeline == output:
        raise ValueError("output must not overwrite the source Prediction Timeline")

    policy = load_risk_rise_policy(args.policy)
    events = detect_risk_rise_events(load_prediction_timeline(timeline), policy)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(
            json.dumps(event.model_dump(mode="json"), ensure_ascii=False) + "\n"
            for event in events
        ),
        encoding="utf-8",
    )
    print(f"generated {len(events)} risk-rise events at {output}")


if __name__ == "__main__":
    main()
