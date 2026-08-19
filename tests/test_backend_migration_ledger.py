from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_backend_migration_ledger import LedgerValidationError, validate_ledger


ROOT = Path(__file__).resolve().parents[1]


def test_backend_migration_ledger_covers_every_legacy_python_source_once() -> None:
    report = validate_ledger(ROOT)
    expected = len(
        list((ROOT / "systems" / "backend" / "ontology_dashboard").rglob("*.py"))
    )

    assert report.total_sources == expected
    assert report.migrated_sources == 7
    assert report.disposition_counts["DEFER"] == 0
    assert sum(report.disposition_counts.values()) == expected


def test_backend_migration_ledger_rejects_reappeared_migrated_source(tmp_path: Path) -> None:
    legacy = tmp_path / "systems" / "backend" / "ontology_dashboard"
    legacy.mkdir(parents=True)
    (legacy / "example.py").write_text("VALUE = 1\n", encoding="utf-8")
    target = tmp_path / "systems" / "backend" / "app" / "example.py"
    target.parent.mkdir(parents=True)
    target.write_text("VALUE = 1\n", encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "backend-migration-map.md").write_text(
        """# synthetic ledger

## 3. Source 처분 Ledger

| Source | 책임 | 처분 | 목표/조건 | Phase |
|---|---|---|---|---|
| `example.py` | first | `MOVE` | app/example | #1 |

## 4. next

## 8. Physical migration progress

| Legacy Source | Canonical target(s) | State |
|---|---|---|
| `example.py` | `systems/backend/app/example.py` | `MIGRATED` |
""",
        encoding="utf-8",
    )

    with pytest.raises(LedgerValidationError, match="reappeared"):
        validate_ledger(tmp_path)


def test_backend_migration_ledger_rejects_duplicate_coverage(tmp_path: Path) -> None:
    legacy = tmp_path / "systems" / "backend" / "ontology_dashboard"
    legacy.mkdir(parents=True)
    (legacy / "example.py").write_text("VALUE = 1\n", encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "backend-migration-map.md").write_text(
        """# synthetic ledger

## 3. Source 처분 Ledger

| Source | 책임 | 처분 | 목표/조건 | Phase |
|---|---|---|---|---|
| `example.py` | first | `MOVE` | app/example | #1 |
| `example.py` | duplicate | `REMOVE` | none | #1 |

## 4. next
""",
        encoding="utf-8",
    )

    with pytest.raises(LedgerValidationError, match="duplicate ledger coverage"):
        validate_ledger(tmp_path)


def test_backend_migration_ledger_rejects_defer(tmp_path: Path) -> None:
    legacy = tmp_path / "systems" / "backend" / "ontology_dashboard"
    legacy.mkdir(parents=True)
    (legacy / "example.py").write_text("VALUE = 1\n", encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "backend-migration-map.md").write_text(
        """# synthetic ledger

## 3. Source 처분 Ledger

| Source | 책임 | 처분 | 목표/조건 | Phase |
|---|---|---|---|---|
| `example.py` | unresolved | `DEFER` | later | #68 |

## 4. next
""",
        encoding="utf-8",
    )

    with pytest.raises(LedgerValidationError, match="DEFER=0"):
        validate_ledger(tmp_path)


def test_backend_migration_ledger_rejects_empty_migrated_target(tmp_path: Path) -> None:
    legacy = tmp_path / "systems" / "backend" / "ontology_dashboard"
    legacy.mkdir(parents=True)
    target = tmp_path / "systems" / "backend" / "app" / "example.py"
    target.parent.mkdir(parents=True)
    target.write_text("", encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "backend-migration-map.md").write_text(
        """# synthetic ledger

## 3. Source 처분 Ledger

| Source | 책임 | 처분 | 목표/조건 | Phase |
|---|---|---|---|---|
| `example.py` | first | `MOVE` | app/example | #1 |

## 4. next

## 8. Physical migration progress

| Legacy Source | Canonical target(s) | State |
|---|---|---|
| `example.py` | `systems/backend/app/example.py` | `MIGRATED` |
""",
        encoding="utf-8",
    )

    with pytest.raises(LedgerValidationError, match="canonical target is empty"):
        validate_ledger(tmp_path)
