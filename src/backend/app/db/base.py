"""数据库元数据与建表辅助函数（plan §3.1 建模原则；DDL 由 Alembic 迁移实现）。

约定（plan §3.1 第 6 条）：
- 时间统一 ``timestamptz``（UTC）；交易日用 ``date``；金额/价格/数量用 ``numeric(20,4)``。
- 主键默认 ``uuid``，服务端 ``gen_random_uuid()``（契约 §1：UUID v4）。
- 枚举列一律 ``text`` + ``CHECK``（不用 PG ENUM 类型，便于后续迁移增删取值），取值来自
  :mod:`app.schemas.enums`（契约 v0.2）。契约是唯一事实来源（契约头部声明），plan 与契约
  取值不一致时以契约为准；契约没有对应枚举的列才按 plan 取值。冲突逐条记在 reports/T-B02.md。
- 约束与索引名由 :data:`NAMING_CONVENTION` 生成，``alembic check`` 依赖其稳定。

这里只放 SQLAlchemy Core ``Table`` 定义（供迁移与 ``alembic check`` 比对）；
ORM 映射类在各业务模块需要时再加。
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Any, Final

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

#: 业务 schema（plan §3.1 第 5 条、§3.3）
APP: Final = "app"
MARKET: Final = "market"
OPS: Final = "ops"
EVALUATION: Final = "evaluation"
SCHEMAS: Final[tuple[str, ...]] = (APP, MARKET, OPS, EVALUATION)

NAMING_CONVENTION: Final[dict[str, str]] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)

MONEY: Final = Numeric(20, 4)


def pk_uuid(name: str = "id") -> Column[Any]:
    return Column(
        name, UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def uuid_col(name: str, *, nullable: bool = True, fk: str | None = None, **kw: Any) -> Column[Any]:  # noqa: ANN401
    """uuid 列；``fk`` 形如 ``"app.users.id"``。"""
    args: list[Any] = [ForeignKey(fk, use_alter=kw.pop("use_alter", False))] if fk else []
    return Column(name, UUID(as_uuid=True), *args, nullable=nullable, **kw)


def user_fk(name: str = "user_id", *, nullable: bool = False) -> Column[Any]:
    return uuid_col(name, nullable=nullable, fk="app.users.id")


def ts(
    name: str,
    *,
    nullable: bool = True,
    default_now: bool = False,
    **kw: Any,  # noqa: ANN401
) -> Column[Any]:
    return Column(
        name,
        DateTime(timezone=True),
        nullable=nullable,
        server_default=func.now() if default_now else None,
        **kw,
    )


def created_at(name: str = "created_at") -> Column[Any]:
    return ts(name, nullable=False, default_now=True)


def day(name: str, *, nullable: bool = True, **kw: Any) -> Column[Any]:  # noqa: ANN401
    return Column(name, Date, nullable=nullable, **kw)


def txt(name: str, *, nullable: bool = True, **kw: Any) -> Column[Any]:  # noqa: ANN401
    return Column(name, Text, nullable=nullable, **kw)


def money(name: str, *, nullable: bool = True, **kw: Any) -> Column[Any]:  # noqa: ANN401
    return Column(name, MONEY, nullable=nullable, **kw)


def num(name: str, *, nullable: bool = True, **kw: Any) -> Column[Any]:  # noqa: ANN401
    """无精度 numeric：统计量/权重/比率等计算结果（plan 未给精度）。"""
    return Column(name, Numeric, nullable=nullable, **kw)


def integer(name: str, *, nullable: bool = True, **kw: Any) -> Column[Any]:  # noqa: ANN401
    return Column(name, Integer, nullable=nullable, **kw)


def boolean(name: str, *, nullable: bool = True, **kw: Any) -> Column[Any]:  # noqa: ANN401
    return Column(name, Boolean, nullable=nullable, **kw)


def jsonb(name: str, *, nullable: bool = True, **kw: Any) -> Column[Any]:  # noqa: ANN401
    return Column(name, JSONB, nullable=nullable, **kw)


def text_array(name: str, *, nullable: bool = True, **kw: Any) -> Column[Any]:  # noqa: ANN401
    return Column(name, ARRAY(Text), nullable=nullable, **kw)


def uuid_array(name: str, *, nullable: bool = True, **kw: Any) -> Column[Any]:  # noqa: ANN401
    return Column(name, ARRAY(UUID(as_uuid=True)), nullable=nullable, **kw)


def _sql_list(values: Iterable[str]) -> str:
    items = []
    for v in values:
        if "'" in v:
            raise ValueError(f"枚举取值不能含单引号：{v!r}")
        items.append(f"'{v}'")
    return ", ".join(items)


def one_of(
    column: str, values: Iterable[str] | type[StrEnum], *, name: str | None = None
) -> CheckConstraint:
    """``CHECK (column IN (...))``；列可空时 NULL 自然通过。"""
    vals = [m.value for m in values] if isinstance(values, type) else list(values)
    return CheckConstraint(f"{column} IN ({_sql_list(vals)})", name=name or column)


def jsonpath_one_of(path: str, values: Iterable[str] | type[StrEnum]) -> str:
    """SQL/JSON path 谓词：``path`` 等于取值之一（缺键、类型不符均为假）。"""
    vals = [m.value for m in values] if isinstance(values, type) else list(values)
    return "(" + " || ".join(f'{path} == "{v}"' for v in vals) + ")"


def jsonb_array_items(column: str, bad_item: str, *, nullable: bool = False) -> str:
    """``column`` 是 JSON 数组，且没有元素满足 ``bad_item``。

    ``bad_item`` 是 SQL/JSON path 过滤谓词，``@`` 为元素。

    用 ``jsonb_path_exists`` 写成 CHECK 表达式（不需要自定义函数）。``nullable=True`` 时 NULL 通过。
    """
    expr = (
        f"jsonb_typeof({column}) = 'array' AND NOT jsonb_path_exists("
        f"{column}, '$[*] ? ({bad_item})')"
    )
    return f"({column} IS NULL OR ({expr}))" if nullable else expr


def array_subset(
    column: str, values: Iterable[str] | type[StrEnum], *, name: str | None = None
) -> CheckConstraint:
    """``CHECK (column <@ ARRAY[...])``：text[] 的每个元素都必须在取值集合内。"""
    vals = [m.value for m in values] if isinstance(values, type) else list(values)
    return CheckConstraint(f"{column} <@ ARRAY[{_sql_list(vals)}]::text[]", name=name or column)


def union(*groups: Iterable[str] | type[StrEnum]) -> list[str]:
    """多个来源的取值并集（保持首次出现的顺序）；用于 plan 与契约取值不一致时的保守 CHECK。"""
    out: list[str] = []
    for g in groups:
        for v in [m.value for m in g] if isinstance(g, type) else g:
            if v not in out:
                out.append(v)
    return out
