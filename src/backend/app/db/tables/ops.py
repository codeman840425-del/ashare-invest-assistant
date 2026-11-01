"""运维 schema ``ops``：采集请求日志与单活租约（plan §3.3、§2.12）。

只记录元数据，不记录 licence 与完整 URL。
"""

from __future__ import annotations

from sqlalchemy import Index, PrimaryKeyConstraint, Table, UniqueConstraint, text

from app.db.base import OPS, created_at, integer, metadata, one_of, pk_uuid, ts, txt, uuid_col

ingest_request_log = Table(
    "ingest_request_log",
    metadata,
    uuid_col("id", nullable=False, server_default=text("gen_random_uuid()")),
    ts("requested_at", nullable=False, default_now=True),
    txt("requester", nullable=False),
    txt("priority", nullable=False),
    txt("dataset"),
    txt("endpoint_key", nullable=False),
    integer("symbols_count"),
    txt("dedup_key"),
    txt("status", nullable=False),
    integer("http_status"),
    txt("mairui_code"),
    integer("latency_ms"),
    ts("finished_at"),
    #: T-A07（迁移 0007）：本次调用使用的用户证书行（``app.user_data_licences.id``）；
    #: 不设外键（hypertable），不含证书值。管理端 ``calls_last_minute``/``calls_today`` 按它统计。
    uuid_col("licence_id"),
    PrimaryKeyConstraint("id", "requested_at"),
    one_of("priority", ["P0", "P1", "P2"]),
    one_of("status", ["queued", "done", "failed", "dropped"]),
    schema=OPS,
    comment="hypertable（requested_at，chunk 1 天，保留 30 天：运维策略）",
)
Index(
    "ix_ingest_request_log_licence_requested",
    ingest_request_log.c.licence_id,
    ingest_request_log.c.requested_at.desc(),
)

ingest_leases = Table(
    "ingest_leases",
    metadata,
    pk_uuid(),
    txt("holder_host", nullable=False),
    txt("egress_ip"),
    ts("started_at", nullable=False, default_now=True),
    ts("last_renewed_at"),
    ts("ended_at"),
    txt("end_reason"),
    schema=OPS,
    comment="单活锁历史（审计「任何时刻只有一个调用方」）",
)

pending_file_purges = Table(
    "pending_file_purges",
    metadata,
    pk_uuid(),
    txt("path", nullable=False),
    integer("attempts", nullable=False, server_default=text("0")),
    txt("last_error"),
    ts("last_attempt_at"),
    created_at(),
    UniqueConstraint("path"),
    schema=OPS,
    comment="删除用户数据后未删成功的原始导入文件（plan §7.3）；不含 user_id，下次运行先重试",
)
