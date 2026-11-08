"""T-A29 owner conditions: signed rounded pct, inclusive price, calendar catch-up."""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, insert, select, update

from app.config import Settings
from app.db.tables.licences import user_data_licences
from app.db.tables.market import trading_calendar
from app.db.tables.research import action_plans, alert_rules, alerts, plan_conditions, plan_versions
from app.db.tables.reviews import data_snapshots
from app.db.tables.users import users
from app.ingest.owned_quotes import SCHEMA as OWNED_SCHEMA
from app.plans.models import number
from app.plans.service import OPEN, audit, owner_lock
from app.replay.baseline import require_isolated
from app.workers.assembly import canonical

TZ = ZoneInfo("Asia/Shanghai")
SCHEMA = "p2n07-owned-quote-v1"


def check(
    conn: Connection, owner: uuid.UUID, at: dt.datetime, *, app_env: str = "production"
) -> dict[str, Any]:
    """Trusted project job; only source receipts persisted before this evaluation."""
    if at.tzinfo is None:
        raise ValueError("aware_clock_required")
    owner_lock(conn, owner)
    day = at.astimezone(TZ).date()
    if (
        conn.execute(select(users.c.status).where(users.c.id == owner)).scalar_one_or_none()
        != "approved"
    ):
        return {
            "triggered": [],
            "gaps": ["user_not_approved"],
            "delivery": "persistent_in_app",
        }
    gaps, hits, observations = [], [], []
    is_open = conn.execute(
        select(trading_calendar.c.is_open).where(trading_calendar.c.date == day)
    ).scalar_one_or_none()
    heads = conn.execute(
        select(action_plans)
        .where(
            action_plans.c.user_id == owner,
            action_plans.c.status.in_(OPEN),
            action_plans.c.created_at <= at,
        )
        .order_by(action_plans.c.id)
        .with_for_update()
    ).all()
    for head in heads:
        v = conn.execute(
            select(plan_versions).where(plan_versions.c.id == head.current_version_id)
        ).one()
        if v.created_at > at:
            gaps.append(str(head.id) + ":version_not_yet_available")
            continue
        for c in conn.execute(
            select(plan_conditions)
            .where(plan_conditions.c.plan_version_id == v.id)
            .order_by(plan_conditions.c.id)
        ):
            observation = {
                "condition_id": str(c.id),
                "plan_id": str(head.id),
                "plan_version_id": str(v.id),
                "type": c.type,
                "params": c.params,
                "passed": None,
                "source_snapshot_id": None,
            }
            observations.append(observation)
            dedup = f"plan_condition:{c.id}"
            if conn.execute(
                select(alerts.c.id).where(alerts.c.user_id == owner, alerts.c.dedup_key == dedup)
            ).first():
                continue
            refs, evidence, snapshot, source_at = [], [], None, at
            value: Any
            if c.type == "custom":
                continue
            if c.type == "date":
                target = dt.date.fromisoformat(c.params["on"])
                calendar = dict(
                    conn.execute(
                        select(trading_calendar.c.date, trading_calendar.c.is_open)
                        .where(trading_calendar.c.date >= target)
                        .order_by(trading_calendar.c.date)
                    ).all()
                )
                due = target
                while calendar.get(due) is False:
                    due += dt.timedelta(days=1)
                if calendar.get(due) is not True:
                    gaps.append(str(c.id) + ":calendar_not_covered")
                    continue
                scheduled = dt.datetime.combine(due, dt.time(9), TZ)
                observation["scheduled_for"] = scheduled.isoformat()
                passed = at >= scheduled
                value = {"observed_date": str(day), "scheduled_for": scheduled.isoformat()}
                key, unit = "plan.observed_date", None
            else:
                if is_open is not True:
                    gaps.append(str(c.id) + ":calendar_not_open_or_not_covered")
                    continue
                # T-A29 price rules use a same-day fresh raw quote. Do not drop
                # the valid 11:30/15:00 closing tick via an extra half-open session.
                rows = conn.execute(
                    select(data_snapshots)
                    .where(
                        data_snapshots.c.user_id == owner,
                        data_snapshots.c.purpose == "signal",
                        data_snapshots.c.created_at <= at,
                        data_snapshots.c["items"]["schema_version"].astext.in_(
                            [SCHEMA, OWNED_SCHEMA]
                        ),
                    )
                    .order_by(data_snapshots.c.created_at.desc(), data_snapshots.c.id.desc())
                ).all()
                source = next(
                    (
                        r
                        for r in rows
                        if r.items.get("security_code") == head.security_code
                        and (
                            r.items.get("schema_version") == OWNED_SCHEMA
                            or r.items.get("account_id")
                            == (str(head.account_id) if head.account_id else None)
                        )
                    ),
                    None,
                )
                if source is None:
                    gaps.append(str(c.id) + ":owned_quote_adapter_missing")
                    continue
                raw = source.items
                if hashlib.sha256(canonical(raw).encode()).hexdigest() != source.hash:
                    gaps.append(str(c.id) + ":source_hash_invalid")
                    continue
                if raw.get("schema_version") == OWNED_SCHEMA:
                    licensed = conn.execute(
                        select(user_data_licences.c.id).where(
                            user_data_licences.c.id == source.licence_id,
                            user_data_licences.c.user_id == owner,
                            user_data_licences.c.status == "active",
                            user_data_licences.c.deleted_at.is_(None),
                            user_data_licences.c.created_at <= at,
                        )
                    ).first()
                    if not licensed or raw.get("adj_type") != "none":
                        gaps.append(str(c.id) + ":owned_quote_licence_unavailable")
                        continue
                else:
                    if app_env != "test" or raw.get("synthetic") is not True:
                        gaps.append(str(c.id) + ":production_quote_adapter_missing")
                        continue
                    require_isolated(conn, app_env=app_env)
                try:
                    source_at = dt.datetime.fromisoformat(raw["data_as_of"])
                    available = dt.datetime.fromisoformat(raw["available_at"])
                    expires = dt.datetime.fromisoformat(raw["expires_at"])
                    price = Decimal(number(raw["price"], positive=True))
                except (ValueError, KeyError, TypeError, ArithmeticError):
                    gaps.append(str(c.id) + ":malformed_quote")
                    continue
                if (
                    any(t.tzinfo is None for t in [source_at, available, expires])
                    or not source_at <= available <= at
                    or (
                        at > expires if raw.get("schema_version") == OWNED_SCHEMA else at >= expires
                    )
                    or source_at.astimezone(TZ).date() != day
                    or raw.get("data_status") != "fresh"
                    or raw.get("is_suspended") is not False
                ):
                    gaps.append(str(c.id) + ":quote_unavailable")
                    continue
                if not price.is_finite() or price <= 0:
                    gaps.append(str(c.id) + ":invalid_price")
                    continue
                if c.type == "pct_change":
                    try:
                        previous = Decimal(number(raw["prev_close"], positive=True))
                    except (ValueError, KeyError, TypeError, ArithmeticError):
                        gaps.append(str(c.id) + ":prev_close")
                        continue
                    change = ((price / previous - 1) * 100).quantize(
                        Decimal("0.0001"), rounding=ROUND_HALF_UP
                    )
                    threshold = Decimal(c.params["pct"])
                    if threshold == 0:
                        gaps.append(str(c.id) + ":invalid_zero_pct")
                        continue
                    passed = change >= threshold if threshold > 0 else change <= threshold
                    value, key, unit = str(change), "quote.pct_change", "pct"
                    observation["operands"] = {
                        "last": str(price),
                        "prev_close": str(previous),
                        "rounding": "HALF_UP:4",
                    }
                else:
                    threshold = Decimal(c.params["price"])
                    passed = price >= threshold if c.type == "price_above" else price <= threshold
                    value, key, unit = str(price), "quote.price", "CNY_per_share"
                snapshot = source.id
                observation["source_snapshot_id"] = str(source.id)
                observation["source_hash"] = source.hash
            observation["passed"] = passed
            if not passed:
                continue
            eid = f"plan:{head.id}:condition:{c.id}"
            refs.append(eid)
            evidence.append(
                {
                    "id": eid,
                    "key": key,
                    "value": value,
                    "unit": unit,
                    "provider": "system",
                    "endpoint": "plan_condition_worker",
                    "data_as_of": source_at.isoformat(),
                    "fetched_at": at.isoformat(),
                    "epistemic_type": "fact",
                }
            )
            if c.type == "pct_change":
                operand_id = eid + ":operands"
                refs.append(operand_id)
                evidence.append(
                    {
                        **evidence[0],
                        "id": operand_id,
                        "key": "quote.pct_operands",
                        "value": observation["operands"],
                        "unit": None,
                    }
                )
            rule = uuid.uuid5(c.id, "alert_rule")
            if (
                conn.execute(select(alert_rules.c.id).where(alert_rules.c.id == rule)).first()
                is None
            ):
                conn.execute(
                    insert(alert_rules).values(
                        id=rule,
                        user_id=owner,
                        origin="plan_condition",
                        plan_condition_id=c.id,
                        security_code=head.security_code,
                        type=c.type,
                        params=c.params,
                    )
                )
            identifier = uuid.uuid5(c.id, "alert")
            detail = {
                "origin": "plan_condition",
                "title": "您的计划条件已满足",
                "name": (v.completeness or {}).get("name", head.security_code),
                "plan_id": str(head.id),
                "plan_version_id": str(v.id),
                "condition_id": str(c.id),
                "condition_kind": c.kind,
                "condition_text": c.description,
                "evidence_ids": refs,
                "evidence": evidence,
            }
            conn.execute(
                insert(alerts).values(
                    id=identifier,
                    user_id=owner,
                    rule_id=rule,
                    security_code=head.security_code,
                    severity="info",
                    what_happened=detail,
                    affected=[
                        {
                            "plan_id": str(head.id),
                            "plan_version_no": v.version_no,
                            "condition_id": str(c.id),
                        }
                    ],
                    checklist=[],
                    status="new",
                    triggered_at=at,
                    data_as_of=source_at,
                    snapshot_id=snapshot,
                    dedup_key=dedup,
                )
            )
            conn.execute(
                update(action_plans)
                .where(action_plans.c.id == head.id)
                .values(status="triggered", triggered_at=head.triggered_at or at, updated_at=at)
            )
            audit(
                conn,
                owner,
                "plan.condition_triggered",
                head.id,
                {"condition_id": str(c.id), "alert_id": str(identifier)},
                system=True,
            )
            from app.notify.service import append

            append(
                conn,
                owner=owner,
                kind="plan_triggered",
                severity="attention",
                title="您的计划条件已满足",
                body=c.description,
                code=head.security_code,
                target_type="plan",
                target_id=str(head.id),
                ref_type="plan_condition",
                ref_id=str(c.id),
                at=at,
            )
            hits.append(str(identifier))
    return {
        "triggered": hits,
        "observations": observations,
        "gaps": gaps,
        "delivery": "persistent_in_app",
    }


