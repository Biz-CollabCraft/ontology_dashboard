"""Canonical systems/backend ASGI entrypoint.

The full Week 2 application composition now lives inside ``systems/backend``.
This module intentionally exposes the same application object as
``ontology_dashboard.app`` so local, Docker and CI execution all use the
systems-owned runtime rather than a second scaffold application.
"""

from ontology_dashboard.app import app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
