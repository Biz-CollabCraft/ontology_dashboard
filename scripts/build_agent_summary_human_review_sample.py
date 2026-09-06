from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a human review worksheet from an Agent Review Summary eval artifact."
    )
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--selection-iteration", type=int, default=1)
    args = parser.parse_args()

    artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
    selected = _selected_rows(artifact.get("rows") or [], iteration=args.selection_iteration)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(_render(artifact, selected, args), encoding="utf-8")


def _selected_rows(rows: list[dict[str, Any]], *, iteration: int) -> list[dict[str, Any]]:
    selected = [
        row
        for row in rows
        if int(row.get("iteration") or 0) == iteration
    ]
    return sorted(selected, key=lambda row: str(row.get("scenario_id") or row.get("case_id") or ""))


def _render(artifact: dict[str, Any], rows: list[dict[str, Any]], args: argparse.Namespace) -> str:
    now = datetime.now(UTC).date().isoformat()
    lines = [
        "# Agent Summary Human Review Sample",
        "",
        "## Review identity",
        "",
        f"- Campaign run ID: `{artifact.get('run_id')}`",
        f"- Candidate SHA: `{artifact.get('candidate_sha')}`",
        f"- Provider/model: `{artifact.get('provider')} / {artifact.get('model')}`",
        f"- Source artifact: `{args.artifact}`",
        f"- Eval set: `{artifact.get('eval_set_id')}`",
        f"- Selection rule: each case's output at `iteration={args.selection_iteration}`",
        "- Review status: **not_measured**",
        f"- Worksheet generated: `{now}`",
        "- Reviewer/date: `________________ / ________________`",
        "",
        "This review is an independent human gate. Automated gold, usefulness, and Korean-quality scores are triage signals only.",
        "",
        "## Decision rule",
        "",
        "For every case, record:",
        "",
        "1. **Usable without edit**: yes only if the copy can be shown to its intended role unchanged.",
        "2. **Incorrect required fact**: quote the incorrect fact, or write `none`.",
        "3. **Awkward Korean**: quote the phrase, or write `none`.",
        "4. **Role mismatch**: describe information or action assigned to the wrong role, or write `none`.",
        "5. **PM boundary check**: confirm production impact, lost units, approval review, and data-quality-hold uncertainty.",
        "6. **Heuristic agreement**: whether automated gold/usefulness/Korean pass agrees with human judgment.",
        "",
        "The human gate passes only when all rows are completed and the reviewer explicitly records the disposition.",
        "",
        "## Selected outputs",
        "",
    ]
    for row in rows:
        output = row.get("editable_output") or {}
        role_quotes = {
            item.get("role"): item.get("quote")
            for item in output.get("role_summaries") or []
            if isinstance(item, dict)
        }
        gold = row.get("gold_accuracy") or {}
        pm_score = ((gold.get("role_scores") or {}).get("process_manager") or {}).get("score")
        lines.extend(
            [
                f"### {row.get('scenario_id') or row.get('case_id')} · {row.get('asset_id')}",
                "",
                f"- Title: {output.get('title')}",
                f"- Summary: {output.get('summary')}",
                f"- Field operator: {role_quotes.get('field_operator')}",
                f"- Process manager: {role_quotes.get('process_manager')}",
                f"- Automated gold: `{gold.get('accuracy_goldset_score')}` · PM: `{pm_score}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Reviewer worksheet",
            "",
            "| Case | Usable without edit (Y/N) | Incorrect required fact | Awkward Korean | Role mismatch | PM boundary check | Heuristic agreement (Y/N) | Comment |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    for row in rows:
        lines.append(
            f"| {row.get('scenario_id') or row.get('case_id')} |  |  |  |  |  |  |  |"
        )
    lines.extend(
        [
            "",
            "## Reviewer disposition",
            "",
            f"- Completed rows: `__/{len(rows)}`",
            f"- Usable without edit: `__/{len(rows)}`",
            "- Incorrect required facts: `__`",
            "- Awkward Korean cases: `__`",
            "- Role mismatch cases: `__`",
            "- PM boundary failures: `__`",
            "- Human gate: `not_measured / passed / failed`",
            "- Reviewer rationale:",
            "",
            ">",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
