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
        if not stream.is_relative_to((ROOT/'generated'/mode).resolve()):
            return None
        return _generated_tail(str(stream), stream.stat().st_mtime_ns, stream.stat().st_size)
    except (OSError, ValueError, KeyError):
        return None


@lru_cache(maxsize=6)
def _generated_tail(stream_path, modified_ns, size):
    import csv
    stream = Path(stream_path)
    with (stream.parents[1]/'canonical/asset_master.csv').open(encoding='utf-8-sig', newline='') as handle:
        expected = {row['asset_id'] for row in csv.DictReader(handle)}
    if not expected:
        return None
    ticks = {}
    with stream.open('rb') as handle:
        start = max(0, size - 2*1024*1024)
        handle.seek(start)
        if start:
            handle.readline()
        for line in handle:
            try:
                row = json.loads(line)
                ticks.setdefault(row['observed_at'], {})[row['asset_id']] = row
            except (ValueError, KeyError):
                continue
    complete = [(at, rows) for at, rows in sorted(ticks.items()) if set(rows) == expected]
    if not complete:
        return None
    return stream, complete[-1][0], list(complete[-1][1].values()), complete
