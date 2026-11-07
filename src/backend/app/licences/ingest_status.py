"""``GET /admin/ingest/status`` 的响应组装（T-B47）。

契约 v0.2.8 §7.9、§5.1 ``IngestLicenceStatus``。

只读，数据源：

- ``leader``：``ops.ingest_leases`` 中未结束的最近一条（``holder_host`` → ``instance_id``；
  ``egress_ip`` 只输出掩码 ``a.b.c.x``；``lease_expires_at`` = 最近续租（无则开始）时间 +
  ``ingest.yaml leader.lease_s``）。没有租约时回退到 Redis 心跳里的 ``instance_id``，其余为 null。
- ``budget``：全部证书合计（v0.2.6）：``per_minute_limit`` 为 ``active`` 证书令牌桶上限之和，
  ``used_last_minute`` 为 ``ops.ingest_request_log`` 最近 60 秒已发出的调用数。
- ``queues``：p0/p1/p2 三行，``depth`` 为各证书 Redis 队列积压之和，``oldest_age_s`` 为请求日志里
  该优先级仍 ``queued`` 的最早一条的年龄（秒，无则 0）。
- ``errors_24h``：最近 24 小时 ``failed`` 调用按上游码汇总（麦蕊码优先，其次 ``http_<status>``，
  都没有记 ``network``）。
- ``ip_limit_alerts_24h``：最近 24 小时 ``ops.data_licence_events`` 中 ``ip_limited`` 事件数。
- ``freshness``：数据集新鲜度登记尚未落地（采集 worker 属 T-B04 系列），暂返回空列表。
- ``licences`` / ``licences_truncated``：:func:`app.licences.service.ingest_licences`。

**不返回任何证书值、密文、HMAC 或其片段**：所有查询都不选这些列（``licences[]`` 走只读视图）。
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import json
import logging
from typing import Any, Final

import redis
from sqlalchemy import Connection, Text, cast, func, literal, select

from app.auth.service import bj, now_utc
from app.config import Settings
from app.db.tables.licences import data_licence_events
from app.db.tables.ops import ingest_leases, ingest_request_log
from app.licences import service
from app.master.alerts import master_alerts
from app.schemas.enums import DataLicenceStatus

logger = logging.getLogger("app.licences.ingest_status")

#: 契约 §7.9 ``queues[].priority`` 的取值（与请求日志 ``priority`` P0/P1/P2 对应）
QUEUE_NAMES: Final = (
    ("P0", "p0", "p0_intraday"),
    ("P1", "p1", "p1_daily"),
    ("P2", "p2", "p2_backfill"),
)
_CALLED: Final = ("done", "failed")


def mask_ip(raw: str | None) -> str | None:
    """IPv4 → ``203.0.113.x``；IPv6 → 前 3 组 + ``:x``；无法解析 → null（不回显原值）。"""
    if not raw:
        return None
    try:
        ip = ipaddress.ip_address(raw.strip())
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv4Address):
        a, b, c, _ = str(ip).split(".")
        return f"{a}.{b}.{c}.x"
    groups = ip.exploded.split(":")[:3]
    return ":".join(g.lstrip("0") or "0" for g in groups) + ":x"


def _heartbeat(rds: redis.Redis, settings: Settings) -> dict[str, Any]:
    try:
        raw = rds.get(settings.ingest_heartbeat_key)
    except redis.RedisError as exc:
        logger.warning("ingest-status: heartbeat unavailable (%s)", type(exc).__name__)
        return {}
    if raw is None:
        return {}
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        data = json.loads(text)
    except (UnicodeDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _leader(conn: Connection, settings: Settings, hb: dict[str, Any]) -> dict[str, Any]:
    t = ingest_leases.c
    row = conn.execute(
        select(t.holder_host, t.egress_ip, t.started_at, t.last_renewed_at)
        .where(t.ended_at.is_(None))
        .order_by(func.coalesce(t.last_renewed_at, t.started_at).desc())
        .limit(1)
    ).first()
    if row is None:
        iid = hb.get("instance_id")
        return {
            "instance_id": iid if isinstance(iid, str) and iid else None,
            "egress_ip_masked": None,
            "lease_expires_at": None,
        }
    base: dt.datetime = row.last_renewed_at or row.started_at
    lease_s = int(settings.business.ingest.leader.lease_s)
    return {
        "instance_id": row.holder_host,
        "egress_ip_masked": mask_ip(row.egress_ip),
        "lease_expires_at": bj(base + dt.timedelta(seconds=lease_s)),
    }


def _oldest_queued(conn: Connection, now: dt.datetime) -> dict[str, int]:
    t = ingest_request_log.c
    rows = conn.execute(
        select(t.priority, func.min(t.requested_at))
        .where(t.status == "queued", t.requested_at >= now - dt.timedelta(days=1))
        .group_by(t.priority)
    ).all()
    return {str(p): max(0, int((now - at).total_seconds())) for p, at in rows if at is not None}


def _errors_24h(conn: Connection, now: dt.datetime) -> list[dict[str, Any]]:
    t = ingest_request_log.c
    code = func.coalesce(
        t.mairui_code, literal("http_") + cast(t.http_status, Text), literal("network")
    )
    rows = conn.execute(
        select(code.label("code"), func.count())
        .where(t.status == "failed", t.requested_at >= now - dt.timedelta(hours=24))
        .group_by(code)
        .order_by(func.count().desc(), code)
    ).all()
    return [{"upstream_code": str(c), "count": int(n)} for c, n in rows]


def _used_last_minute(conn: Connection, now: dt.datetime) -> int:
    t = ingest_request_log.c
    n = conn.execute(
        select(func.count()).where(
            t.status.in_(_CALLED), t.requested_at >= now - dt.timedelta(minutes=1)
        )
    ).scalar_one()
    return int(n)


def _ip_alerts_24h(conn: Connection, now: dt.datetime) -> int:
    e = data_licence_events.c
    n = conn.execute(
        select(func.count()).where(e.event == "ip_limited", e.at >= now - dt.timedelta(hours=24))
    ).scalar_one()
    return int(n)


def build(conn: Connection, rds: redis.Redis, settings: Settings) -> dict[str, Any]:
    now = now_utc()
    licences, truncated = service.ingest_licences(conn, rds, settings)
    hb = _heartbeat(rds, settings)
    oldest = _oldest_queued(conn, now)
    queues = [
        {
            "priority": name,
            "depth": sum(int(r["queue_depth"].get(key, 0)) for r in licences),
            "oldest_age_s": oldest.get(log_p, 0),
        }
        for log_p, key, name in QUEUE_NAMES
    ]
    return {
        "leader": _leader(conn, settings, hb),
        "budget": {
            "per_minute_limit": sum(
                int(r["per_minute_limit"])
                for r in licences
                if r["status"] == DataLicenceStatus.ACTIVE.value
            ),
            "used_last_minute": _used_last_minute(conn, now),
        },
        "queues": queues,
        "errors_24h": _errors_24h(conn, now),
        "ip_limit_alerts_24h": _ip_alerts_24h(conn, now),
        "freshness": [],
        "licences": licences,
        "licences_truncated": truncated,
        "alerts": master_alerts(conn, settings.business.securities.master),
    }


__all__ = ["QUEUE_NAMES", "build", "mask_ip"]
