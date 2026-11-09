"""Alembic 环境（T-B02）。

- 目标元数据：:data:`app.db.base.metadata`（导入 :mod:`app.db.tables` 使其完整）。
- 只比较本项目的四个 schema（app / market / ops / evaluation）；``public``、
  ``_timescaledb_*``、``timescaledb_*`` 等扩展内部 schema 一律忽略。
- ``include_object`` 额外排除（T-O08 §13 第 5 项）：
  * 连续聚合视图 ``market.bars_*`` 及其物化 hypertable（后者在 ``_timescaledb_internal``，已被 schema 过滤）；
  * 声明式分区的子表 ``<parent>_pYYYYMM`` / ``<parent>_default``（由迁移与定时任务按月创建，不入元数据）；
  * 以 ``_`` 开头的对象（TimescaleDB 内部 / 压缩相关）。
  物化视图（``app.strategy_rules``）与普通视图 autogenerate 本就不反射。
- URL 不写进 alembic.ini：``-x url=`` > ``DATABASE_URL`` > Settings.database_url。
"""

from __future__ import annotations

import os
import re
from logging.config import fileConfig
from typing import Any

from alembic import context
from alembic.script import ScriptDirectory
from sqlalchemy import engine_from_config, pool

import app.db.tables  # noqa: F401  导入全部表
from app.db.base import SCHEMAS, metadata
from app.db.migration_check import (
    MigrationLineageError,
    crosses_override_revision,
    require_database_mainline,
    require_safe_downgrade,
    require_single_head,
)

config = context.config
mainline_script = ScriptDirectory.from_config(config)
require_single_head(mainline_script)
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

_PARTITION_CHILD = re.compile(r"_(p\d{6}|default)$")
_CAGG = re.compile(r"^bars_")


def _database_url() -> str:
    url = context.get_x_argument(as_dictionary=True).get("url") or os.environ.get("DATABASE_URL")
    if not url:
        from app.config import get_settings

        secret = get_settings().database_url
        url = secret.get_secret_value() if secret is not None else None
    if not url:
        raise RuntimeError("未设置数据库地址：请设置环境变量 DATABASE_URL")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    elif url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    return url


def include_name(name: str | None, type_: str, parent_names: Any) -> bool:
    if type_ == "schema":
        return name in SCHEMAS
    return True


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    if name is None:
        return True
    if type_ == "table":
        if name.startswith("_"):
            return False
        if reflected and compare_to is None:
            if _PARTITION_CHILD.search(name):
                return False
            if getattr(obj, "schema", None) == "market" and _CAGG.match(name):
                return False
    if type_ in {"index", "unique_constraint", "foreign_key_constraint"} and name.startswith("_"):
        return False
    return True


def _configure_kwargs() -> dict[str, Any]:
    return {
        "target_metadata": metadata,
        "include_schemas": True,
        "include_name": include_name,
        "include_object": include_object,
        "compare_type": True,
        "compare_server_default": False,
        "version_table_schema": "public",
    }


def run_migrations_offline() -> None:
    start, destination = context.get_starting_revision_argument(), context.get_revision_argument()
    if (
        start is not None
        and not crosses_override_revision(mainline_script, start)
        and crosses_override_revision(mainline_script, destination)
    ):
        raise MigrationLineageError(
            "UNSAFE_DOWNGRADE_0028: offline SQL cannot check cleared overrides; "
            "use the guarded online migration path"
        )
    context.configure(
        url=_database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_configure_kwargs(),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        with connection.begin():
            require_database_mainline(connection, mainline_script, allow_empty=True)
        context.configure(connection=connection, **_configure_kwargs())
        with context.begin_transaction():
            require_safe_downgrade(connection, mainline_script, context.get_revision_argument())
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
