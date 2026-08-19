from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path
import re

from scripts.check_backend_migration_ledger import migration_progress


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LEGACY_ROOT = REPOSITORY_ROOT / "systems" / "backend" / "ontology_dashboard"
MIGRATION_MAP = REPOSITORY_ROOT / "docs" / "backend-migration-map.md"
ALLOWED_DISPOSITIONS = {"MOVE", "SPLIT", "REPLACE", "REMOVE", "DEFER"}
DISPOSITION_PATTERN = re.compile(r"^`([A-Z]+)`$")
SOURCE_PATTERN = re.compile(r"`([^`]+)`")


def _ledger_rows() -> list[tuple[int, list[str]]]:
    lines = MIGRATION_MAP.read_text(encoding="utf-8").splitlines()
    in_ledger = False
    rows: list[tuple[int, list[str]]] = []

    for line_number, line in enumerate(lines, start=1):
        if line == "## 3. Source 처분 Ledger":
            in_ledger = True
            continue
        if in_ledger and line.startswith("## "):
            break
        if not in_ledger or not line.startswith("|"):
            continue

        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 5 or cells[0] in {"Source", "---"}:
            continue
        rows.append((line_number, cells))

    return rows


def _migrated_sources() -> set[str]:
    return set(migration_progress(MIGRATION_MAP.read_text(encoding="utf-8")))


def test_migration_progress_parser_stops_at_next_section() -> None:
    text = """# synthetic map

## 8. Physical migration progress

| Legacy Source | Canonical target(s) | State |
|---|---|---|
| `example.py` | `systems/backend/app/example.py` | `MIGRATED` |

## 9. Phase 2 notes

| item | owner | note | state |
|---|---|---|---|
| dashboard | team | #53 | planned |
"""

    assert migration_progress(text) == {
        "example.py": ("systems/backend/app/example.py",)
    }


def test_migration_ledger_uses_one_allowed_disposition_per_row() -> None:
    invalid: list[str] = []

    for line_number, cells in _ledger_rows():
        match = DISPOSITION_PATTERN.fullmatch(cells[2])
        if match is None or match.group(1) not in ALLOWED_DISPOSITIONS:
            invalid.append(f"line {line_number}: {cells[2]}")

    assert not invalid, "invalid or composite migration dispositions: " + ", ".join(invalid)


def test_every_legacy_python_source_matches_exactly_one_ledger_row() -> None:
    rows: list[tuple[int, list[str]]] = []
    for line_number, cells in _ledger_rows():
        patterns = SOURCE_PATTERN.findall(cells[0])
        assert patterns, f"migration ledger line {line_number} has no source pattern"
        rows.append((line_number, patterns))

    unmatched: list[str] = []
    multiply_assigned: list[str] = []
    matched_lines: set[int] = set()

    live_sources = {
        source.relative_to(LEGACY_ROOT).as_posix()
        for source in LEGACY_ROOT.rglob("*.py")
    }
    migrated_sources = _migrated_sources()

    for relative_source in sorted(live_sources | migrated_sources):
        matching_rows = [
            line_number
            for line_number, patterns in rows
            if any(fnmatchcase(relative_source, pattern) for pattern in patterns)
        ]
        matched_lines.update(matching_rows)
        if not matching_rows:
            unmatched.append(relative_source)
        elif len(matching_rows) > 1:
            multiply_assigned.append(f"{relative_source}: lines {matching_rows}")

    reappeared = sorted(
        source for source in migrated_sources if (LEGACY_ROOT / source).exists()
    )

    unused_rows = [line_number for line_number, _ in rows if line_number not in matched_lines]

    assert not unmatched, "unassigned legacy Python sources: " + ", ".join(unmatched)
    assert not multiply_assigned, "multiply assigned legacy Python sources: " + "; ".join(
        multiply_assigned
    )
    assert not reappeared, "physically migrated legacy Python sources reappeared: " + ", ".join(
        reappeared
    )
    assert not unused_rows, f"migration ledger rows without matching sources: {unused_rows}"
