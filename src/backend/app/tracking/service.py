"""Frozen per-horizon observations in the existing suggestion_tracking snapshot.

A row's snapshot holds a unique result per strategy VERSION (not a merged vote).
No migration or new event machine. Terminal observations are never overwritten.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from decimal import Decimal, localcontext
from typing import Any, Literal

from sqlalchemy import Connection, insert, select, text, update

from app.common.errors import AppError, ErrorCode
from app.db.tables.accounts import accounts
from app.db.tables.market import daily_bars, minute_bars, trading_calendar
from app.db.tables.realtime import suggestion_tracking, suggestions
from app.db.tables.reviews import data_snapshots
from app.tracking.engine import BEIJING, close_at, due_date, evaluate, gap
from app.tracking.models import Result, Stat

SCHEMA = "p2n03-tracking-v1"
OBS_SCHEMA = "p2n03-market-observations-v1"
PERIODS: tuple[Literal[1, 5, 20], ...] = (1, 5, 20)


def canonical(value: Any) -> str:  # noqa: ANN401
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def digest(value: Any) -> str:  # noqa: ANN401
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def calendar(conn: Connection) -> dict[dt.date, bool]:
    return {r.date: r.is_open for r in conn.execute(select(trading_calendar))}


def owned(conn: Connection, owner: uuid.UUID, identifier: uuid.UUID) -> Any:  # noqa: ANN401
    row = conn.execute(
        select(suggestions).where(suggestions.c.id == identifier, suggestions.c.user_id == owner)
    ).first()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND)
    return row


def instrument(conn: Connection, code: str, end: dt.date, cutoff: dt.datetime) -> dict[str, Any]:
    rows = conn.execute(
        select(daily_bars)
        .where(
            daily_bars.c.code == code,
            daily_bars.c.adj_type == "none",
            daily_bars.c.trade_date <= end,
            daily_bars.c.fetched_at <= cutoff,
        )
        .order_by(daily_bars.c.trade_date)
    ).all()
    bars = []
    for row in rows:
        if any(
            row._mapping[k] is None
            or not Decimal(row._mapping[k]).is_finite()
            or Decimal(row._mapping[k]) <= 0
            for k in ["open", "high", "low", "close"]
        ):
            continue
        # A close must actually be closed; fetched_at is retained, not rewritten.
        if close_at(row.trade_date) > cutoff:
            continue
        bars.append(
            {
                "trade_date": row.trade_date.isoformat(),
                **{key: str(row._mapping[key]) for key in ["open", "high", "low", "close"]},
                "amount": str(row.amount) if row.amount is not None else None,
                "first_seen_at": row.fetched_at.isoformat(),
                "is_final": True,
            }
        )
    return {
        "security_code": code,
        "adjust": "none",
        "currency": None if code == "000300.SH" else "CNY",
        "price_unit": "index_points" if code == "000300.SH" else "CNY/share",
        "amount_unit": None if code == "000300.SH" else "CNY",
        "volume_unit": None if code == "000300.SH" else "share",
        "bars": bars,
    }


def observations(
    conn: Connection, owner: uuid.UUID, cutoff: dt.datetime
) -> tuple[Any, dict[str, Any]]:
    rows = conn.execute(
        select(data_snapshots)
        .where(
            data_snapshots.c.user_id == owner,
            data_snapshots.c.purpose == "report",
            data_snapshots.c.created_at <= cutoff,
        )
        .order_by(data_snapshots.c.created_at.desc(), data_snapshots.c.id.desc())
    ).all()
    for row in rows:
        body = row._mapping["items"]
        if body.get("schema_version") != OBS_SCHEMA:
            continue
        if digest(body) != row.hash:
            raise ValueError("tracking_source_hash_mismatch")
        return row, body
    return None, {}


def minutes(conn: Connection, code: str, day: dt.date, cutoff: dt.datetime) -> list[dict[str, Any]]:
    start = dt.datetime.combine(day, dt.time.min, BEIJING)
    rows = conn.execute(
        select(minute_bars)
        .where(
            minute_bars.c.code == code,
            minute_bars.c.ts >= start,
            minute_bars.c.ts < start + dt.timedelta(days=1),
            minute_bars.c.fetched_at <= cutoff,
            minute_bars.c.ts <= cutoff,
        )
        .order_by(minute_bars.c.ts)
    ).all()
    return [
        dict(r._mapping) for r in rows if r.open is not None and r.open.is_finite() and r.open > 0
    ]


def run_one(conn: Connection, owner: uuid.UUID, identifier: uuid.UUID, at: dt.datetime) -> int:
    row = owned(conn, owner, identifier)
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": "tracking:" + str(identifier)},
    )
    # Bind to the original owned immutable suggestion input, not mutable instances.
    generation = conn.execute(
        select(data_snapshots).where(
            data_snapshots.c.id == row.snapshot_id, data_snapshots.c.user_id == owner
        )
    ).first()
    if generation is None:
        return 0
    body = generation._mapping["items"]
    if body.get("schema_version") != "tb75-suggestion-input-v1":
        return 0
    if digest(body) != generation.hash:
        raise ValueError("tracking_generation_snapshot_hash_conflict")
    original = body["input"]
    conclusions = original["conclusions"]
    versions = [c["strategy_version_id"] for c in conclusions]
    if len(versions) != len(set(versions)):
        raise ValueError("tracking_duplicate_version_instances_need_contract")
    days = calendar(conn)
    count = 0
    for period in PERIODS:
        due = due_date(row.created_at, period, days)
        if due is None:
            # The old table requires a known due_date. Do not invent a weekday.
            continue
        prior = conn.execute(
            select(suggestion_tracking).where(
                suggestion_tracking.c.suggestion_id == identifier,
                suggestion_tracking.c.horizon_days == period,
            )
        ).first()
        if prior is not None and prior.status != "pending":
            continue
        if prior is not None and prior.due_date == due and at < close_at(due):
            # Pending has no priced observation yet. A different wall clock
            # on replay must not create duplicate immutable snapshots.
            continue
        cutoff = min(
            at,
            dt.datetime.combine(due + dt.timedelta(days=1), dt.time.min, BEIJING)
            - dt.timedelta(microseconds=1),
        )
        source, data = observations(conn, owner, cutoff)
        stock = instrument(conn, row.security_code, due, cutoff)
        benchmark = instrument(conn, "000300.SH", due, cutoff)
        payload = data.get("instruments", {}).get(row.security_code, {})
        factors = payload.get("factors", [])
        # Factors and F35/F36/F49 facts have independent, explicit availability.
        # No inference of suspension from missing/zero bars; no implicit factor=1.
        facts = {
            date: {k: v if type(v) is bool else None for k, v in facts["values"].items()}
            for date, facts in payload.get("facts", {}).items()
            if dt.datetime.fromisoformat(facts["available_at"]) <= cutoff
            and date <= due.isoformat()
        }
        minute_inputs = minutes(
            conn, row.security_code, row.created_at.astimezone(BEIJING).date(), cutoff
        )
        minute_inputs += minutes(
            conn,
            row.security_code,
            next(
                d for d in sorted(days) if days[d] and d > row.created_at.astimezone(BEIJING).date()
            ),
            cutoff,
        )
        results = []
        for conclusion in conclusions:
            signal = conclusion["signal"]
            # forced_hold requires a generation-time bound observation. No mutable
            # current holding or missing evidence is silently converted to False.
            forced = None
            holding = payload.get("holdings", {}).get(str(conclusion["instance_id"]))
            bound = conn.execute(
                select(data_snapshots).where(
                    data_snapshots.c.id == uuid.UUID(signal["snapshot_id"]),
                    data_snapshots.c.user_id == owner,
                )
            ).first()
            bound_account = (
                bound._mapping["items"].get("risk_account_id") if bound is not None else None
            )
            account_owner = (
                conn.execute(
                    select(accounts.c.user_id).where(accounts.c.id == uuid.UUID(bound_account))
                ).scalar_one_or_none()
                if bound_account
                else None
            )
            if (
                holding
                and bound_account
                and holding.get("account_id") == bound_account
                and account_owner == owner
                and bound is not None
                and digest(bound._mapping["items"]) == bound.hash
                and dt.datetime.fromisoformat(holding["available_at"]) <= row.created_at
            ):
                q, sellable, bought = (
                    Decimal(str(holding[k]))
                    for k in ["quantity", "sellable_quantity", "bought_today"]
                )
                if (
                    not all(v.is_finite() for v in (q, bought, sellable))
                    or min(q, bought, sellable) < 0
                    or max(bought, sellable) > q
                ):
                    raise ValueError("tracking_holding_observation_out_of_range")
                if q == 0 or (bought == 0 and sellable == q):
                    forced = False
                elif q > 0 and sellable == 0 and bought == q:
                    forced = True
            result = evaluate(
                conclusion={
                    **conclusion,
                    "action": signal["proposed_action"],
                    "security_code": row.security_code,
                },
                created=row.created_at,
                period=period,
                calendar=days,
                instrument=stock,
                benchmark=benchmark,
                factors=factors,
                facts=facts,
                forced_hold=forced,
                now=at,
                minutes=minute_inputs,
            )
            results.append(result.model_dump(mode="json"))
        snapshot_body = {
            "schema_version": SCHEMA,
            "algorithm_version": "p2n03-deterministic-v1",
            "generation_hash": generation.hash,
            "results": results,
            "suggestion_snapshot_id": str(row.snapshot_id),
            "observation_snapshot_id": str(source.id) if source is not None else None,
            "observation_hash": source.hash if source is not None else None,
            "raw_stock": stock,
            "raw_minutes": minute_inputs,
            "raw_benchmark": benchmark,
            "as_of": cutoff.isoformat(),
        }
        fingerprint = digest(snapshot_body)
        snapshot = uuid.uuid5(uuid.NAMESPACE_URL, fingerprint + ":" + str(owner))
        existing = conn.execute(
            select(data_snapshots).where(data_snapshots.c.id == snapshot)
        ).first()
        if existing is None:
            conn.execute(
                insert(data_snapshots).values(
                    id=snapshot,
                    user_id=owner,
                    purpose="review",
                    hash=fingerprint,
                    items=json.loads(canonical(snapshot_body)),
                    created_at=at,
                )
            )
        elif existing.user_id != owner or existing.hash != fingerprint:
            raise ValueError("tracking_snapshot_owner_or_hash_conflict")
        states = {r["state"] for r in results}
        status = (
            "pending"
            if "pending" in states
            else "not_applicable"
            if states <= {"excluded", "untradable"}
            else "done"
        )
        values = {
            "status": status,
            "ref_price": row.reference_price,
            "benchmark_code": "000300.SH",
            "snapshot_id": snapshot,
            "computed_at": at,
        }
        if prior is None:
            conn.execute(
                insert(suggestion_tracking).values(
                    suggestion_id=identifier, horizon_days=period, due_date=due, **values
                )
            )
        else:
            conn.execute(
                update(suggestion_tracking)
                .where(
                    suggestion_tracking.c.suggestion_id == identifier,
                    suggestion_tracking.c.horizon_days == period,
                )
                .values(**values)
            )
        count += 1
    return count


def results_for(
    conn: Connection, owner: uuid.UUID, identifier: uuid.UUID
) -> tuple[list[Result], list[Any]]:
    owned(conn, owner, identifier)
    rows = conn.execute(
        select(data_snapshots)
        .join(suggestion_tracking, suggestion_tracking.c.snapshot_id == data_snapshots.c.id)
        .where(suggestion_tracking.c.suggestion_id == identifier, data_snapshots.c.user_id == owner)
    ).all()
    results: list[Result] = []
    for row in rows:
        content = row._mapping["items"]
        if content.get("schema_version") != SCHEMA:
            continue
        if digest(content) != row.hash:
            raise ValueError("tracking_result_snapshot_hash_conflict")
        results.extend(Result.model_validate(r) for r in content["results"])
    return sorted(results, key=lambda r: (r.horizon_days, str(r.strategy_version_id))), list(rows)


def stat(values: list[Decimal], window: str) -> Stat:
    n = len(values)
    with localcontext() as ctx:
        ctx.prec = 64
        return Stat(
            value=sum(values, Decimal(0)) / n if n >= 5 else None,
            n=n,
            window=window,
            small_sample=n < 30,
        )


def view(conn: Connection, owner: uuid.UUID, identifier: uuid.UUID) -> dict[str, Any]:
    results, snapshots = results_for(conn, owner, identifier)
    gaps = {g.key: g for r in results for g in r.gaps}
    if not results:
        gaps["tracking_not_computed_or_calendar_not_covered"] = gap(
            "tracking_not_computed_or_calendar_not_covered"
        )
    return {
        **{
            "t" + str(p): stat(
                [
                    r.return_pct
                    for r in results
                    if r.horizon_days == p and r.state == "complete" and r.return_pct is not None
                ],
                str(p) + " trading days",
            ).model_dump(mode="json")
            for p in [1, 5, 20]
        },
        "results": [r.model_dump(mode="json") for r in results],
        "data_status": "unavailable"
        if not results
        else "partial"
        if gaps or any(r.state != "complete" for r in results)
        else "fresh",
        "data_as_of": max(
            (
                dt.datetime.fromisoformat(r._mapping["items"]["as_of"])
                for r in snapshots
                if r._mapping["items"].get("schema_version") == SCHEMA
            ),
            default=None,
        ),
        "gaps": [g.model_dump(mode="json") for g in gaps.values()],
    }
