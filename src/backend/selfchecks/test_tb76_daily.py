# ruff: noqa: S101, ANN401, F811
"""Actual isolated queue/DB/HTTP; partial reports are NOT a completed candidate loop."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pytest
import redis
from pydantic import SecretStr
from sqlalchemy import insert, select, update
from sqlalchemy.exc import DBAPIError

from app.common.errors import AppError
from app.config import Settings
from app.db.tables.accounts import broker_position_snapshot_items
from app.db.tables.realtime import daily_reports, pipeline_runs, suggestions
from app.db.tables.research import watchlist_items
from app.db.tables.signals import candidate_signals
from app.db.tables.strategy import (
    strategies,
    strategy_card_versions,
    strategy_cards,
    strategy_instances,
    strategy_versions,
)
from app.engine_policies import load as load_policy
from app.engine_policies import seed
from app.replay.baseline import load
from app.reports.service import build, covered
from app.strategy.runtime import runnable
from app.tracking.worker import TASK as TRACKING
from app.workers import jobs
from app.workers.daily import ANALYZE, REPORT, recover_task
from selfchecks.test_tb70_replay import DB, REDIS, integration, no_network  # noqa: F401
from selfchecks.test_tb74_candidates import AT, ROOT, setup  # noqa: F401

DATE = dt.date(2026, 10, 30)


def settings() -> Settings:
    return Settings(_env_file=None, database_url=SecretStr(DB), redis_url=REDIS, app_env="test")


def enqueue(task: str, owner: uuid.UUID) -> list[tuple[str, str]]:
    r = redis.Redis.from_url(REDIS)
    try:
        assert r.llen(jobs.QUEUE_KEY) == 0
        jobs._push(r, task, {"trade_date": str(DATE), "user_id": str(owner)})
        return jobs.worker_tick(settings(), client=r)
    finally:
        r.close()


def test_real_queue_holdings_calendar_report_http_and_idempotence(
    setup: Any, no_network: Any
) -> None:
    engine, client, stranger, owner, _, _, _, _, snapshot = setup
    with engine.begin() as conn:
        for code in ("688073.SH", "300364.SZ", "301218.SZ"):
            conn.execute(
                insert(broker_position_snapshot_items).values(
                    id=uuid.uuid4(),
                    snapshot_id=snapshot,
                    security_code=code,
                    quantity=400,
                    sellable_quantity=400,
                    broker_cost_price=12,
                    last_price_ref=13,
                )
            )
    assert enqueue(ANALYZE, owner) == [(ANALYZE, "ok"), (TRACKING, "ok")]
    assert enqueue(REPORT, owner) == [(REPORT, "ok")]
    response = client.get("/api/v1/daily-reports/2026-10-30")
    assert response.status_code == 200
    body = response.json()
    assert {s["security_code"] for s in body["stocks"]} == {
        "688018.SH",
        "688073.SH",
        "300364.SZ",
        "301218.SZ",
    }
    assert body["data_status"] == "partial"
    assert body["gaps"]
    assert body["account"]["pnl_day"] is None
    assert all(s["suggestion_id"] is None for s in body["stocks"])
    assert stranger.get("/api/v1/daily-reports/2026-10-30").status_code == 404
    assert stranger.get("/api/v1/daily-reports").json()["items"] == []
    assert client.get("/api/v1/daily-reports").json()["items"][0]["stock_count"] == 4
    assert enqueue(REPORT, owner) == [(REPORT, "ok")]
    with engine.connect() as conn:
        reports = conn.execute(select(daily_reports).where(daily_reports.c.user_id == owner)).all()
        assert len(reports) == 1
        assert reports[0].status == "partial"
    assert not no_network


def test_revision_immutable_building_visibility_signed_pagination(setup: Any) -> None:
    engine, client, stranger, owner, *_ = setup
    with engine.begin() as conn:
        first = build(conn, owner, DATE, AT)
        conn.execute(
            insert(watchlist_items).values(
                id=uuid.uuid4(), user_id=owner, security_code="688073.SH"
            )
        )
        second = build(conn, owner, DATE, AT)
        assert second != first
        conn.execute(
            insert(daily_reports).values(
                id=uuid.uuid4(), user_id=owner, trade_date=DATE, revision=100, status="building"
            )
        )
        build(conn, owner, DATE - dt.timedelta(days=1), AT)
    assert len(client.get("/api/v1/daily-reports/2026-10-30").json()["stocks"]) == 2
    listing = client.get("/api/v1/daily-reports?limit=1").json()
    assert listing["items"][0]["date"] == "2026-10-30"
    assert listing["next_cursor"]
    more = client.get(
        "/api/v1/daily-reports", params={"limit": 1, "cursor": listing["next_cursor"]}
    )
    assert more.json()["items"][0]["date"] == "2026-10-29"
    assert (
        stranger.get("/api/v1/daily-reports", params={"cursor": listing["next_cursor"]}).status_code
        == 400
    )
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(update(daily_reports).where(daily_reports.c.id == first).values(body={}))
    with engine.connect() as conn:
        original = conn.execute(
            select(daily_reports.c.body).where(daily_reports.c.id == first)
        ).scalar_one()
        assert len(original["stocks"]) == 1


def test_true_evaluator_path_records_unassembled_p1_not_fake_suggestions(setup: Any) -> None:
    engine, client, _, owner, _, account, *_ = setup
    card, cardversion, strategy, version, instance = [uuid.uuid4() for _ in range(5)]
    spec = {
        "params_schema": {},
        "rules": [
            {
                "id": key,
                "dimension": "technical",
                "role": role,
                "expr": expr,
                "eval_time": "daily_close",
                "weight": 1,
            }
            for key, role, expr in [
                ("E", "entry", "ma(f.close_qfq,60) > 0"),
                ("X", "exit", "f.close_qfq > 0"),
                ("C", "counter", "f.close_qfq < 0"),
                ("I", "invalidation", "f.close_qfq < 0"),
            ]
        ],
        "action_map": {
            "entry_all_core_pass": "buy",
            "held_hold": "hold",
            "exit": "sell",
            "else": "wait",
        },
        "dimension_view_thresholds": {"bullish": 0.67, "bearish": 0.33},
        "stops": {"stop_loss": None, "take_profit": None, "time_stop_days": 5},
        "valid_until": {"trading_days": 40},
    }
    with engine.begin() as conn:
        load(conn, owner, app_env="test")
        # 自播种引擎策略，使单跑与四文件合跑都出现 evaluated_input_gaps，而不依赖例 1 的 seed()。
        seed(conn, load_policy(ROOT / "config"))
        conn.execute(
            insert(strategy_cards).values(
                id=card,
                key="tb76_fiction_" + card.hex,
                title="明确虚构非正式卡",
                source_kind="user",
                owner_user_id=owner,
            )
        )
        conn.execute(
            insert(strategy_card_versions).values(
                id=cardversion, card_id=card, version_no=1, fields={"mount_policy": "user"}
            )
        )
        conn.execute(
            insert(strategies).values(
                id=strategy,
                key="tb76_fiction_" + strategy.hex,
                name="明确虚构非正式卡",
                owner_user_id=owner,
                horizons=["swing"],
            )
        )
        conn.execute(
            insert(strategy_versions).values(
                id=version,
                strategy_id=strategy,
                card_version_id=cardversion,
                version_no=1,
                config=spec,
                config_hash=version.hex,
                param_hash=version.hex,
                lifecycle="published",
            )
        )
        conn.execute(
            insert(strategy_instances).values(
                id=instance,
                user_id=owner,
                strategy_version_id=version,
                scope="account",
                account_id=account,
                status="active",
                origin="user",
                horizon="swing",
            )
        )
    assert enqueue(ANALYZE, owner) == [(ANALYZE, "ok"), (TRACKING, "ok")]
    with engine.connect() as conn:
        runs = conn.execute(
            select(pipeline_runs)
            .where(pipeline_runs.c.step == "tb76." + ANALYZE)
            .order_by(pipeline_runs.c.started_at.desc())
        ).first()
        outcome = runs.stats["users"][str(owner)]
        assert outcome["evaluations"][0]["state"] == "hold_ok"
        assert outcome["evaluations"][0]["simulation"] is True
        refs = {r["rule_id"]: r for r in outcome["evaluations"][0]["rule_refs"]}
        assert set(refs) == {"E", "X", "C", "I"}
        assert all(refs[key]["passed"] is None for key in ("E", "X", "C", "I"))
        assert "evaluated_input_gaps:688018.SH" in outcome["issues"]
        assert "owned_source_or_card_missing" in outcome["issues"]
        assert (
            len(
                conn.execute(
                    select(candidate_signals).where(candidate_signals.c.instance_id == instance)
                ).all()
            )
            == 0
        )
        actions = [
            strategy["action"]
            for row in conn.execute(select(suggestions).where(suggestions.c.user_id == owner)).all()
            for strategy in (row.strategies or [])
        ]
        assert set(actions).isdisjoint({"buy", "sell", "reduce"})
    assert enqueue(REPORT, owner) == [(REPORT, "ok")]
    response = client.get("/api/v1/daily-reports/2026-10-30")
    assert response.status_code == 200
    assert "pipeline.evaluated_input_gaps:688018.SH" in [
        gap["key"] for gap in response.json()["gaps"]
    ]


def test_runtime_boundary_calendar_and_actual_beat_dedupe(setup: Any) -> None:
    engine, *_ = setup
    assert runnable("simulating", "admin")
    assert not runnable("simulating", "user")
    assert not runnable("draft", "admin")
    with engine.connect() as conn:
        assert covered(conn, DATE)
        with pytest.raises(AppError) as error:
            covered(conn, dt.date(2027, 1, 1))
        assert error.value.details["issue"] == "CALENDAR_NOT_COVERED"
    r = redis.Redis.from_url(REDIS)
    moment = dt.datetime(2026, 10, 30, 9, 30, tzinfo=dt.UTC)
    key = jobs.SLOT_PREFIX + ANALYZE + ":20261030:1730"
    try:
        r.delete(key)
        assert ANALYZE in jobs.beat_slots(settings(), client=r, now=moment)
        assert ANALYZE not in jobs.beat_slots(settings(), client=r, now=moment)
        # Inspect only this task's queue entry, do not start unrelated legacy jobs.
        raw = r.rpop(jobs.QUEUE_KEY)
        assert raw
        assert ANALYZE.encode() in raw
        assert r.llen(jobs.QUEUE_KEY) == 0
    finally:
        r.delete(key)
        r.close()


def test_orphaned_job_recovered_via_real_worker_and_committed_report(setup: Any) -> None:
    engine, client, _, owner, *_ = setup
    orphan = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            insert(pipeline_runs).values(
                id=orphan,
                kind="daily_batch",
                run_date=DATE,
                step="tb76." + REPORT,
                status="running",
                started_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=2),
                stats={"user_id": str(owner)},
            )
        )
    assert recover_task(settings(), user_id=str(owner)) == 1
    r = redis.Redis.from_url(REDIS)
    try:
        assert jobs.worker_tick(settings(), client=r) == [(REPORT, "ok")]
    finally:
        r.close()
    assert client.get("/api/v1/daily-reports/2026-10-30").status_code == 200
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(pipeline_runs.c.status).where(pipeline_runs.c.id == orphan)
            ).scalar_one()
            == "skipped"
        )


def test_existing_suggestion_is_real_owned_report_link_not_fake_engine_acceptance(
    setup: Any,
) -> None:
    from app.db.tables.reviews import data_snapshots
    from app.signals.models import SignalInput
    from app.suggestions.models import SuggestionInput
    from app.suggestions.service import snapshot_items
    from selfchecks.test_tb74_candidates import signal
    from selfchecks.test_tb75_suggestions import conclusion, write

    engine, client, _, owner, *_ = setup
    now = dt.datetime.now(dt.UTC)
    raw = signal("buy").model_dump(mode="json")
    raw.update(created_at=now, valid_until=now + dt.timedelta(hours=1), data_status="stale")
    c = conclusion(setup, override=SignalInput.model_validate(raw))
    content = SuggestionInput.model_validate(
        {
            "security_code": "688018.SH",
            "snapshot_id": uuid.uuid4(),
            "feature_set_version": c.signal.feature_set_version,
            "conclusions": [c],
            "data_status": "stale",
            "data_as_of": AT,
            "gaps": [],
            "suitable": ["swing"],
            "user_overridden": False,
            "created_at": now,
        }
    )
    with engine.begin() as conn:
        conn.execute(
            insert(data_snapshots).values(
                id=content.snapshot_id,
                user_id=owner,
                purpose="signal",
                hash=content.snapshot_id.hex,
                items=snapshot_items(content),
                created_at=now,
            )
        )
    frozen = write(setup, content)["suggestion"]
    with engine.begin() as conn:
        build(conn, owner, DATE, dt.datetime.now(dt.UTC))
    report = client.get("/api/v1/daily-reports/2026-10-30").json()
    assert report["stocks"][0]["suggestion_id"] == frozen["id"]
    assert client.get("/api/v1/suggestions/" + frozen["id"]).status_code == 200
    # Explicitly stale, manually prepared synthetic archive: not engine acceptance.
    assert report["data_status"] == "partial"
