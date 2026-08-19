"""Compatibility exports for the canonical database migration runner.

Only the public migration API is retained here. Tests and implementation code
that need migration internals must import :mod:`app.infra.db.migrations`
directly so monkeypatching affects the module that actually executes them.
"""

from app.infra.db.migrations import MIGRATION_ROOT, migrate, migration_status

__all__ = ["MIGRATION_ROOT", "migrate", "migration_status"]
