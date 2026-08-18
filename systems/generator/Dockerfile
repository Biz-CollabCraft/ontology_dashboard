FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ONTOLOGY_DASHBOARD_PROJECT_ROOT=/app

WORKDIR /app

COPY systems/generator/requirements.txt /tmp/generator-requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r /tmp/generator-requirements.txt

# Generator is its own deployment unit. Backend source is intentionally not
# copied into this image; shared contracts are repository-level data only.
COPY systems/__init__.py /app/systems/__init__.py
COPY systems/generator /app/systems/generator

RUN groupadd --gid 10002 generator \
    && useradd --uid 10002 --gid 10002 --create-home --shell /usr/sbin/nologin generator \
    && mkdir -p /data/source /data/preprocessed /data/ontology /data/models /artifacts /logs \
    && chown -R 10002:10002 /data /artifacts /logs

USER 10002

ENTRYPOINT ["python", "-m", "systems.generator.entrypoint"]
CMD ["run"]
