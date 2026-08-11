"""Static architecture checks for the merged PR #8/#10 system contract.

This verifier uses only the Python standard library so it can run before
system-specific dependencies are installed. PR #11 additionally verifies that
the imported PR #9 runtime has converged into systems/backend and
systems/frontend instead of remaining in root api/web hosts.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYSTEMS = ROOT / "systems"

REQUIRED_PATHS = (
    SYSTEMS / "generator" / "extraction" / "extraction_service.py",
    SYSTEMS / "generator" / "ontology_mapping" / "mapping_service.py",
    SYSTEMS / "generator" / "ontology_mapping" / "workbench.py",
    SYSTEMS / "generator" / "topology" / "topology_service.py",
    SYSTEMS / "generator" / "feature" / "dataset.py",
    SYSTEMS / "generator" / "feature" / "workbench.py",
    SYSTEMS / "generator" / "model" / "model_training.py",
    SYSTEMS / "generator" / "model" / "experiments.py",
    SYSTEMS / "generator" / "model" / "model_registry.py",
    SYSTEMS / "backend" / "app" / "diagnosis" / "diagnosis_service.py",
    SYSTEMS / "backend" / "app" / "diagnosis" / "artifact_provider.py",
    SYSTEMS / "backend" / "app" / "diagnosis" / "model_registry.py",
    SYSTEMS / "backend" / "app" / "diagnosis" / "predictor.py",
    SYSTEMS / "backend" / "app" / "diagnosis" / "evidence.py",
    SYSTEMS / "backend" / "app" / "main.py",
    SYSTEMS / "backend" / "ontology_dashboard" / "main.py",
    SYSTEMS / "backend" / "migrations",
    SYSTEMS / "backend" / "pyproject.toml",
    SYSTEMS / "frontend" / "src",
    SYSTEMS / "frontend" / "package.json",
    SYSTEMS / "frontend" / "vite.config.ts",
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
                        f"backend domain implementation import: {path.relative_to(ROOT)} imports {module}"
                    )


def check_product_api_dependency(errors: list[str]) -> None:
    api_root = SYSTEMS / "backend" / "ontology_dashboard"
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
                errors.append(f"hard-coded sibling artifact path in {path.relative_to(ROOT)}: {fragment}")

    env_text = (backend_root / ".env.example").read_text(encoding="utf-8")
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
    modeling = SYSTEMS / "backend" / "ontology_dashboard" / "modeling"
    forbidden = ("joblib.dump", ".fit(", "predict_proba(")
    for name in ("mapping.py", "features.py", "experiments.py", "registry.py"):
        text = (modeling / name).read_text(encoding="utf-8")
        for fragment in forbidden:
            if fragment in text:
                errors.append(
                    f"Backend modeling compatibility port still owns algorithmic implementation: "
                    f"systems/backend/ontology_dashboard/modeling/{name} contains {fragment}"
                )


def check_runtime_hosts_converged(errors: list[str]) -> None:
    for legacy_root in (ROOT / "api", ROOT / "web"):
        if legacy_root.exists():
            errors.append(
                f"legacy root runtime host still exists after systems convergence: {legacy_root.relative_to(ROOT)}"
            )


def check_frontend_container_converged(errors: list[str]) -> None:
    dockerignore_lines = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    required_ignored_paths = {
        "systems/frontend/node_modules",
        "systems/frontend/dist",
        "systems/frontend/test-results",
        "systems/frontend/playwright-report",
    }
    for path in sorted(required_ignored_paths - dockerignore_lines):
        errors.append(f"frontend Docker build artifact is not ignored: {path}")

    stale_ignored_paths = {
        "web/node_modules",
        "web/dist",
        "web/test-results",
        "web/playwright-report",
    }
    for path in sorted(stale_ignored_paths & dockerignore_lines):
        errors.append(f"legacy frontend Docker ignore path remains after systems convergence: {path}")

    compose_text = (ROOT / "infra" / "docker-compose.yml").read_text(encoding="utf-8")
    if '${WEB_PORT:-3100}:8080' not in compose_text:
        errors.append("infra/docker-compose.yml web service must publish host WEB_PORT to container port 8080")

    dockerfile_text = (SYSTEMS / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    if "EXPOSE 8080" not in dockerfile_text:
        errors.append("systems/frontend/Dockerfile must expose nginx runtime port 8080")
    for fragment in (
        "WORKDIR /workspace/systems/frontend",
        "COPY docs /workspace/docs",
        "COPY --from=build /workspace/systems/frontend/dist /usr/share/nginx/html",
    ):
        if fragment not in dockerfile_text:
            errors.append(
                "systems/frontend/Dockerfile must preserve repository-relative docs imports: "
                f"missing {fragment}"
            )

    nginx_text = (SYSTEMS / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    if "listen 8080;" not in nginx_text:
        errors.append("systems/frontend/nginx.conf must listen on container port 8080")


def check_backend_runtime_root_converged(errors: list[str]) -> None:
    dockerfile_text = (SYSTEMS / "backend" / "Dockerfile").read_text(encoding="utf-8")
    if "ONTOLOGY_DASHBOARD_PROJECT_ROOT=/app" not in dockerfile_text:
        errors.append(
            "systems/backend/Dockerfile must pin ONTOLOGY_DASHBOARD_PROJECT_ROOT=/app "
            "for non-editable package installs"
        )
    for fragment in (
        "mkdir -p /app/data/local /app/.runtime/object-storage",
        "chown -R 10001:10001 /app/data/local /app/.runtime",
    ):
        if fragment not in dockerfile_text:
            errors.append(
                "systems/backend/Dockerfile must provision non-root writable runtime state: "
                f"missing {fragment}"
            )

    runtime_files = (
        SYSTEMS / "backend" / "ontology_dashboard" / "dependencies.py",
        SYSTEMS / "backend" / "ontology_dashboard" / "application.py",
        SYSTEMS / "backend" / "ontology_dashboard" / "routers" / "system.py",
        SYSTEMS / "backend" / "ontology_dashboard" / "routers" / "platform.py",
    )
    forbidden_fragments = (
        "Path(__file__).resolve().parents[3]",
        "Path(__file__).resolve().parents[4]",
    )
    for path in runtime_files:
        text = path.read_text(encoding="utf-8")
        for fragment in forbidden_fragments:
            if fragment in text:
                errors.append(
                    "backend runtime asset lookup depends on installed package depth: "
                    f"{path.relative_to(ROOT)} contains {fragment}"
                )


def check_docker_runtime_ci(errors: list[str]) -> None:
    workflow_text = (ROOT / ".github" / "workflows" / "architecture.yml").read_text(
        encoding="utf-8"
    )
    required_fragments = (
        "docker compose -f infra/docker-compose.yml build api web",
        "docker compose -f infra/docker-compose.yml up -d api web",
        "http://127.0.0.1:8100/health",
        "http://127.0.0.1:3100/health/live",
        "from ontology_dashboard.dependencies import get_artifact_governance_service",
        'assert os.getuid() == 10001',
        'probe_key = "ci/docker-runtime/artifact-storage-smoke.txt"',
        'assert service.backend.get(probe_key) == payload',
        "docker compose -f infra/docker-compose.yml down --volumes --remove-orphans",
    )
    for fragment in required_fragments:
        if fragment not in workflow_text:
            errors.append(f"architecture CI is missing Docker runtime smoke coverage: {fragment}")


def check_git_conflict_markers(errors: list[str]) -> None:
    conflict_prefixes = ("<<<<<<<", "=======", ">>>>>>>")
    ignored_parts = {"node_modules", "dist", ".venv", "__pycache__", ".git"}
    for search_dir in (ROOT / "docs", SYSTEMS):
        if not search_dir.exists():
            continue
        for path in search_dir.rglob("*"):
            if any(part in ignored_parts for part in path.relative_to(ROOT).parts):
                continue
            if not path.is_file() or path.suffix in (".pyc", ".png", ".jpg", ".zip", ".tar", ".gz"):
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
    check_product_api_dependency(errors)
    check_artifact_injection(errors)
    check_legacy_ml_is_compatibility_only(errors)
    check_api_modeling_is_port_only(errors)
    check_runtime_hosts_converged(errors)
    check_frontend_container_converged(errors)
    check_backend_runtime_root_converged(errors)
    check_docker_runtime_ci(errors)
    check_git_conflict_markers(errors)

    if errors:
        print("[ARCHITECTURE-CHECK] FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print("[ARCHITECTURE-CHECK] PASS")
    print("- PR #10 required systems/domain structure exists")
    print("- PR #11 API/frontend runtime hosts are physically converged under systems/")
    print("- frontend Docker context ignores and Compose/nginx runtime port are converged")
    print("- backend runtime asset root is explicit and independent of site-packages depth")
    print("- architecture CI builds and boots backend/frontend Docker runtime hosts")
    print("- generator owns semantic/feature/training and Model Artifact publication")
    print("- backend diagnosis owns runtime inference and Result Artifact/Evidence")
    print("- generator/backend direct Python imports are absent")
    print("- backend domains do not import other domains' implementation modules")
    print("- product API has no static generator implementation import")
    print("- legacy ML/backend modeling compatibility paths are ports, not ML owners")
    print("- Model Artifact location is injected through MODEL_ARTIFACT_URI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
