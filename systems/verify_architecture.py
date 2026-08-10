"""Static checks for the PR #8/#10 ownership contract during PR #9 migration."""

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
    SYSTEMS / "generator" / "feature" / "workbench.py",
    SYSTEMS / "generator" / "model" / "experiments.py",
    SYSTEMS / "generator" / "model" / "model_registry.py",
    SYSTEMS / "backend" / "diagnosis" / "artifact_provider.py",
    SYSTEMS / "backend" / "diagnosis" / "model_registry.py",
    SYSTEMS / "backend" / "diagnosis" / "predictor.py",
    SYSTEMS / "backend" / "diagnosis" / "evidence.py",
    ROOT / "api" / "ontology_dashboard" / "main.py",
    ROOT / "web" / "src",
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
        "generator": ("systems.backend",),
        "backend": ("systems.generator",),
    }
    for system_name, forbidden_prefixes in boundaries.items():
        for path in (SYSTEMS / system_name).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError as exc:
                errors.append(f"cannot parse {path.relative_to(ROOT)}: {exc}")
                continue
            for node in ast.walk(tree):
                for module in _module_names(node):
                    if any(module == prefix or module.startswith(f"{prefix}.") for prefix in forbidden_prefixes):
                        errors.append(f"cross-system direct import: {path.relative_to(ROOT)} imports {module}")


def check_product_api_dependency(errors: list[str]) -> None:
    api_root = ROOT / "api" / "ontology_dashboard"
    for path in api_root.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            for module in _module_names(node):
                if module == "systems.generator" or module.startswith("systems.generator."):
                    errors.append(f"product API imports generator implementation: {path.relative_to(ROOT)} imports {module}")


def check_artifact_injection(errors: list[str]) -> None:
    forbidden_fragments = (
        "../generator/model/model_store",
        "systems/generator/model/model_store",
    )
    for path in (SYSTEMS / "backend").rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for fragment in forbidden_fragments:
            if fragment in text:
                errors.append(f"hard-coded sibling artifact path in {path.relative_to(ROOT)}: {fragment}")
    env_text = (SYSTEMS / "backend" / ".env.example").read_text(encoding="utf-8")
    if "MODEL_ARTIFACT_URI=" not in env_text:
        errors.append("systems/backend/.env.example must define MODEL_ARTIFACT_URI")
    if "MODEL_STORE_DIR=" in env_text:
        errors.append("systems/backend/.env.example must not define MODEL_STORE_DIR")


def check_legacy_ml_is_compatibility_only(errors: list[str]) -> None:
    legacy = ROOT / "ml" / "src" / "factory_signal_ml"
    forbidden = ("joblib.dump", ".fit(", "predict_proba(")
    for name in ("training.py", "predictor.py", "evidence.py", "dataset.py"):
        text = (legacy / name).read_text(encoding="utf-8")
        for fragment in forbidden:
            if fragment in text:
                errors.append(f"legacy ML compatibility module still owns implementation: ml/src/factory_signal_ml/{name}")


def check_api_modeling_is_port_only(errors: list[str]) -> None:
    modeling = ROOT / "api" / "ontology_dashboard" / "modeling"
    forbidden = ("joblib.dump", ".fit(", "predict_proba(")
    for name in ("mapping.py", "features.py", "experiments.py", "registry.py"):
        text = (modeling / name).read_text(encoding="utf-8")
        for fragment in forbidden:
            if fragment in text:
                errors.append(
                    f"API modeling compatibility port still owns algorithmic implementation: "
                    f"api/ontology_dashboard/modeling/{name} contains {fragment}"
                )


def main() -> int:
    errors: list[str] = []
    check_required_structure(errors)
    check_cross_system_imports(errors)
    check_product_api_dependency(errors)
    check_artifact_injection(errors)
    check_legacy_ml_is_compatibility_only(errors)
    check_api_modeling_is_port_only(errors)
    if errors:
        print("[ARCHITECTURE-CHECK] FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("[ARCHITECTURE-CHECK] PASS")
    print("- generator owns semantic/feature/training and Model Artifact publication")
    print("- backend/diagnosis owns runtime inference and Result Artifact/Evidence")
    print("- generator/backend direct Python imports are absent")
    print("- product API does not import generator implementation")
    print("- API modeling modules retain compatibility ports only; ML algorithms live under systems/")
    print("- Model Artifact location is injected through MODEL_ARTIFACT_URI")
    print("- root api/web remain explicit PR #9 migration hosts, not ownership boundaries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
