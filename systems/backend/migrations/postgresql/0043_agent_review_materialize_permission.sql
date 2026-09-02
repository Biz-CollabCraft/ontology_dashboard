-- Keep persisted production RBAC aligned with the application role contract.
-- Production intentionally disables broad demo/reference-data seeding, so new
-- permissions must be introduced through an explicit migration.

INSERT INTO permissions(code, description)
VALUES (
    'agent.review.materialize',
    'Agent Review Summary 명시 생성 및 재생성'
)
ON CONFLICT (code) DO UPDATE
SET description = EXCLUDED.description;

INSERT INTO role_permissions(role_code, permission_code)
VALUES
    ('process_manager', 'agent.review.materialize'),
    ('ml_validator', 'agent.review.materialize'),
    ('fde', 'agent.review.materialize')
ON CONFLICT (role_code, permission_code) DO NOTHING;
