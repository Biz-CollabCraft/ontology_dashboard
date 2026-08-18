import unittest
from argparse import Namespace

from scripts.ci.ai_review import (
    build_verified_evidence,
    classify_comment,
    detect_intent_risk_hints,
    event_to_comment,
    human_technical_feedback,
    idempotency_decision,
    route_context,
)


class AiReviewAutomationTests(unittest.TestCase):
    def test_context_router_selects_backend_and_domain_docs(self):
        categories = route_context(
            ["systems/backend/ontology_dashboard/closed_loop/domain.py"]
        )
        self.assertIn("project_intent", categories)
        self.assertIn("architecture", categories)
        self.assertIn("closed_loop", categories)

    def test_context_router_selects_frontend_mvp_operations_docs(self):
        categories = route_context(
            ["systems/frontend/src/features/mvp/operations/MvpOperationsPage.tsx"]
        )
        self.assertIn("project_intent", categories)
        self.assertIn("architecture", categories)
        self.assertIn("mvp", categories)
        self.assertIn("frontend_operations", categories)

    def test_context_router_selects_deployment_docs_for_dockerignore(self):
        categories = route_context([".dockerignore"])
        self.assertIn("project_intent", categories)
        self.assertIn("deployment", categories)

    def test_project_intent_hint_detects_frontend_state_machine_reimplementation(self):
        diff = """diff --git a/x b/x
+++ b/x
+if (workOrder.status === \"approved\") actions.push(\"start\")
"""
        hints = detect_intent_risk_hints(
            diff, ["systems/frontend/src/features/mvp/operations/MvpOperationsPage.tsx"]
        )
        self.assertTrue(any("state machine" in hint for hint in hints))

    def test_project_intent_hint_detects_frontend_generated_persisted_id(self):
        diff = """diff --git a/x b/x
+++ b/x
+const id = `${projectId}-${eventId}-${Date.now()}`
"""
        hints = detect_intent_risk_hints(
            diff, ["systems/frontend/src/features/mvp/operations/MvpOperationsPage.tsx"]
        )
        self.assertTrue(any("identifiers" in hint for hint in hints))

    def test_project_intent_hint_detects_demo_fixture_hardcoding(self):
        diff = """diff --git a/x b/x
+++ b/x
+if (projectId === \"manufacturing-demo-project\") return fixture
"""
        hints = detect_intent_risk_hints(
            diff,
            ["systems/backend/ontology_dashboard/predictive_maintenance_runtime/service.py"],
        )
        self.assertTrue(any("fixture-specific" in hint for hint in hints))

    def test_comment_classifier_examples(self):
        self.assertEqual(
            classify_comment("[P2] .dockerignore가 classifier에서 빠집니다"),
            "actionable_review",
        )
        self.assertEqual(
            classify_comment("이 방식 대신 server available_actions를 쓰는 게 맞지 않나요?"),
            "technical_question",
        )
        self.assertEqual(classify_comment("approve 입니다"), "approval")
        self.assertEqual(classify_comment("확인했습니다"), "acknowledgement")
        self.assertEqual(classify_comment("감사합니다"), "acknowledgement")

    def test_comment_event_ignores_automated_marker_and_bot_loop(self):
        event = {
            "action": "created",
            "issue": {"number": 44, "pull_request": {"url": "x"}},
            "comment": {
                "id": 123,
                "body": "<!-- automated-comment-review source-kind=issue_comment source-comment-id=1 head-sha=abc -->\n[P2] test",
                "user": {"login": "github-actions[bot]", "type": "Bot"},
            },
        }
        info = event_to_comment(event)
        self.assertFalse(info.eligible)

    def test_idempotency_noops_same_source_and_head(self):
        comments = [
            {
                "id": 77,
                "body": "<!-- automated-comment-review source-kind=issue_comment source-comment-id=123 head-sha=abc -->\nresponse",
            }
        ]
        self.assertEqual(
            idempotency_decision(comments, "issue_comment", "123", "abc"),
            ("noop", "77"),
        )

    def test_idempotency_updates_when_head_changes(self):
        comments = [
            {
                "id": 77,
                "body": "<!-- automated-comment-review source-kind=issue_comment source-comment-id=123 head-sha=abc -->\nresponse",
            }
        ]
        self.assertEqual(
            idempotency_decision(comments, "issue_comment", "123", "def"),
            ("update", "77"),
        )

    def test_feedback_filter_keeps_only_human_technical_feedback(self):
        feedback = human_technical_feedback(
            [
                {
                    "id": 1,
                    "body": "[P2] unknown path가 fail-open입니다",
                    "user": {"login": "KOR-GANG", "type": "User"},
                },
                {
                    "id": 2,
                    "body": "감사합니다",
                    "user": {"login": "teammate", "type": "User"},
                },
                {
                    "id": 3,
                    "body": "[P2] bot finding",
                    "user": {"login": "github-actions[bot]", "type": "Bot"},
                },
            ],
            [],
            [],
        )
        self.assertEqual(len(feedback), 1)
        self.assertEqual(feedback[0]["author"], "KOR-GANG")

    def test_required_false_is_na_not_missing_evidence(self):
        evidence = build_verified_evidence(
            Namespace(
                architecture_result="success",
                docker_required="false",
                docker_verified="false",
                frontend_required="false",
                frontend_verified="false",
                mvp_required="false",
                mvp_verified="false",
            )
        )
        self.assertEqual(evidence["missing_required"], [])
        self.assertEqual(evidence["merge_readiness_ceiling"], "Ready to Merge")

    def test_required_unverified_caps_readiness(self):
        evidence = build_verified_evidence(
            Namespace(
                architecture_result="success",
                docker_required="true",
                docker_verified="false",
                frontend_required="false",
                frontend_verified="false",
                mvp_required="false",
                mvp_verified="false",
            )
        )
        self.assertEqual(evidence["missing_required"], ["docker_runtime"])
        self.assertEqual(evidence["merge_readiness_ceiling"], "Conditional")


if __name__ == "__main__":
    unittest.main()
