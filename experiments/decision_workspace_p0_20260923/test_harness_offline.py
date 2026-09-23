"""Safeguard and wiring checks only: no requests, runners, databases or sleeps."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("p0_harness", HERE / "harness.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


class OfflineChecks(unittest.TestCase):
    def test_control_dsn_is_never_a_runtime_dsn(self):
        self.assertEqual(h.validate_dsn(h.ADMIN, admin=True), "decision_p0_control")
        with self.assertRaises(ValueError):
            h.validate_dsn(h.ADMIN)
        self.assertEqual(h.validate_dsn(h.DB_PREFIX + "decision_p0_fresh_123"), "decision_p0_fresh_123")

    def test_rejects_other_endpoints_and_query_overrides(self):
        for dsn in (h.ADMIN.replace("55434", "5432"), h.ADMIN.replace("127.0.0.1", "example.com"),
                    h.DB_PREFIX + "production", h.DB_PREFIX + "decision_p0_a?host=example.com",
                    h.DB_PREFIX + "decision_p0_a#x", h.ADMIN.replace("decision_p0:", "postgres:")):
            with self.subTest(dsn=dsn), self.assertRaises(ValueError):
                h.validate_dsn(dsn)

    def test_no_authorization_exits_before_preflight(self):
        with patch.object(sys, "argv", ["harness.py"]), patch.object(h, "preflight") as preflight:
            with self.assertRaises(SystemExit) as stop:
                h.main()
            self.assertEqual(stop.exception.code, 2)
            preflight.assert_not_called()

    def test_check_never_connects_or_runs(self):
        with patch.object(sys, "argv", ["harness.py", "--check"]), patch.object(h, "prepare_environment"), \
             patch.object(h, "preflight", return_value={}), patch.object(h, "create_database") as create, \
             patch.object(h, "scenario") as run:
            h.main()
            create.assert_not_called()
            run.assert_not_called()

    def test_failed_invariant_is_preserved_before_abort(self):
        # Keep even temporary verification files inside the experiment directory.
        with tempfile.TemporaryDirectory(dir=HERE) as temp:
            output = Path(temp)
            journal = h.Journal(output)
            try:
                with self.assertRaises(AssertionError):
                    journal.require(False, "injected offline failure")
                row = json.loads((output / "raw.jsonl").read_text())
                self.assertFalse(row["passed"])
                h.summarize(journal, "failed", "AssertionError")
                self.assertEqual(json.loads((output / "summary.json").read_text())["status"], "failed")
            finally:
                journal.file.close()

    def test_actual_route_wiring_without_requests(self):
        # Fresh interpreter prevents environment changes from affecting other unit checks.
        result = subprocess.run([sys.executable, "-B", "-c",
            "import importlib.util; "
            f"s=importlib.util.spec_from_file_location('p0', {str(HERE / 'harness.py')!r}); "
            "h=importlib.util.module_from_spec(s); s.loader.exec_module(h); h.prepare_environment(); "
            "app=h.make_http_app(object()); "
            "routes=[r for r in app.routes if 'decision-sessions' in r.path]; "
            "assert len(routes)==2; "
            "assert all(r.endpoint.__module__=='app.operations.router' for r in routes); "
            "assert all(d.call in app.dependency_overrides for r in routes for d in r.dependant.dependencies); "
            "print('actual POST/GET endpoints and all external dependencies wired')"],
            cwd=h.ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
