"""Immutable owner Context versions and separate Evidence bindings."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import ValidationError as SchemaValidationError
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.infra.db.connection import tenant_connection
from app.operations.operational_context_contract import (
    OperationalRequestIdentity, OperationalScope, OperationalContextEnvelope,
    OperationalContextStatus, FreshnessMetadata, FreshnessState,
)
from app.operations.operational_context_versions.registry import MODELS, validate_payload

DOMAINS = (*MODELS, 'planning')
SCOPE_FIELDS = ('organization_id', 'project_id', 'workspace_id', 'asset_id')
TIME_FIELDS = ('source_updated_at', 'valid_from', 'valid_to')
SOURCE_FIELDS = (
    'owner_domain', *SCOPE_FIELDS, 'source_version', 'schema_id', 'schema_version',
    *TIME_FIELDS, 'source_ref', 'source_classification', 'max_age_seconds',
)
# These are Event projections, not changes to the owner production plan.
PLANNING_BINDING_FIELDS = frozenset({
    'event_impact', 'production_impact', 'load_level', 'runtime_hours_7d', 'limitations',
})


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def normalized_times(record):
    result = dict(record)
    for key in TIME_FIELDS:
        value = result[key]
        if not isinstance(value, datetime):
            value = datetime.fromisoformat(value)
        result[key] = value.astimezone(timezone.utc).isoformat()
    return result


class ContextSnapshot(BaseModel):
    """Import envelope; source data and Event projection are persisted separately."""
    model_config = ConfigDict(extra='forbid')
    organization_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    owner_domain: str
    source_version: str = Field(min_length=1, max_length=240)
    schema_id: str = ''  # Legacy manifests resolve explicitly to the frozen v1 contract.
    schema_version: int = Field(default=1, ge=1)
    source_ref: str = Field(min_length=1)
    source_classification: str = Field(pattern='^(synthetic_demo_context|owner_system)$')
    source_updated_at: datetime
    valid_from: datetime
    valid_to: datetime
    max_age_seconds: int = Field(default=172800, ge=0, le=31536000)
    evidence_snapshot_id: str | None = None
    payload: dict[str, Any]

    @model_validator(mode='after')
    def validate_snapshot(self):
        for name in TIME_FIELDS:
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f'{name} must include timezone')
        if self.valid_from >= self.valid_to or self.source_updated_at >= self.valid_to:
            raise ValueError('invalid snapshot time interval')
        if self.owner_domain not in DOMAINS:
            raise ValueError('unsupported owner domain')
        expected_schema = f'operational-context.{self.owner_domain}'
        if not self.schema_id:
            self.schema_id = expected_schema
        if self.schema_id != expected_schema:
            raise ValueError('payload schema does not match owner domain')
        validate_payload(self.schema_id, self.schema_version, self.payload)
        canonical(self.payload)  # Reject non-finite/non-JSON values before persistence.
        if self.source_classification == 'owner_system' and any(
            token in self.source_ref.lower() for token in ('fixture:', 'data/fixtures/', 'synthetic_demo')
        ):
            raise ValueError('demo source cannot be relabeled as owner system')
        if self.owner_domain in ('production', 'maintenance_readiness', 'quality_delivery'):
            if self.payload['source_classification'] != self.source_classification:
                raise ValueError('source classification mismatch')
        if self.owner_domain in ('maintenance_readiness', 'quality_delivery'):
            if self.payload['asset_id'] != self.asset_id:
                raise ValueError('payload asset scope mismatch')
        if self.owner_domain == 'production' and self.schema_version == 2:
            basis = self.payload['supply_basis']
            if basis['evidence_snapshot_id'] != self.evidence_snapshot_id or any(e['from_asset_id'] != self.asset_id for e in basis['edges']):
                raise ValueError('supply basis scope or snapshot mismatch')
        if self.owner_domain == 'production' and self.schema_version == 1:
            if any(x['assigned_asset_id'] != self.asset_id for x in self.payload['production_orders']):
                raise ValueError('production order asset scope mismatch')
            if any(x['asset_id'] != self.asset_id for x in self.payload['wip']):
                raise ValueError('WIP asset scope mismatch')
        if self.owner_domain == 'planning':
            impact = self.payload.get('event_impact') or {}
            if impact.get('equipment_id') != self.asset_id or not self.evidence_snapshot_id:
                raise ValueError('planning requires asset and exact evidence snapshot')
            if impact.get('event_id') != self.evidence_snapshot_id:
                raise ValueError('planning evidence snapshot mismatch')
            temporal = self.payload.get('temporal_scope') or {}
            for field, expected in [('generated_at', self.source_updated_at), ('valid_from', self.valid_from), ('valid_to', self.valid_to)]:
                if datetime.fromisoformat(str(temporal.get(field))) != expected:
                    raise ValueError('planning payload time mismatch')
        return self


def storage_records(snapshot):
    record = normalized_times(snapshot.model_dump(mode='json'))
    source = {key: record[key] for key in SOURCE_FIELDS}
    source_id = digest({key: source[key] for key in ('owner_domain', *SCOPE_FIELDS, 'source_version')})
    source['source_context_id'] = source_id
    projected = {}
    source_payload = dict(record['payload'])
    if snapshot.owner_domain == 'planning':
        projected = {key: source_payload.pop(key) for key in PLANNING_BINDING_FIELDS if key in source_payload}
    source['payload'] = source_payload
    binding = {
        'source_context_id': source_id,
        'organization_id': snapshot.organization_id,
        'project_id': snapshot.project_id,
        'evidence_snapshot_id': snapshot.evidence_snapshot_id or '',
        'binding_schema_version': 1,
        'payload': projected,
    }
    return source, binding


class OperationalContextRepository:
    def __init__(self, database: str | Path):
        self.database = str(database)
        self.postgres = self.database.startswith(('postgresql://', 'postgresql+psycopg://'))

    @contextmanager
    def connection(self, organization_id, project_id):
        if self.postgres:
            with tenant_connection(self.database.replace('postgresql+psycopg://', 'postgresql://'), organization_id, project_id=project_id) as c:
                yield c
        else:
            with sqlite3.connect(self.database) as c:
                c.row_factory = sqlite3.Row
                c.execute('PRAGMA foreign_keys=ON')
                yield c

    def execute(self, connection, sql, params=()):
        return connection.execute(sql.replace('?', '%s') if self.postgres else sql, params)

    def _insert_record(self, c, table, record, key_fields):
        # table and key_fields are fixed internal identifiers, never caller SQL.
        values = {key: value for key, value in record.items() if key != 'payload'}
        values['payload_json'] = canonical(record['payload'])
        values['content_sha256'] = digest(record)
        cursor = self.execute(c, f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)}) ON CONFLICT DO NOTHING", tuple(values.values()))
        if cursor.rowcount:
            return True
        where = ' AND '.join(f'{key}=?' for key in key_fields)
        row = self.execute(c, f'SELECT content_sha256 FROM {table} WHERE {where}', tuple(record[key] for key in key_fields)).fetchone()
        if row is None or row['content_sha256'] != values['content_sha256']:
            raise ValueError('immutable context version or binding conflict; publish a new owner version or Event')
        return False

    def _import_on_connection(self, c, snapshots):
        counts = {'inserted': 0, 'unchanged': 0}
        for snapshot in snapshots:
            source, binding = storage_records(snapshot)
            self._insert_record(c, 'operational_context_sources', source, ('source_context_id',))
            inserted = self._insert_record(c, 'operational_context_bindings', binding, ('source_context_id', 'evidence_snapshot_id'))
            counts['inserted' if inserted else 'unchanged'] += 1
        return counts

    def import_snapshots(self, snapshots: list[ContextSnapshot]) -> dict[str, int]:
        snapshots = [ContextSnapshot.model_validate(s.model_dump()) for s in snapshots]
        scopes = {(s.organization_id, s.project_id) for s in snapshots}
        if not scopes:
            return {'inserted': 0, 'unchanged': 0}
        if len(scopes) != 1:
            raise ValueError('one import transaction must target one organization/project')
        with self.connection(*next(iter(scopes))) as c:
            for snapshot in snapshots:
                if snapshot.owner_domain == 'production' and snapshot.schema_version == 2:
                    basis = snapshot.payload['supply_basis']
                    for edge in basis['edges']:
                        row = self.execute(c, """SELECT source_sha256 FROM pm_asset_relations
                            WHERE organization_id=? AND project_id=? AND workspace_id=? AND dataset_version_id=?
                            AND from_asset_id=? AND to_asset_id=? AND relation_type=?""",
                            (snapshot.organization_id,snapshot.project_id,snapshot.workspace_id,basis['dataset_version_id'],snapshot.asset_id,edge['to_asset_id'],edge['relation_type'])).fetchone()
                        if row is None or row['source_sha256'] != edge['source_sha256']:
                            raise ValueError('supply edge missing or provenance mismatch')
            return self._import_on_connection(c, snapshots)

    def migrate_legacy(self, *, organization_id, project_id, workspace_id, apply=False, allow_demo=False):
        """Verify legacy original checksums and atomically COPY one workspace; never delete."""
        with self.connection(organization_id, project_id) as c:
            rows = self.execute(c, '''SELECT * FROM operational_context_snapshots
                WHERE organization_id=? AND project_id=? AND workspace_id=?''',
                (organization_id, project_id, workspace_id)).fetchall()
            snapshots = []
            for row in rows:
                legacy = {key: row[key] for key in SOURCE_FIELDS if key not in ('schema_id', 'schema_version')}
                legacy['evidence_snapshot_id'] = row['evidence_snapshot_id']
                legacy['payload'] = json.loads(row['payload_json'])
                legacy = normalized_times(legacy)
                if digest(legacy) != row['content_sha256']:
                    raise ValueError('legacy original checksum mismatch; migration aborted')
                snapshot = ContextSnapshot.model_validate(legacy)
                if snapshot.source_classification == 'synthetic_demo_context' and not allow_demo:
                    raise ValueError('synthetic legacy snapshots require explicit nonproduction import')
                snapshots.append(snapshot)
            result = {'validated': len(snapshots), 'applied': apply}
            if apply:
                result.update(self._import_on_connection(c, snapshots))
            return result

    def _rows(self, identity):
        at = identity.decision_as_of.astimezone(timezone.utc).isoformat()
        with self.connection(identity.organization_id, identity.project_id) as c:
            return self.execute(c, '''WITH ranked AS (
                SELECT s.*, b.evidence_snapshot_id, b.binding_schema_version,
                    b.payload_json AS binding_payload_json, b.content_sha256 AS binding_sha256,
                    ROW_NUMBER() OVER (PARTITION BY s.owner_domain
                        ORDER BY s.source_updated_at DESC, s.source_version DESC,
                        CASE WHEN b.evidence_snapshot_id=? THEN 1 ELSE 0 END DESC) AS context_rank
                FROM operational_context_sources s JOIN operational_context_bindings b
                  ON b.source_context_id=s.source_context_id AND b.organization_id=s.organization_id AND b.project_id=s.project_id
                WHERE s.organization_id=? AND s.project_id=? AND s.workspace_id=? AND s.asset_id=?
                  AND s.source_updated_at<=? AND s.valid_from<=? AND s.valid_to>?
                  AND (b.evidence_snapshot_id='' OR b.evidence_snapshot_id=?)
                ) SELECT * FROM ranked WHERE context_rank=1''',
                (identity.evidence_snapshot_id, identity.organization_id, identity.project_id, identity.workspace_id,
                 identity.asset_id, at, at, at, identity.evidence_snapshot_id)).fetchall()

    def _row(self, owner_domain, identity):
        return next((r for r in self._rows(identity) if r['owner_domain'] == owner_domain), None)

    def capture(self, identity):
        try:
            return CapturedOperationalContextRepository(self.database, identity, {r['owner_domain']: dict(r) for r in self._rows(identity)})
        except Exception as exc:
            return CapturedOperationalContextRepository(self.database, identity, {}, exc)

    def lookup(self, owner_domain, *, identity, retrieved_at):
        common = dict(owner_domain=owner_domain, scope=OperationalScope(**{k: getattr(identity, k) for k in SCOPE_FIELDS}), retrieved_at=retrieved_at, as_of=identity.decision_as_of)
        def unavailable(status, reason):
            return OperationalContextEnvelope(**common, status=status, freshness=FreshnessMetadata(policy_version='db-context-asof-v2', max_age_seconds=0, state=FreshnessState.UNKNOWN), limitations=(reason,))
        try:
            row = self._row(owner_domain, identity)
        except Exception:
            return unavailable(OperationalContextStatus.FAILED, 'Operational context storage is unavailable; values withheld.')
        if row is None:
            return unavailable(OperationalContextStatus.NOT_CONNECTED, 'No matching scoped operational snapshot at the selected as-of; values withheld.')
        try:
            source = normalized_times({key: row[key] for key in SOURCE_FIELDS})
            source.update(source_context_id=row['source_context_id'], payload=json.loads(row['payload_json']))
            binding = {key: row[key] for key in ('source_context_id', 'organization_id', 'project_id', 'evidence_snapshot_id', 'binding_schema_version')}
            binding['payload'] = json.loads(row['binding_payload_json'])
            # Verify the stored original, BEFORE any contract validation or projection.
            if digest(source) != row['content_sha256'] or digest(binding) != row['binding_sha256']:
                raise ValueError('original checksum mismatch')
            if binding['binding_schema_version'] != 1:
                raise ValueError('unsupported binding version')
            if set(source['payload']) & set(binding['payload']):
                raise ValueError('binding cannot override source facts')
            if owner_domain != 'planning' and binding['payload']:
                raise ValueError('only planning v1 has Event projection fields')
            if not set(binding['payload']) <= PLANNING_BINDING_FIELDS:
                raise ValueError('unsupported Event projection fields')
            payload = {**source['payload'], **binding['payload']}
            validated = ContextSnapshot(**{key: source[key] for key in SOURCE_FIELDS}, evidence_snapshot_id=binding['evidence_snapshot_id'] or None, payload=payload)
            expected_source, expected_binding = storage_records(validated)
            if expected_source != source or expected_binding != binding:
                raise ValueError('noncanonical source or binding identity')
            updated = validated.source_updated_at
            stale = (identity.decision_as_of - updated).total_seconds() > validated.max_age_seconds
        except (ValueError, TypeError, KeyError, SchemaValidationError):
            return unavailable(OperationalContextStatus.FAILED, 'Stored operational snapshot failed validation; values withheld.')
        limitations = list(payload.get('limitations') or [])
        limitations.append(f"Context source: {source['source_classification']}; version {source['source_version']}; schema {source['schema_id']} v{source['schema_version']}.")
        if stale:
            limitations.append('Snapshot exceeded freshness policy at decision as-of; values withheld.')
        return OperationalContextEnvelope(**common, status=OperationalContextStatus.STALE if stale else OperationalContextStatus.AVAILABLE,
            source_version=source['source_version'], source_updated_at=updated,
            freshness=FreshnessMetadata(policy_version='db-context-asof-v2', max_age_seconds=source['max_age_seconds'], state=FreshnessState.STALE if stale else FreshnessState.FRESH),
            source_refs=(source['source_ref'],), data={} if stale else payload, limitations=tuple(limitations))

    def read_view(self, *, identity, retrieved_at, risk_status):
        from app.operations.operational_context_read import (
            ContextReadItem, ContextSourceProvenance, OperationalContextRead,
        )
        from app.operations.operational_impact_simulation import (
            ImpactSimulationAssumptions, simulate_operational_impact,
        )
        captured = self.capture(identity)
        domains = {}
        reasons = {
            'not_connected': 'NO_MATCHING_SCOPE_SNAPSHOT_AT_AS_OF',
            'stale': 'FRESHNESS_POLICY_EXCEEDED',
            'failed': 'STORAGE_OR_CONTRACT_VALIDATION_FAILED',
        }
        for domain in DOMAINS:
            envelope = captured.lookup(domain, identity=identity, retrieved_at=retrieved_at)
            provenance = None
            # Only validated rows may contribute source metadata, including stale rows.
            if envelope.status in (OperationalContextStatus.AVAILABLE, OperationalContextStatus.STALE):
                row = captured.rows[domain]
                provenance = ContextSourceProvenance(
                    source_context_id=row['source_context_id'], schema_id=row['schema_id'],
                    schema_version=row['schema_version'], source_classification=row['source_classification'],
                    valid_from=row['valid_from'], valid_to=row['valid_to'],
                    source_sha256=row['content_sha256'], binding_sha256=row['binding_sha256'],
                    bound_evidence_snapshot_id=row['evidence_snapshot_id'] or None,
                )
            domains[domain] = ContextReadItem(context=envelope, provenance=provenance,
                reason_codes=(reasons[envelope.status.value],) if envelope.status.value in reasons else ())
        readiness_item = domains['maintenance_readiness']
        if readiness_item.context.status == OperationalContextStatus.AVAILABLE:
            from app.operations.operational_context_ports import _maintenance_readiness
            from app.operations.operational_context_versions.v1 import MaintenanceReadinessContext
            parsed = MaintenanceReadinessContext.model_validate(readiness_item.context.data)
            domains['maintenance_readiness'] = readiness_item.model_copy(update={
                'context': readiness_item.context.model_copy(update={'data': {
                    **readiness_item.context.data, 'readiness': _maintenance_readiness(parsed),
                }})})
        policy = domains['impact_policy'].context
        assumptions = ImpactSimulationAssumptions.model_validate(policy.data) if policy.data else ImpactSimulationAssumptions(
            policy_version='unavailable-db-policy-v1', primary_capacity_units={},
            alternative_capacity_allowed={}, source_refs=('unavailable:impact-policy',),
        )
        impact = simulate_operational_impact(identity=identity, risk_status=risk_status,
            contexts={name: domains[name].context for name in ('production', 'maintenance_readiness', 'quality_delivery')},
            assumptions=assumptions)
        return OperationalContextRead(identity=identity, retrieved_at=retrieved_at,
            context_fingerprint=captured.version_fingerprint(identity), domains=domains, production_impact=impact)

    def ports(self):
        return {name: DatabaseOperationalContextReadPort(self, name) for name in ('production', 'maintenance_readiness', 'quality_delivery')}

    def contexts(self, *, identity, retrieved_at):
        captured = self.capture(identity)
        return {name: port.lookup(identity=identity, retrieved_at=retrieved_at) for name, port in captured.ports().items()}

    def version_fingerprint(self, identity):
        captured = self.capture(identity)
        items = []
        for domain in DOMAINS:
            envelope = captured.lookup(domain, identity=identity, retrieved_at=identity.decision_as_of)
            row = captured.rows.get(domain) or {}
            items.append((domain, envelope.status.value, row.get('content_sha256'), row.get('binding_sha256')))
        return digest(items)


class CapturedOperationalContextRepository(OperationalContextRepository):
    def __init__(self, database, identity, rows, error=None):
        super().__init__(database)
        self.identity = identity
        self.rows = rows
        self.error = error

    def capture(self, identity):
        if identity != self.identity:
            raise ValueError('captured operational context identity mismatch')
        return self

    def _row(self, owner_domain, identity):
        self.capture(identity)
        if self.error is not None:
            raise self.error
        return self.rows.get(owner_domain)

    def import_snapshots(self, snapshots):
        raise RuntimeError('captured operational context is read-only')

    def migrate_legacy(self, **kwargs):
        raise RuntimeError('captured operational context is read-only')


@dataclass(frozen=True)
class DatabaseOperationalContextReadPort:
    repository: OperationalContextRepository
    owner_domain: str
    def lookup(self, *, identity, retrieved_at):
        return self.repository.lookup(self.owner_domain, identity=identity, retrieved_at=retrieved_at)


def planning_context(repository: OperationalContextRepository, identity: OperationalRequestIdentity) -> dict:
    envelope = repository.lookup('planning', identity=identity, retrieved_at=identity.decision_as_of)
    if not envelope.data:
        return {'load_level': None, 'runtime_hours_7d': None, 'production_impact': None, 'limitations': list(envelope.limitations)}
    return {**envelope.data, 'limitations': list(envelope.limitations)}
