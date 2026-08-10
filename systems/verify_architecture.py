"""Static architecture checks for the systems/ scaffold.

This script intentionally uses only the Python standard library so it can run
before installing system-specific dependencies.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYSTEMS = ROOT / "systems"

REQUIRED_PATHS = (
    SYSTEMS / "generator" / "extraction",
    SYSTEMS / "generator" / "ontology_mapping",
    SYSTEMS / "generator" / "topology",
    SYSTEMS / "generator" / "feature",
    SYSTEMS / "generator" / "model" / "model_registry.py",
    SYSTEMS / "backend" / "app" / "diagnosis" / "diagnosis_service.py",
    SYSTEMS / "backend" / "app" / "main.py",
    SYSTEMS / "frontend" / "src",
)


def _module_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.module:
        return [node.module]
    return []


def check_required_structure(errors: list[str]) -> None:
    for path in REQUIRED_PATHS:
        if not path.exists():
            errors.append(f"missing required architecture path: {path.relative_to(ROOT)}")


def check_cross_system_imports(errors: list[str]) -> None:
    boundaries = {
        "generator": ("systems.backend", "backend"),
        "backend": ("systems.generator", "generator"),
    }
    for system_name, forbidden_prefixes in boundaries.items():
        system_root = SYSTEMS / system_name
        for path in system_root.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError as exc:
                errors.append(f"cannot parse {path.relative_to(ROOT)}: {exc}")
                continue
            for node in ast.walk(tree):
                for module in _module_names(node):
                    if any(
                        module == prefix or module.startswith(f"{prefix}.")
                        for prefix in forbidden_prefixes
                    ):
                        errors.append(
                            "cross-system direct import: "
                            f"{path.relative_to(ROOT)} imports {module}"
                        )


def check_backend_domain_dependencies(errors: list[str]) -> None:
    app_root = SYSTEMS / "backend" / "app"
    implementation_suffixes = ("_service", "_repository", "_adapter")
    for path in app_root.glob("*/*.py"):
        current_domain = path.parent.name
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            for module in _module_names(node):
                parts = module.split(".")
                if len(parts) < 3 or parts[0] != "app":
                    continue
                target_domain = parts[1]
                if target_domain == current_domain:
                    continue
                if parts[-1].endswith(implementation_suffixes):
                    errors.append(
                        "backend domain implementation import: "
                        f"{path.relative_to(ROOT)} imports {module}"
                    )


def check_artifact_injection(errors: list[str]) -> None:
    backend_root = SYSTEMS / "backend"
    forbidden_fragments = (
        "../generator/model/model_store",
        "systems/generator/model/model_store",
    )
    for path in backend_root.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for fragment in forbidden_fragments:
            if fragment in text:
                errors.append(
                    f"hard-coded sibling artifact path in {path.relative_to(ROOT)}: {fragment}"
                )

    env_example = backend_root / ".env.example"
    env_text = env_example.read_text(encoding="utf-8")
    if "MODEL_ARTIFACT_URI=" not in env_text:
        errors.append("systems/backend/.env.example must define MODEL_ARTIFACT_URI")
    if "MODEL_STORE_DIR=" in env_text:
        errors.append("systems/backend/.env.example must not define MODEL_STORE_DIR")


def check_git_conflict_markers(errors: list[str]) -> None:
    conflict_prefixes = ("<<<<<<<", "=======", ">>>>>>>")
    search_dirs = (ROOT / "docs", SYSTEMS)
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for path in search_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix in (".pyc", ".png", ".jpg", ".zip", ".tar", ".gz"):
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for line_idx, line in enumerate(content.splitlines(), start=1):
                if line.startswith(conflict_prefixes):
                    errors.append(
                        f"git conflict marker found in {path.relative_to(ROOT)}:{line_idx}: {line.strip()}"
                    )


def main() -> int:
    errors: list[str] = []
    check_required_structure(errors)
    check_cross_system_imports(errors)
    check_backend_domain_dependencies(errors)
    check_artifact_injection(errors)
    check_git_conflict_markers(errors)

    if errors:
        print("[ARCHITECTURE-CHECK] FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print("[ARCHITECTURE-CHECK] PASS")
    print("- required systems/domain scaffold exists")
    print("- generator/backend direct Python imports are absent")
    print("- backend domains do not import other domains' service/repository/adapter implementations")
    print("- backend artifact location is injected through MODEL_ARTIFACT_URI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
