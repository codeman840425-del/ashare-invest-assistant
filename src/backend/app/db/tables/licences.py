"""每用户数据证书（契约 v0.2.6，plan §2.1B / §3.3，T-A07；迁移 0007）。

- ``app.user_data_licences``：证书**只存 HPKE 密文**（``ciphertext``）与去重 HMAC
  （``licence_hmac``）；软删除时两者置 NULL。
  每个用户、每个证书 HMAC 在未删除行里各最多一行（部分唯一索引）。
  ``status`` 不含 ``not_set``（没有行即 ``not_set``）。
- ``app.user_data_licence_status``：**不含密文与 HMAC** 的视图，api 读状态只用它。
  按 plan 设计 api 的数据库角色不应有 ``ciphertext`` 的 SELECT 权限；目前全站只有一个数据库角色，
  列级授权留给运维（见 T-B45 报告）。视图不在 metadata 里（alembic 不反射视图），用
  :data:`user_data_licence_status` 这个轻量 ``table()`` 对象查询。
- ``ops.data_licence_events``：只追加（触发器拒绝 UPDATE/DELETE），不含证书值。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import CheckConstraint, Column, Index, Table, column, table, text
from sqlalchemy.dialects.postgresql import BYTEA, UUID
from sqlalchemy.types import Boolean, Date, DateTime, Integer, Text, TypeEngine

from app.db.base import (
    APP,
    OPS,
    boolean,
    created_at,
    day,
    integer,
    metadata,
    one_of,
    pk_uuid,
    ts,
    txt,
    user_fk,
    uuid_col,
)
from app.schemas.enums import DATA_LICENCE_ERROR_CODES, DataLicenceStatus, DataLicenceTier

#: 行上可出现的状态（``not_set`` = 没有未删除的行）
ROW_STATUSES: tuple[str, ...] = tuple(
    s.value for s in DataLicenceStatus if s is not DataLicenceStatus.NOT_SET
)
DATA_LICENCE_EVENTS: tuple[str, ...] = (
    "set",
    "replaced",
    "deleted",
    "verified",
    "invalid",
    "expired",
    "quota_exceeded",
    "ip_limited",
    "paused",
    "resumed",
    "expiry_reminder",
)
DATA_LICENCE_ACTORS: tuple[str, ...] = ("user", "admin", "ingest")
PROVIDERS: tuple[str, ...] = ("mairui",)

user_data_licences = Table(
    "user_data_licences",
    metadata,
    pk_uuid(),
    user_fk(),
    txt("provider", nullable=False, server_default=text("'mairui'")),
    Column("ciphertext", BYTEA, comment="HPKE 密文（enc||ct）；删除时置 NULL"),
    integer("seal_key_version", nullable=False),
    Column("licence_hmac", BYTEA, comment="去重 HMAC；删除时置 NULL；不对外"),
    txt("tier", nullable=False),
    boolean("has_quant_pro", nullable=False, server_default=text("false")),
    day("expires_on"),
    txt("status", nullable=False),
    ts("status_changed_at", nullable=False, default_now=True),
    ts("last_verified_at"),
    txt("last_error_code"),
    ts("last_error_at"),
    integer("consecutive_failures", nullable=False, server_default=text("0")),
    ts("paused_until"),
    integer("per_minute_limit_override"),
    created_at(),
    ts("updated_at", nullable=False, default_now=True),
    ts("deleted_at"),
    one_of("provider", PROVIDERS),
    one_of("tier", DataLicenceTier),
    one_of("status", ROW_STATUSES),
    one_of("last_error_code", DATA_LICENCE_ERROR_CODES),
    CheckConstraint("seal_key_version >= 1", name="seal_key_version_positive"),
    CheckConstraint("consecutive_failures >= 0", name="consecutive_failures_nonneg"),
    CheckConstraint(
        "per_minute_limit_override IS NULL OR per_minute_limit_override > 0",
        name="per_minute_limit_override_positive",
    ),
    CheckConstraint(
        "deleted_at IS NOT NULL OR (ciphertext IS NOT NULL AND licence_hmac IS NOT NULL)",
        name="live_has_secret",
    ),
    CheckConstraint(
        "deleted_at IS NULL OR (ciphertext IS NULL AND licence_hmac IS NULL)",
        name="deleted_wiped",
    ),
    schema=APP,
)
Index(
    "uq_user_data_licences_user_live",
    user_data_licences.c.user_id,
    unique=True,
    postgresql_where=text("deleted_at IS NULL"),
)
Index(
    "uq_user_data_licences_hmac_live",
    user_data_licences.c.licence_hmac,
    unique=True,
    postgresql_where=text("deleted_at IS NULL"),
)

data_licence_events = Table(
    "data_licence_events",
    metadata,
    pk_uuid(),
    uuid_col("licence_id", nullable=False, fk="app.user_data_licences.id"),
    user_fk(),
    txt("event", nullable=False),
    txt("actor", nullable=False),
    txt("from_status"),
    txt("to_status"),
    txt("upstream_code"),
    ts("at", nullable=False, default_now=True),
    one_of("event", DATA_LICENCE_EVENTS),
    one_of("actor", DATA_LICENCE_ACTORS),
    one_of("from_status", [s.value for s in DataLicenceStatus]),
    one_of("to_status", [s.value for s in DataLicenceStatus]),
    schema=OPS,
    comment="只追加（触发器拒绝 UPDATE/DELETE）；不含证书值",
)
Index(
    "ix_data_licence_events_licence_at",
    data_licence_events.c.licence_id,
    data_licence_events.c.at.desc(),
)

#: 视图 ``app.user_data_licence_status`` 的列（= 表去掉 ciphertext、licence_hmac）
VIEW_COLUMNS: tuple[str, ...] = tuple(
    c.name for c in user_data_licences.columns if c.name not in {"ciphertext", "licence_hmac"}
)

_VIEW_TYPES: dict[str, TypeEngine[Any]] = {
    "id": UUID(as_uuid=True),
    "user_id": UUID(as_uuid=True),
    "seal_key_version": Integer(),
    "has_quant_pro": Boolean(),
    "expires_on": Date(),
    "consecutive_failures": Integer(),
    "per_minute_limit_override": Integer(),
}
_TS = {
    "status_changed_at",
    "last_verified_at",
    "last_error_at",
    "paused_until",
    "created_at",
    "updated_at",
    "deleted_at",
}


def _view_type(name: str) -> TypeEngine[Any]:
    if name in _TS:
        return DateTime(timezone=True)
    return _VIEW_TYPES.get(name, Text())


user_data_licence_status = table(
    "user_data_licence_status",
    *(column(n, _view_type(n)) for n in VIEW_COLUMNS),
    schema=APP,
)
