#!/usr/bin/env python3
"""Compare complete context with original and boundary-preserving selection offline."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "systems/backend")]

from scripts.evaluate_operational_evidence_budget import evaluate as evaluate_inputs
from app.operations.operational_evidence_selection import (
    EvidenceCandidate,
    EvidenceSelectionStrategy,
    _selection_sort_key,
    select_evidence_candidates,
)


def preserve_boundaries(candidates, *, role, budget=8):
    """Experimental policy: preserve every eligible boundary ID, same ranking otherwise.

    No gold references are used in selection. Upstream candidate projection is unchanged.
    """
    ordered = sorted(
        (candidate for candidate in candidates if candidate.eligible),
        key=lambda candidate: _selection_sort_key(candidate, role=role),
    )
    required = [candidate for candidate in ordered if candidate.required_for_boundary]
    optional = [candidate for candidate in ordered if not candidate.required_for_boundary]
    limit = len(ordered) if budget is None else max(budget, len(required))
    return tuple([*required, *optional[: max(0, limit - len(required))]])


def summarize(selected, *, all_candidates, required_refs):
    selected_ids = {candidate.candidate_id for candidate in selected}
    refs = {candidate.source_ref for candidate in selected}
    boundaries = {candidate.candidate_id for candidate in all_candidates if candidate.required_for_boundary}
    limitations = {candidate.candidate_id for candidate in all_candidates if candidate.candidate_type == "limitation"}
    wire = json.dumps([candidate.model_dump(mode="json") for candidate in selected],
                      ensure_ascii=False, sort_keys=True)
    return {
        "selected_count": len(selected),
        "source_refs_preserved": len(required_refs & refs),
        "source_refs_required": len(required_refs),
        "boundary_candidates_preserved": len(boundaries & selected_ids),
        "boundary_candidates_required": len(boundaries),
        "limitation_candidates_preserved": len(limitations & selected_ids),
        "limitation_candidates_required": len(limitations),
        "missing_required_source_refs": sorted(required_refs - refs),
        "missing_boundary_candidate_ids": sorted(boundaries - selected_ids),
        "candidate_json_utf8_bytes": len(wire.encode()),
        "selected_candidate_ids": [candidate.candidate_id for candidate in selected],
    }


def evaluate():
    inputs = evaluate_inputs()
    rows = []
    sweeps = []
    for scenario in inputs["scenarios"]:
        candidates = tuple(EvidenceCandidate.model_validate(item) for item in scenario["candidates"])
        required_refs = set(scenario["required_evidence_ids"])
        for role in ("process_manager", "field_operator", "system_admin"):
            full = select_evidence_candidates(candidates, strategy=EvidenceSelectionStrategy.FULL_CONTEXT).selected
            unlimited = select_evidence_candidates(candidates,
                strategy=EvidenceSelectionStrategy.DETERMINISTIC, role=role, max_candidates=None).selected
            assert {c.candidate_id for c in unlimited} == {c.candidate_id for c in full}
            arms = {
                "full_context": full,
                "original_budget_8": select_evidence_candidates(candidates,
                    strategy=EvidenceSelectionStrategy.DETERMINISTIC, role=role, max_candidates=8).selected,
                "preserve_boundaries_budget_8": preserve_boundaries(candidates, role=role, budget=8),
            }
            for arm, selected in arms.items():
                metrics = summarize(selected, all_candidates=full, required_refs=required_refs)
                if arm == "preserve_boundaries_budget_8":
                    assert not metrics["missing_boundary_candidate_ids"]
                    assert selected == preserve_boundaries(tuple(reversed(candidates)), role=role, budget=8)
                rows.append({"scenario": scenario["scenario"], "role": role, "arm": arm, **metrics})
            for budget in range(1, len(full) + 1):
                selected = preserve_boundaries(candidates, role=role, budget=budget)
                metrics = summarize(selected, all_candidates=full, required_refs=required_refs)
                assert not metrics["missing_boundary_candidate_ids"]
                sweeps.append({"scenario": scenario["scenario"], "role": role, "budget": budget, **metrics})
    return {
        "mode": "offline_synthetic_preservation_comparison",
        "head": inputs["head"], "working_tree_status": inputs["working_tree_status"],
        "input_sha256": {**inputs["input_sha256"], str(Path(__file__).relative_to(ROOT)):
            hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
        "policy": "All eligible required_for_boundary candidates preserved by candidate ID; optional candidates use unchanged production ranking; total budget is soft.",
        "gold_used_for_selection": False,
        "actual_prompt_tokens": "not_measured", "llm_latency": "not_measured",
        "generation_quality": "not_measured", "human_usefulness": "not_measured",
        "source_scenarios": [{k: s[k] for k in ("scenario", "unavailable_original_required_refs", "candidates")} for s in inputs["scenarios"]],
        "rows": rows, "preserving_policy_budget_sweep": sweeps,
        "limitations": [
            "One synthetic base context plus two synthetic stress variants; not independent production samples.",
            "All roles use the original process-manager source-reference rubric for sensitivity analysis.",
            "Unavailable original required sources are reported separately and excluded from available-source recall.",
            "Preservation is measured after candidate projection; this does not establish lossless raw-source representation.",
            "Byte counts describe serialized candidate metadata, not actual downstream LLM prompt payloads.",
        ],
    }


def report(result):
    labels = {"base": "기본", "production_stale": "생산 데이터 만료",
              "production_stale_two_limitations_same_source": "만료 + 복수 제약"}
    arms = {"full_context": "전체 전달", "original_budget_8": "기존 8개",
            "preserve_boundaries_budget_8": "보완 8개"}
    lines = ["# 전체 전달 / 기존 선별 / 보존 규칙 보완 비교", "",
        "현재 로컬 입력을 다시 생성하여 실행한 오프라인 합성 평가다. 제품의 정책과 기본값은 변경하지 않았다.", "",
        "## 공정관리자 결과", "",
        "| 조건 | 방식 | 선택 수 | 지정 출처 보존 | 필수 경계 후보 보존 | 후보 JSON 바이트 |",
        "| --- | --- | --- | --- | --- | --- |"]
    for row in result["rows"]:
        if row["role"] == "process_manager":
            lines.append(f"| {labels[row['scenario']]} | {arms[row['arm']]} | {row['selected_count']} | "
                f"{row['source_refs_preserved']}/{row['source_refs_required']} | "
                f"{row['boundary_candidates_preserved']}/{row['boundary_candidates_required']} | "
                f"{row['candidate_json_utf8_bytes']:,} |")
    lines += ["", "## 보완 정책에서 지정 출처와 필수 경계 후보를 모두 보존하는 최소 한도", "",
        "| 조건 | 역할 | 최소 한도 | 실제 선택 수 |", "| --- | --- | --- | --- |"]
    for scenario in labels:
        for role in ("process_manager", "field_operator", "system_admin"):
            passing = [row for row in result["preserving_policy_budget_sweep"]
                if row["scenario"] == scenario and row["role"] == role
                and not row["missing_required_source_refs"] and not row["missing_boundary_candidate_ids"]]
            first = min(passing, key=lambda row: row["budget"])
            lines.append(f"| {labels[scenario]} | {role} | {first['budget']} | {first['selected_count']} |")
    lines += ["", "## 결론", "",
        "기존 8개는 기본 사례의 지정 출처를 모두 남기지만 필수 경계 후보 하나를 누락한다. 보완 8개는 경계 후보를 모두 보존하지만 필요 부품 출처가 빠진다. 제약의 필수 보존과 업무상 필요한 출처의 충분성은 별개다.",
        "공정관리자에서 두 기준을 동시에 충족하는 보완안의 최소 한도는 기본 9개, 만료 13개, 복수 제약 14개였다. 이 값은 세 합성 조건에서 사후 측정한 값이며 일반 기본값이나 최적값으로 권고하지 않는다.",
        "현재 범위에서는 전체 전달이 선별로 인한 후보 누락을 피하는 가장 단순한 기준선이다. 보완안은 후보 수를 줄이면서 필수 제약을 보존하지만, 업무상 필요한 정보의 충분성을 보장하는 추가 정책과 생성 품질 평가가 필요하다.",
        "", "## 실험 정의와 해석", "",
        "- 보완안은 required_for_boundary=true인 적격 후보를 후보 ID별로 모두 보존한다. 같은 출처의 사실과 관계 제약을 하나로 대표화하지 않는다.",
        "- 나머지 후보는 제품의 기존 우선순위와 역할 정렬을 그대로 사용한다. 총 선택 한도는 max(8, 필수 후보 수)다. 필수 후보에 추가로 8개를 고르는 정책은 아니다.",
        "- 필수 출처 평가표는 선택 함수에 전달하지 않는다. 출처 보존율은 선택 후 평가한다. 업무상 필요한 출처와 required_for_boundary 플래그는 서로 다른 기준이다.",
        "- 3개 조건 × 3개 역할 × 3개 방식 = 27개 비교 행. 보완안은 추가로 모든 정수 한도에서 비교했다.",
        "- 무제한 선별과 전체 전달의 후보 ID 집합이 같음을 확인했다. 보완안은 입력 순서를 뒤집어도 동일하게 선택하며, 모든 한도에서 필수 경계 후보 누락이 없음을 assert했다.",
        "- 생산 데이터 만료 조건은 원래 지정 출처 5개 중 사용할 수 없는 생산 출처 2개를 별도 기록하고 나머지 3개로 출처 보존율을 계산한다.",
        "- 모든 역할에 공정관리자용 출처 평가표를 적용했다. 다른 역할의 결과는 민감도 확인이며 역할별 품질 평가가 아니다.",
        "- 필수 후보 보존은 선택 단계의 구조적 보장이다. 후보 생성 이전의 정보 손실, 필수 플래그의 적절성, 최종 생성문 품질은 검증하지 않았다.",
        "- 실제 프롬프트 토큰, LLM 지연, 생성 품질, 사람의 판단 유용성은 not_measured다. 바이트 수는 후보 JSON 크기이며 비용이나 실제 프롬프트 감소율로 해석할 수 없다.",
        "", "## 재현", "", "```sh",
        "python3 scripts/compare_operational_evidence_preservation.py --output-dir docs/eval/evidence-preservation-comparison-2026-09-09",
        "```", "", "원시 결과 results.json에는 입력 해시, 작업 트리 상태, 후보 전문, 선택·누락 ID를 저장한다."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    summary = report(result)
    (args.output_dir / "report.md").write_text(summary)
    print(summary)
