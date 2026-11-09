# ruff: noqa: S101
"""T-T44 / T-A80 L-4：0030 库删任一 gate 函数后 apply-roles 必须非 0。"""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
APPLY = ROOT / "deploy/db/roles/apply-roles.sh"
GATE_FNS = (
    "ops.gate_user_refs(uuid)",
    "ops.purge_user_gate_facts(uuid)",
)


def _require_apply_env() -> dict[str, str]:
    """缺口令目录或 PG* 时带原因 skip（非静默）。"""
    pwdir = os.environ.get("AIA_DB_ROLE_PASSWORD_DIR")
    host = os.environ.get("PGHOST")
    port = os.environ.get("PGPORT")
    user = os.environ.get("PGUSER")
    if not pwdir or not Path(pwdir).is_dir():
        pytest.skip(
            "AIA_DB_ROLE_PASSWORD_DIR 未设置或不是目录："
            "T-A80 L-4 需要 apply-roles 口令目录（T-T44）"
        )
    if not host or not port or not user:
        pytest.skip(
            "PGHOST/PGPORT/PGUSER 未齐：T-A80 L-4 需在 o61-pg 临时库上跑 apply-roles（T-T44）"
        )
    template = os.environ.get("TT44_GATE_TEMPLATE_DB", "tt44_tmp_tpl")
    return {
        "PGHOST": host,
        "PGPORT": port,
        "PGUSER": user,
        "AIA_DB_ROLE_PASSWORD_DIR": pwdir,
        "TEMPLATE": template,
    }


def _psql_env(env: dict[str, str], db: str) -> dict[str, str]:
    e = {**os.environ, "PGHOST": env["PGHOST"], "PGPORT": env["PGPORT"], "PGUSER": env["PGUSER"], "PGDATABASE": db}
    return e


def _psql(env: dict[str, str], db: str, sql: str) -> subprocess.CompletedProcess[str]:
    # 单条 -c；CREATE/DROP DATABASE 不能放进显式事务块
    return subprocess.run(
        ["psql", "-v", "ON_ERROR_STOP=1", "-c", sql],
        env=_psql_env(env, db),
        text=True,
        capture_output=True,
        check=False,
    )


def _psql_scalar(env: dict[str, str], db: str, sql: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["psql", "-v", "ON_ERROR_STOP=1", "-tAc", sql],
        env=_psql_env(env, db),
        text=True,
        capture_output=True,
        check=False,
    )


def _drop_db(env: dict[str, str], db: str) -> None:
    _psql(
        env,
        "postgres",
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname='{db}' AND pid<>pg_backend_pid();",
    )
    _psql(env, "postgres", f"DROP DATABASE IF EXISTS {db};")


@pytest.mark.parametrize("gate_fn", GATE_FNS)
def test_ta80_l4_apply_roles_nonzero_when_any_gate_fn_missing(gate_fn: str) -> None:
    """0030 库删掉任一 gate 函数后，apply-roles 必须返回非 0；函数仍缺失（单事务回滚）。"""
    env = _require_apply_env()
    assert APPLY.is_file(), f"missing {APPLY}"
    db = f"tt44_tmp_gate_{uuid.uuid4().hex[:10]}"
    try:
        _drop_db(env, db)
        # CREATE … TEMPLATE 要求模板库无其它会话；只断模板连接，不改模板内容
        _psql(
            env,
            "postgres",
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname='{env['TEMPLATE']}' AND pid<>pg_backend_pid();",
        )
        c = _psql(env, "postgres", f"CREATE DATABASE {db} TEMPLATE {env['TEMPLATE']};")
        assert c.returncode == 0, c.stderr[-500:]
        c = _psql_scalar(env, db, "SELECT version_num FROM alembic_version;")
        assert c.returncode == 0 and c.stdout.strip().startswith("0030"), c.stdout
        c = _psql(env, db, f"DROP FUNCTION {gate_fn};")
        assert c.returncode == 0, c.stderr[-500:]
        c = _psql_scalar(env, db, f"SELECT to_regprocedure('{gate_fn}') IS NULL;")
        assert c.stdout.strip() == "t"

        run_env = _psql_env(env, db)
        run_env["AIA_DB_ROLE_PASSWORD_DIR"] = env["AIA_DB_ROLE_PASSWORD_DIR"]
        proc = subprocess.run(
            ["bash", str(APPLY)],
            env=run_env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert proc.returncode != 0, (
            f"缺 {gate_fn} 时 apply 应非 0，实际 0；stderr_tail={proc.stderr[-300:]!r}"
        )
        c = _psql_scalar(env, db, f"SELECT to_regprocedure('{gate_fn}') IS NULL;")
        assert c.returncode == 0 and c.stdout.strip() == "t"
    finally:
        _drop_db(env, db)
