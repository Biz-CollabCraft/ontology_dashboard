from app.identity.identity_schema import ROLE_PERMISSIONS


def test_system_operator_has_only_system_operations_permissions():
    assert ROLE_PERMISSIONS["system_operator"] == {
        "system.assets.read",
        "system.assets.create_version",
        "system.assets.validate",
        "system.assets.publish",
        "system.assets.activate",
        "system.jobs.read",
        "system.jobs.create",
        "system.jobs.cancel",
        "system.impact.read",
        "system.impact.create",
        "system.rebuild.execute",
        "system.contracts.read",
        "system.contracts.create_version",
        "system.contracts.validate",
        "system.contracts.publish",
        "system.models.read",
        "system.models.select",
        "system.models.activate",
        "system.models.rollback",
        "system.audit.read",
        "system.logs.read",
        "system.logs.export",
        "system.recovery_guides.read",
        "system.e2e.read",
    }


def test_tenant_admin_does_not_inherit_system_operations_permission():
    assert not {
        "system.assets.read",
        "system.assets.create_version",
        "system.assets.validate",
        "system.assets.publish",
        "system.assets.activate",
        "system.jobs.read",
        "system.jobs.create",
        "system.jobs.cancel",
        "system.impact.read",
        "system.impact.create",
        "system.rebuild.execute",
        "system.contracts.read",
        "system.contracts.create_version",
        "system.contracts.validate",
        "system.contracts.publish",
        "system.models.read",
        "system.models.select",
        "system.models.activate",
        "system.models.rollback",
        "system.audit.read",
        "system.logs.read",
        "system.logs.export",
        "system.recovery_guides.read",
        "system.e2e.read",
    } & ROLE_PERMISSIONS["tenant_admin"]
