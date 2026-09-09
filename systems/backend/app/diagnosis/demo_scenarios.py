"""Shared demo observation selection; no maintenance records are modified."""
import json
import os
import tempfile
from pathlib import Path
from functools import lru_cache

ROOT = Path('/home/bistell/ontology_dashboard/data/demo-scenarios')

def scenario_status():
    catalog = json.loads((ROOT/'catalog.json').read_text()) if (ROOT/'catalog.json').exists() else {}
    current = json.loads((ROOT/'selection.json').read_text()).get('mode','live') if (ROOT/'selection.json').exists() else 'live'
    return {'mode': current, 'options': {key: {k:v for k,v in row.items() if k!='window'} for key,row in catalog.items()}}

def select_scenario(mode, user_id):
    if mode not in {'live','normal','emergency'}:
        raise ValueError('unsupported scenario')
    if mode != 'live':
        load_window(mode)
    ROOT.mkdir(parents=True,exist_ok=True)
    fd, path = tempfile.mkstemp(dir=ROOT, prefix='selection-', suffix='.tmp')
    try:
        with os.fdopen(fd,'w') as handle:
            json.dump({'mode':mode,'selected_by':user_id},handle)
        os.replace(path,ROOT/'selection.json')
    finally:
        if os.path.exists(path): os.unlink(path)
    return scenario_status()

@lru_cache(maxsize=2)
def load_window(mode):
    if mode not in {'normal','emergency'}: raise ValueError('unsupported scenario')
    data=json.loads((ROOT/(mode+'-window.json')).read_text())
    ticks=data['ticks']
    if not ticks or len(ticks[-1][1])!=100: raise ValueError('incomplete scenario')
    return Path(data['stream']),data['observed_at'],list(ticks[-1][1].values()),ticks

def selected_window():
    mode=scenario_status()['mode']
    return None if mode=='live' else load_window(mode)
