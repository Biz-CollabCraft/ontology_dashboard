"""Read-only Decision Session caller with a durable request key.

Supply an authenticated httpx.Client and its CSRF header. Credentials and cookies
are never written to the local request-state file. Frontend integration is separate.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.parse import quote
from uuid import uuid4

import httpx


def _write(path, state):
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(state, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def _locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600), "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def create_or_resume_session(*, client: httpx.Client, asset_id: str, params: dict,
                             actor_id: str, state_path: Path, headers: dict,
                             max_attempts: int = 8, retry_delay_seconds: float = 5,
                             sleep=time.sleep):
    """Retry only this read-only POST; retain the key even if the process exits.

    Use the same state_path for retries; a different decision needs a new path.
    Permanent 4xx errors, including changed evidence/configuration, are not retried.
    """
    if not 1 <= max_attempts <= 20 or not 0 <= retry_delay_seconds <= 30:
        raise ValueError("invalid retry bounds")
    if "request_id" in params or not actor_id:
        raise ValueError("caller state owns request_id; actor_id is required")
    path = Path(state_path)
    binding = hashlib.sha256(json.dumps([str(client.base_url), actor_id, asset_id, params], sort_keys=True).encode()).hexdigest()
    with _locked(path):
        if path.exists():
            if path.stat().st_size > 4096:
                raise ValueError("invalid request state size")
            state = json.loads(path.read_text())
            if state.get("binding") != binding:
                raise ValueError("request state belongs to another identity or server")
        else:
            state = {"version": 1, "binding": binding, "request_id": uuid4().hex}
            _write(path, state)
    url = f"/api/objects/{quote(asset_id, safe='')}/decision-sessions"
    for attempt in range(max_attempts):
        try:
            response = client.post(url, params={**params, "request_id": state["request_id"]}, headers=headers)
        except httpx.TransportError:
            if attempt + 1 == max_attempts:
                raise
        else:
            busy = response.status_code == 409 and response.json().get("detail") in {
                "decision_run_in_progress", "decision_run_lease_lost"}
            if not busy or attempt + 1 == max_attempts:
                response.raise_for_status()
                result = response.json()
                with _locked(path):
                    state["decision_session_id"] = result["session"]["decision_session_id"]
                    _write(path, state)
                return result
        sleep(retry_delay_seconds)
