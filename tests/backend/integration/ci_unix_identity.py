"""CI-only verification of newly created resources; legacy identities stay separate."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

PG_IMAGE = 'timescale/timescaledb:2.31.0-pg16@sha256:322ae364eca3321cf2a48f1ef31213b87843413b3cf8feeebf54e999a26bb731'
REDIS_IMAGE = 'redis:7.4.12-alpine3.21@sha256:8da19c7399dca900c6822a1cf30f9d2285585e2c4b457ff4095b0f4500054d3f'
ROOT = Path(__file__).resolve().parents[3]
PG_SOCKET = '/tmp/tb70-tb91-owned-socket'
REDIS_SOCKET = '/tmp/tb91-owned-redis'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def docker_json(*args):
    proc = subprocess.run(['docker', *args], capture_output=True, text=True, check=True, timeout=30)
    return json.loads(proc.stdout)


def validate_identity(raw, row, receipt):
    kind = row['kind']
    require(kind in {'pg', 'redis'}, 'Unknown resource kind')
    image, socket, destination, tmpfs = ((PG_IMAGE, PG_SOCKET, '/var/run/postgresql', '/var/lib/postgresql/data')
                                        if kind == 'pg' else (REDIS_IMAGE, REDIS_SOCKET, '/run/aia-ci-redis', '/data'))
    require(re.fullmatch(r'[0-9a-f]{64}', row['Id']), 'Exact container ID required')
    require(raw['Id'] == row['Id'] and raw['Name'] == '/' + row['name'], 'Wrong container identity')
    require(row['image'] == raw['Config']['Image'] == image, 'Wrong pinned digest')
    require(row['socket'] == socket and row['destination'] == destination, 'Wrong socket declaration')
    owner = receipt['owner']
    require(owner == {'aia.task': 'O-CI1-RES', 'aia.run': receipt['run_id'], 'aia.attempt': receipt['attempt'], 'aia.owner': owner.get('aia.owner')}, 'Wrong ownership schema')
    require(re.fullmatch(r'[0-9a-f]{24}', owner['aia.owner']), 'Missing creation owner token')
    require(row['name'] == f"aia-ci-unix-{kind}-{receipt['run_id']}-{owner['aia.owner'][:8]}", 'Wrong run container name')
    require(all(raw['Config']['Labels'].get(k) == v for k, v in owner.items()), 'Wrong live owner labels')
    require(raw['State']['Running'] is True and raw['HostConfig']['NetworkMode'] == 'none', 'Service not running network-none')
    require(not raw['HostConfig']['PortBindings'] and not any((raw.get('NetworkSettings', {}).get('Ports') or {}).values()), 'Published/listening container ports forbidden')
    mounts = [{k: m.get(k) for k in ('Type', 'Source', 'Destination', 'RW')} for m in raw['Mounts']]
    recorded = next(r for r in receipt['resources'] if r['Id'] == row['Id'])
    require(sorted(mounts, key=lambda m: m['Destination']) == sorted(recorded['mounts'], key=lambda m: m['Destination']), 'Live mount differs from actual creation receipt')
    binds = [m for m in mounts if m['Type'] == 'bind']
    require(binds == [{'Type': 'bind', 'Source': socket, 'Destination': destination, 'RW': True}], 'Wrong exact socket bind')
    require(all(m['Type'] == 'bind' or (m['Type'] == 'tmpfs' and m['Destination'] == tmpfs and m['RW']) for m in mounts), 'Unexpected volume/mount')
    require(raw['Image'] == recorded['image_id'] == row['start_inspect']['image_id'], 'Live image ID drift')
    creates = [c for c in receipt['commands'] if c['exit'] == 0 and c['argv'][:2] == ['docker', 'create'] and '--name' in c['argv'] and c['argv'][c['argv'].index('--name') + 1] == row['name']]
    require(len(creates) == 1 and image in creates[0]['argv'], 'No successful original create command')
    require(any(c['exit'] == 0 and c['argv'] == ['docker', 'start', row['Id']] for c in receipt['commands']), 'No successful original start command')


def verify():
    require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted', 'Explicit ephemeral Linux CI only')
    require('AIA_CI_UNIX_RECEIPT' in os.environ, 'Missing CI creation receipt')
    path = Path(os.environ['AIA_CI_UNIX_RECEIPT']).resolve(strict=True)
    require(path.is_relative_to(Path(os.environ['RUNNER_TEMP']).resolve()), 'Receipt outside this runner temporary root')
    require(Path(os.environ['GITHUB_WORKSPACE']).resolve() == ROOT, 'Wrong checkout root')
    receipt = json.loads(path.read_text(encoding='utf-8'))
    require(receipt['schema'] == 'aia-ci-unix-resources-v1' and receipt['state'] == 'ready', 'Unready creation receipt')
    for field, env in [('run_id', 'GITHUB_RUN_ID'), ('attempt', 'GITHUB_RUN_ATTEMPT'), ('sha', 'GITHUB_SHA')]:
        require(receipt[field] == os.environ[env], 'Receipt belongs to another run/attempt/SHA')
    head = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    require(head == receipt['sha'], 'Checkout SHA differs')
    require(receipt['require_isolated_passed'] is True and receipt['current_database'] == 'tb70_replay' and receipt['version'] == '0034', 'Fresh baseline database not verified')
    require(len(receipt['containers']) == 2 and {r['kind'] for r in receipt['containers']} == {'pg', 'redis'}, 'Exact PG/Redis pair required')
    pg_id = next(r['Id'] for r in receipt['containers'] if r['kind'] == 'pg')
    require(any(r['name'] == 'tb70_replay' and r['container_id'] == pg_id and r['fresh_empty'] is True for r in receipt['created_databases']), 'No fresh baseline creation receipt')
    actual = []
    for row in receipt['containers']:
        raw = docker_json('inspect', row['Id'])[0]
        validate_identity(raw, row, receipt)
        image = docker_json('image', 'inspect', raw['Image'])[0]
        require(image['Id'] == raw['Image'] and row['image'].split('@', 1)[1] in {d.split('@', 1)[1] for d in image['RepoDigests']}, 'Image content digest not in actual daemon image')
        actual.append({'Id': raw['Id'], 'kind': row['kind'], 'mounts': [{k: m.get(k) for k in ('Type', 'Source', 'Destination', 'RW')} for m in raw['Mounts']]})
    paths = {p['path']: p for p in receipt['paths']}
    require(set(paths) == {PG_SOCKET, REDIS_SOCKET, '/tmp/tb70-pg-socket', '/tmp/tb70-redis-socket'}, 'Wrong created path set')
    for name, record in paths.items():
        current = Path(name).lstat() if 'target' in record else Path(name).stat()
        require(current.st_ino == record['inode'], 'Owned socket path inode changed')
    for socket in [PG_SOCKET + '/.s.PGSQL.5432', REDIS_SOCKET + '/redis.sock']:
        require(stat.S_ISSOCK(Path(socket).stat().st_mode), 'Owned service socket absent')
    for alias, target in [('/tmp/tb70-pg-socket', PG_SOCKET), ('/tmp/tb70-redis-socket', REDIS_SOCKET)]:
        require(Path(alias).is_symlink() and Path(alias).resolve() == Path(target), 'Wrong socket alias')
    artifacts = Path(os.environ['P2N10_ARTIFACTS']).resolve(strict=True)
    require(artifacts.is_relative_to(path.parent) and artifacts.is_dir(), 'Artifacts outside owned receipt directory')
    ordered = sorted(actual, key=lambda r: r['kind'] != 'pg')
    # Original consumer reads mounts[0].Source; use the actual inspected socket bind.
    for resource in ordered:
        resource['mounts'].sort(key=lambda m: m['Type'] != 'bind')
    (artifacts / 'isolation.json').write_text(json.dumps(ordered, indent=2) + '\n', encoding='utf-8')
    return receipt, artifacts


def owned_name(receipt, name):
    require(re.fullmatch(r'tb70_p2n10_[0-9a-f]{32}', name), 'Foreign logical database denied')
    prefix = f"tb70_ci_{receipt['run_id']}_{receipt['attempt']}_"
    digest = hashlib.sha256((receipt['owner']['aia.owner'] + ':' + name).encode()).hexdigest()[:16]
    actual = prefix + digest
    require(len(actual) <= 63, 'Owned database name exceeds PostgreSQL limit')
    return actual


def require_owned_database(receipt, logical, actual, created):
    require(actual == owned_name(receipt, logical) and actual in created, 'Database not actually created by this run')


def save_database_event(artifacts, receipt, logical, actual, action):
    path = artifacts / 'owned-databases.json'
    rows = json.loads(path.read_text()) if path.exists() else []
    rows.append({'run_id': receipt['run_id'], 'attempt': receipt['attempt'], 'sha': receipt['sha'], 'owner': receipt['owner']['aia.owner'], 'container_id': next(r['Id'] for r in receipt['containers'] if r['kind'] == 'pg'), 'logical': logical, 'actual': actual, 'action': action})
    path.write_text(json.dumps(rows, indent=2) + '\n', encoding='utf-8')
