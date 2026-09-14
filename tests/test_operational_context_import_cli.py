import json
import sys

import pytest
from scripts import import_operational_context as cli
from scripts.build_operational_context_demo_seed import build_seed


def invoke(tmp_path, monkeypatch, *, extra=(), scope='org-ontology-demo'):
    manifest = tmp_path / 'context.json'
    manifest.write_text(json.dumps(build_seed()))
    monkeypatch.setattr(sys, 'argv', ['import-context', '--manifest', str(manifest),
        '--organization-id', scope, '--project-id', 'manufacturing-demo-project',
        '--workspace-id', 'manufacturing-demo', *extra])
    cli.main()


def test_dry_run_does_not_connect(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('APP_ENV', 'test')
    def forbidden(*args):
        raise AssertionError('dry run must not open a database')
    monkeypatch.setattr(cli, 'OperationalContextRepository', forbidden)
    invoke(tmp_path, monkeypatch, extra=['--allow-demo'])
    assert json.loads(capsys.readouterr().out) == {'validated': 14, 'applied': False}


@pytest.mark.parametrize('env,extra', [('test', []), ('production', ['--allow-demo'])])
def test_demo_import_requires_explicit_nonproduction_target(tmp_path, monkeypatch, env, extra):
    monkeypatch.setenv('APP_ENV', env)
    with pytest.raises(ValueError, match='synthetic'):
        invoke(tmp_path, monkeypatch, extra=extra)


def test_manifest_cannot_select_another_tenant(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match='scope'):
        invoke(tmp_path, monkeypatch, extra=['--allow-demo'], scope='other-org')
