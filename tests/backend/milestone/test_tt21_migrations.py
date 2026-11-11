"""固定main当前head负例及幂等验收；不自动降级/修复库。"""
import sys
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import text
from app.db.migration_check import MigrationLineageError, require_database_mainline, script_directory, BACKEND
from selfchecks.test_ta14_migrations import config
# Resolve the sibling helper under pytest's importlib mode, independent of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tt21_head import expected_main_head


def columns(conn):
    return conn.execute(text("SELECT column_name,is_nullable FROM information_schema.columns "
                             "WHERE table_schema='app' AND table_name='feature_catalog' "
                             "AND column_name IN ('dimension','warmup_bars','epistemic_type') ORDER BY column_name")).all()


def test_nonmainline_is_rejected_without_schema_or_main_head_drift(tt21_integration):
    engine, client, *_ = tt21_integration
    head = expected_main_head(BACKEND)
    with engine.begin() as conn:
        before = columns(conn)
        assert conn.execute(text('SELECT version_num FROM public.alembic_version')).scalar_one() == head
        conn.execute(text("UPDATE public.alembic_version SET version_num='0021'"))
    try:
        with engine.connect() as conn, pytest.raises(MigrationLineageError, match='DATABASE_REVISION_NOT_MAINLINE: 0021'):
            require_database_mainline(conn, script_directory())
        with pytest.raises(MigrationLineageError, match='DATABASE_REVISION_NOT_MAINLINE: 0021'), client:
            pass
        with pytest.raises(MigrationLineageError, match='DATABASE_REVISION_NOT_MAINLINE: 0021'):
            command.upgrade(config(), 'head')
        with engine.connect() as conn:
            assert conn.execute(text('SELECT version_num FROM public.alembic_version')).scalar_one() == '0021'
            assert columns(conn) == before
    finally:
        # 只收回本例主动制造的隔离负例元数据；不从任意DB值推断期望，不改DDL。
        with engine.begin() as conn:
            assert conn.execute(text('SELECT version_num FROM public.alembic_version')).scalar_one() == '0021'
            conn.execute(text('UPDATE public.alembic_version SET version_num=:h'), {'h': head})


def test_current_main_head_upgrade_is_idempotent_without_downgrade(tt21_integration):
    engine, *_ = tt21_integration
    head = expected_main_head(BACKEND)
    with engine.connect() as conn:
        assert conn.execute(text('SELECT version_num FROM public.alembic_version')).scalar_one() == head
        before = columns(conn)
    command.upgrade(config(), 'head')
    command.upgrade(config(), 'head')
    with engine.connect() as conn:
        assert conn.execute(text('SELECT version_num FROM public.alembic_version')).scalar_one() == head
        assert columns(conn) == before
        assert len(before) == 3 and all(row[1] == 'YES' for row in before)
