CREATE TABLE factory_record_bundles (
 organization_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
 bundle_id TEXT NOT NULL, dataset_version_id TEXT NOT NULL,
 payload_json TEXT NOT NULL, content_sha256 TEXT NOT NULL,
 PRIMARY KEY(organization_id,project_id,workspace_id,bundle_id)
);
CREATE INDEX factory_records_scope ON factory_record_bundles(organization_id,project_id,workspace_id,dataset_version_id);
CREATE TRIGGER factory_records_no_update BEFORE UPDATE ON factory_record_bundles BEGIN SELECT RAISE(ABORT,'immutable factory records'); END;
CREATE TRIGGER factory_records_no_delete BEFORE DELETE ON factory_record_bundles BEGIN SELECT RAISE(ABORT,'immutable factory records'); END;
