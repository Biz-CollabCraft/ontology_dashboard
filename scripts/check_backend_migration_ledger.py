#!/usr/bin/env python3
"""Deterministically validate the Backend legacy migration disposition ledger."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = ROOT / "docs" / "backend-migration-map.md"
DEFAULT_LEGACY_ROOT = ROOT / "systems" / "backend" / "ontology_dashboard"
ALLOWED_DISPOSITIONS = {"MOVE", "SPLIT", "REPLACE", "REMOVE", "DEFER"}


class LedgerValidationError(RuntimeError):
    """Raised when the migration ledger is structurally incomplete or ambiguous."""


@dataclass(frozen=True)
class LedgerReport:
    total_sources: int
    disposition_counts: dict[str, int]
    row_count: int


def _ledger_section(text: str) -> str:
    marker = "## 3. Source 처분 Ledger"
    start = text.find(marker)
    if start < 0:
        raise LedgerValidationError(f"missing ledger section: {marker}")
    end = text.find("\n## 4.", start)
    if end < 0:
        raise LedgerValidationError("missing section boundary after Source 처분 Ledger")
    return text[start:end]


def _parse_rows(text: str) -> list[tuple[list[str], str, int]]:
    rows: list[tuple[list[str], str, int]] = []
    errors: list[str] = []
    for line_number, line in enumerate(_ledger_section(text).splitlines(), start=1):
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or cells[0] == "Source" or set(cells[0]) <= {"-", ":"}:
            continue
        if len(cells) != 5:
            errors.append(f"ledger row {line_number}: expected 5 columns, got {len(cells)}")
            continue
        sources = re.findall(r"`([^`]+)`", cells[0])
        if not sources:
            errors.append(f"ledger row {line_number}: Source cell has no code path")
            continue
        disposition_match = re.fullmatch(r"`([A-Z]+)`", cells[2])
        if disposition_match is None:
            errors.append(
                f"ledger row {line_number}: disposition must be exactly one enum value, got {cells[2]!r}"
            )
            continue
        disposition = disposition_match.group(1)
        if disposition not in ALLOWED_DISPOSITIONS:
            errors.append(
                f"ledger row {line_number}: unsupported disposition {disposition!r}; "
                f"allowed={sorted(ALLOWED_DISPOSITIONS)}"
            )
            continue
        rows.append((sources, disposition, line_number))
    if errors:
        raise LedgerValidationError("\n".join(errors))
    return rows


def _expand_source(legacy_root: Path, source: str) -> set[str]:
    if source.endswith("/*"):
        directory = legacy_root / source[:-2]
        if not directory.is_dir():
            raise LedgerValidationError(f"ledger wildcard directory does not exist: {source}")
        matched = {
            path.relative_to(legacy_root).as_posix()
            for path in directory.rglob("*.py")
            if path.is_file()
        }
        if not matched:
            raise LedgerValidationError(f"ledger wildcard matches no Python sources: {source}")
        return matched

    path = legacy_root / source
    if not path.is_file():
        raise LedgerValidationError(f"ledger source does not exist: {source}")
    if path.suffix != ".py":
        raise LedgerValidationError(f"ledger source is not a Python source: {source}")
    return {path.relative_to(legacy_root).as_posix()}


def validate_ledger(
    root: Path = ROOT,
    *,
    ledger_path: Path | None = None,
    legacy_root: Path | None = None,
) -> LedgerReport:
    ledger = ledger_path or root / "docs" / "backend-migration-map.md"
    legacy = legacy_root or root / "systems" / "backend" / "ontology_dashboard"
    text = ledger.read_text(encoding="utf-8")
    rows = _parse_rows(text)

    actual = {
        path.relative_to(legacy).as_posix()
        for path in legacy.rglob("*.py")
        if path.is_file()
    }
    assigned: dict[str, tuple[str, int, str]] = {}
    duplicates: list[str] = []
    deferred_rows: list[str] = []

    for sources, disposition, line_number in rows:
        if disposition == "DEFER":
            deferred_rows.append(f"row {line_number}: {', '.join(sources)}")
        for source in sources:
            for relative_path in sorted(_expand_source(legacy, source)):
                previous = assigned.get(relative_path)
                if previous is not None:
                    duplicates.append(
                        f"{relative_path}: row {previous[1]} ({previous[2]}) and "
                        f"row {line_number} ({source})"
                    )
                    continue
                assigned[relative_path] = (disposition, line_number, source)

    errors: list[str] = []
    missing = sorted(actual - set(assigned))
    extra = sorted(set(assigned) - actual)
    if missing:
        errors.append("unassigned legacy Python sources:\n  - " + "\n  - ".join(missing))
    if extra:
        errors.append("ledger assigns non-existent legacy Python sources:\n  - " + "\n  - ".join(extra))
    if duplicates:
        errors.append("duplicate ledger coverage:\n  - " + "\n  - ".join(sorted(duplicates)))
    if deferred_rows:
        errors.append(
            "Phase 0.5 requires DEFER=0 before Phase 14:\n  - "
            + "\n  - ".join(deferred_rows)
        )
    if "UNDECIDED" in _ledger_section(text):
        errors.append("UNDECIDED is not an allowed Source ledger disposition")
    if errors:
        raise LedgerValidationError("\n".join(errors))

    counts = Counter(item[0] for item in assigned.values())
    return LedgerReport(
        total_sources=len(actual),
        disposition_counts={key: counts.get(key, 0) for key in sorted(ALLOWED_DISPOSITIONS)},
        row_count=len(rows),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    try:
        report = validate_ledger(args.root.resolve())
    except (LedgerValidationError, OSError) as error:
        print("[BACKEND-MIGRATION-LEDGER] FAIL")
        print(error)
        return 1
    if not args.quiet:
        counts = ", ".join(
            f"{name}={count}" for name, count in report.disposition_counts.items()
        )
        print("[BACKEND-MIGRATION-LEDGER] PASS")
        print(f"- legacy Python sources: {report.total_sources}")
        print(f"- ledger rows: {report.row_count}")
        print(f"- dispositions: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
