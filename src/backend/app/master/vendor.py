"""T-B61 worker 批次状态机；不采集、不读取凭据，调用者显式提交事务。"""

from __future__ import annotations

import datetime as dt
import json
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, delete, func, insert, select, text, update

from app.db.tables.licences import user_data_licence_holds, user_data_licence_status
from app.db.tables.market import master_runs, security_reconciliation_diffs
from app.db.tables.vendor import DATASETS
from app.db.tables.vendor import master_vendor_batches as batches
from app.db.tables.vendor import master_vendor_list_rows as rows_table
from app.master.reconcile import reconcile_vendor_lists

BEIJING = ZoneInfo("Asia/Shanghai")
APPLY_TASK = "master.reconcile_vendor_apply"
RECONCILE_TASK = "master.reconcile_vendor"
SWEEP_TASK = "master.vendor_batches_sweep"


def deadline_for(started: dt.datetime, trigger: str) -> dt.datetime:
    bj = started.astimezone(BEIJING)
    day = bj.date()
    if trigger == "beat_1800":
        day += dt.timedelta(days=1)
        hour, minute = 7, 30
    elif trigger == "beat_0730":
        hour, minute = 18, 0
    else:
        # manual 的“下一次计划时间”沿用 jobs.slot_jobs：工作日傍晚、次日补拉。
        # 不把周一早间、周六傍晚或周日不存在的钟点当作截止时刻。
        for offset in range(8):
            target = day + dt.timedelta(days=offset)
            wd = target.weekday()
            for hour, minute, enabled in ((7, 30, 1 <= wd <= 5), (18, 0, wd <= 4)):
                candidate = dt.datetime.combine(target, dt.time(hour, minute), BEIJING)
                if enabled and candidate > bj:
                    return candidate.astimezone(dt.UTC)
        raise RuntimeError("未找到下一次既有主数据计划时段")
    return dt.datetime.combine(day, dt.time(hour, minute), BEIJING).astimezone(dt.UTC)


def licence_available(conn: Connection, lid: UUID, now: dt.datetime) -> bool:
    v, h = user_data_licence_status, user_data_licence_holds
    row = conn.execute(
        select(v.c.status, v.c.paused_until, v.c.expires_on, h.c.user_id.label("held"))
        .select_from(v.outerjoin(h, h.c.user_id == v.c.user_id))
        .where(v.c.id == lid, v.c.deleted_at.is_(None))
    ).first()
    return bool(
        row
        and row.status == "active"
        and row.held is None
        and (row.paused_until is None or row.paused_until <= now)
        and (row.expires_on is None or row.expires_on >= now.astimezone(BEIJING).date())
    )


