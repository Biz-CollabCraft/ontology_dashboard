-- Receive-only Backend Inbox for Generator Prediction Result Batch payloads.
-- Product Result/Evidence promotion is intentionally out of scope here.

CREATE TABLE IF NOT EXISTS pm_prediction_result_inbox_batches (
    receive_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    workspace_id text NOT NULL,
    batch_id text NOT NULL,
    payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[a-f0-9]{64}$'),
    validation_status text NOT NULL CHECK (
        validation_status IN ('accepted','duplicate','conflict','rejected')
    ),
    rejection_reason text,
    raw_payload jsonb NOT NULL,
    promotion_result_id text,
    received_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS pm_prediction_result_inbox_items (
    receive_item_id text PRIMARY KEY,
    receive_id text NOT NULL REFERENCES pm_prediction_result_inbox_batches(receive_id)
      ON DELETE CASCADE,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    workspace_id text NOT NULL,
    batch_id text NOT NULL,
    event_id text NOT NULL,
    payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[a-f0-9]{64}$'),
    validation_status text NOT NULL CHECK (
        validation_status IN ('accepted','duplicate','conflict','rejected')
    ),
    rejection_reason text,
    raw_item jsonb NOT NULL,
    promotion_result_id text,
    received_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pm_prediction_inbox_batches_status
  ON pm_prediction_result_inbox_batches(
    organization_id,project_id,workspace_id,validation_status,received_at DESC
  );

CREATE INDEX IF NOT EXISTS idx_pm_prediction_inbox_items_batch
  ON pm_prediction_result_inbox_items(
    organization_id,project_id,workspace_id,batch_id
  );

CREATE INDEX IF NOT EXISTS idx_pm_prediction_inbox_batches_identity
  ON pm_prediction_result_inbox_batches(
    organization_id,project_id,workspace_id,batch_id,payload_sha256
  );

CREATE INDEX IF NOT EXISTS idx_pm_prediction_inbox_items_identity
  ON pm_prediction_result_inbox_items(
    organization_id,project_id,workspace_id,event_id,payload_sha256
  );
