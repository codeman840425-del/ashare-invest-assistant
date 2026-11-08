"""app.db 元数据约定（plan §3.1 建模原则第 5/6 条；不连数据库，只检查 SQLAlchemy Core 元数据）。

- 业务 schema 只有 app / market / ops / evaluation；
- 主键/约束名由 NAMING_CONVENTION 生成（pk_<表名>），``alembic check`` 依赖其稳定；
- 时间列一律 timestamptz；带精度的 numeric 一律 numeric(20,4)；
- 枚举列用 text + CHECK，CHECK 取值不得含单引号；表定义能在 PostgreSQL 方言下编译出 DDL。
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import pytest

base = pytest.importorskip("app.db.base", reason="等待后端 T-B02 数据库元数据落地")
tables_pkg = pytest.importorskip("app.db.tables")

from sqlalchemy import CheckConstraint, DateTime, Numeric  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402
from sqlalchemy.schema import CreateTable  # noqa: E402

TABLES = list(base.metadata.tables.values())


class _Color(StrEnum):
    RED = "red"
    BLUE = "blue"


def test_tables_registered_in_known_schemas():
    assert len(TABLES) > 0
    assert {t.schema for t in TABLES} <= set(base.SCHEMAS)
    assert base.SCHEMAS == ("app", "market", "ops", "evaluation")
    # 包内每个表模块都要被 app.db.tables 导入，否则 alembic check 会漏表
    pkg_dir = Path(tables_pkg.__file__).parent
    assert {p.stem for p in pkg_dir.glob("*.py") if p.stem != "__init__"} == set(tables_pkg.__all__)


def test_primary_keys_named_by_convention():
    bad = [t.fullname for t in TABLES if t.primary_key.name != f"pk_{t.name}" or not t.primary_key.columns]
    assert not bad


def test_timestamps_are_timestamptz():
    bad = [f"{t.fullname}.{c.name}" for t in TABLES for c in t.columns
           if isinstance(c.type, DateTime) and not c.type.timezone]
    assert not bad


def test_numeric_precision_is_20_4_or_unbounded():
    bad = [f"{t.fullname}.{c.name}" for t in TABLES for c in t.columns
           if isinstance(c.type, Numeric) and c.type.precision is not None
           and (c.type.precision, c.type.scale) != (20, 4)]
    assert not bad


def test_all_tables_compile_to_postgres_ddl():
    dialect = postgresql.dialect()
    for t in TABLES:
        ddl = str(CreateTable(t).compile(dialect=dialect))
        assert f"pk_{t.name}" in ddl, t.fullname


def test_check_constraints_are_named():
    bad = [t.fullname for t in TABLES for c in t.constraints
           if isinstance(c, CheckConstraint) and not c.name]
    assert not bad


def test_one_of_and_array_subset_helpers():
    ck = base.one_of("color", _Color)
    assert str(ck.sqltext) == "color IN ('red', 'blue')" and ck.name == "color"
    ck2 = base.one_of("color", ["x", "y"], name="c2")
    assert str(ck2.sqltext) == "color IN ('x', 'y')" and ck2.name == "c2"
    arr = base.array_subset("tags", _Color)
    assert str(arr.sqltext) == "tags <@ ARRAY['red', 'blue']::text[]"
    with pytest.raises(ValueError):
        base.one_of("color", ["it's"])


def test_union_keeps_first_seen_order():
    assert base.union(["blue", "green"], _Color, ["green", "pink"]) == ["blue", "green", "red", "pink"]


def test_column_helpers():
    assert base.money("m").type.precision == 20 and base.money("m").type.scale == 4
    assert base.created_at().nullable is False and base.created_at().server_default is not None
    assert base.ts("t").server_default is None and base.ts("t").type.timezone
    fk = base.user_fk()
    assert fk.nullable is False and {f.target_fullname for f in fk.foreign_keys} == {"app.users.id"}
    assert base.uuid_col("u").foreign_keys == set()
    pk = base.pk_uuid()
    assert pk.primary_key and "gen_random_uuid" in str(pk.server_default.arg)
    for helper in (base.day, base.txt, base.num, base.integer, base.boolean, base.jsonb,
                   base.text_array, base.uuid_array):
        assert helper("c", nullable=False).nullable is False
