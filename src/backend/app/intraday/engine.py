"""P2N-06 trusted market.updated consumer. Offline input adapter is explicitly isolated.

No provider IO; production minute/quote ownership adapter remains deployment-gated.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import uuid
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

import redis
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Row, select, text, update
from sqlalchemy.dialects.postgresql import insert

from app.api.v1.portfolio import _account
from app.config import Settings
from app.db.tables.accounts import accounts
from app.db.tables.licences import user_data_licences
from app.db.tables.market import securities, trading_calendar
from app.db.tables.realtime import (
    intraday_candidate_refs,
    intraday_universe,
    signal_event_projections,
    signal_events,
    signal_states,
    user_realtime_prefs,
)
from app.db.tables.research import watchlist_items
from app.db.tables.reviews import data_snapshots
from app.db.tables.strategy import (
    engine_policies,
    feature_catalog,
    strategies,
    strategy_card_versions,
    strategy_instances,
    strategy_versions,
)
from app.db.tables.users import users
from app.engine_policies import latest as latest_policy
from app.features.evaluation import RuleEvaluator
from app.features.pipeline import instant, prepare
from app.intraday.events import project as event_view
from app.intraday.state import advance
from app.notify.service import append
from app.notify.transport import enqueue, flush, publish
from app.replay.baseline import require_isolated
from app.strategy.runtime import runnable
from app.workers.assembly import archive_conclusions, canonical, conclusion

TZ = ZoneInfo("Asia/Shanghai")
SCHEMA = "p2n06-owned-input-v1"
TASK = "intraday.market_updated"


class Updated(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    v: Literal[1]
    licence_id: uuid.UUID
    tick_id: str = Field(pattern=r"^\d{8}T\d{6}$")
    dataset: Literal[
        "quotes", "minute_bars", "daily_bars", "financials", "announcements", "security_master"
    ]
    codes: list[str] = Field(max_length=500)
    quote_ts_max: dt.datetime
    published_at: dt.datetime


def scope(conn: Connection, licence: uuid.UUID) -> Row[Any, Any, Any] | None:
    return conn.execute(
        select(user_data_licences.c.id, user_data_licences.c.user_id, users.c.role)
        .join(users, users.c.id == user_data_licences.c.user_id)
        .where(
            user_data_licences.c.id == licence,
            user_data_licences.c.status == "active",
            user_data_licences.c.deleted_at.is_(None),
            users.c.status == "approved",
        )
    ).first()


def session(conn: Connection, at: dt.datetime) -> bool:
    local = at.astimezone(TZ)
    t = local.time()
    return bool(
        conn.execute(
            select(trading_calendar.c.is_open).where(trading_calendar.c.date == local.date())
        ).scalar_one_or_none()
    ) and (dt.time(9, 30) <= t < dt.time(11, 30) or dt.time(13) <= t < dt.time(15))


def universe(
    conn: Connection, owner: uuid.UUID, licence: uuid.UUID, date: dt.date, settings: Settings
) -> set[str]:
    account_ids = (
        conn.execute(
            select(accounts.c.id).where(
                accounts.c.user_id == owner, accounts.c.archived_at.is_(None)
            )
        )
        .scalars()
        .all()
    )
    positions = {}
    for account in account_ids:
        positions.update(_account(conn, account, date).positions)
    watches = conn.execute(
        select(watchlist_items.c.security_code).where(
            watchlist_items.c.user_id == owner, watchlist_items.c.removed_at.is_(None)
        )
    ).all()
    focus = set(
        conn.execute(
            select(user_realtime_prefs.c.focus_codes).where(user_realtime_prefs.c.user_id == owner)
        ).scalar_one_or_none()
        or []
    )
    codes = (
        sorted(set(positions))
        + sorted(focus - set(positions))
        + sorted({w.security_code for w in watches} - set(positions) - focus)
    )
    eligible = set()
    for i, code in enumerate(codes[: settings.business.realtime.universe.universe_hard_cap]):
        sec = conn.execute(select(securities).where(securities.c.code == code)).first()
        if (
            sec is None
            or sec.type not in {"stock", "cdr"}
            or sec.listing_status != "listed"
            or (sec.delist_date and sec.delist_date <= date)
        ):
            continue
        eligible.add(code)
        stmt = insert(intraday_universe).values(
            trade_date=date,
            source_licence_id=licence,
            security_code=code,
            tier=1 if i < settings.business.realtime.universe.tier1_cap else 2,
            holders_count=int(code in positions),
            watchers_count=int(any(w.security_code == code for w in watches)),
            focus_users_count=int(code in focus),
        )
        conn.execute(
            stmt.on_conflict_do_update(
                index_elements=["trade_date", "source_licence_id", "security_code"],
                set_={"computed_at": dt.datetime.now(dt.UTC)},
            )
        )
    return eligible


def source(
    conn: Connection, owner: uuid.UUID, licence: uuid.UUID, code: str, tick: str, at: dt.datetime
) -> Row[Any] | None:
    row = conn.execute(
        select(data_snapshots)
        .where(
            data_snapshots.c.user_id == owner,
            data_snapshots.c.licence_id == licence,
            data_snapshots.c.purpose == "signal",
            data_snapshots.c["items"]["schema_version"].astext == SCHEMA,
            data_snapshots.c["items"]["security_code"].astext == code,
            data_snapshots.c["items"]["tick_id"].astext == tick,
            data_snapshots.c.created_at <= at,
        )
        .order_by(data_snapshots.c.created_at.desc(), data_snapshots.c.id.desc())
    ).first()
    if row is None:
        return None
    if hashlib.sha256(canonical(row.items).encode()).hexdigest() != row.hash:
        raise ValueError("source_hash_mismatch")
    if row.items.get("simulation") is not True:
        raise ValueError("isolated_source_label_required")
    return row


def evaluate(
    conn: Connection,
    settings: Settings,
    owner: uuid.UUID,
    instance: Row[Any],
    version: Row[Any],
    src: Row[Any],
    at: dt.datetime,
    *,
    shared: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    config = copy.deepcopy(version.config.get("spec", version.config))
    for key, value in (instance.param_overrides or {}).items():
        if key not in config["params_schema"]:
            raise ValueError("undeclared_parameter")
        config["params_schema"][key]["default"] = value
    registry = {
        r.feature_key: {"unit": r.unit, "status": r.status, "source": r.source}
        for r in conn.execute(select(feature_catalog))
    }
    card = conn.execute(
        select(strategy_card_versions.c.fields).where(
            strategy_card_versions.c.id == version.card_version_id
        )
    ).scalar_one()
    if version.config.get("source_hash"):
        from app.strategy.cards.source_reviews import required_features, source_issues

        if source_issues(registry, required_features(config, card), version.lifecycle):
            raise ValueError("runtime_source_gate")
    raw = src.items
    frame = prepare(
        raw["instrument"],
        raw["sessions"],
        as_of=at,
        factors=raw.get("factors", []),
        scalars=raw.get("scalars", []),
        registry=registry,
        lots=[] if shared else raw.get("lots", []),
        entry=None if shared else raw.get("entry"),
    )
    quote = raw["quote"]
    price = Decimal(str(quote["price"]))
    if not price.is_finite() or price <= 0 or instant(quote["t"]) > at:
        raise ValueError("invalid_owned_quote")
    frame["market_price"] = price
    frame["features"]["f.is_suspended"] = quote["is_suspended"]
    held = {} if shared else raw.get("holding", {})
    # Input is an owned, immutable isolated receipt, not a caller supplied final conclusion.
    result = RuleEvaluator().evaluate(
        card=card,
        spec=config,
        frame=frame,
        holding=held,
        security={"board": raw["instrument"]["board"]},
        market_rules=settings.business.market_rules,
        registry=registry,
    )
    result.update(snapshot_id=str(src.id), security_code=raw["security_code"], simulation=True)
    return result, config, registry


def compute(settings: Settings, message: Updated) -> list[uuid.UUID]:
    from app.workers.jobs import _engine

    if settings.app_env != "test":
        return []  # no safe production-owned minute adapter yet
    engine = _engine(settings)
    events = []
    at = message.published_at
    if at.tzinfo is None or message.quote_ts_max.tzinfo is None:
        raise ValueError("aware_clock_required")
    tick_at = dt.datetime.strptime(message.tick_id, "%Y%m%dT%H%M%S").replace(tzinfo=TZ)
    if tick_at > at or message.quote_ts_max > at:
        raise ValueError("future_tick")
    with engine.begin() as conn:
        require_isolated(conn, app_env=settings.app_env)
        holder = scope(conn, message.licence_id)
        if holder is None or not session(conn, at):
            return []
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:owner,74))"),
            {"owner": str(holder.user_id)},
        )
        allowed = universe(conn, holder.user_id, holder.id, at.astimezone(TZ).date(), settings)
        instances = conn.execute(
            select(strategy_instances)
            .where(
                strategy_instances.c.user_id == holder.user_id,
                strategy_instances.c.status == "active",
            )
            .order_by(strategy_instances.c.id)
        ).all()
        seen = set()
        for code in sorted(set(message.codes) & allowed):
            src = source(conn, holder.user_id, holder.id, code, message.tick_id, at)
            if src is None:
                continue
            q = src.items["quote"]
            quote_at = instant(q["t"])
            age = (at - quote_at).total_seconds()
            fresh = 0 <= age <= settings.business.realtime.intervals.effective_stale_threshold_s
            suspended = q.get("is_suspended")
            for instance in instances:
                if instance.scope == "security" and instance.security_code != code:
                    continue
                if instance.scope not in {"security", "account"}:
                    continue
                version = conn.execute(
                    select(strategy_versions).where(
                        strategy_versions.c.id
                        == (instance.derived_strategy_version_id or instance.strategy_version_id)
                    )
                ).one()
                if not runnable(version.lifecycle, holder.role):
                    continue
                params = {
                    k: v["default"]
                    for k, v in version.config.get("spec", version.config)["params_schema"].items()
                }
                params.update(instance.param_overrides or {})
                ph = hashlib.sha256(canonical(params).encode()).hexdigest()
                key = (code, version.id, ph)
                if key in seen:
                    continue
                seen.add(key)
                conn.execute(
                    insert(signal_states)
                    .values(
                        source_licence_id=holder.id,
                        security_code=code,
                        strategy_version_id=version.id,
                        params_hash=ph,
                        rule_states={},
                    )
                    .on_conflict_do_nothing(
                        index_elements=[
                            "source_licence_id",
                            "security_code",
                            "strategy_version_id",
                            "params_hash",
                        ]
                    )
                )
                old = conn.execute(
                    select(signal_states)
                    .where(
                        signal_states.c.source_licence_id == holder.id,
                        signal_states.c.security_code == code,
                        signal_states.c.strategy_version_id == version.id,
                        signal_states.c.params_hash == ph,
                    )
                    .with_for_update()
                ).one()
                if old.last_tick_id is not None and old.last_tick_id >= message.tick_id:
                    continue
                status = (
                    "suspended"
                    if suspended is True
                    else "fresh"
                    if fresh and suspended is False
                    else "stale"
                )
                states = old.rule_states or {}
                flips: list[tuple[dict[str, Any], object, object]] = []
                if status == "fresh":
                    result, spec, _registry = evaluate(
                        conn, settings, holder.user_id, instance, version, src, at, shared=True
                    )
                    states, flips = advance(
                        states,
                        result["rule_refs"],
                        settings.business.realtime.flip_detection.debounce_rounds,
                        settings.business.realtime.flip_detection.invalidation_immediate,
                    )
                else:
                    states = {
                        k: dict(v, pending_value=None, pending_count=0) for k, v in states.items()
                    }
                changed = conn.execute(
                    update(signal_states)
                    .where(
                        signal_states.c.id == old.id,
                        (
                            signal_states.c.last_tick_id.is_(None)
                            | (signal_states.c.last_tick_id < message.tick_id)
                        ),
                    )
                    .values(
                        last_tick_id=message.tick_id,
                        rule_states=states,
                        state=status,
                        changed_at=at,
                    )
                ).rowcount
                if not changed:
                    continue
                emitted = []
                if old.state and old.state != status:
                    trigger = "resume" if status == "fresh" else "stale"
                    emitted.append(
                        (
                            trigger,
                            {
                                "kind": "suspended"
                                if status == "suspended" or old.state == "suspended"
                                else "data_stale",
                                "rule_id": None,
                                "strategy_key": None,
                                "price": None,
                                "direction": "resumed"
                                if old.state == "suspended" and status == "fresh"
                                else "recovered"
                                if status == "fresh"
                                else status,
                                "candidate_signal_id": None,
                            },
                            old.state,
                            status,
                        )
                    )
                if status == "fresh":
                    strategy = conn.execute(
                        select(strategies).where(strategies.c.id == version.strategy_id)
                    ).one()
                    rules = {r["id"]: r for r in spec["rules"]}
                    for ref, before, after in flips:
                        invalid = ref["role"] == "invalidation" and after is True
                        kind = rules[ref["rule_id"]].get("event_kind", "rule_flip")
                        if invalid:
                            kind = "stop_hit"
                        emitted.append(
                            (
                                "invalidation" if invalid else "flip",
                                {
                                    "kind": kind,
                                    "rule_id": ref["rule_id"],
                                    "strategy_key": strategy.key,
                                    "price": str(q["price"])
                                    if q.get("price") is not None
                                    else None,
                                    "direction": "up" if after else "down",
                                    "candidate_signal_id": None,
                                },
                                str(before).lower() if before is not None else "unknown",
                                str(after).lower(),
                            )
                        )
                policy = latest_policy(conn)
                for trigger, detail, before, after in emitted:
                    identifier = uuid.uuid4()
                    conn.execute(
                        insert(signal_events).values(
                            id=identifier,
                            source_licence_id=holder.id,
                            input_snapshot_id=src.id,
                            engine_policy_id=policy.id if policy else None,
                            tick_id=message.tick_id,
                            scope="shared",
                            security_code=code,
                            strategy_version_id=version.id,
                            params_hash=ph,
                            rule_id=detail["rule_id"],
                            from_state=before,
                            to_state=after,
                            trigger_kind=trigger,
                            detail=detail,
                            quote_ts=quote_at,
                            created_at=at,
                        )
                    )
                    events.append(identifier)
    return events


def matching(conn: Connection, event: Row[Any], holder: Row[Any, Any, Any]) -> list[Row[Any]]:
    src = conn.execute(
        select(data_snapshots).where(
            data_snapshots.c.id == event.input_snapshot_id,
            data_snapshots.c.user_id == holder.user_id,
            data_snapshots.c.licence_id == holder.id,
        )
    ).one_or_none()
    ver = conn.execute(
        select(strategy_versions).where(strategy_versions.c.id == event.strategy_version_id)
    ).one_or_none()
    if src is None or ver is None or not runnable(ver.lifecycle, holder.role):
        return []
    result = []
    for inst in conn.execute(
        select(strategy_instances)
        .where(
            strategy_instances.c.user_id == holder.user_id, strategy_instances.c.status == "active"
        )
        .order_by(strategy_instances.c.created_at, strategy_instances.c.id)
        .with_for_update()
    ):
        if (
            inst.derived_strategy_version_id or inst.strategy_version_id
        ) != event.strategy_version_id:
            continue
        if inst.scope not in {"security", "account"}:
            continue
        if inst.scope == "security" and inst.security_code != event.security_code:
            continue
        if src.items.get("account_id") != (str(inst.account_id) if inst.account_id else None):
            continue
        if (
            inst.account_id
            and conn.execute(
                select(accounts.c.id).where(
                    accounts.c.id == inst.account_id,
                    accounts.c.user_id == holder.user_id,
                    accounts.c.archived_at.is_(None),
                )
            ).first()
            is None
        ):
            continue
        params = {
            k: v["default"] for k, v in ver.config.get("spec", ver.config)["params_schema"].items()
        }
        params.update(inst.param_overrides or {})
        if hashlib.sha256(canonical(params).encode()).hexdigest() == event.params_hash:
            result.append(inst)
    return result


def primary_instance(
    instances: list[Row[Any]], candidates: dict[uuid.UUID, uuid.UUID]
) -> Row[Any] | None:
    """Input is the historically matched, created_at/id ordered set."""
    return next((i for i in instances if i.id in candidates), instances[0] if instances else None)


def handoff(settings: Settings, event_id: uuid.UUID, r: redis.Redis) -> int:
    from app.db.tables.realtime import suggestion_threads, suggestions
    from app.suggestions.models import Conclusion
    from app.suggestions.service import summary
    from app.workers.jobs import _engine

    if settings.app_env != "test":
        return 0
    engine = _engine(settings)
    try:
        with engine.begin() as conn:
            require_isolated(conn, app_env=settings.app_env)
            event = conn.execute(select(signal_events).where(signal_events.c.id == event_id)).one()
            if event.legacy_binding_unknown:
                return 0
            holder = scope(conn, event.source_licence_id)
            if holder is None:
                return 0
            conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:owner,74))"),
                {"owner": str(holder.user_id)},
            )
            if conn.execute(
                select(signal_event_projections.c.event_id).where(
                    signal_event_projections.c.event_id == event.id,
                    signal_event_projections.c.user_id == holder.user_id,
                )
            ).first():
                return 0
            instances = matching(conn, event, holder)
            rows = []
            policy = conn.execute(
                select(engine_policies).where(engine_policies.c.id == event.engine_policy_id)
            ).one_or_none()
            if instances and event.trigger_kind in {"flip", "invalidation"}:
                if policy is None:
                    return 0
                src = conn.execute(
                    select(data_snapshots).where(data_snapshots.c.id == event.input_snapshot_id)
                ).one()
                ver = conn.execute(
                    select(strategy_versions).where(
                        strategy_versions.c.id == event.strategy_version_id
                    )
                ).one()
                strategy = conn.execute(
                    select(strategies).where(strategies.c.id == ver.strategy_id)
                ).one()
                for inst in instances:
                    result, _, registry = evaluate(
                        conn, settings, holder.user_id, inst, ver, src, event.created_at
                    )
                    row = conclusion(
                        conn,
                        owner=holder.user_id,
                        instance=inst,
                        version=ver,
                        strategy=strategy,
                        result=result,
                        registry=registry,
                        source=src,
                        policy=policy,
                        settings=settings,
                        origin_signal_event_id=event.id,
                    )
                    rows.append(row)
                    conn.execute(
                        insert(intraday_candidate_refs).values(
                            instance_id=inst.id,
                            event_id=event.id,
                            candidate_id=row.candidate_signal_id,
                        )
                    )
            candidate_by_instance = {
                row.instance_id: row.candidate_signal_id for row in rows if row.candidate_signal_id
            }
            selected = primary_instance(instances, candidate_by_instance)
            conn.execute(
                insert(signal_event_projections).values(
                    event_id=event.id,
                    user_id=holder.user_id,
                    instance_id=selected.id if selected else None,
                    instance_ids=[i.id for i in instances[:20]],
                    candidate_signal_id=candidate_by_instance.get(selected.id)
                    if selected
                    else None,
                )
            )
            if not rows:
                return 0
            # Preserve frozen unaffected conclusions, not a current-state recomputation.
            prior = conn.execute(
                select(data_snapshots.c.id, data_snapshots.c["items"])
                .join(suggestions, suggestions.c.snapshot_id == data_snapshots.c.id)
                .join(
                    suggestion_threads,
                    suggestion_threads.c.current_suggestion_id == suggestions.c.id,
                )
                .where(
                    suggestion_threads.c.user_id == holder.user_id,
                    suggestion_threads.c.security_code == event.security_code,
                    suggestions.c.user_id == holder.user_id,
                    data_snapshots.c.user_id == holder.user_id,
                    suggestions.c.security_code == event.security_code,
                )
                .order_by(suggestions.c.created_at.desc(), suggestions.c.id.desc())
                .limit(1)
            ).first()
            affected = {row.instance_id for row in rows}
            carried = [
                Conclusion.model_validate(raw)
                for raw in (prior._mapping["items"] if prior else {})
                .get("input", {})
                .get("conclusions", [])
                if uuid.UUID(str(raw["instance_id"])) not in affected
            ]
            if policy is None:
                raise ValueError("frozen_policy_missing")
            archived = archive_conclusions(
                conn,
                holder.user_id,
                event.security_code,
                rows + carried,
                policy,
                carry_from_snapshot_id=prior.id if prior and carried else None,
            )
            sid = archived["suggestion"]["id"]
            nid, new = append(
                conn,
                owner=holder.user_id,
                kind="invalidation"
                if event.trigger_kind == "invalidation"
                else "suggestion_change",
                severity="important" if event.trigger_kind == "invalidation" else "attention",
                title="规则状态已变化",
                body="请查看规则证据与当前建议。",
                code=event.security_code,
                target_type="suggestion",
                target_id=str(sid),
                ref_type="signal",
                ref_id=str(event.id),
                at=event.created_at,
            )
        # Only committed products are published. HTTP remains durable fallback.
        if archived["changed"]:
            with engine.connect() as conn:
                sr = conn.execute(
                    select(suggestions).where(
                        suggestions.c.id == uuid.UUID(sid), suggestions.c.user_id == holder.user_id
                    )
                ).one()
                data = summary(sr)
            publish(
                r,
                holder.user_id,
                "suggestion",
                {
                    "id": sid,
                    "security_code": event.security_code,
                    "name": archived["suggestion"]["name"],
                    "supersedes_id": archived["superseded_id"],
                    "summary": data,
                },
                event.created_at,
                "suggestion:" + sid,
            )
        from app.db.tables.signals import candidate_signals

        for row in rows:
            if row.candidate_signal_id:
                with engine.connect() as conn:
                    cr = conn.execute(
                        select(candidate_signals).where(
                            candidate_signals.c.id == row.candidate_signal_id,
                            candidate_signals.c.user_id == holder.user_id,
                        )
                    ).one()
                publish(
                    r,
                    holder.user_id,
                    "candidate_signal",
                    {
                        "id": str(cr.id),
                        "security_code": cr.security_code,
                        "name": archived["suggestion"]["name"],
                        "state": cr.state,
                        "proposed_action": cr.proposed_action,
                        "strategy_key": strategy.key,
                        "strategy_name": strategy.name,
                    },
                    event.created_at,
                    "candidate:" + str(cr.id) + ":" + cr.state,
                )
        if new:
            enqueue(engine, r, holder.user_id, nid, event.created_at)
        return int(new)
    except Exception as exc:  # noqa: BLE001 - all fanout rolls back, recover retries committed source
        import logging

        logging.getLogger(__name__).warning("intraday_handoff_failed:%s", type(exc).__name__)
        return 0


def task(settings: Settings, event: dict[str, Any]) -> int:
    from app.workers.jobs import _engine, _redis

    message = Updated.model_validate(event)
    ids = compute(settings, message)
    r = _redis(settings)
    try:
        for identifier in ids:
            handoff(settings, identifier, r)
            with _engine(settings).connect() as conn:
                ev = conn.execute(
                    select(signal_events).where(signal_events.c.id == identifier)
                ).one()
                h = scope(conn, message.licence_id)
                frozen = conn.execute(
                    select(signal_event_projections.c.event_id).where(
                        signal_event_projections.c.event_id == ev.id
                    )
                ).first()
                data = event_view(conn, ev) if frozen else None
            if h and data:
                publish(r, h.user_id, "signal", data, ev.created_at, "signal:" + str(ev.id))
        recover(settings, message.licence_id, r, message.published_at)
        flush(
            _engine(settings),
            r,
            message.published_at,
        )
    finally:
        r.close()
    return len(ids)


def recover(settings: Settings, licence_id: uuid.UUID, r: redis.Redis, at: dt.datetime) -> int:
    """Resume committed shared facts; child mapping enforces global idempotency."""
    from app.workers.jobs import _engine

    if settings.app_env != "test":
        return 0
    with _engine(settings).connect() as conn:
        if scope(conn, licence_id) is None:
            return 0
        ids = (
            conn.execute(
                select(signal_events.c.id)
                .where(
                    signal_events.c.source_licence_id == licence_id,
                    signal_events.c.created_at <= at,
                )
                .order_by(signal_events.c.created_at.desc(), signal_events.c.id.desc())
                .limit(500)
            )
            .scalars()
            .all()
        )
    return sum(handoff(settings, i, r) for i in ids)
