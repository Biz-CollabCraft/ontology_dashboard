from __future__ import annotations

import sys

import pytest
from fastapi import FastAPI

from systems.backend.app.main import app as canonical_app


HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def _openapi_route_surface(app: FastAPI) -> list[tuple[str, str]]:
    schema = app.openapi()
    return sorted(
        (path, method.lower())
        for path, operations in schema.get("paths", {}).items()
        for method in operations
        if method.lower() in HTTP_METHODS
    )


def _legacy_compatibility_app() -> FastAPI:
    """Observe the legacy app already loaded by the transitional canonical root.

    Do not introduce a new executable legacy import from this regression test: the
    migration ratchet intentionally forbids increasing transitional references. Once
    #64 makes the canonical composition root independent, the legacy module will no
    longer be present here and this comparison can disappear with #65/#66.
    """

    module = sys.modules.get("ontology_dashboard.app")
    if module is None:
        pytest.skip(
            "legacy compatibility package is no longer loaded by the canonical root; "
            "replace this transitional comparison with the #65/#66 canonical strict gate"
        )
    legacy_app = getattr(module, "app", None)
    assert isinstance(legacy_app, FastAPI)
    return legacy_app


def test_canonical_entrypoint_exposes_required_route_surface() -> None:
    canonical_surface = _openapi_route_surface(canonical_app)

    assert canonical_surface
    assert ("/health", "get") in canonical_surface


def test_legacy_compatibility_entrypoint_matches_canonical_route_surface() -> None:
    # This comparison is intentionally transitional. app.main is still an alias over
    # the legacy composition root today; #64 owns the composition-root inversion,
    # #65 removes the compatibility package, and #66 installs the final strict gate.
    legacy_surface = _openapi_route_surface(_legacy_compatibility_app())

    assert legacy_surface == _openapi_route_surface(canonical_app)
