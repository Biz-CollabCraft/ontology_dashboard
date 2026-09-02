ALTER TABLE system_pipeline_jobs DROP CONSTRAINT IF EXISTS system_pipeline_jobs_job_type_check;
ALTER TABLE system_pipeline_jobs ADD CONSTRAINT system_pipeline_jobs_job_type_check
    CHECK(job_type IN ('mapping_rebuild','downstream_rebuild'));
ALTER TABLE system_pipeline_jobs DROP CONSTRAINT IF EXISTS system_pipeline_jobs_status_check;
ALTER TABLE system_pipeline_jobs ADD CONSTRAINT system_pipeline_jobs_status_check
    CHECK(status IN ('queued','running','checkpointed','cancel_requested','succeeded','partially_succeeded','failed','cancelled'));
