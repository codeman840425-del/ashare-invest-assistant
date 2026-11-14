"""Offline checks of the explicit migration snapshot; no database or DDL execution."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from .tt21_head import expected_main_head

BACKEND = Path(__file__).resolve().parents[3] / 'src/backend'


def test_explicit_mainline_snapshot_has_reviewed_0035_head():
    manifest = json.loads(Path(__file__).with_name('tt21_mainline.json').read_text())
    assert manifest['baseline'] == '6190fbb17057094843e22d2e7a7935c9a270c770'
    assert manifest['main_migration_baseline'] == '465e02046fa8d971897603742497444f884e89a2'
    assert manifest['expected_head'] == '0035'
    assert len(manifest['migrations']) == 34
    assert expected_main_head(BACKEND) == '0035'


@pytest.mark.parametrize('mutation', ['change', 'add', 'remove'])
def test_explicit_mainline_snapshot_rejects_unreviewed_migrations(tmp_path, mutation):
    target = tmp_path / 'backend'
    shutil.copytree(BACKEND / 'migrations', target / 'migrations')
    versions = target / 'migrations/versions'
    if mutation == 'change':
        migration = versions / '0034_tb133_minute_bars_sources.py'
        migration.write_bytes(migration.read_bytes() + b'\n# unreviewed change\n')
    elif mutation == 'add':
        (versions / '0036_unreviewed.py').write_text("revision = '0036'\ndown_revision = '0035'\n")
    else:
        (versions / '0034_tb133_minute_bars_sources.py').unlink()
    with pytest.raises(AssertionError, match='受测迁移文件不是固定main'):
        expected_main_head(target)