def request_batches(
    conn: Connection, *, master_run_id: int | None, trigger: str, now: dt.datetime
) -> tuple[int, list[dict[str, str]], bool]:
    if master_run_id is None:
        master_run_id = conn.execute(
            select(master_runs.c.id)
            .where(
                master_runs.c.status.in_(["ok", "partial"]),
                func.cardinality(master_runs.c.snapshot_ids) > 0,
            )
            .order_by(master_runs.c.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if master_run_id is None:
            raise RuntimeError("没有成功主数据运行，不能建立对账批次")
    parent = (
        conn.execute(select(master_runs).where(master_runs.c.id == master_run_id).with_for_update())
        .mappings()
        .one()
    )
    intents: list[dict[str, str]] = []
    pending = False
    stats = dict(parent["stats"])
    final = {x["licence_id"]: x for x in stats.get("vendor", [])}
    scopes = (
        conn.execute(
            select(user_data_licence_status.c.id).where(
                user_data_licence_status.c.deleted_at.is_(None)
            )
        )
        .scalars()
        .all()
    )
    scopes = sorted(
        set(scopes)
        | set(
            conn.execute(
                select(batches.c.source_licence_id).where(batches.c.master_run_id == master_run_id)
            ).scalars()
        ),
        key=str,
    )
    for lid in scopes:
        old = (
            conn.execute(
                select(batches)
                .where(batches.c.master_run_id == master_run_id, batches.c.source_licence_id == lid)
                .order_by(batches.c.attempt.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        if old and old["status"] not in {"requested", "failed"}:
            if old["status"] == "fetched":
                pending = True
            continue
        if old and old["status"] == "failed" and old["attempt"] >= 3:
            final[str(lid)] = {
                "licence_id": str(lid),
                "final": "failed",
                "error_code": old["error_code"],
            }
            continue
        if (
            old
            and old["status"] == "failed"
            and old["fetched_at"] is not None
            and now < old["fetched_at"] + dt.timedelta(minutes=10)
        ):
            pending = True
            continue
        if old and old["status"] == "requested":
            row = old
        else:
            deadline = (
                old["deadline_at"]
                if old
                else deadline_for(
                    now if trigger == "manual" else parent["started_at"],
                    parent["trigger"] if trigger != "manual" else "manual",
                )
            )
            usable = licence_available(conn, lid, now)
            status = "expired" if now >= deadline else ("requested" if usable else "skipped")
            error = (
                "deadline_exceeded"
                if status == "expired"
                else (None if usable else "licence_unavailable")
            )
            row = (
                conn.execute(
                    insert(batches)
                    .values(
                        id=uuid4(),
                        master_run_id=master_run_id,
                        source_licence_id=lid,
                        status=status,
                        attempt=old["attempt"] + 1 if old else 1,
                        requested_at=now,
                        deadline_at=deadline,
                        error_code=error,
                    )
                    .returning(batches)
                )
                .mappings()
                .one()
            )
        if row["status"] == "requested":
            if now >= row["deadline_at"]:
                conn.execute(
                    update(batches)
                    .where(batches.c.id == row["id"])
                    .values(status="expired", error_code="deadline_exceeded")
                )
                continue
            if not licence_available(conn, lid, now):
                conn.execute(
                    update(batches)
                    .where(batches.c.id == row["id"])
                    .values(status="skipped", error_code="licence_unavailable")
                )
                continue
            pending = True
            intents.append(
                {
                    "kind": "vendor_lists",
                    "batch_id": str(row["id"]),
                    "licence_id": str(lid),
                    "datasets": json.dumps(list(DATASETS)),
                    "priority": "p1_daily",
                    "deadline_at": row["deadline_at"].isoformat(),
                }
            )
    if final:
        stats["vendor"] = list(final.values())
        conn.execute(
            update(master_runs).where(master_runs.c.id == master_run_id).values(stats=stats)
        )
    return master_run_id, intents, pending


def _scope_lock(conn: Connection, lid: UUID) -> None:
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:scope))"),
        {"scope": "master.mairui_lists:" + str(lid)},
    )


def _quote_conflicts(conn: Connection, *, lid: UUID, day: dt.date, codes: set[str]) -> None:
    if day.weekday() >= 5:
        return
    table = security_reconciliation_diffs
    scope = (
        table.c.source == "mairui_real_all",
        table.c.source_licence_id == lid,
        table.c.kind == "quote_conflict",
    )
    latest = conn.execute(
        select(func.max(func.greatest(table.c.last_seen_on, table.c.resolved_on))).where(*scope)
    ).scalar()
    if latest and day < latest:
        raise ValueError("拒绝过期冲突快照")
    opened = {
        r["security_code"]: r
        for r in conn.execute(select(table).where(*scope, table.c.status == "open")).mappings()
    }
    for code, row in opened.items():
        if code not in codes:
            conn.execute(
                update(table)
                .where(table.c.id == row["id"])
                .values(status="resolved", resolved_on=day)
            )
    for code in codes:
        previous = opened.get(code)
        if previous:
            conn.execute(
                update(table)
                .where(table.c.id == previous["id"])
                .values(
                    last_seen_on=day,
                    seen_days=previous["seen_days"] + int(day > previous["last_seen_on"]),
                )
            )
        else:
            conn.execute(
                insert(table).values(
                    kind="quote_conflict",
                    source="mairui_real_all",
                    source_licence_id=lid,
                    security_code=code,
                    first_seen_on=day,
                    last_seen_on=day,
                    seen_days=1,
                )
            )


def apply_batch(
    conn: Connection, batch_id: UUID, *, now: dt.datetime, stale_alert_days: int = 5
) -> str:
    row = (
        conn.execute(select(batches).where(batches.c.id == batch_id).with_for_update())
        .mappings()
        .one_or_none()
    )
    if row is None or row["status"] != "fetched":
        return "noop"
    lid = row["source_licence_id"]
    _scope_lock(conn, lid)
    newer = conn.execute(
        select(batches.c.id)
        .where(
            batches.c.source_licence_id == lid,
            batches.c.status == "reconciled",
            batches.c.fetched_at > row["fetched_at"],
        )
        .limit(1)
    ).first()
    if newer:
        conn.execute(update(batches).where(batches.c.id == batch_id).values(status="superseded"))
        return "superseded"
    statuses = {x["dataset"]: x["status"] for x in row["datasets"]}
    if any(statuses.get(x) != "ok" for x in DATASETS[:3]):
        raise ValueError("完整列表状态缺失，拒绝比对")
    names = {"hslt_list": "hslt_list", "bj_list": "bj_list_all", "kc_list": "kc_list_all"}
    snapshots: dict[str, dict[str, str]] = {x: {} for x in names.values()}
    conflicts = set()
    for item in conn.execute(
        select(rows_table).where(rows_table.c.batch_id == batch_id)
    ).mappings():
        if item["dataset"] in names:
            snapshots[names[item["dataset"]]][item["security_code"]] = item["vendor_name"] or ""
        elif item["dup_conflict"]:
            conflicts.add(item["security_code"])
    day = row["fetched_at"].astimezone(BEIJING).date()
    reconcile_vendor_lists(
        conn, snapshots, source_licence_id=lid, as_of=day, stale_alert_days=stale_alert_days
    )
    if statuses.get("hsrl_real") == "ok":
        _quote_conflicts(conn, lid=lid, day=day, codes=conflicts)
    conn.execute(
        update(batches)
        .where(batches.c.id == batch_id)
        .values(status="reconciled", reconciled_at=now)
    )
    return "reconciled"


def sweep_batches(conn: Connection, *, now: dt.datetime) -> list[UUID]:
    conn.execute(
        update(batches)
        .where(batches.c.status == "requested", batches.c.deadline_at <= now)
        .values(status="expired", error_code="deadline_exceeded")
    )
    return list(
        conn.execute(
            select(batches.c.id).where(
                batches.c.status == "fetched", batches.c.fetched_at < now - dt.timedelta(minutes=30)
            )
        ).scalars()
    )


def purge_batch_rows(conn: Connection, *, now: dt.datetime) -> int:
    return int(
        conn.execute(
            delete(rows_table).where(
                rows_table.c.batch_id.in_(
                    select(batches.c.id).where(batches.c.requested_at < now - dt.timedelta(days=14))
                )
            )
        ).rowcount
        or 0
    )