TASK = "plans.check_conditions"


def task(settings: Settings, user_id: str, as_of: str | None = None) -> int:
    from app.workers.jobs import _engine

    now = dt.datetime.fromisoformat(as_of) if as_of is not None else dt.datetime.now(dt.UTC)
    with _engine(settings).begin() as conn:
        if now.tzinfo is not None and now > dt.datetime.now(dt.UTC):
            require_isolated(conn, app_env=settings.app_env)
        owner = uuid.UUID(user_id)
        result = check(conn, owner, now, app_env=settings.app_env)
        if result["gaps"] == ["user_not_approved"]:
            return 0
        # Immutable private diagnostic receipt, not an extra public state machine.
        body = {
            "schema_version": "p2n07-condition-assessment-v1",
            "as_of": now.isoformat(),
            **result,
        }
        digest = hashlib.sha256(canonical(body).encode()).hexdigest()
        identifier = uuid.uuid5(owner, digest)
        if (
            conn.execute(
                select(data_snapshots.c.id).where(data_snapshots.c.id == identifier)
            ).first()
            is None
        ):
            conn.execute(
                insert(data_snapshots).values(
                    id=identifier, user_id=owner, purpose="plan", hash=digest, items=body
                )
            )
    from app.db.tables.notify import notifications
    from app.notify.transport import enqueue, flush, publish
    from app.workers.jobs import _redis

    r = _redis(settings)
    try:
        with _engine(settings).connect() as conn:
            notice_ids = (
                conn.execute(
                    select(notifications.c.id).where(
                        notifications.c.user_id == owner,
                        notifications.c.kind == "plan_triggered",
                        notifications.c.updated_at == now,
                    )
                )
                .scalars()
                .all()
            )
            rows = conn.execute(
                select(alerts).where(
                    alerts.c.id.in_([uuid.UUID(v) for v in result["triggered"]]),
                    alerts.c.user_id == owner,
                )
            ).all()
        for row in rows:
            publish(
                r,
                owner,
                "plan_triggered",
                {
                    "plan_id": row.what_happened["plan_id"],
                    "condition": row.what_happened["condition_text"],
                    "at": row.triggered_at.isoformat(),
                },
                now,
                "plan-triggered:" + str(row.id),
            )
        for identifier in notice_ids:
            enqueue(_engine(settings), r, owner, identifier, now)
        flush(_engine(settings), r, now)
    finally:
        r.close()
    return len(result["triggered"])
