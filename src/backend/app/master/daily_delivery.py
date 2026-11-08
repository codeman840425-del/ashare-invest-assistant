"""T-B90 worker-side daily outbox. Never reads a licence or performs HTTP.

Deployment authorization is an operator-installed root-owned immutable receipt,
NOT an API field, environment toggle, test assertion or proxy's claimed approval.
No receipt is installed by this module. Actual human authorization remains a
pre-deployment operational prerequisite.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, insert, select, text, update

from app.db.tables.licences import user_data_licence_status
from app.db.tables.market import master_runs
from app.db.tables.vendor import master_vendor_batches as batches
from app.db.tables.vendor import master_vendor_list_rows as rows
from app.master.mairui_snapshot import DATASETS, DailyNames, apply_delivery
from app.master.sync import BEIJING
from app.master.vendor import licence_available
from app.reports.service import covered

AUTHORIZATION = Path("/run/aia/authorizations/mairui-daily.json")
STREAM = "ingest:requests"
KIND = "mairui_daily_snapshot"
APPLY = "master.mairui_daily_apply"
SWEEP = "master.mairui_daily_sweep"
LISTS = ("hslt_list", "bj_list", "kc_list")
# T-B90 correction: one scheduling slot is NOT one external HTTP request.
# The current complete-source plan requires three distinct HTTP requests, while
# the assigned authorization permits only one. No receipt/env/client flag may
# widen this cap. Keep collection blocked pending an explicit contract ruling.
DAILY_HTTP_LIMIT = 1


def live_budget_issue() -> str | None:
    return "daily_http_budget_unresolved" if len(LISTS) > DAILY_HTTP_LIMIT else None


@dataclass(frozen=True)
class Grant:
    user_id: uuid.UUID
    licence_id: uuid.UUID
    receipt_id: uuid.UUID
    start: dt.datetime
    end: dt.datetime
    digest: str


def read_grant(path: Path = AUTHORIZATION) -> Grant | None:
    """Read only this explicit nonsecret approval receipt, not arbitrary files.

    Must be installed by operator as root-owned 0444 regular file on a read-only
    directory/mount; application/client writes are refused. No actual receipt is
    read by tests unless a synthetic path is supplied.
    """
    try:
        parent = path.parent.stat()
        if (
            path.parent.resolve() != path.parent.absolute()
            or parent.st_uid != 0
            or stat.S_IMODE(parent.st_mode) & 0o022
        ):
            return None
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or stat.S_IMODE(st.st_mode) != 0o444:
            return None
        raw = os.read(fd, 8193)
        if len(raw) > 8192:
            return None
        obj = json.loads(raw)
        if (
            set(obj) != {"kind", "user_id", "licence_id", "receipt_id", "not_before", "expires_at"}
            or obj["kind"] != KIND
        ):
            return None
        start, end = (
            dt.datetime.fromisoformat(obj["not_before"]),
            dt.datetime.fromisoformat(obj["expires_at"]),
        )
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            return None
        return Grant(
            uuid.UUID(obj["user_id"]),
            uuid.UUID(obj["licence_id"]),
            uuid.UUID(obj["receipt_id"]),
            start,
            end,
            hashlib.sha256(raw).hexdigest(),
        )
    except (ValueError, TypeError, KeyError):
        return None
    finally:
        os.close(fd)


def eligible(conn: Connection, grant: Grant, now: dt.datetime) -> bool:
    return (
        grant.start <= now < grant.end
        and conn.execute(
            select(master_runs.c.id)
            .where(
                master_runs.c.stats["task"].astext == KIND,
                master_runs.c.stats["upstream_halted"].astext == "true",
            )
            .limit(1)
        ).first()
        is None
        and licence_available(conn, grant.licence_id, now)
        and conn.execute(
            select(user_data_licence_status.c.id).where(
                user_data_licence_status.c.id == grant.licence_id,
                user_data_licence_status.c.user_id == grant.user_id,
            )
        ).first()
        is not None
    )


def request(conn: Connection, grant: Grant, now: dt.datetime) -> uuid.UUID | None:
    if live_budget_issue():
        return None
    day = now.astimezone(BEIJING).date()
    if (
        now.astimezone(BEIJING).time() < dt.time(18)
        or not covered(conn, day)
        or not eligible(conn, grant, now)
    ):
        return None
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('mairui_daily_outbox'))"))
    old = conn.execute(
        select(master_runs).where(
            master_runs.c.stats["task"].astext == KIND,
            master_runs.c.stats["trade_date"].astext == str(day),
        )
    ).first()
    if old:
        return uuid.UUID(old.stats["batch_id"])
    bid = uuid.uuid4()
    rid = conn.execute(
        insert(master_runs)
        .values(
            trigger="beat_1800",
            started_at=now,
            status=None,  # Existing master_runs contract: NULL means in progress.
            stats={
                "task": KIND,
                "trade_date": str(day),
                "batch_id": str(bid),
                "receipt_digest": grant.digest,
                "receipt_id": str(grant.receipt_id),
                "attempted": [],
            },
        )
        .returning(master_runs.c.id)
    ).scalar_one()
    conn.execute(
        insert(batches).values(
            id=bid,
            master_run_id=rid,
            source_licence_id=grant.licence_id,
            status="requested",
            attempt=1,
            requested_at=now,
            deadline_at=dt.datetime.combine(day, dt.time(23, 59, 59), BEIJING),
            datasets=[],
        )
    )
    return bid


def publish_pending(engine: Engine, rds: Any) -> int:  # noqa: ANN401
    """Durable DB outbox replay also repairs commit->Redis and fetched->apply gaps."""
    if live_budget_issue():
        return 0
    with engine.connect() as conn:
        pending = conn.execute(
            select(batches.c.id, batches.c.status)
            .join(master_runs, master_runs.c.id == batches.c.master_run_id)
            .where(
                master_runs.c.stats["task"].astext == KIND,
                batches.c.status.in_(["requested", "fetched", "failed", "expired"]),
                master_runs.c.finished_at.is_(None),
            )
            .order_by(batches.c.requested_at)
        ).all()
    for b in pending:
        if b.status == "requested":
            rds.xadd(STREAM, {"kind": KIND, "batch_id": str(b.id)})
        else:
            rds.lpush("jobs:worker", json.dumps({"task": APPLY, "args": {"batch_id": str(b.id)}}))
    return len(pending)


def apply_batch(conn: Connection, bid: uuid.UUID, *, now: dt.datetime, cfg: Any, root: Path) -> int:  # noqa: ANN401
    batch = conn.execute(select(batches).where(batches.c.id == bid).with_for_update()).first()
    if batch is None:
        raise ValueError("daily_batch_missing")
    parent = conn.execute(
        select(master_runs).where(master_runs.c.id == batch.master_run_id).with_for_update()
    ).first()
    if parent is None or parent.stats.get("task") != KIND:
        raise ValueError("not_daily_batch")
    if parent.finished_at is not None:
        return int(parent.stats["applied_run_id"])
    if batch.status == "requested":
        return parent.id
    day = dt.date.fromisoformat(parent.stats["trade_date"])
    delivery = None
    if batch.status == "fetched":
        summaries = {s["dataset"]: s for s in batch.datasets}
        if set(summaries) != set(LISTS) or any(s["status"] != "ok" for s in summaries.values()):
            raise ValueError("daily_dataset_incomplete")
        names: dict[str, str] = {}
        for row in conn.execute(select(rows).where(rows.c.batch_id == bid)):
            if (
                row.dataset not in LISTS
                or not row.vendor_name
                or (row.security_code in names and names[row.security_code] != row.vendor_name)
            ):
                raise ValueError("daily_name_conflict")
            names[row.security_code] = row.vendor_name
        delivery = DailyNames(names, batch.fetched_at, DATASETS)
    rid = apply_delivery(conn, delivery, now=now, cfg=cfg, root=root, snapshot_day=day)
    status = conn.execute(select(master_runs.c.status).where(master_runs.c.id == rid)).scalar_one()
    conn.execute(
        update(batches)
        .where(batches.c.id == bid)
        .values(status="reconciled" if status == "ok" else "failed", reconciled_at=now)
    )
    conn.execute(
        update(master_runs)
        .where(master_runs.c.id == parent.id)
        .values(status=status, finished_at=now, stats={**parent.stats, "applied_run_id": rid})
    )
    return rid
