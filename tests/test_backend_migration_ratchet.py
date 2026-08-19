from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.check_backend_migration_ratchet import (
    LegacyReference,
    MigrationBaseline,
    MigrationRatchetError,
    assert_monotonic,
    collect_transitional_references,
    snapshot_repository,
    validate_ratchet,
    write_baseline,
)


ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _synthetic_repository(root: Path) -> Path:
    _write(
        root / "systems/backend/ontology_dashboard/example.py",
        "VALUE = 1\n",
    )
    _write(
        root / "systems/backend/app/main.py",
        "from ontology_dashboard.example import VALUE\n",
    )
    _write(
        root / "docs/backend-migration-map.md",
        """# synthetic migration map

## 3. Source 처분 Ledger

| Source | 책임 | 처분 | 목표/조건 | Phase |
|---|---|---|---|---|
| `example.py` | synthetic | `MOVE` | app/example | #1 |

## 4. Capability disposition
""",
    )
    baseline = root / "docs/backend-migration-baseline.json"
    write_baseline(baseline, snapshot_repository(root))
    return baseline


class BackendMigrationRatchetTests(unittest.TestCase):
    def test_pr_base_edit_retriggers_both_ratchet_workflows(self) -> None:
        workflow_paths = (
            ROOT / ".github/workflows/architecture.yml",
            ROOT / ".github/workflows/backend-contract-ci.yml",
        )

        for workflow_path in workflow_paths:
            with self.subTest(workflow=workflow_path.name):
                workflow = workflow_path.read_text(encoding="utf-8")
                pull_request_section = workflow.split("pull_request:", 1)[1].split(
                    "push:", 1
                )[0]
                self.assertIn("edited", pull_request_section)

    def test_repository_matches_committed_baseline(self) -> None:
        report = validate_ratchet(ROOT)

        self.assertEqual(report.mode, "ratchet")
        self.assertGreater(report.legacy_source_count, 0)
        self.assertGreater(report.transitional_reference_count, 0)

    def test_valid_synthetic_repository_matches_exact_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = _synthetic_repository(root)

            report = validate_ratchet(root, baseline_path=baseline)

        self.assertEqual(report.legacy_source_count, 1)
        self.assertEqual(report.transitional_reference_count, 1)

    def test_new_legacy_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = _synthetic_repository(root)
            _write(
                root / "systems/backend/ontology_dashboard/reintroduced.py",
                "VALUE = 2\n",
            )

            with self.assertRaisesRegex(MigrationRatchetError, "RAT002"):
                validate_ratchet(root, baseline_path=baseline)

    def test_new_nonlegacy_import_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = _synthetic_repository(root)
            _write(
                root / "systems/backend/app/consumer.py",
                "import ontology_dashboard.example\n",
            )

            with self.assertRaisesRegex(MigrationRatchetError, "RAT003"):
                validate_ratchet(root, baseline_path=baseline)

    def test_invalid_disposition_ledger_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = _synthetic_repository(root)
            migration_map = root / "docs/backend-migration-map.md"
            migration_map.write_text(
                migration_map.read_text(encoding="utf-8").replace(
                    "`MOVE`", "`UNDECIDED`"
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(MigrationRatchetError, "RAT005"):
                validate_ratchet(root, baseline_path=baseline)

    def test_dynamic_import_and_string_entrypoints_are_collected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy_module = "ontology_" + "dashboard.worker"
            _write(
                root / "systems/backend/app/runtime.py",
                "import importlib\n"
                + f"WORKER = importlib.import_module({legacy_module!r})\n",
            )
            _write(
                root / "Dockerfile",
                "CMD [\"uvicorn\", \""
                + "ontology_"
                + "dashboard.app:app\"]\n",
            )

            references = collect_transitional_references(root)

        self.assertIn(
            LegacyReference(
                "systems/backend/app/runtime.py",
                "dynamic_import",
                "ontology_dashboard.worker",
            ),
            references,
        )
        self.assertIn(
            LegacyReference(
                "Dockerfile",
                "runtime_entrypoint",
                "ontology_dashboard.app:app",
            ),
            references,
        )

    def test_direct_and_keyword_dynamic_imports_are_collected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets = (
                "ontology_" + "dashboard.direct",
                "ontology_" + "dashboard.keyword",
                "ontology_" + "dashboard.builtin",
            )
            _write(
                root / "systems/backend/app/runtime.py",
                "from importlib import import_module\n"
                + "import importlib\n"
                + f"DIRECT = import_module({targets[0]!r})\n"
                + f"KEYWORD = importlib.import_module(name={targets[1]!r})\n"
                + f"BUILTIN = __import__(name={targets[2]!r})\n",
            )

            references = collect_transitional_references(root)

        for target in targets:
            self.assertIn(
                LegacyReference(
                    "systems/backend/app/runtime.py",
                    "dynamic_import",
                    target,
                ),
                references,
            )

    def test_baseline_may_decrease_but_cannot_increase(self) -> None:
        reference = LegacyReference(
            "systems/backend/app/main.py",
            "static_import",
            "ontology_dashboard.example",
        )
        base = MigrationBaseline(
            "ratchet",
            frozenset({"example.py"}),
            frozenset({reference}),
        )
        reduced = MigrationBaseline("ratchet", frozenset(), frozenset())
        increased = MigrationBaseline(
            "ratchet",
            frozenset({"example.py", "reintroduced.py"}),
            frozenset({reference}),
        )

        assert_monotonic(reduced, base)
        with self.assertRaisesRegex(MigrationRatchetError, "RAT004"):
            assert_monotonic(increased, base)


if __name__ == "__main__":
    unittest.main()
