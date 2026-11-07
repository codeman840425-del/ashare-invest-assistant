"""T-B76 durable DB progress behind the existing Redis worker, without vendor IO."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import Connection, insert, select, text, true, update

from app.aggregates.service import select_account
from app.api.v1.portfolio import _account
from app.config import Settings
from app.db.tables.market import securities
from app.db.tables.realtime import pipeline_runs
from app.db.tables.reviews import data_snapshots
from app.db.tables.strategy import (
    feature_catalog,
    strategies,
    strategy_card_versions,
    strategy_instances,
    strategy_versions,
)
from app.db.tables.users import users
from app.features.evaluation import evaluate_snapshot
from app.replay.baseline import VERSION, require_isolated
from app.reports.service import build, canonical, covered
from app.strategy.runtime import runnable

ANALYZE = "daily_analysis"
REPORT = "daily_report"
RECOVER = "daily_recover"
BEIJING = dt.timezone(dt.timedelta(hours=8))


def analyze(
    conn: Connection, settings: Settings, owner: uuid.UUID, date: dt.date, role: str
) -> dict[str, Any]:
    account_id = select_account(conn, owner, None)
    account = _account(conn, account_id, date) if account_id else None
    positions = account.positions if account else {}
    issues: list[str] = []
    evaluations: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    instances = conn.execute(
        select(strategy_instances)
        .where(strategy_instances.c.user_id == owner, strategy_instances.c.status == "active")
        .order_by(strategy_instances.c.id)
    ).all()
    if not instances:
        issues.append("active_instances_missing")
    for instance in instances:
        version = conn.execute(
            select(strategy_versions)
            .join(strategies, strategies.c.id == strategy_versions.c.strategy_id)
            .where(
                strategy_versions.c.id
                == (instance.derived_strategy_version_id or instance.strategy_version_id),
                (strategies.c.owner_user_id.is_(None) | (strategies.c.owner_user_id == owner)),
            )
        ).one_or_none()
        if version is None:
            issues.append("version_unavailable")
            continue
        bindings.append(
            {
                "instance_id": str(instance.id),
                "version_id": str(version.id),
                "config_hash": version.config_hash,
                "lifecycle": version.lifecycle,
                "role": role,
            }
        )
        if not runnable(version.lifecycle, role):
            issues.append("runtime_lifecycle_blocked:" + str(instance.id))
            continue
        # No real certificate reader/production price source exists here yet. Synthetic
        # offline replay is accepted ONLY inside the pre-existing isolated boundary.
        if settings.app_env != "test":
            issues.append("owned_market_cache_adapter_missing")
            continue
        require_isolated(conn, app_env=settings.app_env)
        sources = conn.execute(
            select(data_snapshots)
            .where(
                data_snapshots.c.user_id == owner,
                data_snapshots.c.purpose == "report",
                data_snapshots.c.licence_id.is_(None),
            )
            .order_by(data_snapshots.c.created_at.desc(), data_snapshots.c.id.desc())
        ).all()
        source = next(
            (s for s in sources if (s.items or {}).get("schema_version") == VERSION), None
        )
        card = conn.execute(
            select(strategy_card_versions.c.fields).where(
                strategy_card_versions.c.id == version.card_version_id
            )
        ).scalar_one_or_none()
        if source is None or card is None:
            issues.append("owned_source_or_card_missing")
            continue
        registry = {
            row.feature_key: {"unit": row.unit}
            for row in conn.execute(select(feature_catalog.c.feature_key, feature_catalog.c.unit))
        }
        codes = (
            sorted(positions)
            if instance.scope == "account" and instance.account_id == account_id
            else [instance.security_code]
            if instance.scope == "security" and instance.security_code in positions
            else []
        )
        for code in codes:
            security = conn.execute(
                select(securities.c.type, securities.c.listing_status).where(
                    securities.c.code == code
                )
            ).first()
            if security is None or security.type != "stock" or security.listing_status != "listed":
                issues.append("security_not_eligible:" + code)
                continue
            position = positions[code]
            result = evaluate_snapshot(
                conn,
                user_id=owner,
                snapshot_id=source.id,
                security_code=code,
                as_of=dt.datetime.combine(date, dt.time(17, 30), BEIJING),
                card=card,
                spec=version.config.get("spec", version.config),
                registry=registry,
                market_rules=settings.business.market_rules,
                factors=[],
                holding={"qty": position.qty, "sellable": position.sellable},
            )
            evaluations.append(
                {
                    "instance_id": str(instance.id),
                    "security_code": code,
                    "simulation": True,
                    "source_hash": source.hash,
                    "state": result["state"],
                    "action": result["action"],
                    "rule_refs": result["rule_refs"],
                    "evidence": result["evidence"],
                    "gaps": result["gaps"],
                }
            )
            # RuleEvaluator currently has no complete P1 confidence/stops/dimension
            # output. Never fake those required fields to force archive admission.
            issues.append("p1_conclusion_assembler_missing:" + code)
    return {"issues": sorted(set(issues)), "evaluations": evaluations, "bindings": bindings}


def phase(settings: Settings, phase: str, trade_date: str, user_id: str | None = None) -> int:
    import json

    from app.workers.jobs import _engine

    date = dt.date.fromisoformat(trade_date)
    engine = _engine(settings)
    # Session lock survives per-user commits; duplicate consumers never overlap.
    with engine.connect() as conn:
        lock = "tb76:" + phase + ":" + trade_date
        locked = conn.execute(
            text("SELECT pg_try_advisory_lock(hashtextextended(:key,76))"), {"key": lock}
        ).scalar_one()
        conn.commit()
        if not locked:
            return 0
        run_id = uuid.uuid4()
        try:
            if not covered(conn, date):
                conn.commit()
                return 0
            conn.execute(
                update(pipeline_runs)
                .where(
                    pipeline_runs.c.step == "tb76." + phase,
                    pipeline_runs.c.run_date == date,
                    pipeline_runs.c.status == "running",
                    pipeline_runs.c.stats["user_id"].astext == user_id if user_id else true(),
                )
                .values(status="skipped", finished_at=dt.datetime.now(dt.UTC))
            )
            conn.execute(
                insert(pipeline_runs).values(
                    id=run_id,
                    kind="daily_batch",
                    run_date=date,
                    step="tb76." + phase,
                    status="running",
                    stats={"user_id": user_id},
                )
            )
            conn.commit()
            owners = conn.execute(
                select(users.c.id, users.c.role)
                .where(
                    users.c.status == "approved",
                    users.c.id == uuid.UUID(user_id) if user_id else true(),
                )
                .order_by(users.c.id)
            ).all()
            conn.commit()
            outcomes: dict[str, Any] = {}
            for owner in owners:
                with conn.begin():
                    if phase == ANALYZE:
                        outcomes[str(owner.id)] = analyze(
                            conn, settings, owner.id, date, owner.role
                        )
                    elif phase == REPORT:
                        outcomes[str(owner.id)] = {
                            "report_id": str(build(conn, owner.id, date, dt.datetime.now(dt.UTC)))
                        }
                    else:
                        raise ValueError("unknown_daily_phase")
            conn.execute(
                update(pipeline_runs)
                .where(pipeline_runs.c.id == run_id)
                .values(
                    status="partial",
                    finished_at=dt.datetime.now(dt.UTC),
                    stats=json.loads(canonical({"users": outcomes, "user_id": user_id})),
                )
            )
            conn.execute(
                update(pipeline_runs)
                .where(
                    pipeline_runs.c.step == "tb76.intent." + phase,
                    pipeline_runs.c.run_date == date,
                    pipeline_runs.c.status == "running",
                    pipeline_runs.c.stats["user_id"].astext == user_id if user_id else true(),
                )
                .values(status="partial", finished_at=dt.datetime.now(dt.UTC))
            )
            conn.commit()
            return len(outcomes)
        except Exception as exc:
            conn.rollback()
            conn.execute(
                update(pipeline_runs)
                .where(pipeline_runs.c.id == run_id)
                .values(
                    status="failed", finished_at=dt.datetime.now(dt.UTC), error=type(exc).__name__
                )
            )
            conn.commit()
            raise
        finally:
            conn.execute(
                text("SELECT pg_advisory_unlock(hashtextextended(:key,76))"), {"key": lock}
            )
            conn.commit()


def analysis_task(settings: Settings, trade_date: str, user_id: str | None = None) -> int:
    return phase(settings, ANALYZE, trade_date, user_id)


def report_task(settings: Settings, trade_date: str, user_id: str | None = None) -> int:
    return phase(settings, REPORT, trade_date, user_id)


def recover_task(settings: Settings, user_id: str | None = None) -> int:
    from app.workers.jobs import _engine, _push, _redis

    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
    with _engine(settings).connect() as conn:
        rows = conn.execute(
            select(
                pipeline_runs.c.id,
                pipeline_runs.c.step,
                pipeline_runs.c.run_date,
                pipeline_runs.c.stats,
            )
            .where(
                pipeline_runs.c.step.in_(
                    [
                        "tb76." + ANALYZE,
                        "tb76." + REPORT,
                        "tb76.intent." + ANALYZE,
                        "tb76.intent." + REPORT,
                    ]
                ),
                pipeline_runs.c.status == "running",
                pipeline_runs.c.started_at < cutoff,
            )
            .distinct()
        ).all()
    redis = _redis(settings)
    try:
        count = 0
        for row in rows:
            key = "tb76:recover:" + str(row.id)
            if redis.set(key, 1, nx=True, ex=3600):
                _push(
                    redis,
                    row.step.removeprefix("tb76.").removeprefix("intent."),
                    {
                        "trade_date": str(row.run_date),
                        **(
                            {"user_id": row.stats["user_id"]}
                            if (row.stats or {}).get("user_id")
                            else {}
                        ),
                    },
                )
                count += 1
        return count
    finally:
        redis.close()


def final_failure(settings: Settings, args: dict[str, Any], exc: BaseException) -> None:
    # phase() persisted the non-sensitive exception type; no payload/error-line logging.
    return None


def record_intent(settings: Settings, task: str, date: str) -> None:
    from app.workers.jobs import _engine

    with _engine(settings).begin() as conn:
        key = "tb76.intent:" + task + ":" + date
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,76))"), {"key": key})
        existing = conn.execute(
            select(pipeline_runs.c.id).where(
                pipeline_runs.c.kind == "daily_batch",
                pipeline_runs.c.step == "tb76.intent." + task,
                pipeline_runs.c.run_date == dt.date.fromisoformat(date),
            )
        ).first()
        if existing is None:
            conn.execute(
                insert(pipeline_runs).values(
                    id=uuid.uuid4(),
                    kind="daily_batch",
                    step="tb76.intent." + task,
                    run_date=dt.date.fromisoformat(date),
                    status="running",
                )
            )
