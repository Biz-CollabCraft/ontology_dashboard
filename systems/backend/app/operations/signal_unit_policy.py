"""Scoped display-unit assumptions; no conversion or inference of safety limits."""
import json
from functools import lru_cache
from app.common.runtime_settings import project_root


@lru_cache(maxsize=1)
def signal_unit_policy():
    return json.loads((project_root() / 'contracts/policies/manufacturing-signal-units-v1.json').read_text())


def apply_signal_units(view, *, organization_id, project_id, workspace_id):
    policy = signal_unit_policy()
    if policy['scope'] != dict(organization_id=organization_id, project_id=project_id, workspace_id=workspace_id):
        return view
    features = []
    for feature in view['features']:
        rule = policy['signals'].get(feature['key'])
        if rule and not feature.get('unit'):
            feature = {**feature, 'label': rule['label'], 'unit': rule['unit'] + ' · 가정'}
        features.append(feature)
    return {**view, 'features': features}
