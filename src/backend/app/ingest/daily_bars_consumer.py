"""DB-owned daily-bar consumer. No Redis dependency or default live transport.

Windows use real open days and an explicitly verified page size. The tick
coordinates durable quota continuation; process remains a single-batch primitive.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from sqlalchemy import Connection, Engine, select, update
from sqlalchemy.engine import RowMapping

from app.db.tables.daily_bars import outbox
from app.db.tables.licences import user_data_licence_status as licences
from app.db.tables.realtime import pipeline_runs
from app.db.tables.users import users
from app.ingest import daily_bars as fetcher
from app.ingest.daily_bars_plan import (
    BEIJING,
    DailyBarsPlanError,
    ready_for_window,
    segments,
    window_days,
)
from app.ingest.daily_lists import STOP as LISTS_STOP
from app.ingest.daily_lists import DailyHaltError, daily_bars_seam, limited
from app.ingest.egress import EgressDenied, single_egress
from app.marketdata import daily_bars_outbox as intents
from app.marketdata.daily_bars import DailyBar, DailyBarsResult, _empty_stats
from app.marketdata.daily_bars_outbox import batch_budget, valid_grant
from app.master.vendor import licence_available
from app.reports.service import covered

GrantReader = Callable[[uuid.UUID], fetcher.DailyBarsGrant | None]
RESUME_PENDING = "daily_bars_resume_pending"


class UpstreamHaltError(RuntimeError):
    """Persist STOP independently from the rolled-back bars transaction."""


def _halted(conn: Connection) -> bool:
    return (
        conn.execute(
            select(outbox.c.id)
            .where(outbox.c.kind == fetcher.KIND, outbox.c.status == "halted")
            .limit(1)
        ).first()
        is not None
    )


def _authorized(conn: Connection, item: RowMapping, grant: object, now: dt.datetime) -> bool:
    if not valid_grant(grant, item["user_id"], now):
        return False
    return bool(
        (grant.licence_id, grant.receipt_id, grant.digest)
        == (item["source_licence_id"], item["receipt_id"], item["receipt_digest"])
        and licence_available(conn, grant.licence_id, now)
        and conn.execute(
            select(licences.c.id).where(
                licences.c.id == grant.licence_id,
                licences.c.user_id == grant.user_id,
            )
        ).first()
        and conn.execute(
            select(users.c.id).where(
                users.c.id == grant.user_id,
                users.c.status == "approved",
            )
        ).first()
    )


def _failed(
    conn: Connection, item: RowMapping, issue: str, now: dt.datetime, *, halted: bool = False
) -> None:
    conn.execute(
        update(outbox)
        .where(outbox.c.id == item["id"])
        .values(
            status="halted" if halted else "failed",
            error_code=issue,
            finished_at=now,
        )
    )
    conn.execute(
        update(pipeline_runs)
        .where(pipeline_runs.c.id == item["pipeline_run_id"])
        .values(
            status="failed",
            finished_at=now,
            error=issue,
            stats=_empty_stats(item["user_id"], item["window_trading_days"], issues=[issue]),
        )
    )


def process(
    engine: Engine,
    item_id: uuid.UUID,
    *,
    transport: fetcher.Transport | None = None,
    grant_reader: GrantReader | None = None,
    clock: fetcher.Clock = lambda: dt.datetime.now(dt.UTC),
    stop: Path = LISTS_STOP,
    halt: Path = fetcher.HALT,
    page_days: int | None = None,
    continue_batches: bool = False,
) -> str:
    """Reserve before HTTP, never replay an uncertain batch, update its original run."""
    if transport is None:
        return "disabled"
    read = grant_reader or (lambda owner: fetcher.read_daily_bars_grant(now=clock(), user_id=owner))
    # Same outermost session lock as the daily lists, across reservation commits.
    with single_egress(engine) as lease:
        if lease is None:
            return "busy"
        with engine.begin() as conn:
            if _halted(conn):
                return "halted"
            item = (
                conn.execute(
                    select(outbox)
                    .where(
                        outbox.c.id == item_id,
                        outbox.c.kind == fetcher.KIND,
                    )
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if item is None:
                return "missing"
            if item["status"] not in {"pending", "running"}:
                return "noop"
            run = (
                conn.execute(
                    select(pipeline_runs).where(
                        pipeline_runs.c.id == item["pipeline_run_id"],
                    )
                )
                .mappings()
                .one()
            )
            if (run["kind"], run["step"], run["run_date"], run["stats"].get("user_id")) != (
                "daily_batch",
                "daily_bars.fetch",
                item["trade_date"],
                str(item["user_id"]),
            ):
                raise RuntimeError("daily_bars_run_identity_changed")
            if (
                continue_batches
                and fetcher._stamp(clock).astimezone(BEIJING).date()
                != item["created_at"].astimezone(BEIJING).date()
            ):
                _failed(conn, item, "daily_bars_batch_expired", clock())
                return "failed"
            if item["attempted_at"] is not None:
                _failed(conn, item, "daily_bars_uncertain_attempt_no_retry", clock())
                return "failed"
            if batch_budget(item["batch_kind"]).kind == "unset":
                return "disabled"
            if item["window_trading_days"] not in (None, 1) and page_days is None:
                _failed(conn, item, "daily_bars_history_page_size_unverified", clock())
                return "failed"
            if not _authorized(conn, item, read(item["user_id"]), clock()):
                _failed(conn, item, "data_licence_unavailable", clock())
                return "failed"
            try:
                days = window_days(conn, item["trade_date"], item["window_trading_days"])
                segments(days, page_days)
            except DailyBarsPlanError as exc:
                _failed(conn, item, str(exc), clock())
                return "failed"
            conn.execute(update(outbox).where(outbox.c.id == item_id).values(status="running"))
        attempted = False
        resume_pending = False
        unready: set[str] = set()

        def code_ready(conn: Connection, code: str) -> bool:
            ready = ready_for_window(conn, code, item["source_licence_id"], days, now=clock())
            if not ready:
                unready.add(code)
            return ready

        def send(
            code: str, start: dt.date, end: dt.date
        ) -> tuple[int, DailyBar | DailyBarsResult | None]:
            nonlocal attempted
            if (
                continue_batches
                and fetcher._stamp(clock).astimezone(BEIJING).date()
                != item["created_at"].astimezone(BEIJING).date()
            ):
                raise DailyBarsPlanError("daily_bars_batch_expired")
            if stop.exists() or halt.exists():
                raise UpstreamHaltError()
            with engine.begin() as reservation:
                current = (
                    reservation.execute(
                        select(outbox)
                        .where(
                            outbox.c.id == item_id,
                        )
                        .with_for_update()
                    )
                    .mappings()
                    .one()
                )
                if _halted(reservation):
                    raise UpstreamHaltError()
                if current["status"] != "running" or not _authorized(
                    reservation,
                    current,
                    read(item["user_id"]),
                    clock(),
                ):
                    raise RuntimeError("daily_bars_authorization_changed")
                if current["attempted_at"] is not None and not attempted:
                    raise RuntimeError("daily_bars_uncertain_attempt_no_retry")
                if not attempted:
                    reservation.execute(
                        update(outbox).where(outbox.c.id == item_id).values(attempted_at=clock())
                    )
            attempted = True  # The write-ahead marker is committed before transport.
            if stop.exists() or halt.exists():
                raise UpstreamHaltError()
            try:
                status, bar = transport(code, start, end)
            except (DailyHaltError, EgressDenied):
                raise UpstreamHaltError() from None
            if limited(status, bar) or (
                isinstance(bar, DailyBarsResult) and bar.halted is not None
            ):
                raise UpstreamHaltError()
            return status, bar

        def record(
            conn: Connection,
            day: dt.date,
            owner: uuid.UUID | None,
            window: int | None,
            *,
            status: str,
            stats: dict[str, object],
            error: str | None = None,
        ) -> None:
            nonlocal resume_pending
            issues = stats.get("issues")
            if isinstance(issues, (list, tuple)) and "daily_bars_upstream_halted" in issues:
                raise UpstreamHaltError()
            if status == "failed":
                raise DailyBarsPlanError(error or "daily_bars_plan_invalid")
            if (day, owner, window) != (
                item["trade_date"],
                item["user_id"],
                item["window_trading_days"],
            ):
                raise RuntimeError("daily_bars_run_identity_changed")
            if (
                continue_batches
                and isinstance(issues, (list, tuple))
                and "daily_bars_quota_deferred" in issues
            ):
                resume_pending = any(
                    ready_for_window(conn, code, item["source_licence_id"], days, now=clock())
                    for code in unready
                )
                if not resume_pending:
                    stats = {**stats, "issues": [*issues, "daily_bars_resume_stalled"]}
            conn.execute(
                update(pipeline_runs)
                .where(
                    pipeline_runs.c.id == item["pipeline_run_id"],
                    pipeline_runs.c.step == "daily_bars.fetch",
                    pipeline_runs.c.run_date == day,
                )
                .values(status=status, stats=stats, error=error, finished_at=clock())
            )

        try:
            if stop.exists() or halt.exists():
                raise UpstreamHaltError()
            with engine.begin() as conn:
                daily_bars_seam(
                    fetcher.fetch_mairui_daily_bars,
                    conn,
                    trade_date=item["trade_date"],
                    user_id=item["user_id"],
                    window_trading_days=item["window_trading_days"],
                    batch_kind=item["batch_kind"],
                    sender=send,
                    grant_reader=lambda: read(item["user_id"]),
                    clock=clock,
                    stop_path=stop,
                    halt_path=halt,
                    run_recorder=record,
                    page_days=page_days,
                    code_ready=lambda code: code_ready(conn, code),
                )
                conn.execute(
                    update(outbox)
                    .where(outbox.c.id == item_id)
                    .values(
                        status="done",
                        finished_at=clock(),
                        error_code=RESUME_PENDING if resume_pending else None,
                    )
                )
            return "done"
        except UpstreamHaltError:
            # Even a failed fsync must leave the independently committed DB stop.
            persisted = fetcher.persist_halt(halt)
            with engine.begin() as conn:
                _failed(
                    conn,
                    item,
                    "daily_bars_upstream_halted" if persisted else "daily_bars_halt_persist_failed",
                    clock(),
                    halted=True,
                )
            return "halted"
        except DailyBarsPlanError as exc:
            with engine.begin() as conn:
                _failed(conn, item, str(exc), clock())
            return "failed"
        except OSError:
            # An unreadable gate is busy, not permission to ACK or send again.
            return "busy"
        except Exception:  # noqa: BLE001 - fixed audit token, never upstream exception text
            with engine.begin() as conn:
                _failed(conn, item, "daily_bars_collection_failed_no_retry", clock())
            return "failed"


def _end_resume(conn: Connection, item: RowMapping, issue: str, *, halted: bool = False) -> None:
    """Close only continuation; retain committed bars and their original run stats."""
    stats = conn.execute(
        select(pipeline_runs.c.stats).where(pipeline_runs.c.id == item["pipeline_run_id"])
    ).scalar_one()
    stats = {**stats, "issues": [*stats.get("issues", []), issue]}
    conn.execute(
        update(pipeline_runs)
        .where(pipeline_runs.c.id == item["pipeline_run_id"])
        .values(stats=stats)
    )
    conn.execute(
        update(outbox)
        .where(outbox.c.id == item["id"])
        .values(
            status="halted" if halted else "done",
            error_code=issue,
        )
    )


def _resume_stopped(conn: Connection, item: RowMapping, stop: Path, halt: Path) -> bool:
    for gate in (stop, halt):
        try:
            gate.lstat()
        except FileNotFoundError:
            continue
        persisted = fetcher.persist_halt(halt)
        _end_resume(
            conn,
            item,
            "daily_bars_upstream_halted" if persisted else "daily_bars_halt_persist_failed",
            halted=True,
        )
        return True
    return False


def _resume(
    engine: Engine,
    *,
    grant_reader: GrantReader | None,
    clock: fetcher.Clock,
    stop: Path,
    halt: Path,
) -> bool:
    """Recover committed progress under the same send lock, without replaying HTTP."""
    with single_egress(engine) as lease:
        if lease is None:
            return False
        with engine.begin() as conn:
            if _halted(conn):
                return False
            item = (
                conn.execute(
                    select(outbox)
                    .where(
                        outbox.c.kind == fetcher.KIND,
                        outbox.c.status == "done",
                        outbox.c.error_code == RESUME_PENDING,
                    )
                    .order_by(outbox.c.created_at, outbox.c.batch_seq, outbox.c.id)
                    .limit(1)
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if item is None:
                return False
            now = fetcher._stamp(clock)
            if now.astimezone(BEIJING).date() != item["created_at"].astimezone(BEIJING).date():
                _end_resume(conn, item, "daily_bars_batch_expired")
                return False
            if _resume_stopped(conn, item, stop, halt):
                return False
            if batch_budget(item["batch_kind"]).kind == "unset":
                return False
            # Continuation alone must not open the protected history window.
            # Scheduling/initial-batch interruption and jobs:delayed are subsequent work.
            local = now.astimezone(BEIJING)
            history = item["batch_kind"] == "backfill" or item["window_trading_days"] not in (
                None,
                1,
            )
            if (
                history
                and dt.time(17) <= local.time() < dt.time(17, 45)
                and covered(conn, local.date())
            ):
                return False
            grant = (
                grant_reader(item["user_id"])
                if grant_reader
                else fetcher.read_daily_bars_grant(now=now, user_id=item["user_id"])
            )
            if not _authorized(conn, item, grant, now):
                _end_resume(conn, item, "data_licence_unavailable")
                return False
            if _resume_stopped(conn, item, stop, halt) or _halted(conn):
                return False
            intents.enqueue(
                conn,
                trade_date=item["trade_date"],
                user_id=item["user_id"],
                window_trading_days=item["window_trading_days"],
                batch_kind=item["batch_kind"],
                batch_seq=item["batch_seq"] + 1,
                grant_reader=lambda _: grant,
                now=now,
            )
            conn.execute(update(outbox).where(outbox.c.id == item["id"]).values(error_code=None))
            return True


def tick(
    engine: Engine,
    *,
    transport: fetcher.Transport | None = None,
    grant_reader: GrantReader | None = None,
    clock: fetcher.Clock = lambda: dt.datetime.now(dt.UTC),
    stop: Path = LISTS_STOP,
    halt: Path = fetcher.HALT,
    page_days: int | None = None,
) -> int:
    """Poll durable daily-bar intents; no shared stream or list message is consumed."""
    if all(batch_budget(kind).kind == "unset" for kind in ("daily", "backfill")):
        return 0
    if transport is None:
        return 0
    try:
        _resume(engine, grant_reader=grant_reader, clock=clock, stop=stop, halt=halt)
    except OSError:
        return 0
    with engine.connect() as conn:
        item_id = conn.execute(
            select(outbox.c.id)
            .where(
                outbox.c.kind == fetcher.KIND,
                outbox.c.status.in_(["pending", "running"]),
            )
            .order_by(outbox.c.created_at, outbox.c.batch_seq, outbox.c.id)
            .limit(1)
        ).scalar_one_or_none()
    if item_id is None:
        return 0
    result = daily_bars_seam(
        process,
        engine,
        item_id,
        sender=transport,
        grant_reader=grant_reader,
        clock=clock,
        stop=stop,
        halt=halt,
        page_days=page_days,
        continue_batches=True,
    )
    if result == "done":
        # An IO failure leaves the durable marker pending, without replaying HTTP.
        with suppress(OSError):
            _resume(engine, grant_reader=grant_reader, clock=clock, stop=stop, halt=halt)
    return int(result in {"done", "failed", "halted"})
