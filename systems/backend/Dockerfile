FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

COPY ml /build/ml
COPY systems/backend /build/backend

ARG API_EXTRAS=""
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir --prefix=/install /build/ml \
    && if [ -n "$API_EXTRAS" ]; then \
         python -m pip install --no-cache-dir --prefix=/install "/build/backend[$API_EXTRAS]"; \
       else \
         python -m pip install --no-cache-dir --prefix=/install /build/backend; \
       fi

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/ontology \
    TMPDIR=/tmp \
    ONTOLOGY_DASHBOARD_MIGRATION_ROOT=/app/systems/backend/migrations

RUN groupadd --gid 10001 ontology \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin ontology

COPY --from=builder /install /usr/local

WORKDIR /app
COPY --chown=10001:10001 systems/__init__.py /app/systems/__init__.py
COPY --chown=10001:10001 systems/backend /app/systems/backend
COPY --chown=10001:10001 schemas /app/schemas
COPY --chown=10001:10001 prompts /app/prompts
COPY --chown=10001:10001 data/fixtures /app/data/fixtures

USER 10001

EXPOSE 8000

STOPSIGNAL SIGTERM
CMD ["python", "-m", "uvicorn", "ontology_dashboard.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
