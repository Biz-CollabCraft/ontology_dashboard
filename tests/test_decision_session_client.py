from pathlib import Path
import importlib
import json
import httpx
import pytest

@pytest.fixture
def call(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/"scripts"))
    return importlib.import_module("decision_session_client").create_or_resume_session


def test_lost_response_then_new_caller_reuses_key_without_storing_credentials(call,tmp_path):
    keys=[]
    def handler(request):
        keys.append(request.url.params["request_id"])
        if len(keys)==1:raise httpx.ReadTimeout("lost response",request=request)
        return httpx.Response(200,json={"session":{"decision_session_id":"DS-saved"}})
    path=tmp_path/"state.json"
    args=dict(asset_id="CNC-1",params={"project_id":"p"},actor_id="u",state_path=path,headers={"X-CSRF-Token":"synthetic-secret"},max_attempts=1)
    with httpx.Client(base_url="http://local.test",transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.ReadTimeout):call(client=client,**args)
    with httpx.Client(base_url="http://local.test",transport=httpx.MockTransport(handler)) as client:
        assert call(client=client,**args)["session"]["decision_session_id"]=="DS-saved"
        with pytest.raises(ValueError,match="identity"):
            call(client=client,**(args|{"actor_id":"another"}))
    assert len(set(keys))==1
    assert "synthetic-secret" not in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("detail,retried",[("decision_run_in_progress",True),("decision_run_configuration_or_evidence_changed",False)])
def test_only_busy_409_is_retried(call,tmp_path,detail,retried):
    keys=[];delays=[]
    def handler(request):
        keys.append(request.url.params["request_id"])
        return httpx.Response(409,json={"detail":detail}) if len(keys)==1 else httpx.Response(200,json={"session":{"decision_session_id":"DS-test"}})
    with httpx.Client(base_url="http://local.test",transport=httpx.MockTransport(handler)) as client:
        args=dict(client=client,asset_id="CNC-1",params={},actor_id="u",state_path=tmp_path/"state.json",headers={},sleep=delays.append)
        if retried:
            call(**args)
            assert len(keys)==2 and keys[0]==keys[1] and delays==[5]
        else:
            with pytest.raises(httpx.HTTPStatusError):call(**args)
            assert len(keys)==1 and delays==[]
