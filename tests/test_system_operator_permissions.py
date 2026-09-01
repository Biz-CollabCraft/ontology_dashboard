from app.identity.identity_schema import ROLE_PERMISSIONS


def test_system_operator_has_only_operational_asset_read_permission():
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
    } & ROLE_PERMISSIONS["tenant_admin"]
