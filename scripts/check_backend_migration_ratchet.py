#!/usr/bin/env python3
"""Enforce the monotonic Backend legacy migration baseline.

The ratchet intentionally allows the existing ``ontology_dashboard`` package
during migration, but it rejects every increase in legacy Python sources or
non-legacy references.  Migration PRs must remove entries from the baseline in
the same commit that removes the corresponding source/reference.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "docs" / "backend-migration-baseline.json"
LEGACY_ROOT_RELATIVE = Path("systems/backend/ontology_dashboard")
BASELINE_SCHEMA_VERSION = "backend-migration-ratchet-v1"
VALID_MODES = {"ratchet", "strict"}
IGNORED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
}
ENTRYPOINT_SUFFIXES = {".js", ".json", ".ps1", ".py", ".sh", ".toml", ".ts", ".tsx", ".yaml", ".yml"}
ENTRYPOINT_SEPARATOR = r"(?:\s+|[\"']?\s*,\s*[\"']?)"
ENTRYPOINT_PATTERNS = (
    re.compile(
        r"\bpython(?:3(?:\.\d+)?)?"
        + ENTRYPOINT_SEPARATOR
        + r"-m"
        + ENTRYPOINT_SEPARATOR
        +
        r"(?P<target>ontology_dashboard(?:\.[A-Za-z_]\w*)+)"
    ),
    re.compile(
        r"\b(?:uvicorn|gunicorn)"
        + ENTRYPOINT_SEPARATOR
        +
        r"(?P<target>ontology_dashboard(?:\.[A-Za-z_]\w*)*(?::[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)?)"
    ),
)


class MigrationRatchetError(RuntimeError):
    """Raised when the migration baseline or repository violates the ratchet."""


@dataclass(frozen=True, order=True)
class LegacyReference:
    source: str
    kind: str
    target: str

    def to_json(self) -> dict[str, str]:
        return {"source": self.source, "kind": self.kind, "target": self.target}


@dataclass(frozen=True)
class MigrationBaseline:
    mode: str
    legacy_sources: frozenset[str]
    transitional_references: frozenset[LegacyReference]


@dataclass(frozen=True)
class RatchetReport:
    mode: str
    legacy_source_count: int
    transitional_reference_count: int
    compared_to_base: bool


def _is_ignored(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    return any(part in IGNORED_PARTS for part in relative.parts)


def _is_legacy_module(module: str) -> bool:
    return (
        module == "ontology_dashboard"
        or module.startswith("ontology_dashboard.")
        or module == "systems.backend.ontology_dashboard"
        or module.startswith("systems.backend.ontology_dashboard.")
    )


def _literal_dynamic_target(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        prefix: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                prefix.append(value.value)
                continue
            break
        rendered = "".join(prefix)
        if _is_legacy_module(rendered.rstrip(".")):
            return f"{rendered}*"
    return None


def _dynamic_import_kind(call: ast.Call) -> str | None:
    function = call.func
    if isinstance(function, ast.Name) and function.id == "__import__":
        return "dynamic_import"
    if isinstance(function, ast.Attribute) and function.attr == "import_module":
        return "dynamic_import"
    return None


def _python_references(path: Path, root: Path) -> set[LegacyReference]:
    relative = path.relative_to(root).as_posix()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise MigrationRatchetError(
            f"RAT003 {relative}: cannot inspect Python imports: {exc}"
        ) from exc

    references: set[LegacyReference] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_legacy_module(alias.name):
                    references.add(LegacyReference(relative, "static_import", alias.name))
        elif isinstance(node, ast.ImportFrom) and node.module and _is_legacy_module(node.module):
            references.add(LegacyReference(relative, "static_import", node.module))
        elif isinstance(node, ast.Call) and _dynamic_import_kind(node) and node.args:
            target = _literal_dynamic_target(node.args[0])
            if target and _is_legacy_module(target.rstrip(".*")):
                references.add(LegacyReference(relative, "dynamic_import", target))
    return references


def _entrypoint_references(path: Path, root: Path) -> set[LegacyReference]:
    relative = path.relative_to(root).as_posix()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    references: set[LegacyReference] = set()
    for pattern in ENTRYPOINT_PATTERNS:
        for match in pattern.finditer(text):
            references.add(
                LegacyReference(relative, "runtime_entrypoint", match.group("target"))
            )
    return references


def collect_legacy_sources(root: Path) -> frozenset[str]:
    legacy_root = root / LEGACY_ROOT_RELATIVE
    if not legacy_root.exists():
        return frozenset()
    return frozenset(
        path.relative_to(legacy_root).as_posix()
        for path in legacy_root.rglob("*.py")
        if path.is_file() and not _is_ignored(path, root)
    )


def collect_transitional_references(root: Path) -> frozenset[LegacyReference]:
    legacy_root = (root / LEGACY_ROOT_RELATIVE).resolve()
    references: set[LegacyReference] = set()
    for path in root.rglob("*"):
        if not path.is_file() or _is_ignored(path, root):
            continue
        try:
            if path.resolve().is_relative_to(legacy_root):
                continue
        except OSError:
            continue
        if path.suffix == ".py":
            references.update(_python_references(path, root))
        if path.name == "Dockerfile" or path.suffix in ENTRYPOINT_SUFFIXES:
            references.update(_entrypoint_references(path, root))
    return frozenset(references)


def snapshot_repository(root: Path) -> MigrationBaseline:
    return MigrationBaseline(
        mode="ratchet",
        legacy_sources=collect_legacy_sources(root),
        transitional_references=collect_transitional_references(root),
    )


def _parse_baseline_payload(payload: object, *, source: str) -> MigrationBaseline:
    if not isinstance(payload, dict):
        raise MigrationRatchetError(f"RAT001 {source}: baseline root must be an object")
    expected_keys = {
        "schema_version",
        "mode",
        "legacy_root",
        "legacy_sources",
        "transitional_references",
    }
    unknown = sorted(set(payload) - expected_keys)
    missing = sorted(expected_keys - set(payload))
    if unknown or missing:
        raise MigrationRatchetError(
            f"RAT001 {source}: invalid keys; missing={missing}, unknown={unknown}"
        )
    if payload["schema_version"] != BASELINE_SCHEMA_VERSION:
        raise MigrationRatchetError(
            f"RAT001 {source}: schema_version must be {BASELINE_SCHEMA_VERSION!r}"
        )
    mode = payload["mode"]
    if mode not in VALID_MODES:
        raise MigrationRatchetError(
            f"RAT001 {source}: mode must be one of {sorted(VALID_MODES)}, got {mode!r}"
        )
    if payload["legacy_root"] != LEGACY_ROOT_RELATIVE.as_posix():
        raise MigrationRatchetError(
            f"RAT001 {source}: legacy_root must be {LEGACY_ROOT_RELATIVE.as_posix()!r}"
        )

    raw_sources = payload["legacy_sources"]
    if not isinstance(raw_sources, list) or not all(
        isinstance(item, str) for item in raw_sources
    ):
        raise MigrationRatchetError(
            f"RAT001 {source}: legacy_sources must be a string list"
        )
    if raw_sources != sorted(set(raw_sources)):
        raise MigrationRatchetError(
            f"RAT001 {source}: legacy_sources must be unique and lexicographically sorted"
        )
    invalid_sources = [
        item
        for item in raw_sources
        if "*" in item or Path(item).is_absolute() or ".." in Path(item).parts
    ]
    if invalid_sources:
        raise MigrationRatchetError(
            f"RAT001 {source}: legacy_sources require explicit safe relative paths: {invalid_sources}"
        )

    raw_references = payload["transitional_references"]
    if not isinstance(raw_references, list):
        raise MigrationRatchetError(
            f"RAT001 {source}: transitional_references must be an object list"
        )
    references: list[LegacyReference] = []
    for index, item in enumerate(raw_references):
        if not isinstance(item, dict) or set(item) != {"source", "kind", "target"}:
            raise MigrationRatchetError(
                f"RAT001 {source}: reference[{index}] must contain source/kind/target"
            )
        if not all(isinstance(item[key], str) and item[key] for key in item):
            raise MigrationRatchetError(
                f"RAT001 {source}: reference[{index}] values must be non-empty strings"
            )
        references.append(LegacyReference(**item))
    if references != sorted(set(references)):
        raise MigrationRatchetError(
            f"RAT001 {source}: transitional_references must be unique and sorted"
        )
    return MigrationBaseline(mode, frozenset(raw_sources), frozenset(references))


def load_baseline(path: Path) -> MigrationBaseline:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationRatchetError(f"RAT001 {path}: cannot read baseline: {exc}") from exc
    return _parse_baseline_payload(payload, source=path.as_posix())


def baseline_payload(baseline: MigrationBaseline) -> dict[str, object]:
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "mode": baseline.mode,
        "legacy_root": LEGACY_ROOT_RELATIVE.as_posix(),
        "legacy_sources": sorted(baseline.legacy_sources),
        "transitional_references": [
            reference.to_json() for reference in sorted(baseline.transitional_references)
        ],
    }


def write_baseline(path: Path, baseline: MigrationBaseline) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(baseline_payload(baseline), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _render_items(items: Iterable[object]) -> str:
    rendered = []
    for item in sorted(items):
        if isinstance(item, LegacyReference):
            rendered.append(f"{item.source} [{item.kind}] -> {item.target}")
        else:
            rendered.append(str(item))
    return "\n  - " + "\n  - ".join(rendered) if rendered else ""


def assert_monotonic(current: MigrationBaseline, base: MigrationBaseline) -> None:
    errors: list[str] = []
    if base.mode == "strict" and current.mode != "strict":
        errors.append("strict baseline cannot return to ratchet mode")
    added_sources = current.legacy_sources - base.legacy_sources
    if added_sources:
        errors.append(
            "legacy source baseline increased; migration baseline may only decrease:"
            + _render_items(added_sources)
        )
    added_references = current.transitional_references - base.transitional_references
    if added_references:
        errors.append(
            "legacy reference baseline increased; new imports/entrypoints are forbidden:"
            + _render_items(added_references)
        )
    if errors:
        raise MigrationRatchetError("RAT004 " + "\n".join(errors))


def _baseline_from_git(
    root: Path, baseline_path: Path, base_ref: str
) -> MigrationBaseline | None:
    relative = baseline_path.resolve().relative_to(root.resolve()).as_posix()
    valid_ref = subprocess.run(
        ["git", "cat-file", "-e", f"{base_ref}^{{commit}}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if valid_ref.returncode != 0:
        raise MigrationRatchetError(
            f"RAT004 cannot resolve PR base commit {base_ref!r}: {valid_ref.stderr.strip()}"
        )
    completed = subprocess.run(
        ["git", "show", f"{base_ref}:{relative}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise MigrationRatchetError(
            f"RAT004 base baseline {base_ref}:{relative} is invalid JSON: {exc}"
        ) from exc
    return _parse_baseline_payload(payload, source=f"{base_ref}:{relative}")


def _validate_ledger(root: Path) -> None:
    try:
        from scripts.check_backend_migration_ledger import (  # type: ignore[import-not-found]
            LedgerValidationError,
            validate_ledger,
        )
    except ModuleNotFoundError:
        from check_backend_migration_ledger import (  # type: ignore[no-redef]
            LedgerValidationError,
            validate_ledger,
        )
    try:
        validate_ledger(root)
    except (LedgerValidationError, OSError) as exc:
        raise MigrationRatchetError(f"RAT005 migration ledger validation failed: {exc}") from exc


def validate_ratchet(
    root: Path = ROOT,
    *,
    baseline_path: Path | None = None,
    base_ref: str | None = None,
) -> RatchetReport:
    root = root.resolve()
    path = (baseline_path or root / "docs" / "backend-migration-baseline.json").resolve()
    declared = load_baseline(path)
    actual = snapshot_repository(root)
    errors: list[str] = []

    missing_sources = actual.legacy_sources - declared.legacy_sources
    stale_sources = declared.legacy_sources - actual.legacy_sources
    if missing_sources or stale_sources:
        errors.append(
            "RAT002 legacy source baseline must exactly match the repository; "
            f"undeclared={_render_items(missing_sources) or ' none'}, "
            f"stale={_render_items(stale_sources) or ' none'}"
        )
    missing_references = actual.transitional_references - declared.transitional_references
    stale_references = declared.transitional_references - actual.transitional_references
    if missing_references or stale_references:
        errors.append(
            "RAT003 transitional reference baseline must exactly match executable imports/entrypoints; "
            f"undeclared={_render_items(missing_references) or ' none'}, "
            f"stale={_render_items(stale_references) or ' none'}"
        )
    if declared.mode == "strict" and (declared.legacy_sources or declared.transitional_references):
        errors.append("RAT006 strict mode requires empty legacy source and reference baselines")
    if errors:
        raise MigrationRatchetError("\n".join(errors))

    _validate_ledger(root)
    compared = False
    if base_ref:
        base = _baseline_from_git(root, path, base_ref)
        if base is not None:
            assert_monotonic(declared, base)
            compared = True

    return RatchetReport(
        mode=declared.mode,
        legacy_source_count=len(declared.legacy_sources),
        transitional_reference_count=len(declared.transitional_references),
        compared_to_base=compared,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--base-ref")
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    baseline_path = (args.baseline or root / "docs" / "backend-migration-baseline.json").resolve()

    try:
        if args.write_baseline:
            write_baseline(baseline_path, snapshot_repository(root))
        report = validate_ratchet(
            root,
            baseline_path=baseline_path,
            base_ref=args.base_ref or None,
        )
    except (MigrationRatchetError, OSError) as error:
        print("[BACKEND-MIGRATION-RATCHET] FAIL")
        print(error)
        return 1

    if not args.quiet:
        print("[BACKEND-MIGRATION-RATCHET] PASS")
        print(f"- mode: {report.mode}")
        print(f"- legacy Python sources: {report.legacy_source_count}")
        print(f"- transitional references: {report.transitional_reference_count}")
        print(f"- compared to PR base: {str(report.compared_to_base).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
