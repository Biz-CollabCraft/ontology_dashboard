"""Service for managing Prediction Result Outbox and single-dispatch HTTP client."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from systems.generator.generator_config import PATHS
from systems.generator.app.runtime_pipeline.pipeline_exception import (
    PipelineDeliveryFailedError,
    PipelineDeliveryServerError,
    PipelineDeliveryTimeoutError,
)
from systems.generator.app.runtime_pipeline.pipeline_schema import (
    PredictionOutboxItem,
    PredictionResultBatchPayload,
    now_utc_iso,
)

logger = logging.getLogger(__name__)


class PredictionDeliveryService:
    """HTTP client for dispatching prediction result batches with Outbox persistence and single-dispatch execution."""

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        timeout_seconds: float = 5.0,
        outbox_dir: Optional[Path] = None,
    ) -> None:
        self.endpoint_url = endpoint_url or os.environ.get(
            "GENERATOR_PREDICTION_RESULT_URL",
            "http://localhost:8000/internal/prediction-results",
        )
        self.timeout = timeout_seconds
        if outbox_dir is None:
            self.outbox_dir = PATHS.notification_outbox_root
        else:
            self.outbox_dir = Path(outbox_dir)
        self.outbox_dir.mkdir(parents=True, exist_ok=True)

    def save_outbox_item(self, item: PredictionOutboxItem) -> Path:
        """Atomically persist or update PredictionOutboxItem file."""
        dest_path = self.outbox_dir / f"{item.event_id}.json"
        temp_path = self.outbox_dir / f".tmp_{item.event_id}.json"
        item.updated_at = now_utc_iso()
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(item.model_dump_json(indent=2))
            f.flush()
            os.fsync(f.fileno())
        temp_path.replace(dest_path)
        return dest_path

    def get_outbox_item(self, event_id: str) -> Optional[PredictionOutboxItem]:
        """Load single outbox item by event_id."""
        path = self.outbox_dir / f"{event_id}.json"
        if not path.is_file():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return PredictionOutboxItem.model_validate(data)
        except Exception as exc:
            logger.error(f"[PredictionDeliveryService] Failed to load outbox item '{event_id}': {exc}")
            return None

    def list_outbox_items(self, status: Optional[str] = None) -> list[PredictionOutboxItem]:
        """List all outbox items, optionally filtered by status."""
        items: list[PredictionOutboxItem] = []
        for file in sorted(self.outbox_dir.glob("*.json")):
            if file.name.startswith(".tmp_"):
                continue
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                item = PredictionOutboxItem.model_validate(data)
                if status is None or item.status == status:
                    items.append(item)
            except Exception as exc:
                quarantine_dir = self.outbox_dir / "quarantine"
                quarantine_dir.mkdir(parents=True, exist_ok=True)
                dest = quarantine_dir / file.name
                try:
                    file.replace(dest)
                    logger.error(
                        f"[PredictionDeliveryService] Corrupt outbox file '{file.name}' quarantined to '{dest}': {exc} "
                        f"(error_code=PIPELINE_DELIVERY_OUTBOX_CORRUPT, retryable=False)"
                    )
                except Exception:
                    logger.error(f"[PredictionDeliveryService] Failed to quarantine corrupt file '{file.name}': {exc}")
        return items

    @staticmethod
    def compute_canonical_payload_sha256(payload: PredictionResultBatchPayload) -> tuple[str, str]:
        """Compute SHA-256 checksum of canonical payload representation and generate deterministic event_id."""
        import hashlib
        d = payload.model_dump(mode="json")
        d.pop("event_id", None)
        d.pop("generated_at", None)
        d.pop("job_id", None)

        canonical_json = json.dumps(d, sort_keys=True, separators=(",", ":"))
        payload_sha256 = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

        contract_ver = (
            payload.source_lineage.pipeline_contract_version
            if hasattr(payload, "source_lineage") and payload.source_lineage
            else "generator-prediction-result-v1"
        )
        raw_key = f"{contract_ver}:{payload.run_id}:{payload.asset_id}:{payload_sha256}"
        event_id = f"evt-{hashlib.sha256(raw_key.encode('utf-8')).hexdigest()[:32]}"
        return event_id, payload_sha256

    def register_idempotent_outbox_record(self, payload: PredictionResultBatchPayload) -> tuple[PredictionOutboxItem, str]:
        """
        Registers or reuses outbox record with deterministic event ID and payload sha256.
        If event_id already exists:
          - If payload sha256 matches: return existing item as idempotent success.
          - If payload sha256 differs: raise PipelineOutboxEventConflictError.
        """
        from systems.generator.app.runtime_pipeline.pipeline_exception import (
            PipelineOutboxEventConflictError,
        )

        event_id, payload_sha256 = self.compute_canonical_payload_sha256(payload)
        payload.event_id = event_id

        existing_item = self.get_outbox_item(event_id)
        if existing_item is not None:
            _, existing_sha256 = self.compute_canonical_payload_sha256(existing_item.payload)
            if existing_sha256 == payload_sha256:
                logger.info(
                    f"[PredictionDeliveryService] Idempotent reuse of existing outbox record '{event_id}' for equipment '{payload.asset_id}'"
                )
                return existing_item, payload_sha256
            else:
                raise PipelineOutboxEventConflictError(
                    f"Outbox event ID '{event_id}' already exists with different payload checksum for equipment '{payload.asset_id}'",
                    details=[{
                        "event_id": event_id,
                        "asset_id": payload.asset_id,
                        "existing_sha256": existing_sha256,
                        "new_sha256": payload_sha256,
                    }],
                    retryable=False,
                )

        item = self.create_outbox_record(payload)
        return item, payload_sha256

    def create_outbox_record(self, payload: PredictionResultBatchPayload) -> PredictionOutboxItem:
        """Create new pending outbox record for payload."""
        item = PredictionOutboxItem(
            event_id=payload.event_id,
            run_id=payload.run_id,
            job_id=payload.job_id,
            asset_id=payload.asset_id,
            status="pending",
            attempt=0,
            max_attempts=5,
            payload=payload,
        )
        self.save_outbox_item(item)
        return item


    def send_once(self, payload: PredictionResultBatchPayload) -> dict[str, Any]:
        """Perform a single HTTP POST dispatch attempt to the backend receiver."""
        body = payload.model_dump_json().encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": payload.event_id,
            "X-Request-ID": payload.run_id,
        }
        req = urllib.request.Request(
            self.endpoint_url,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status_code = resp.getcode()
                resp_body = resp.read().decode("utf-8")
                logger.info(
                    f"[PredictionDeliveryService] Successfully sent prediction batch '{payload.event_id}' "
                    f"(HTTP {status_code}) to {self.endpoint_url}"
                )
                return {"delivered": True, "status_code": status_code, "response": resp_body}
        except urllib.error.HTTPError as h_err:
            if 400 <= h_err.code < 500:
                logger.error(
                    f"[PredictionDeliveryService] Receiver rejected prediction batch '{payload.event_id}' with HTTP {h_err.code}"
                )
                raise PipelineDeliveryFailedError(
                    f"수신 시스템이 결과 배치를 거부했습니다 (HTTP {h_err.code})",
                    details=[{"status_code": h_err.code, "event_id": payload.event_id}],
                    retryable=False,
                ) from h_err
            # 5xx server error
            logger.warning(
                f"[PredictionDeliveryService] Server error from receiver (HTTP {h_err.code}): {h_err}"
            )
            raise PipelineDeliveryServerError(
                f"수신 시스템 서버 오류 (HTTP {h_err.code}): {h_err}",
                details=[{"status_code": h_err.code, "event_id": payload.event_id}],
                retryable=True,
            ) from h_err
        except (urllib.error.URLError, TimeoutError, OSError) as net_err:
            logger.warning(
                f"[PredictionDeliveryService] Network error sending prediction batch '{payload.event_id}': {net_err}"
            )
            raise PipelineDeliveryTimeoutError(
                f"결과 배치 전송 네트워크/타임아웃 오류: {net_err}",
                details=[{"error": str(net_err), "event_id": payload.event_id}],
                retryable=True,
            ) from net_err
