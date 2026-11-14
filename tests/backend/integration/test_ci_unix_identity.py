"""Synthetic negative identity controls; these do not claim real Docker validation."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from . import ci_unix_identity as identity


def specimen():
    token = 'a' * 24
    ident = 'b' * 64
    image_id = 'sha256:' + 'c' * 64
    owner = {'aia.task': 'O-CI1-RES', 'aia.run': '123', 'aia.attempt': '2', 'aia.owner': token}
    name = 'aia-ci-unix-pg-123-' + token[:8]
    mounts = [{'Type': 'bind', 'Source': identity.PG_SOCKET, 'Destination': '/var/run/postgresql', 'RW': True},
              {'Type': 'tmpfs', 'Source': '', 'Destination': '/var/lib/postgresql/data', 'RW': True}]
    row = {'kind': 'pg', 'Id': ident, 'name': name, 'image': identity.PG_IMAGE, 'socket': identity.PG_SOCKET,
           'destination': '/var/run/postgresql', 'start_inspect': {'image_id': image_id}}
    raw = {'Id': ident, 'Name': '/' + name, 'Image': image_id, 'Config': {'Image': identity.PG_IMAGE, 'Labels': owner.copy()},
           'State': {'Running': True}, 'HostConfig': {'NetworkMode': 'none', 'PortBindings': {}}, 'NetworkSettings': {'Ports': {'5432/tcp': None}}, 'Mounts': copy.deepcopy(mounts)}
    receipt = {'run_id': '123', 'attempt': '2', 'sha': 'd' * 40, 'owner': owner,
               'resources': [{'Id': ident, 'image_id': image_id, 'mounts': mounts}],
               'commands': [{'argv': ['docker', 'create', '--name', name, identity.PG_IMAGE], 'exit': 0}, {'argv': ['docker', 'start', ident], 'exit': 0}]}
    return raw, row, receipt


def test_matching_inspected_creation_identity():
    identity.validate_identity(*specimen())


@pytest.mark.parametrize('fault', ['id', 'name', 'image', 'image_id', 'owner', 'run', 'attempt', 'network', 'ports', 'stopped', 'mount', 'rw', 'extra_mount', 'no_create', 'failed_create', 'no_start'])
def test_wrong_or_unproven_identity_is_rejected(fault):
    raw, row, receipt = specimen()
    if fault == 'id': raw['Id'] = 'e' * 64
    elif fault == 'name': raw['Name'] = '/foreign'
    elif fault == 'image': raw['Config']['Image'] = 'unlocked:latest'
    elif fault == 'image_id': raw['Image'] = 'sha256:' + 'e' * 64
    elif fault == 'owner': raw['Config']['Labels']['aia.owner'] = 'e' * 24
    elif fault == 'run': receipt['run_id'] = '999'
    elif fault == 'attempt': receipt['attempt'] = '999'
    elif fault == 'network': raw['HostConfig']['NetworkMode'] = 'bridge'
    elif fault == 'ports': raw['HostConfig']['PortBindings'] = {'5432/tcp': [{'HostPort': '5432'}]}
    elif fault == 'stopped': raw['State']['Running'] = False
    elif fault == 'mount': raw['Mounts'][0]['Source'] = '/foreign'
    elif fault == 'rw': raw['Mounts'][0]['RW'] = False
    elif fault == 'extra_mount': raw['Mounts'].append({'Type': 'volume', 'Source': 'foreign', 'Destination': '/extra', 'RW': True})
    elif fault == 'no_create': receipt['commands'].pop(0)
    elif fault == 'failed_create': receipt['commands'][0]['exit'] = 1
    else: receipt['commands'].pop()
    with pytest.raises(RuntimeError):
        identity.validate_identity(raw, row, receipt)


def test_missing_receipt_cannot_enable_ci(monkeypatch):
    monkeypatch.setattr(identity.sys, 'platform', 'linux')
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    monkeypatch.setenv('RUNNER_ENVIRONMENT', 'github-hosted')
    monkeypatch.delenv('AIA_CI_UNIX_RECEIPT', raising=False)
    with pytest.raises(RuntimeError, match='Missing CI creation receipt'):
        identity.verify()


@pytest.mark.parametrize('fault', ['run_id', 'attempt', 'sha', 'state', 'schema'])
def test_wrong_creation_receipt_rejected_before_docker(tmp_path, monkeypatch, fault):
    receipt = {'schema': 'aia-ci-unix-resources-v1', 'state': 'ready', 'run_id': '123', 'attempt': '2', 'sha': 'd' * 40}
    receipt[fault] = 'wrong'
    path = tmp_path / 'receipt.json'
    path.write_text(json.dumps(receipt))
    monkeypatch.setattr(identity.sys, 'platform', 'linux')
    for name, value in {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted', 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2', 'GITHUB_SHA': 'd' * 40, 'GITHUB_WORKSPACE': str(identity.ROOT), 'RUNNER_TEMP': str(tmp_path), 'AIA_CI_UNIX_RECEIPT': str(path)}.items():
        monkeypatch.setenv(name, value)
    def forbidden(*args, **kwargs):
        pytest.fail('Invalid receipt must fail before any live command')
    monkeypatch.setattr(identity.subprocess, 'run', forbidden)
    with pytest.raises(RuntimeError):
        identity.verify()


def test_database_requires_successful_creation_and_exact_run_owner():
    _, _, receipt = specimen()
    logical = 'tb70_p2n10_' + 'f' * 32
    actual = identity.owned_name(receipt, logical)
    with pytest.raises(RuntimeError, match='not actually created'):
        identity.require_owned_database(receipt, logical, actual, set())
    identity.require_owned_database(receipt, logical, actual, {actual})
    foreign = copy.deepcopy(receipt)
    foreign['owner']['aia.owner'] = 'e' * 24
    with pytest.raises(RuntimeError):
        identity.require_owned_database(foreign, logical, actual, {actual})
    with pytest.raises(RuntimeError):
        identity.owned_name(receipt, 'postgres')


def test_failed_database_create_never_registers_ownership():
    from .ci_owned_database import create_owned_database
    _, _, receipt = specimen()
    logical = 'tb70_p2n10_' + 'f' * 32
    created = set()
    def fail(query):
        raise RuntimeError('synthetic CREATE failure')
    with pytest.raises(RuntimeError, match='CREATE failure'):
        create_owned_database(SimpleNamespace(execute=fail), receipt, logical, created)
    assert created == set()
    writes = []
    actual = create_owned_database(SimpleNamespace(execute=writes.append), receipt, logical, created)
    assert actual == identity.owned_name(receipt, logical) and created == {actual}
    assert len(writes) == 1 and actual in writes[0].as_string()


def test_database_acl_refuses_wrong_live_database_before_any_ddl():
    from .ci_owned_database import deploy_owned_grants
    _, _, receipt = specimen()
    logical = 'tb70_p2n10_' + 'f' * 32
    actual = identity.owned_name(receipt, logical)
    writes = []
    conn = SimpleNamespace(
        exec_driver_sql=lambda query: SimpleNamespace(scalar_one=lambda: 'foreign'),
        connection=SimpleNamespace(driver_connection=SimpleNamespace(execute=writes.append)),
    )
    with pytest.raises(AssertionError):
        deploy_owned_grants(conn, receipt, logical, actual, {actual})
    assert writes == []


def test_database_acl_uses_original_database_only_grants():
    from .ci_owned_database import ROOT, deploy_owned_grants
    _, _, receipt = specimen()
    logical = 'tb70_p2n10_' + 'f' * 32
    actual = identity.owned_name(receipt, logical)
    writes = []
    conn = SimpleNamespace(
        exec_driver_sql=lambda query: SimpleNamespace(scalar_one=lambda: actual),
        connection=SimpleNamespace(driver_connection=SimpleNamespace(execute=writes.append)),
    )
    deploy_owned_grants(conn, receipt, logical, actual, {actual})
    original = (ROOT / 'deploy/db/roles/grants.sql').read_text()
    assert writes == [original[original.index('DO $grants$'):]]
