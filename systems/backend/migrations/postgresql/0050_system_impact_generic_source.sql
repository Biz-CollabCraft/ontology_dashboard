ALTER TABLE system_impact_analyses ADD COLUMN IF NOT EXISTS source_asset_type TEXT;
ALTER TABLE system_impact_analyses ADD COLUMN IF NOT EXISTS source_asset_id TEXT;
ALTER TABLE system_impact_analyses ADD COLUMN IF NOT EXISTS source_version TEXT;
ALTER TABLE system_impact_analyses ADD COLUMN IF NOT EXISTS source_sha256 TEXT;
ALTER TABLE system_impact_analyses ADD COLUMN IF NOT EXISTS source_job_id TEXT;
