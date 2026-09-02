CREATE TABLE IF NOT EXISTS system_impact_analyses (
    analysis_id TEXT PRIMARY KEY, status TEXT NOT NULL, mapping_id TEXT NOT NULL,
    mapping_version TEXT NOT NULL, mapping_sha256 TEXT NOT NULL, rebuild_job_id TEXT NOT NULL,
    include_stages_json JSONB NOT NULL, source_json JSONB NOT NULL, nodes_json JSONB NOT NULL,
    edges_json JSONB NOT NULL, actions_json JSONB NOT NULL, snapshot_sha256 TEXT NOT NULL,
    created_by TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL, completed_at TIMESTAMPTZ,
    error_code TEXT, error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_system_impact_analyses_mapping ON system_impact_analyses(mapping_id,mapping_version,created_at);
CREATE TABLE IF NOT EXISTS system_pipeline_job_steps (
    step_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, action_id TEXT NOT NULL,
    stage TEXT NOT NULL CHECK(stage IN ('preprocessing','feature','training')),
    sequence INTEGER NOT NULL, status TEXT NOT NULL,
    input_json JSONB NOT NULL, output_json JSONB, error_code TEXT, error_message TEXT,
    started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ, UNIQUE(job_id,action_id)
);
CREATE INDEX IF NOT EXISTS idx_system_pipeline_job_steps_job ON system_pipeline_job_steps(job_id,sequence);
