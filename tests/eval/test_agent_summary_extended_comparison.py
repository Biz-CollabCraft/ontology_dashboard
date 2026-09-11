import copy
import pytest
from scripts.run_pr167_extended_comparison import EvalProvider, MODELS, SETTINGS, frozen
from app.infra.llm import OpenAICompatibleProvider

@pytest.mark.parametrize("model", MODELS)
def test_explicit_supported_request_parameters(monkeypatch, model):
    monkeypatch.setenv("LLM_API_KEY","test-only")
    monkeypatch.setenv("LLM_BASE_URL","https://api.openai.com/v1")
    bodies=[]
    class Response:
        status_code=200
        def json(self):
            return {"model":model,"usage":{},"choices":[{"finish_reason":"stop"}]}
    monkeypatch.setattr(OpenAICompatibleProvider,"_post_chat_completion",lambda self,body:(bodies.append(copy.deepcopy(body)) or Response()))
    provider=EvalProvider(model)
    provider._post_chat_completion({"temperature":0,"response_format":{"type":"json_object"}})
    body=bodies[0]
    assert body["max_completion_tokens"]==4096
    if model.startswith("gpt-5"):
        assert body["reasoning_effort"]=="low"
        assert "temperature" not in body
    else:
        assert body["temperature"]==0
        assert "reasoning_effort" not in body

def test_frozen_binding_records_model_specific_reasoning():
    _,report=frozen()
    settings=report["archive_manifest"]["model_settings"]
    for model in MODELS:
        assert all(settings[model][key]==value for key,value in SETTINGS[model].items())
    assert report["selection_rubric"]["complete"]


def test_frozen_restores_gold_configuration_after_evaluation():
    from scripts import compare_agent_review_summary_models as comparison
    evaluation = comparison.evaluation
    previous_path, previous_cache = evaluation.GOLD_ANSWERS_PATH, evaluation._GOLD_ANSWERS_CACHE
    frozen()
    assert evaluation.GOLD_ANSWERS_PATH == previous_path
    assert evaluation._GOLD_ANSWERS_CACHE is previous_cache

@pytest.mark.parametrize("script,arguments", [
    ("run_pr167_extended_comparison.py", []),
    ("run_pr167_extended_comparison.py", ["--availability", "--prepare"]),
    ("run_pr167_registered_comparison.py", []),
])
def test_historical_comparison_requires_explicit_live_mode(tmp_path, script, arguments):
    import os, subprocess, sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    env = {k:v for k,v in os.environ.items() if k not in {"OPENAI_API_KEY", "LLM_API_KEY"}}
    result = subprocess.run([sys.executable, str(root / "scripts" / script),
                             "--output-dir", str(tmp_path / "experiment"), *arguments],
                            cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 2
    assert "--live" in result.stderr
    assert not (tmp_path / "experiment").exists()
