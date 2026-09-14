from app.operations.signal_unit_policy import apply_signal_units

SCOPE = dict(organization_id='org-ontology-demo', project_id='manufacturing-demo-project', workspace_id='manufacturing-demo')

def test_scoped_assumptions_preserve_values_and_source_units():
    features = [{'key': 'pressure_raw', 'unit': '', 'current': {'value': 102.18}}, {'key': 'voltage_raw', 'unit': 'mV'}, {'key': 'rotation_raw_6h_mean', 'unit': 'model unit'}]
    original = {'features': features}
    result = apply_signal_units(original, **SCOPE)
    assert result['features'][0]['unit'] == 'kPa · 가정'
    assert result['features'][0]['current'] == features[0]['current']
    assert features[0]['unit'] == ''
    assert result['features'][1:] == features[1:]
    assert apply_signal_units(original, **{**SCOPE, 'project_id': 'other'}) is original
