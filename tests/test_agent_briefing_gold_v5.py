import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLD_PATH = ROOT / "tests/fixtures/agent_review_packets/natural_briefing_v5/gold-v5.json"
VALIDATION_PATH = ROOT / "tests/fixtures/agent_review_packets/natural_briefing_v5/validation.json"

INTERNAL_VISIBLE_TERMS = re.compile(
    r"운영 스냅샷|스냅샷|계획 가정|데모|합성 데이터|\boutcome\b|maintenance_recommended|\[근거\s*\d+\]"
)


def load_gold():
    return json.loads(GOLD_PATH.read_text())


def visible_text(case):
    briefing = case["reference_briefing"]
    parts = [briefing.get("title", ""), briefing.get("summary", "")]
    parts.extend(role.get("quote", "") for role in briefing.get("role_summaries", []))
    return "\n".join(parts)


def role(case, role_name):
    return next(r for r in case["reference_briefing"]["role_summaries"] if r["role"] == role_name)


def test_gold_v5_has_expected_identity_and_case_split():
    data = load_gold()

    assert data["gold_answer_set_id"] == "agent-review-decision-briefing-v5-reader-lines"
    assert data["derived_from"] == "agent-review-decision-briefing-v4.2 + decision-flow-v1 human revision"
    assert len(data["cases"]) == 9
    assert [case["case_id"] for case in data["cases"][:8]] == [f"GS-{idx:03d}" for idx in range(1, 9)]

    approved = data["cases"][-1]
    assert approved["case_id"] == "GS-002-approved-work-order"
    assert approved["base_case_id"] == "GS-002"


def test_gold_v5_role_quotes_are_reader_lines_without_visible_bullets_or_ref_numbers():
    for case in load_gold()["cases"]:
        for role_summary in case["reference_briefing"]["role_summaries"]:
            lines = [line for line in role_summary["quote"].splitlines() if line.strip()]

            assert 3 <= len(lines) <= 5, (case["case_id"], role_summary["role"], lines)
            assert role_summary["display_contract"]["format"] == "reader_line"
            assert all(not line.lstrip().startswith(("-", "•")) for line in lines)
            assert all("[근거" not in line for line in lines)


def test_gold_v5_keeps_internal_terms_out_of_visible_answer_text():
    for case in load_gold()["cases"]:
        assert not INTERNAL_VISIBLE_TERMS.search(visible_text(case)), case["case_id"]


def test_gold_v5_keeps_basic_and_approved_work_order_cases_separate():
    cases = {case["case_id"]: case for case in load_gold()["cases"]}
    basic = visible_text(cases["GS-002"])
    approved = visible_text(cases["GS-002-approved-work-order"])

    assert "작업요청·승인 상태는 미확인" in basic
    basic_maintenance = role(cases["GS-002"], "maintenance_technician")["quote"]
    assert "**승인 상태**" not in basic_maintenance
    assert "승인 시각" not in basic_maintenance

    assert "커플링 정렬 보정 작업요청은 **승인 상태**" in approved
    assert "승인 시각은 39일 전 23:55" in approved
    assert "시작·완료 기록" in approved
    assert "실제 재고 수량과 작업 가능 시간" in approved
    assert "조달 예상 기간 2일" in approved
    assert "도착 예정" not in approved


def test_gold_v5_visible_answer_uses_relative_time_and_korean_units():
    text = "\n".join(visible_text(case) for case in load_gold()["cases"])

    assert "2026-07-31T" not in text
    assert "39일 전 23:40" in text
    assert "39일 전 23:55" in text
    assert "230 min" not in text
    assert "N·m·min" not in text
    assert "230분" in text
    assert "12,650 뉴턴미터·분" in text


def test_gold_v5_explains_threshold_crossing_as_decision_not_product_code():
    text = "\n".join(visible_text(case) for case in load_gold()["cases"])

    assert "제품 유형 M" not in text
    assert "product_variant" not in text
    assert "product_type" not in text
    assert "공구 마모 230분은 기준 220분을 넘어 공구 매거진·스핀들 공구 체결부 확인으로 이어집니다" in text
    assert "과부하 지표 12,650 뉴턴미터·분은 기준 12,000 뉴턴미터·분을 넘어 주축 모터·커플링·동력 전달부" in text


def test_gold_v5_describes_decision_conditions_without_owning_operational_decisions():
    text = "\n".join(visible_text(case) for case in load_gold()["cases"])

    assert "결정하세요" not in text
    assert "판단하세요" not in text
    assert not re.search(r"(?:승인|착수|정비\s*(?:일정|범위)|라인|셀|생산\s*순서|정지\s*시점)[^.?!\n]{0,36}(?:결정|판단|진행|확정)해야\s*합니다", text)


def test_gold_v5_validation_manifest_passed_without_violations():
    validation = json.loads(VALIDATION_PATH.read_text())

    assert validation["status"] == "passed"
    assert validation["case_count"] == 9
    assert validation["base_case_count"] == 8
    assert validation["variant_case_count"] == 1
    assert validation["violations"] == []
