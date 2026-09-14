from copy import deepcopy
from jsonschema import Draft202012Validator
from app.infra.llm.provider import _openai_compatible_schema
from app.operations.agent_review_summary_provider import agent_review_summary_editable_schema


def test_briefing_required_title_survives_provider_projection():
    schema = agent_review_summary_editable_schema()
    original = deepcopy(schema)
    projected = _openai_compatible_schema(schema)
    assert schema == original
    assert set(projected['required']) == set(projected['properties'])
    roles = projected['properties']['role_summaries']['items']['properties']['role']['enum']
    example = {'title':'현재 근거','summary':'확인 필요','role_summaries':[{'role':r,'quote':'확인 필요'} for r in roles]}
    Draft202012Validator(projected).validate(example)
    assert '$schema' not in projected


def test_schema_keywords_are_preserved_as_property_and_definition_names():
    schema = {'title':'metadata','description':'metadata','type':'object',
              'properties': {'title':{'type':'string','title':'metadata'},
                             'description':{'type':'object','properties':{'minLength':{'const':3}}}},
              '$defs': {'title':{'type':'string','description':'metadata'}}}
    projected = _openai_compatible_schema(schema)
    assert 'title' not in projected and 'description' not in projected
    assert projected['properties']['title'] == {'type':'string'}
    assert projected['properties']['description']['properties']['minLength'] == {'enum':[3]}
    assert projected['$defs']['title'] == {'type':'string'}
