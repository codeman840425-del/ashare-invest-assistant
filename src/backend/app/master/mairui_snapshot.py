"""T-A22 normalized complete-list delivery. No HTTP, licences or live authorization.

Existing ingest must supply all three completed lists after explicit DAILY user
approval; B86 approval is not a receipt for this job. The default worker port is
closed. Snapshots here are canonical normalized artifacts, not raw HTTP captures.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Table, func, insert, select, text, update
from sqlalchemy.exc import IntegrityError

from app.config_files import SecuritiesMaster
from app.db.tables.market import (
    master_runs,
    master_snapshots,
    securities,
    security_listing_status_history,
    security_risk_flag_history,
    trading_calendar,
)
from app.master.sync import BEIJING, listing_status_for, risk_flag

TASK = "master.mairui_risk_snapshot"
DATASETS = frozenset({"hslt_list", "bj_list_all", "kc_list_all"})
PUBLIC_PATHS = "/hslt/list;/bj/list/all;/kc/list/all"
SOURCE = "mairui_list"


@dataclass(frozen=True)
class DailyNames:
    names: dict[str, str]
    fetched_at: dt.datetime
    datasets: frozenset[str]


def _runs(conn: Connection, day: dt.date) -> Any:  # noqa: ANN401
    return conn.execute(
        select(master_runs)
        .where(
            master_runs.c.stats["task"].astext == TASK,
            master_runs.c.stats["trade_date"].astext == str(day),
        )
        .order_by(master_runs.c.id.desc())
    ).first()


def _period(
    conn: Connection, table: Table, code: str, day: dt.date, key: str, value: str | None, sid: int
) -> None:
    c = table.c
    old = conn.execute(
        select(table).where(c.code == code, c.valid_until.is_(None)).with_for_update()
    ).first()
    source = (
        conn.execute(
            select(master_snapshots.c.source).where(master_snapshots.c.id == old.snapshot_id)
        ).scalar()
        if old is not None
        else None
    )
    if old is not None and old.valid_from > day:
        raise ValueError("out_of_order_history")
    if old is not None and old._mapping[key] == value and source == SOURCE:
        return
    if old is not None:
        if old.valid_from == day:
            raise ValueError("same_day_source_or_content_conflict")
        conn.execute(
            update(table)
            .where(c.code == code, c.valid_from == old.valid_from)
            .values(valid_until=day)
        )
    extra = {"reason": SOURCE} if key == "listing_status" else {}
    conn.execute(
        insert(table).values(code=code, valid_from=day, snapshot_id=sid, **{key: value}, **extra)
    )


def apply_delivery(
    conn: Connection,
    delivery: DailyNames | None,
    *,
    now: dt.datetime,
    cfg: SecuritiesMaster,
    root: Path,
    snapshot_day: dt.date | None = None,
) -> int:
    if now.tzinfo is None:
        raise ValueError("timezone_required")
    bj = now.astimezone(BEIJING)
    day = snapshot_day or bj.date()
    if day > bj.date():
        raise ValueError("snapshot_day_in_future")
    if day == bj.date() and bj.time() < dt.time(18):
        raise ValueError("before_beijing_1800")
    is_open = conn.execute(
        select(trading_calendar.c.is_open).where(trading_calendar.c.date == day)
    ).scalar_one_or_none()
    if is_open is not True:
        raise ValueError("CALENDAR_NOT_COVERED" if is_open is None else "not_trading_day")
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('master.mairui_risk_snapshot'))"))
    previous = _runs(conn, day)
    latest = conn.execute(
        select(func.max(master_snapshots.c.trade_date)).where(
            master_snapshots.c.source == SOURCE, master_snapshots.c.parse_status == "ok"
        )
    ).scalar()
    issue = None
    names = {}
    if latest and day < latest:
        issue = "out_of_order_delivery"
    elif delivery is None:
        issue = "daily_list_authorization_or_delivery_required"
    elif (
        delivery.fetched_at.tzinfo is None
        or delivery.fetched_at > now
        or delivery.fetched_at.astimezone(BEIJING).date() != day
        or delivery.fetched_at.astimezone(BEIJING).time() < dt.time(18)
        or delivery.datasets != DATASETS
    ):
        issue = "incomplete_or_wrong_time_delivery"
    elif not delivery.names:
        issue = "empty"
    elif any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in delivery.names.items()
    ) or any(k.strip() and not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", k) for k in delivery.names):
        issue = "parse_error"
    else:
        valid = {k: v.strip() for k, v in delivery.names.items() if k.strip() and v.strip()}
        if (
            100 * (len(delivery.names) - len(valid)) / len(delivery.names)
            > cfg.reject_key_missing_pct
        ):
            issue = "key_missing"
        else:
            names = valid
    artifact = {
        "source": SOURCE,
        "snapshot_date": str(day),
        "datasets": sorted(DATASETS),
        "names": names,
    }
    raw = json.dumps(artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    sha = hashlib.sha256(raw).hexdigest()
    if previous is not None and previous.status == "ok":
        if previous.stats.get("sha256") != sha:
            raise ValueError("already_accepted_day")
        return int(previous.id)
    last_count = conn.execute(
        select(master_snapshots.c.row_count)
        .where(master_snapshots.c.source == SOURCE, master_snapshots.c.parse_status == "ok")
        .order_by(master_snapshots.c.fetched_at.desc())
        .limit(1)
    ).scalar()
    if (
        issue is None
        and last_count
        and 100 * (last_count - len(names)) / last_count > cfg.reject_drop_pct
    ):
        issue = "drop_pct"
    rid = int(
        conn.execute(
            insert(master_runs)
            .values(started_at=now, trigger="beat_1800")
            .returning(master_runs.c.id)
        ).scalar_one()
    )
    existing = conn.execute(
        select(master_snapshots).where(
            master_snapshots.c.source == SOURCE, master_snapshots.c.sha256 == sha
        )
    ).first()
    rejected = issue if issue in {"empty", "drop_pct", "key_missing"} else "parse_error"
    if existing is not None:
        sid = int(existing.id)
        # An immutable failed artifact is not silently turned into accepted evidence.
        if existing.parse_status != "ok" and issue is None:
            issue = "previous_artifact_rejected"
    else:
        root.mkdir(parents=True, exist_ok=True)
        path = root / (str(day) + "-" + sha + ".json")
        if path.is_symlink():
            raise ValueError("artifact_integrity_conflict")
        if path.exists():
            if path.read_bytes() != raw:
                raise ValueError("artifact_integrity_conflict")
        else:
            with path.open("xb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        sid = int(
            conn.execute(
                insert(master_snapshots)
                .values(
                    source=SOURCE,
                    url=PUBLIC_PATHS,
                    fetched_at=delivery.fetched_at if delivery is not None else now,
                    trade_date=day,
                    row_count=len(names),
                    sha256=sha,
                    parse_status="ok" if issue is None else "rejected",
                    reject_reason=None if issue is None else rejected,
                    raw_path=str(path),
                )
                .returning(master_snapshots.c.id)
            ).scalar_one()
        )
    seen = []
    changes = []
    if issue is None:
        try:
            with conn.begin_nested():
                rows = conn.execute(
                    select(securities)
                    .where(securities.c.code.in_(names), securities.c.type.in_({"stock", "cdr"}))
                    .with_for_update()
                ).all()
                for row in rows:
                    if row.listing_status not in {"listed", "delisting_period"}:
                        continue  # Never revive, add, delist or mark missing from this source.
                    flag = risk_flag(names[row.code])
                    status = listing_status_for(names[row.code])
                    _period(conn, security_risk_flag_history, row.code, day, "risk_flag", flag, sid)
                    _period(
                        conn,
                        security_listing_status_history,
                        row.code,
                        day,
                        "listing_status",
                        status,
                        sid,
                    )
                    if row.risk_flag != flag or row.listing_status != status:
                        changes.append(
                            {
                                "code": row.code,
                                "before": {
                                    "risk_flag": row.risk_flag,
                                    "listing_status": row.listing_status,
                                },
                                "after": {"risk_flag": flag, "listing_status": status},
                            }
                        )
                    sources = {
                        **(row.field_sources or {}),
                        "risk_flag": SOURCE,
                        "listing_status": SOURCE,
                    }
                    conn.execute(
                        update(securities)
                        .where(securities.c.code == row.code)
                        .values(risk_flag=flag, listing_status=status, field_sources=sources)
                    )
                    seen.append(row.code)
        except (ValueError, IntegrityError):
            issue = "history_conflict"
            seen = []
            changes = []
            conn.execute(
                update(master_snapshots)
                .where(master_snapshots.c.id == sid)
                .values(parse_status="rejected", reject_reason="parse_error")
            )
    if issue is None and not seen:
        issue = "no_known_active_securities"
        conn.execute(
            update(master_snapshots)
            .where(master_snapshots.c.id == sid)
            .values(parse_status="rejected", reject_reason="parse_error")
        )
    stats = {
        "task": TASK,
        "trade_date": str(day),
        "source": SOURCE,
        "sha256": sha,
        "seen_codes": sorted(seen),
        "changes": changes,
        "changed_count": len(changes),
        "sources": {
            SOURCE: {
                "status": "ok" if issue is None else "rejected",
                "reason": issue,
                "snapshot_id": sid,
            }
        },
        "alert": None if issue is None else "master.snapshot_rejected",
    }
    conn.execute(
        update(master_runs)
        .where(master_runs.c.id == rid)
        .values(
            finished_at=now,
            status="ok" if issue is None else "failed",
            snapshot_ids=[sid],
            stats=stats,
        )
    )
    return rid


def read_flags(conn: Connection, code: str, day: dt.date, *, as_of: dt.datetime) -> dict[str, Any]:
    if as_of.tzinfo is None:
        raise ValueError("timezone_required")
    unknown = {
        "f.is_st": None,
        "f.is_delisting_period": None,
        "source": SOURCE,
        "gap": "snapshot_missing_or_not_visible",
    }
    run = _runs(conn, day)
    if (
        run is None
        or run.status != "ok"
        or run.finished_at > as_of
        or as_of.astimezone(BEIJING).date() <= day
        or code not in run.stats["seen_codes"]
    ):
        return unknown
    values = {}
    for table, key in [
        (security_risk_flag_history, "risk_flag"),
        (security_listing_status_history, "listing_status"),
    ]:
        row = conn.execute(
            select(table.c[key], master_snapshots.c.source, master_snapshots.c.fetched_at)
            .join(master_snapshots, master_snapshots.c.id == table.c.snapshot_id)
            .where(
                table.c.code == code,
                table.c.valid_from <= day,
                (table.c.valid_until.is_(None) | (table.c.valid_until > day)),
            )
        ).first()
        if row is None or row.source != SOURCE or row.fetched_at > as_of:
            return unknown
        values[key] = row[0]
    if values["listing_status"] not in {"listed", "delisting_period"}:
        return unknown
    fetched = conn.execute(
        select(master_snapshots.c.fetched_at).where(master_snapshots.c.id == run.snapshot_ids[0])
    ).scalar_one()
    return {
        "fetched_at": fetched,
        "data_as_of": dt.datetime.combine(day, dt.time(18), BEIJING),
        "f.is_st": values["risk_flag"] in {"st", "star_st", "delisting"},
        "f.is_delisting_period": values["listing_status"] == "delisting_period",
        "source": SOURCE,
        "snapshot_id": run.snapshot_ids[0],
        "gap": None,
    }


def latest_visible_flags(conn: Connection, code: str, *, as_of: dt.datetime) -> dict[str, Any]:
    """Pick the preceding calendar trading day, NOT the latest successful delivery.

    A failed trading day must not silently fall back to an older success.
    """
    if as_of.tzinfo is None:
        raise ValueError("timezone_required")
    today = as_of.astimezone(BEIJING).date()
    unknown = {
        "f.is_st": None,
        "f.is_delisting_period": None,
        "gap": "calendar_or_snapshot_missing",
    }
    if (
        conn.execute(
            select(trading_calendar.c.date).where(trading_calendar.c.date == today)
        ).scalar_one_or_none()
        is None
    ):
        return unknown
    day = conn.execute(
        select(func.max(trading_calendar.c.date)).where(
            trading_calendar.c.date < as_of.astimezone(BEIJING).date(),
            trading_calendar.c.is_open.is_(True),
        )
    ).scalar()
    if day is None:
        return unknown
    covered_days = conn.execute(
        select(func.count())
        .select_from(trading_calendar)
        .where(trading_calendar.c.date >= day, trading_calendar.c.date <= today)
    ).scalar_one()
    if covered_days != (today - day).days + 1:
        return unknown
    return read_flags(conn, code, day, as_of=as_of)
