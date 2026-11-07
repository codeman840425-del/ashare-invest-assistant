# ruff: noqa: S101, ANN401, F811
"""Isolated-only lineage rejection and 0020->0022->0020; never executes paused 0021."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.db.migration_check import (
    BACKEND,
    MigrationLineageError,
    require_database_mainline,
    require_single_head,
    script_directory,
)
from app.replay.baseline import require_isolated
from selfchecks.test_tb70_replay import DB, integration, no_network  # noqa: F401


def config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.cmd_opts = SimpleNamespace(x=["url=" + DB])
    return cfg


def test_exact_single_head_and_paused_file_unchanged() -> None:
    script = script_directory()
    assert require_single_head(script) == "0022"
    assert script.get_revision("0022").down_revision == "0020"
    assert "0021" not in {r.revision for r in script.walk_revisions()}
    assert (
        hashlib.sha256(
            (BACKEND / "migrations/paused/0021_t_b61b_not_set.py").read_bytes()
        ).hexdigest()
        == "3a2bd00e8ab4d6b957d0fa38e45cd2f5cb1b093b897c6571589a97268588296c"
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=True,
    )
    assert len(result.stdout.strip().splitlines()) == 1
    assert result.stdout.startswith("0022 ")


def test_multiple_synthetic_heads_fail_before_database_access(tmp_path: Path) -> None:
    versions = tmp_path / "versions"
    versions.mkdir()
    for rev, parent in [("a", None), ("b", "a"), ("c", "a")]:
        (versions / (rev + ".py")).write_text(f"revision={rev!r}\ndown_revision={parent!r}\n")
    with pytest.raises(MigrationLineageError, match="MIGRATION_HEADS_NOT_UNIQUE"):
        require_single_head(ScriptDirectory(str(tmp_path)))


def test_nonmainline_0021_stops_api_and_migration_without_applying_paused_ddl(
    integration: Any,
) -> None:
    engine, client, *_ = integration
    with engine.begin() as conn:
        require_isolated(conn, app_env="test")
        assert (
            conn.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one()
            == "0020"
        )
        conn.execute(text("UPDATE public.alembic_version SET version_num='0021'"))
    try:
        with (
            engine.connect() as conn,
            pytest.raises(MigrationLineageError, match="DATABASE_REVISION_NOT_MAINLINE: 0021"),
        ):
            require_database_mainline(conn, script_directory())
        with (
            pytest.raises(MigrationLineageError, match="DATABASE_REVISION_NOT_MAINLINE: 0021"),
            client,
        ):
            pass
        with pytest.raises(MigrationLineageError, match="DATABASE_REVISION_NOT_MAINLINE: 0021"):
            command.upgrade(config(), "head")
        with engine.connect() as conn:
            assert (
                conn.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one()
                == "0021"
            )
            assert (
                conn.execute(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_schema='app' AND table_name='feature_catalog' "
                        "AND column_name IN ('dimension','warmup_bars','epistemic_type')"
                    )
                ).scalar_one()
                == 0
            )
    finally:
        # Restore only synthetic version metadata; paused migration never ran.
        with engine.begin() as conn:
            conn.execute(text("UPDATE public.alembic_version SET version_num='0020'"))


def test_real_isolated_upgrade_head_idempotent_nullable_columns_and_restore(
    integration: Any,
) -> None:
    engine, *_ = integration
    with engine.connect() as conn:
        require_isolated(conn, app_env="test")
        require_database_mainline(conn, script_directory())
    try:
        command.upgrade(config(), "head")
        command.upgrade(config(), "head")
        with engine.connect() as conn:
            assert (
                conn.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one()
                == "0022"
            )
            require_database_mainline(conn, script_directory())
            nullable = (
                conn.execute(
                    text(
                        "SELECT is_nullable FROM information_schema.columns "
                        "WHERE table_schema='app' AND table_name='feature_catalog' "
                        "AND column_name IN ('dimension','warmup_bars','epistemic_type')"
                    )
                )
                .scalars()
                .all()
            )
            assert nullable == ["YES"] * 3
    finally:
        command.downgrade(config(), "0020")
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one()
            == "0020"
        )
