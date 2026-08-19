"""Static architecture checks for the merged PR #8/#10 system contract.

This verifier uses only the Python standard library so it can run before
system-specific dependencies are installed. PR #11 additionally verifies that
the imported PR #9 runtime has converged into systems/backend and
systems/frontend instead of remaining in root api/web hosts.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYSTEMS = ROOT / "systems"

BACKEND_COMPOSITION_ROOT_FILES = {
    Path("main.py"),
    Path("dependencies.py"),
    Path("settings.py"),
    Path("health.py"),
    Path("error_handlers.py"),
}
DOMAIN_IMPLEMENTATION_SUFFIXES = ("_service", "_repository", "_adapter")

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
    SYSTEMS / "backend" / "app" / "common" / "runtime_settings.py",
    SYSTEMS / "backend" / "app" / "common" / "rate_limit.py",
    SYSTEMS / "backend" / "app" / "infra" / "db" / "pool.py",
    SYSTEMS / "backend" / "app" / "infra" / "db" / "connection.py",
    SYSTEMS / "backend" / "app" / "infra" / "storage" / "object_storage.py",
    SYSTEMS / "backend" / "app" / "infra" / "external" / "project3" / "client.py",
    SYSTEMS / "backend" / "app" / "infra" / "llm" / "provider.py",
    SYSTEMS / "backend" / "app" / "main.py",
    SYSTEMS / "backend" / "ontology_dashboard" / "main.py",
    SYSTEMS / "backend" / "migrations",
    SYSTEMS / "backend" / "pyproject.toml",
    SYSTEMS / "frontend" / "src",
    SYSTEMS / "frontend" / "package.json",
    SYSTEMS / "frontend" / "vite.config.ts",
)


def _module_names(node: ast.AST, *, package: str | None = None) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if node.level and package:
            package_parts = package.split(".")
            keep = len(package_parts) - node.level + 1
            if keep <= 0:
                return [module] if module else []
            resolved_parts = package_parts[:keep]
            if module:
                resolved_parts.extend(module.split("."))
                resolved = ".".join(part for part in resolved_parts if part)
                return [resolved] if resolved else []

            resolved_modules: list[str] = []
            for alias in node.names:
                alias_parts = list(resolved_parts)
                if alias.name != "*":
                    alias_parts.extend(alias.name.split("."))
                resolved = ".".join(part for part in alias_parts if part)
                if resolved:
                    resolved_modules.append(resolved)
            return resolved_modules
        if module:
            return [module]
    return []


def _backend_app_package(path: Path, app_root: Path) -> str:
    parent = path.parent.relative_to(app_root)
    return ".".join(("app", *parent.parts))


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


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    caught = handler.type
    if isinstance(caught, ast.Name):
        return caught.id in {"ImportError", "ModuleNotFoundError"}
    if isinstance(caught, ast.Tuple):
        return any(
            isinstance(item, ast.Name) and item.id in {"ImportError", "ModuleNotFoundError"}
            for item in caught.elts
        )
    return False


def _is_masking_fallback(value: ast.AST) -> bool:
    if isinstance(value, ast.Constant):
        return value.value is None
    if isinstance(value, (ast.Dict, ast.List, ast.Set, ast.Tuple)):
        return len(value.elts if hasattr(value, "elts") else value.keys) == 0
    return False


def check_generator_package_import_masking(errors: list[str]) -> None:
    """Reject package facades that turn required import failures into fake availability.

    Optional dependency detection inside implementation modules is allowed. The unsafe
    pattern is a package ``__init__.py`` catching ImportError/ModuleNotFoundError and
    publishing ``None`` or an empty collection instead, because a shallow ``import``
    smoke then succeeds while required Generator symbols are unusable.
    """

    generator_root = SYSTEMS / "generator"
    for path in generator_root.rglob("__init__.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            errors.append(f"cannot parse {path.relative_to(ROOT)}: {exc}")
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            for handler in node.handlers:
                if not _catches_import_error(handler):
                    continue
                for handler_node in ast.walk(handler):
                    if not isinstance(handler_node, (ast.Assign, ast.AnnAssign)):
                        continue
                    value = handler_node.value
                    if value is not None and _is_masking_fallback(value):
                        errors.append(
                            "generator package facade masks a required import failure: "
                            f"{path.relative_to(ROOT)} catches ImportError/ModuleNotFoundError "
                            "and substitutes None or an empty collection"
                        )
                        break


def check_backend_domain_dependencies(errors: list[str]) -> None:
    app_root = SYSTEMS / "backend" / "app"
    for path in app_root.glob("*/*.py"):
        current_domain = path.parent.name
        package = _backend_app_package(path, app_root)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            for module in _module_names(node, package=package):
                parts = module.split(".")
                if len(parts) < 3 or parts[0] != "app":
                    continue
                target_domain = parts[1]
                if target_domain == current_domain:
                    continue
                if parts[-1].endswith(DOMAIN_IMPLEMENTATION_SUFFIXES):
                    errors.append(
                        f"backend domain implementation import: {path.relative_to(ROOT)} imports {module}"
                    )


def check_backend_domain_first_ratchet(errors: list[str]) -> None:
    """Prevent Phase 1 physical convergence from drifting back toward legacy layout."""

    app_root = SYSTEMS / "backend" / "app"
    forbidden_top_level = {
        "routers",
        "adapters",
        "orchestration",
        "integrations",
        "modeling",
        "domain_packs",
        "predictive_maintenance_runtime",
        "closed_loop",
    }
    for name in sorted(forbidden_top_level):
        if (app_root / name).exists():
            errors.append(f"backend technical top-level package is forbidden: systems/backend/app/{name}")

    allowed_legacy_imports = {
        Path("systems/backend/app/main.py"): {"ontology_dashboard.app"},
        Path("systems/backend/app/diagnosis/model_registry.py"): {
            "ontology_dashboard.modeling.models"
        },
    }

    for path in app_root.rglob("*.py"):
        relative = path.relative_to(ROOT)
        relative_to_app = path.relative_to(app_root)
        is_composition_root = relative_to_app in BACKEND_COMPOSITION_ROOT_FILES
        package = _backend_app_package(path, app_root)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            errors.append(f"cannot parse {relative}: {exc}")
            continue

        domain = relative_to_app.parts[0]
        for node in ast.walk(tree):
            for module in _module_names(node, package=package):
                if module == "ontology_dashboard" or module.startswith("ontology_dashboard."):
                    allowed = allowed_legacy_imports.get(relative, set())
                    if module not in allowed:
                        errors.append(
                            f"new canonical-to-legacy Backend import is forbidden: {relative} imports {module}"
                        )

                # Phase #64 composition modules are intentionally allowed to
                # assemble FastAPI and concrete Infra adapters. Keep the legacy
                # import ratchet above active until Phase #65 removes it.
                if is_composition_root:
                    continue

                if domain == "common" and module.startswith("app.") and not module.startswith(
                    "app.common"
                ):
                    errors.append(f"backend common reverse dependency: {relative} imports {module}")

                if domain == "infra":
                    if module == "ontology_dashboard" or module.startswith("ontology_dashboard."):
                        errors.append(f"backend infra imports legacy package: {relative} imports {module}")
                    parts = module.split(".")
                    if len(parts) >= 3 and parts[0] == "app" and parts[1] not in {
                        "common",
                        "infra",
                    } and parts[-1].endswith(DOMAIN_IMPLEMENTATION_SUFFIXES):
                        errors.append(
                            f"backend infra imports domain implementation: {relative} imports {module}"
                        )

                if domain not in {"common", "infra"} and module.startswith("app.infra"):
                    errors.append(f"backend domain imports infra implementation: {relative} imports {module}")

                if (
                    domain not in {"common", "infra"}
                    and not path.name.endswith("_router.py")
                    and (module == "fastapi" or module.startswith("fastapi."))
                ):
                    errors.append(f"backend domain layer imports FastAPI: {relative} imports {module}")


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
    review_workflow_text = (ROOT / ".github" / "workflows" / "code-review.yml").read_text(
        encoding="utf-8"
    )
    review_helper_text = (ROOT / "scripts" / "ci" / "ai_review.py").read_text(
        encoding="utf-8"
    )
    comment_review_workflow_text = (
        ROOT / ".github" / "workflows" / "pr-comment-review.yml"
    ).read_text(encoding="utf-8")
    required_fragments = (
        "docker compose -f infra/docker-compose.yml build api web",
        "docker compose -f infra/docker-compose.yml up -d api web",
        "http://127.0.0.1:8100/health",
        "http://127.0.0.1:3100/health/live",
        "from ontology_dashboard.dependencies import get_artifact_governance_service",
        'assert os.getuid() == 10001',
        'probe_key = "ci/docker-runtime/artifact-storage-smoke.txt"',
        'assert service.backend.get(probe_key) == payload',
        'id: docker_runtime',
        'echo "verified=true" >> "$GITHUB_OUTPUT"',
        'docker_runtime_verified: ${{ needs.docker_runtime.outputs.verified }}',
        'frontend_unit_verified: ${{ needs.fast_validation.outputs.frontend_unit_verified }}',
        'mvp_e2e_verified: ${{ needs.mvp_e2e.outputs.verified }}',
        'id: frontend_unit',
        'npm test',
        'npm ci --no-audit --no-fund',
        'cache: pip',
        'cache: npm',
        'image: mcr.microsoft.com/playwright:v1.62.1-noble',
        'Verify Playwright Chromium from official image',
        'npx playwright --version',
        'chromium.executablePath()',
        'id: mvp_e2e',
        'PLAYWRIGHT_PYTHON_BIN: python',
        'npm run test:e2e:mvp',
        'BACKEND_MIGRATION_BASE_REF: ${{ github.event.pull_request.base.sha }}',
        'python -m unittest tests.test_backend_migration_ratchet',
        'group: architecture-${{ github.event.pull_request.number || github.ref }}',
        'cancel-in-progress: true',
        'needs: [changes, fast_validation, mvp_e2e, docker_runtime]',
        'assert_required_success "MVP Playwright E2E"',
        'assert_required_success "Docker runtime smoke"',
        'python -m unittest tests.test_backend_domain_first_architecture',
        'needs: architecture',
        '${{ always() &&',
        'uses: ./.github/workflows/code-review.yml',
        'docker_runtime_verified: ${{ needs.architecture.outputs.docker_runtime_verified }}',
        'frontend_unit_verified: ${{ needs.architecture.outputs.frontend_unit_verified }}',
        'mvp_e2e_verified: ${{ needs.architecture.outputs.mvp_e2e_verified }}',
        'workflow_run_id: ${{ github.run_id }}',
        "docker compose -f infra/docker-compose.yml down --volumes --remove-orphans",
    )
    for fragment in required_fragments:
        if fragment not in workflow_text:
            errors.append(f"architecture CI is missing Docker runtime smoke coverage: {fragment}")

    if "npx playwright install --with-deps chromium" in workflow_text:
        errors.append(
            "Playwright MVP E2E must use the official Playwright image instead of "
            "installing operating-system dependencies through apt during CI"
        )

    review_required_fragments = (
        "workflow_call:",
        "Collect deterministic CI and human feedback evidence",
        'ARCHITECTURE_JOB_RESULT: ${{ inputs.architecture_result }}',
        'WORKFLOW_RUN_ID: ${{ inputs.workflow_run_id }}',
        '"repos/${GITHUB_REPOSITORY}/actions/jobs/${architecture_job_id}/logs"',
        'DOCKER_RUNTIME_VERIFIED: ${{ inputs.docker_runtime_verified }}',
        'FRONTEND_UNIT_VERIFIED: ${{ inputs.frontend_unit_verified }}',
        'MVP_E2E_VERIFIED: ${{ inputs.mvp_e2e_verified }}',
        "Select base-trusted reviewer implementation",
        'git show "${BASE_SHA}:scripts/ci/ai_review.py" > /tmp/trusted-ai-review.py',
        'REVIEWER_CODE_SOURCE=base:scripts/ci/ai_review.py',
        "python3 /tmp/trusted-ai-review.py prepare-pr",
        "--architecture-log /tmp/architecture-job.log",
        "--policy-output /tmp/review-policy.json",
        "python3 /tmp/trusted-ai-review.py parse-pr",
    )
    for fragment in review_required_fragments:
        if fragment not in review_workflow_text:
            errors.append(
                "Gemini review must consume completed architecture/Docker evidence before starting: "
                f"missing {fragment}"
            )

    review_helper_required_fragments = (
        "def build_verified_evidence(",
        'if args.architecture_result != "success":',
        'ceiling = "Not Ready"',
        '"required": _bool(args.docker_required)',
        '"required": _bool(args.frontend_required)',
        '"required": _bool(args.mvp_required)',
        "def _enforce_readiness(",
        "VERIFIED_EVIDENCE",
        "Do NOT emit a PASS matrix",
        "TRUSTED_BASE_CONTEXT",
    )
    for fragment in review_helper_required_fragments:
        if fragment not in review_helper_text:
            errors.append(
                "Gemini project-aware review helper is missing deterministic evidence/trust guard: "
                f"{fragment}"
            )

    comment_review_required_fragments = (
        "issue_comment:",
        "pull_request_review_comment:",
        "pull_request_review:",
        "Checkout trusted default branch reviewer code",
        "python3 scripts/ci/ai_review.py event-info",
        "python3 scripts/ci/ai_review.py repo-gate",
        "needs.gate.outputs.same_repo == 'true'",
        "Fetch PR objects without checking out untrusted head code",
        "python3 scripts/ci/ai_review.py idempotency",
        "steps.idem.outputs.action != 'noop'",
        "Authenticate to Google Cloud with GitHub OIDC",
        "Publish or update one response for the source comment",
    )
    for fragment in comment_review_required_fragments:
        if fragment not in comment_review_workflow_text:
            errors.append(
                "PR comment reviewer is missing trusted-context/loop/idempotency guard: "
                f"{fragment}"
            )

    if "pull_request:" in review_workflow_text.split("jobs:", 1)[0]:
        errors.append(
            ".github/workflows/code-review.yml must not run directly on pull_request; "
            "it must be called after the architecture job completes"
        )

    if "needs.architecture.result == 'success'" in workflow_text:
        errors.append(
            "Gemini review must run after architecture completes even when architecture fails, "
            "so it can explain the failure and remediation"
        )

    frontend_package_text = (SYSTEMS / "frontend" / "package.json").read_text(encoding="utf-8")
    if '"test:e2e:mvp": "playwright test e2e/mvp-frontend-convergence.spec.ts --project=chromium"' not in frontend_package_text:
        errors.append("frontend package scripts must expose the critical MVP Playwright smoke")

    playwright_text = (SYSTEMS / "frontend" / "playwright.config.ts").read_text(encoding="utf-8")
    if 'process.env.PLAYWRIGHT_PYTHON_BIN ?? "../../.venv/bin/python"' not in playwright_text:
        errors.append(
            "Playwright backend bootstrap must allow CI to inject a Python executable instead of requiring a local .venv"
        )


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


def check_backend_migration_ledger(errors: list[str]) -> None:
    checker = ROOT / "scripts" / "check_backend_migration_ledger.py"
    completed = subprocess.run(
        [sys.executable, str(checker), "--root", str(ROOT), "--quiet"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stdout or completed.stderr).strip()
        errors.append(f"backend migration ledger is incomplete or ambiguous: {detail}")


def check_backend_migration_ratchet(errors: list[str]) -> None:
    checker = ROOT / "scripts" / "check_backend_migration_ratchet.py"
    command = [sys.executable, str(checker), "--root", str(ROOT), "--quiet"]
    base_ref = os.environ.get("BACKEND_MIGRATION_BASE_REF", "").strip()
    if base_ref:
        command.extend(("--base-ref", base_ref))
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stdout or completed.stderr).strip()
        errors.append(f"backend migration ratchet failed: {detail}")


def main() -> int:
    errors: list[str] = []
    check_required_structure(errors)
    check_cross_system_imports(errors)
    check_generator_package_import_masking(errors)
    check_backend_domain_dependencies(errors)
    check_backend_domain_first_ratchet(errors)
    check_product_api_dependency(errors)
    check_artifact_injection(errors)
    check_legacy_ml_is_compatibility_only(errors)
    check_api_modeling_is_port_only(errors)
    check_runtime_hosts_converged(errors)
    check_frontend_container_converged(errors)
    check_backend_runtime_root_converged(errors)
    check_docker_runtime_ci(errors)
    check_git_conflict_markers(errors)
    check_backend_migration_ledger(errors)
    check_backend_migration_ratchet(errors)

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
    print("- Generator package facades do not mask required import failures")
    print("- backend domains do not import other domains' implementation modules")
    print("- Backend Phase 1 common/infra and canonical-to-legacy import ratchets are enforced")
    print("- product API has no static generator implementation import")
    print("- legacy ML/backend modeling compatibility paths are ports, not ML owners")
    print("- Model Artifact location is injected through MODEL_ARTIFACT_URI")
    print("- Backend migration ledger covers every legacy Python source exactly once with DEFER=0")
    print("- Backend migration baseline is exact and cannot increase from the PR base")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
