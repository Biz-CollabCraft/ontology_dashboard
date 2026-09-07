CREATE TABLE factory_record_bundles (
 organization_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
 bundle_id TEXT NOT NULL, dataset_version_id TEXT NOT NULL,
 payload_json TEXT NOT NULL, content_sha256 TEXT NOT NULL,
 PRIMARY KEY(organization_id,project_id,workspace_id,bundle_id)
);
CREATE INDEX factory_records_scope ON factory_record_bundles(organization_id,project_id,workspace_id,dataset_version_id);
ALTER TABLE factory_record_bundles ENABLE ROW LEVEL SECURITY;
ALTER TABLE factory_record_bundles FORCE ROW LEVEL SECURITY;
CREATE POLICY factory_records_scope_policy ON factory_record_bundles
USING (organization_id = nullif(current_setting('app.organization_id',true),'') AND project_id = nullif(current_setting('app.project_id',true),''))
WITH CHECK (organization_id = nullif(current_setting('app.organization_id',true),'') AND project_id = nullif(current_setting('app.project_id',true),''));
CREATE TRIGGER factory_records_immutable BEFORE UPDATE OR DELETE ON factory_record_bundles
FOR EACH ROW EXECUTE FUNCTION reject_operational_context_snapshot_mutation();
