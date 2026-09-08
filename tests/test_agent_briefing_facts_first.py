import json
from pathlib import Path
import pytest
from app.operations.agent_review_summary import compose_deterministic_agent_review_summary
from app.operations.agent_review_summary_provider import build_agent_review_summary_prompt_payload,build_tool_selected_agent_review_summary_prompt_payload
ROOT=Path(__file__).resolve().parents[1]
@pytest.mark.parametrize('builder',[build_agent_review_summary_prompt_payload,build_tool_selected_agent_review_summary_prompt_payload])
def test_baseline_prose_cannot_leak_to_provider(builder):
 p=json.loads((ROOT/'tests/fixtures/agent_review_packets/GS-002.json').read_text())
 b=compose_deterministic_agent_review_summary(p);b['title']='DO_NOT_COPY_TITLE';b['summary']='DO_NOT_COPY_SUMMARY'
 for r in b['role_summaries']:r['quote']='DO_NOT_COPY_QUOTE'
 payload=builder(packet=p,baseline_summary=b)
 assert 'DO_NOT_COPY' not in json.dumps(payload)
 assert payload['baseline_editable_fields']['summary']==''
 assert len(payload['baseline_editable_fields']['role_summaries'])==3
