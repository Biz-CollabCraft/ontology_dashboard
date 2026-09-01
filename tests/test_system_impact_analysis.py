from pathlib import Path
from app.infra.db.impact_analysis_repository import ImpactAnalysisRepository
from app.infra.db.migrations import migrate
from app.system_operations.impact_analysis_schema import ImpactAnalysisCreate
from app.system_operations.impact_analysis_service import ImpactAnalysisService

class Jobs:
    def get(self,_):
        return {"status":"succeeded","mapping_id":"mapping-a","mapping_version":"v2","mapping_sha256":"1"*64,"result":{"rebuild":{"published_datasets":[{"dataset_id":"dataset-a","dataset_version":"window-v2","manifest_uri":"data/observations/dataset-a/window-v2/dataset_manifest.json"}]}}}

def test_impact_analysis_recommends_preprocessing_and_blocks_missing_inputs(tmp_path:Path):
    db=tmp_path/"impact.db"; migrate(str(db))
    service=ImpactAnalysisService(ImpactAnalysisRepository(db),Jobs())
    result=service.create(ImpactAnalysisCreate(mapping_id="mapping-a",mapping_version="v2",mapping_sha256="1"*64,rebuild_job_id="0782bb0e-52dc-46d4-9562-d40bfaa9fb11",include_stages=["preprocessing","feature","training"]),"operator")
    assert [a["stage"] for a in result["recommended_actions"]]==["preprocessing"]
    assert [a["stage"] for a in result["blocked_actions"]]==["feature","training"]
    assert result["snapshot_sha256"] != "0"*64


def test_managed_asset_impact_analysis_is_fail_closed_without_runtime_inputs(tmp_path: Path):
    db = tmp_path / "managed-impact.db"
    migrate(str(db))
    service = ImpactAnalysisService(ImpactAnalysisRepository(db), Jobs())
    result = service.create(
        ImpactAnalysisCreate(
            source_asset_type="training_config",
            source_asset_id="pdm-training",
            source_version="training-config-v2",
            source_sha256="2" * 64,
            include_stages=["training"],
        ),
        "operator",
    )
    assert result["source_asset_type"] == "training_config"
    assert result["recommended_actions"] == []
    assert result["blocked_actions"][0]["missing_parameters"] == [
        "dataset_id", "dataset_version", "feature_dataset_version", "base_models"
    ]
