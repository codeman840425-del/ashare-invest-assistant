"""Offline adversarial checks of the real fixture preconditions; never open a DB."""
from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url

from . import conftest as milestone
from . import tt21_plugin as original
from .tt21_head import expected_main_head


def test_current_head_alias_preserves_real_fixture_object_and_lifecycle():
    assert milestone.integration is milestone.tt21_integration is original.tt21_integration
    assert expected_main_head(Path(original.tb70.__file__).resolve().parents[1]) == '0034'


@pytest.mark.parametrize('version', ['0020', '0030', '0035'])
def test_real_fixture_rejects_wrong_database_version_before_writes(tmp_path, monkeypatch, version):
    statements = []
    def execute(query):
        text = str(query).lower()
        statements.append(text)
        assert text.startswith('select '), 'No writes allowed before version guard'
        value = 'tb70_replay' if 'current_database' in text else version
        return SimpleNamespace(scalar_one=lambda: value)
    conn = SimpleNamespace(engine=SimpleNamespace(url=make_url(original.DB)), execute=execute)
    monkeypatch.setattr(original.Path, 'exists', lambda self: True)
    monkeypatch.setattr(original, 'create_engine', lambda url: SimpleNamespace(begin=lambda: nullcontext(conn)))
    def app_forbidden(*args, **kwargs):
        pytest.fail('Wrong version reached application setup')
    monkeypatch.setattr(original, 'create_app', app_forbidden)
    generator = original.tt21_integration.__wrapped__(tmp_path)
    with pytest.raises(AssertionError):
        next(generator)
    assert len(statements) == 2 and 'current_database' in statements[0]
    assert 'version_num' in statements[1]


@pytest.mark.parametrize('fault', ['tcp_host', 'foreign_database', 'wrong_live_database'])
def test_real_fixture_rejects_wrong_resource_before_version_or_writes(tmp_path, monkeypatch, fault):
    url = make_url(original.DB)
    if fault == 'tcp_host':
        url = url.set(host='127.0.0.1')
    elif fault == 'foreign_database':
        url = url.set(database='foreign')
    statements = []
    def execute(query):
        statements.append(str(query).lower())
        assert 'current_database' in statements[-1], 'Resource failure reached version/write SQL'
        return SimpleNamespace(scalar_one=lambda: 'foreign')
    conn = SimpleNamespace(engine=SimpleNamespace(url=url), execute=execute)
    monkeypatch.setattr(original.Path, 'exists', lambda self: True)
    monkeypatch.setattr(original, 'create_engine', lambda value: SimpleNamespace(begin=lambda: nullcontext(conn)))
    with pytest.raises(ValueError, match='dedicated tb70_ test database and UNIX socket'):
        next(original.tt21_integration.__wrapped__(tmp_path))
    assert len(statements) == (1 if fault == 'wrong_live_database' else 0)


def test_real_fixture_missing_socket_fails_without_opening_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(original.Path, 'exists', lambda self: False)
    def engine_forbidden(*args, **kwargs):
        pytest.fail('Missing socket attempted an engine connection')
    monkeypatch.setattr(original, 'create_engine', engine_forbidden)
    with pytest.raises(pytest.fail.Exception, match='专用隔离PG未就绪'):
        next(original.tt21_integration.__wrapped__(tmp_path))
