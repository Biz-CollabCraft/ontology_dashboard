"""Prepare the two family artifacts used by the local real-time runtime.

This is intentionally an explicit local bootstrap, not an implicit application
fallback.  It publishes real Model Artifacts from the sibling gen_data canonical
package and atomically selects one CNC and one compressor model.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _manifest_candidates(models_store: Path, model_id: str) -> list[dict]:
    root = models_store / "artifacts" / model_id
    candidates: list[dict] = []
    if not root.exists():
        return candidates
    for manifest_path in root.glob("*/manifest.json"):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("model_id") == model_id and payload.get("model_version"):
            payload["_artifact_dir"] = str(manifest_path.parent)
            candidates.append(payload)
    return sorted(
        candidates,
        key=lambda item: (str(item.get("created_at") or ""), str(item["model_version"])),
    )


def _publish(command: str, *, gen_data_root: Path, models_store: Path) -> None:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(ROOT),
            "DATA_DIR": str((gen_data_root / "canonical" / "dataset").resolve()),
            "MODELS_STORE_DIR": str(models_store.resolve()),
            "MODEL_ARTIFACT_URI": str((models_store / "artifacts").resolve()),
            "GENERATOR_TRAINING_N_JOBS": env.get("GENERATOR_TRAINING_N_JOBS", "-1"),
        }
    )
    subprocess.run(
        [sys.executable, "-m", "systems.generator.entrypoint", command],
        cwd=ROOT,
        env=env,
        check=True,
    )


def prepare(*, gen_data_root: Path, models_store: Path, force: bool = False) -> dict:
    os.environ["MODELS_STORE_DIR"] = str(models_store.resolve())
    from systems.generator.model.publisher import (
        ModelArtifactContractValidationError,
        validate_model_artifact,
    )

    def valid_candidates(model_id: str) -> list[dict]:
        result: list[dict] = []
        for candidate in _manifest_candidates(models_store, model_id):
            try:
                validate_model_artifact(
                    artifact_dir=Path(candidate["_artifact_dir"]),
                    expected_model_id=model_id,
                    expected_model_version=str(candidate["model_version"]),
                    load_model=True,
                    artifacts_root=models_store / "artifacts",
                )
            except ModelArtifactContractValidationError:
                continue
            result.append(candidate)
        return result

    required = {
        "compressor-failure-risk": "train-publish",
        "cnc-failure-risk": "train-publish-cnc",
    }
    selected: dict[str, dict[str, object]] = {}
    for model_id, command in required.items():
        candidates = [] if force else valid_candidates(model_id)
        if not candidates:
            print(f"[models] publishing {model_id} from {gen_data_root}", flush=True)
            _publish(command, gen_data_root=gen_data_root, models_store=models_store)
            candidates = valid_candidates(model_id)
        if not candidates:
            raise RuntimeError(f"model publication produced no valid manifest: {model_id}")
        selected[model_id] = {
            "model_version": str(candidates[-1]["model_version"]),
            "required": True,
        }

    from systems.generator.app.runtime_pipeline.active_model_set_service import (
        ActiveModelSetService,
    )
    from systems.generator.app.runtime_pipeline.pipeline_schema import ActiveModelSet

    model_set = ActiveModelSet(
        model_set_id="pdm-local-realtime",
        model_set_version="1.0.0",
        updated_at=datetime.now(timezone.utc),
        models=selected,
    )
    published = ActiveModelSetService(models_store_dir=models_store).update_active_model_set(
        model_set,
        validate_artifacts=True,
    )
    return published.model_dump(mode="json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gen-data-root",
        type=Path,
        default=ROOT.parent / "gen_data",
    )
    parser.add_argument(
        "--models-store",
        type=Path,
        default=ROOT / "models_store" / "local-realtime",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    payload = prepare(
        gen_data_root=args.gen_data_root.resolve(),
        models_store=args.models_store.resolve(),
        force=args.force,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
