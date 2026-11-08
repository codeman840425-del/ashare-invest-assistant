"""T-T24（编排补充 b）：0008 → 0011 迁移升级保数据 + 状态映射（review-T-B02y M1 回填规则）。

用 testcontainers 的一次性数据库（``pg_url`` 上新建 ``tt24_mig_<hex>``，结束 ``DROP … WITH (FORCE)``），
绝不连共享库（aia-t01 / be-b03a-pg 等）。步骤：

1. ``alembic upgrade 0008``，按 0008 的表结构直接写入：用户（approved / disabled）、策略与版本、
   6 个实例——paused ×2（account / security 范围）、archived ×3（有 archived 事件 / 仅 confirmed_at /
   仅 created_at）、active ×1，外加 created/confirmed/paused/archived 事件；``market.securities`` 保持为空
   （0009 在该表已有行时会拒绝升级——类型无法推断）。
2. ``alembic upgrade 0011``，断言：
   - 行数、主键、user_id / scope / security_code / origin / param_overrides / created_at / confirmed_at /
     status 全部不变，事件条数与内容不变，用户状态不变；
   - paused → ``paused_by='user'``，``pause_reason_code``、``paused_until`` 为 NULL；
   - archived → ``archived_at`` = 最近一次 ``kind='archived'`` 事件时间，否则 ``confirmed_at``，否则 ``created_at``；
   - 非 paused/archived 行的暂停与归档字段全为 NULL；
   - 升级后一致性 CHECK 生效（paused 行清掉 ``paused_by`` 被拒）。
3. 往返：``downgrade 0008`` 再 ``upgrade 0011``，数据仍在、回填结果相同。

origin/main（0cb78ad）上 alembic 只到 0008：没有 0009–0011 时整文件 xfail，
owner：T-B02y（0009，含 c55a42e 回填）/ T-B03d（0010 holds）/ T-B16（0011 purge）——待 ops 推送到 origin。
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = ROOT / "src" / "backend"
VERSIONS = BACKEND_DIR / "migrations" / "versions"

NEEDED = ("0009", "0010", "0011")
OWNERS = "T-B02y（0009/c55a42e）、T-B03d（0010）、T-B16（0011）；ops 推送 0009–0011 到 origin"


def _present() -> list[str]:
    if not VERSIONS.is_dir():
        return []
    return sorted({p.name[:4] for p in VERSIONS.glob("[0-9][0-9][0-9][0-9]_*.py")})


def _missing() -> list[str]:
    have = set(_present())
    return [r for r in NEEDED if r not in have]


def _with_db(url: str, name: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, "/" + name, p.query, p.fragment))


def _alembic(env: dict[str, str], *args: str) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, f"alembic {' '.join(args)} 失败：\n" + (proc.stderr or proc.stdout)[-2000:]


T0 = datetime(2026, 1, 5, 1, 0, tzinfo=UTC)


def _ts(day: int, hour: int = 1) -> datetime:
    return datetime(2026, 1, day, hour, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def migdb(pg_url: str) -> Iterator[SimpleNamespace]:
    import psycopg

    missing = _missing()
    if missing:
        pytest.xfail(f"迁移 {','.join(missing)} 不在本版本（alembic 只到 {(_present() or ['?'])[-1]}）；owner：{OWNERS}")
    base = pg_url.replace("postgresql+psycopg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")
    name = "tt24_mig_" + secrets.token_hex(4)
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = _with_db(base, name)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("BUSINESS__",))}
    env.update({"DATABASE_URL": url, "APP_ENV": "test", "PYTHONDONTWRITEBYTECODE": "1"})
    env.pop("APP_MASTER_KEY", None)
    try:
        yield SimpleNamespace(url=url, env=env, name=name)
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _q(url: str, stmt: str, params: Any = None) -> list[tuple[Any, ...]]:
    import psycopg

    with psycopg.connect(url) as c:
        cur = c.execute(stmt, params)
        return list(cur.fetchall()) if cur.description else []


INST_COLS = (
    "id, user_id, strategy_version_id, scope, account_id, security_code, status, origin, "
    "param_overrides, budget_amount, auto_downweight, created_at, confirmed_at"
)


def _seed(url: str) -> SimpleNamespace:
    import psycopg
    from psycopg.types.json import Jsonb

    ids = SimpleNamespace()
    with psycopg.connect(url) as c:
        assert c.execute("select version_num from alembic_version").fetchone() == ("0008",)
        assert c.execute("select count(*) from market.securities").fetchone() == (0,)
        ids.u1 = c.execute(
            "insert into app.users (username, password_hash, role, status) "
            "values ('tt24_alice', 'x', 'user', 'approved') returning id"
        ).fetchone()[0]
        ids.u2 = c.execute(
            "insert into app.users (username, password_hash, role, status) "
            "values ('tt24_bob', 'x', 'user', 'disabled') returning id"
        ).fetchone()[0]
        sid = c.execute(
            "insert into app.strategies (key, name, owner_user_id) values ('tt24_s', 'tt24', %s) returning id",
            (ids.u1,),
        ).fetchone()[0]
        ids.sv = c.execute(
            "insert into app.strategy_versions (strategy_id, version_no, config, config_hash) "
            "values (%s, 1, %s, 'h1') returning id",
            (sid, Jsonb({"k": 1})),
        ).fetchone()[0]

        def inst(user: Any, status: str, created: datetime, confirmed: datetime | None,
                 scope: str = "account", code: str | None = None, po: Any = None) -> Any:
            return c.execute(
                "insert into app.strategy_instances (user_id, strategy_version_id, scope, security_code, status, "
                "origin, param_overrides, budget_amount, created_at, confirmed_at) "
                "values (%s, %s, %s, %s, %s, 'user', %s, 1000.50, %s, %s) returning id",
                (user, ids.sv, scope, code, status, None if po is None else Jsonb(po), created, confirmed),
            ).fetchone()[0]

        def ev(i: Any, kind: str, at: datetime, actor: Any) -> None:
            c.execute(
                "insert into app.strategy_instance_events (instance_id, kind, detail, actor_id, at) "
                "values (%s, %s, %s, %s, %s)",
                (i, kind, Jsonb({"tt24": kind}), actor, at),
            )

        ids.paused_acct = inst(ids.u1, "paused", _ts(1), _ts(2), po={"n": 5})
        ev(ids.paused_acct, "created", _ts(1), ids.u1)
        ev(ids.paused_acct, "confirmed", _ts(2), ids.u1)
        ev(ids.paused_acct, "paused", _ts(3), ids.u1)
        # security 范围、证券表为空：0009 的 ETF 触发器只管新写入，既有行必须原样保留
        ids.paused_sec = inst(ids.u2, "paused", _ts(1, 2), _ts(2, 2), scope="security", code="600000.SH")
        ids.arch_event = inst(ids.u1, "archived", _ts(1, 3), _ts(2, 3))
        ev(ids.arch_event, "archived", _ts(6), ids.u1)
        ev(ids.arch_event, "resumed", _ts(7), ids.u1)
        ev(ids.arch_event, "archived", _ts(8), ids.u1)  # 最近一次 → archived_at
        ev(ids.arch_event, "paused", _ts(9), ids.u1)  # 非 archived 事件不参与
        ids.arch_confirmed = inst(ids.u1, "archived", _ts(1, 4), _ts(4, 4))
        ids.arch_created = inst(ids.u2, "archived", _ts(1, 5), None)
        ids.active = inst(ids.u1, "active", _ts(1, 6), _ts(2, 6))
        ids.proposed = inst(ids.u1, "proposed", _ts(1, 7), None)
        c.commit()
    ids.expect_archived_at = {
        ids.arch_event: _ts(8),
        ids.arch_confirmed: _ts(4, 4),
        ids.arch_created: _ts(1, 5),
    }
    return ids


def _snapshot(url: str) -> dict[str, Any]:
    return {
        "inst": _q(url, f"select {INST_COLS} from app.strategy_instances order by id"),
        "events": _q(url, "select id, instance_id, kind, detail, actor_id, at from app.strategy_instance_events order by id"),
        "users": _q(url, "select id, username, role, status from app.users order by id"),
    }


def _assert_mapped(url: str, ids: SimpleNamespace) -> None:
    rows = {
        r[0]: r[1:]
        for r in _q(
            url,
            "select id, status, paused_by, pause_reason_code, paused_until, archived_at "
            "from app.strategy_instances",
        )
    }
    assert len(rows) == 7
    for i in (ids.paused_acct, ids.paused_sec):
        assert rows[i] == ("paused", "user", None, None, None), rows[i]
    for i, at in ids.expect_archived_at.items():
        status, pb, prc, pu, aat = rows[i]
        assert (status, pb, prc, pu) == ("archived", None, None, None)
        assert aat == at, (i, aat, at)
    for i, st in ((ids.active, "active"), (ids.proposed, "proposed")):
        assert rows[i] == (st, None, None, None, None), rows[i]


def test_upgrade_0008_to_0011_preserves_and_maps_states(migdb: SimpleNamespace) -> None:
    import psycopg

    _alembic(migdb.env, "upgrade", "0008")
    ids = _seed(migdb.url)
    before = _snapshot(migdb.url)

    _alembic(migdb.env, "upgrade", "0011")
    assert _q(migdb.url, "select version_num from alembic_version") == [("0011",)]
    after = _snapshot(migdb.url)
    assert after == before, "升级改动了既有实例 / 事件 / 用户数据"
    _assert_mapped(migdb.url, ids)

    # 一致性 CHECK 已生效：paused 行去掉 paused_by 必须被拒
    with psycopg.connect(migdb.url) as c, pytest.raises(psycopg.errors.CheckViolation):
        c.execute("update app.strategy_instances set paused_by = null where id = %s", (ids.paused_acct,))
    # archived 行去掉 archived_at 同样被拒（归档一致性 CHECK）
    with psycopg.connect(migdb.url) as c, pytest.raises(psycopg.errors.CheckViolation):
        c.execute("update app.strategy_instances set archived_at = null where id = %s", (ids.arch_created,))
    migdb.ids, migdb.before = ids, before


def test_roundtrip_downgrade_0008_then_upgrade_0011(migdb: SimpleNamespace) -> None:
    if not hasattr(migdb, "ids"):
        pytest.skip("依赖上一用例的升级结果")
    _alembic(migdb.env, "downgrade", "0008")
    assert _q(migdb.url, "select version_num from alembic_version") == [("0008",)]
    assert _snapshot(migdb.url) == migdb.before, "降级到 0008 丢了数据"
    _alembic(migdb.env, "upgrade", "0011")
    assert _snapshot(migdb.url) == migdb.before
    _assert_mapped(migdb.url, migdb.ids)


def test_owner_gate_is_explicit() -> None:
    """控制：本文件只在 0009–0011 缺失时 xfail，缺哪个就报哪个。"""
    have = _present()
    assert "0008" in have, have
    assert _missing() == [r for r in NEEDED if r not in have]
