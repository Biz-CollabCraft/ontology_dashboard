"""Shared demo observation selection; no maintenance records are modified."""
import json
import os
import tempfile
from pathlib import Path
from functools import lru_cache

from app.diagnosis.contracts import complete_file_tick_window

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
    generated = generated_window(mode)
    if generated is not None:
        return generated
    return None if mode=='live' else load_window(mode)


def generated_window(mode):
    """Read complete native generator ticks, never a half-written equipment set."""
    state_path = ROOT/'live-state.json'
    if not state_path.exists():
        return None
    try:
        row = json.loads(state_path.read_text()).get(mode)
        if not row:
            return None
        stream = Path(row['stream']).resolve()
        generated_root = (ROOT/'generated'/mode).resolve()
        if not stream.is_relative_to(generated_root):
            return None
        streams = [stream, *generated_root.glob('runs/*/source/sensor_records.jsonl')]
        return _generated_tail(
            tuple(sorted({str(item.resolve()) for item in streams})),
            max(item.stat().st_mtime_ns for item in streams if item.exists()),
            sum(item.stat().st_size for item in streams if item.exists()),
        )
    except (OSError, ValueError, KeyError):
        return None


@lru_cache(maxsize=6)
def _generated_tail(stream_paths, modified_ns, size):
    streams = [Path(path) for path in stream_paths]
    return complete_file_tick_window(streams)
