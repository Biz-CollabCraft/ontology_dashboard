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

-- A fresh production database runs every migration before optional reference
-- data seeding.  Create the roles referenced below so this migration does not
-- depend on a previous application startup having populated ``roles``.
INSERT INTO roles(code, display_name, description)
VALUES
    ('process_manager', '운영 매니저', '우선순위, 배정, 기한과 에스컬레이션을 관리합니다.'),
    ('ml_validator', '데이터 사이언티스트', '모델, 데이터, threshold, 오류와 drift를 검증합니다.'),
    ('fde', 'Forward Deployed Engineer', '고객 workflow, ontology, integration과 dashboard template을 구축합니다.')
ON CONFLICT (code) DO UPDATE
SET display_name = EXCLUDED.display_name,
    description = EXCLUDED.description;

INSERT INTO role_permissions(role_code, permission_code)
VALUES
    ('process_manager', 'agent.review.materialize'),
    ('ml_validator', 'agent.review.materialize'),
    ('fde', 'agent.review.materialize')
ON CONFLICT (role_code, permission_code) DO NOTHING;
