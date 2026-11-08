"""Slice2 only: real isolated PG transactions, synthetic users/receipts, no network."""

# ruff: noqa: S101, S106, S108, PT012, ANN401, E501
from __future__ import annotations

import datetime as dt
import json
import uuid
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
import yaml
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine, insert, select, text, update

from app.aggregates.calendar import seed_calendar
from app.common.errors import AppError
from app.config_files import RiskControlsConfig
from app.db.tables.accounts import accounts
from app.db.tables.market import securities, trading_calendar
from app.db.tables.notify import notifications
from app.db.tables.reviews import data_snapshots
from app.db.tables.strategy import (
    risk_control_settings,
    risk_events,
    strategies,
    strategy_instance_events,
    strategy_instances,
    strategy_versions,
)
from app.db.tables.users import users
from app.feedback.core import (
    Fill,
    NavPoint,
    Observation,
    account_drawdown,
    closed_losses,
    simulated_failures,
)
from app.feedback.pause import INPUT, apply_receipt, digest, pause_until, resume_due
from app.reference_files import CalendarReference, load_reference_file
from app.strategy.instances.service import operate
from app.strategy.instances.state import InstanceOp
from app.suggestions.risk import effective_config
from app.workers.assembly import persist
from selfchecks.test_tb89_full_migrations import deploy_grants

ROOT = Path(__file__).resolve().parents[3]
SOCKET = "/tmp/tb70-p2n08s2-owned-pg"
TZ = dt.timezone(dt.timedelta(hours=8))
BASE = dt.datetime(2026, 11, 2, 9, tzinfo=TZ)
GOLDEN = json.loads((ROOT / "docs/strategies/golden/P2N-R08_golden.json").read_text())["cases"]
OPERANDS = json.loads((Path(__file__).parent / "fixtures/p2n08_operands.json").read_text())


def cases(suffix: str) -> list[Any]:
    r = next(r for r in GOLDEN if r["id"].endswith(suffix))
    return list(zip(r["input"]["scenarios"], r["expected"]["results"], strict=True))


def actual_config() -> RiskControlsConfig:
    return RiskControlsConfig.model_validate(
        yaml.safe_load((ROOT / "config/risk_controls.yaml").read_text())
    )


@pytest.fixture
def pg() -> Any:
    name = "tb70_p2n08s2_" + uuid.uuid4().hex
    url = "postgresql+psycopg://postgres@/" + name + "?host=" + SOCKET
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "src/backend/migrations"))
    cfg.cmd_opts = Namespace(x=["url=" + url])
    with psycopg.connect(dbname="postgres", user="postgres", host=SOCKET, autocommit=True) as admin:
        assert admin.execute("SHOW listen_addresses").fetchone() == ("",)
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        root = create_engine(url, hide_parameters=True)
        api = None
        try:
            command.upgrade(cfg, "head")
            with root.begin() as c:
                deploy_grants(c)
            api = create_engine(url.replace("postgres@", "aia_api@"), hide_parameters=True)
            yield root, api
        finally:
            if api is not None:
                api.dispose()
            root.dispose()
            admin.execute(
                sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS false").format(sql.Identifier(name))
            )
            admin.execute(
                "SELECT pg_terminate_backend(pid,5000) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()",
                (name,),
            ).fetchall()
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def env(pg: Any) -> Any:
    root, api = pg
    owner, other, account, template, version, instance = [uuid.uuid4() for _ in range(6)]
    with root.begin() as c:
        for uid in [owner, other]:
            c.execute(
                insert(users).values(
                    id=uid,
                    username="fake_" + uid.hex[:16],
                    password_hash="synthetic-non-authenticating-hash",
                    role="user",
                    status="approved",
                    created_at=BASE - dt.timedelta(days=1),
                )
            )
        c.execute(
            insert(accounts).values(
                id=account, user_id=owner, name="纯虚构账户", created_at=BASE - dt.timedelta(days=1)
            )
        )
        c.execute(
            insert(securities).values(
                code="688018.SH",
                name="合成",
                type="stock",
                exchange="SH",
                board="star",
                listing_status="listed",
            )
        )
        c.execute(
            insert(strategies).values(
                id=template,
                key="synthetic_" + template.hex,
                name="仅虚构状态机模板",
                owner_user_id=None,
                horizons=["short"],
            )
        )
        c.execute(
            insert(strategy_versions).values(
                id=version,
                strategy_id=template,
                version_no=1,
                config={"synthetic": True},
                config_hash=template.hex,
                lifecycle="published",
                param_hash=template.hex,
                created_at=BASE - dt.timedelta(days=1),
            )
        )
        c.execute(
            insert(strategy_instances).values(
                id=instance,
                user_id=owner,
                strategy_version_id=version,
                scope="security",
                security_code="688018.SH",
                account_id=account,
                status="active",
                origin="user",
                horizon="short",
                created_at=BASE - dt.timedelta(days=1),
                updated_at=BASE - dt.timedelta(days=1),
            )
        )
        seed = load_reference_file(ROOT / "config", "trading_calendar.json")
        assert isinstance(seed, CalendarReference)
        seed_calendar(c, seed)
    return root, api, owner, other, account, version, instance


def receipt(
    env: Any,
    at: dt.datetime,
    losses: int,
    *,
    failures: int = 0,
    drawdown: str = "0",
    owner_override: uuid.UUID | None = None,
    corrupt_hash: bool = False,
) -> uuid.UUID:
    _, api, owner, _, account, version, instance = env
    with api.connect() as c:
        cfg = effective_config(c, owner, actual_config()).rc5_loss_streak_drawdown
    fills = []
    for i in range(losses):
        point = at - dt.timedelta(minutes=30 - i * 2)
        fills.extend(
            [
                Fill(
                    owner,
                    account,
                    "688018.SH",
                    uuid.uuid4(),
                    point,
                    point,
                    "buy",
                    Decimal(200),
                    Decimal(10),
                    Decimal(1),
                    (f"b{i}",),
                ),
                Fill(
                    owner,
                    account,
                    "688018.SH",
                    uuid.uuid4(),
                    point + dt.timedelta(seconds=1),
                    point + dt.timedelta(seconds=1),
                    "sell",
                    Decimal(200),
                    Decimal(10),
                    Decimal(0),
                    (f"s{i}",),
                ),
            ]
        )
    closed = closed_losses(owner, account, fills, cfg, at=at).metric
    observations = [
        Observation(
            owner,
            version,
            uuid.uuid4(),
            instance,
            BASE - dt.timedelta(days=1),
            "short",
            cfg.sim_fail_horizon_by_horizon["short"],
            "complete",
            failures == 0,
            at - dt.timedelta(minutes=i),
            at,
            (f"sim{i}",),
        )
        for i in range(max(1, failures))
    ]
    sim = simulated_failures(owner, version, observations, cfg, version_horizon="short", at=at)
    nav = account_drawdown(
        owner,
        account,
        [
            NavPoint(
                owner,
                account,
                at - dt.timedelta(days=1),
                at - dt.timedelta(days=1),
                Decimal(100),
                ("peak",),
            ),
            NavPoint(owner, account, at, at, Decimal(100) - Decimal(drawdown), ("nav",)),
        ],
        cfg,
        at=at,
        complete_history=True,
    )
    metrics = {}
    evidence = []
    for key, result in [
        ("closed_loss_streak", closed),
        ("drawdown_from_peak_pct", nav),
        ("strategy_sim_fail_streak", sim),
    ]:
        ident = "synthetic:" + key
        metrics[key] = {
            "value": str(result.value) if result.value is not None else None,
            "evidence_ids": [ident],
            "gaps": list(result.gaps),
        }
        evidence.append(
            {
                "id": ident,
                "key": key,
                "value": str(result.value),
                "unit": "pct" if key == "drawdown_from_peak_pct" else "count",
                "provider": "system",
                "endpoint": "synthetic:RC5-core",
                "data_as_of": at.isoformat(),
                "fetched_at": at.isoformat(),
                "epistemic_type": "estimate",
            }
        )
    items = {
        "schema": INPUT,
        "user_id": str(owner),
        "account_id": str(account),
        "instance_id": str(instance),
        "strategy_version_id": str(version),
        "as_of": at.isoformat(),
        "policy_hash": digest(cfg.model_dump(mode="json")),
        "metrics": metrics,
        "evidence": evidence,
    }
    sid = uuid.uuid4()
    with api.begin() as c:
        if corrupt_hash:
            c.execute(
                insert(data_snapshots).values(
                    id=sid,
                    user_id=owner,
                    purpose="signal",
                    hash="invalid-synthetic-hash",
                    items=items,
                    created_at=at,
                )
            )
        else:
            persist(c, owner_override or owner, sid, items, at)
    return sid


def apply(env: Any, sid: uuid.UUID, at: dt.datetime) -> Any:
    with env[1].begin() as c:
        return apply_receipt(c, env[2], env[6], sid, actual_config(), now=at)


def counts(env: Any) -> tuple[int, int, int]:
    with env[1].connect() as c:
        return tuple(
            c.execute(select(text("count(*)")).select_from(t)).scalar_one()
            for t in [risk_events, strategy_instance_events, notifications]
        )


def state(env: Any) -> Any:
    with env[1].connect() as c:
        return c.execute(select(strategy_instances).where(strategy_instances.c.id == env[6])).one()


@pytest.mark.parametrize(("case", "expected"), cases("-086"))
def test_golden_086_calendar_boundary(case: Any, expected: Any) -> None:
    open_days = {dt.date.fromisoformat(d) for d in case["calendar"]}
    calendar = {}
    if open_days:
        date = min(open_days)
        while date <= max(open_days):
            calendar[date] = date in open_days
            date += dt.timedelta(days=1)
    end = pause_until(dt.datetime.fromisoformat(case["trigger_at"]), case["pause_days"], calendar)
    assert (end.isoformat() if end else None) == expected["paused_until"]


def test_actual_config_keys_and_missing_closed() -> None:
    cfg = actual_config()
    assert cfg.rc5_loss_streak_drawdown.sim_fail_horizon_by_horizon == {
        "intraday_t": 1,
        "short": 5,
        "swing": 20,
        "long": 20,
    }
    assert cfg.health.internal_recover_ratio == Decimal(".8")
    owner, version = uuid.uuid4(), uuid.uuid4()
    for horizon, days in (("intraday_t", 1), ("short", 5), ("swing", 20), ("long", 20)):
        observation = Observation(
            owner,
            version,
            uuid.uuid4(),
            None,
            None,
            horizon,
            days,
            "complete",
            False,
            BASE,
            BASE,
            ("synthetic-evidence",),
        )
        assert (
            simulated_failures(
                owner,
                version,
                [observation],
                cfg.rc5_loss_streak_drawdown,
                version_horizon=None,
                at=BASE,
            ).value
            == 1
        )
        assert (
            simulated_failures(
                owner,
                version,
                [replace(observation, horizon_days=2)],
                cfg.rc5_loss_streak_drawdown,
                version_horizon=None,
                at=BASE,
            ).value
            == 0
        )


def test_real_pause_cursor_replay_manual_and_exact_expiry(env: Any) -> None:
    cfg = actual_config()
    with env[1].connect() as c:
        assert c.execute(text("SELECT current_user")).scalar_one() == "aia_api"
        assert not c.execute(
            text("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
        ).scalar_one()
    first = receipt(env, BASE, 2)
    assert not apply(env, first, BASE).changed
    point = BASE + dt.timedelta(days=1, hours=1)
    sid = receipt(env, point, 3)
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: apply(env, sid, point), range(5)))
    assert sum(r.changed for r in results) == 1
    row = state(env)
    assert (row.status, row.paused_by, row.pause_reason_code) == (
        "paused",
        "system",
        "LOSS_STREAK_PAUSE",
    )
    assert row.paused_until == dt.datetime(2026, 11, 10, 15, tzinfo=TZ)
    for operand in OPERANDS:
        at = point + dt.timedelta(seconds=operand["index"] * 100 + abs(operand["delta"]))
        assert not apply(env, receipt(env, at, 3), at).changed
    assert counts(env)[1:] == (1, 0)
    with env[1].begin() as c:
        event_row = c.execute(select(strategy_instance_events)).one()
        assert event_row.at == point
        assert event_row.detail["detail"]["snapshot_id"] == str(sid)
        operate(c, env[2], env[6], InstanceOp.PAUSE)
        assert c.execute(select(strategy_instances.c.paused_by)).scalar_one() == "system"
        operate(c, env[2], env[6], InstanceOp.RESUME)
    assert (state(env).status, state(env).paused_until, state(env).pause_reason_code) == (
        "active",
        None,
        None,
    )
    assert not apply(env, sid, point).changed
    # A fresh unchanged observation cannot re-pause a manual resume.
    later = dt.datetime(2026, 11, 9, 10, tzinfo=TZ)
    assert not apply(env, receipt(env, later, 3), later).changed
    new = later + dt.timedelta(minutes=1)
    assert apply(env, receipt(env, new, 4), new).changed
    until = state(env).paused_until
    with env[1].begin() as c:
        assert not resume_due(
            c, env[2], env[6], cfg, now=until - dt.timedelta(microseconds=1)
        ).changed
    with env[1].begin() as c:
        assert resume_due(c, env[2], env[6], cfg, now=until).resumed
    after = counts(env)
    with env[1].begin() as c:
        assert not resume_due(c, env[2], env[6], cfg, now=until + dt.timedelta(days=1)).changed
    assert counts(env) == after
    assert not apply(
        env, receipt(env, until + dt.timedelta(minutes=1), 4), until + dt.timedelta(minutes=1)
    ).changed
    assert state(env).status == "active"


@pytest.mark.parametrize(("case", "expected"), cases("-092"))
def test_golden_092_actual_db_restore_guard(env: Any, case: Any, expected: Any) -> None:
    apply(env, receipt(env, BASE, 2), BASE)
    point = BASE + dt.timedelta(hours=1)
    assert apply(env, receipt(env, point, 3), point).changed
    with env[0].begin() as c:
        c.execute(
            update(strategy_versions)
            .where(strategy_versions.c.id == env[5])
            .values(lifecycle=case["lifecycle"])
        )
        if not case["calendar_available"]:
            c.execute(trading_calendar.delete())
    now = dt.datetime.fromisoformat(case["now"])
    with env[1].begin() as c:
        result = resume_due(c, env[2], env[6], actual_config(), now=now)
    row = state(env)
    assert row.status == expected["status"]
    assert row.paused_until == (
        dt.datetime.fromisoformat(expected["paused_until"]) if expected["paused_until"] else None
    )
    assert row.pause_reason_code == expected["reason"]
    assert result.blocked == expected["expiry_blocked"]
    assert bool(result.gaps) == expected["gap"]
    assert counts(env)[2] == int(expected["blocked_notification_required"])
    before = counts(env)
    with env[1].begin() as c:
        assert not resume_due(c, env[2], env[6], actual_config(), now=now).changed
    assert counts(env) == before
    if result.blocked:
        with env[1].connect() as c:
            events = c.execute(
                select(strategy_instance_events).order_by(strategy_instance_events.c.at)
            ).all()
            assert events[-1].detail["actor"] == "system"
            assert events[-1].detail["detail"] == expected["system_event_detail"]
            assert events[-1].at == now


def test_scope_missing_config_source_hash_calendar_and_transaction_rollback(env: Any) -> None:
    cfg = actual_config()
    sid = receipt(env, BASE, 2)
    with pytest.raises(AppError), env[1].begin() as c:
        apply_receipt(c, env[3], env[6], sid, cfg, now=BASE)
    corrupt = receipt(env, BASE, 2, corrupt_hash=True)
    with pytest.raises(ValueError, match="rc5_receipt_hash_invalid"), env[1].begin() as c:
        apply_receipt(c, env[2], env[6], corrupt, cfg, now=BASE)
    foreign = receipt(env, BASE, 2, owner_override=env[3])
    with pytest.raises(AppError), env[1].begin() as c:
        apply_receipt(c, env[2], env[6], foreign, cfg, now=BASE)
    missing = cfg.model_copy(
        update={
            "rc5_loss_streak_drawdown": cfg.rc5_loss_streak_drawdown.model_copy(
                update={"sim_fail_horizon_by_horizon": None}
            )
        }
    )
    with env[1].begin() as c:
        assert apply_receipt(c, env[2], env[6], sid, missing, now=BASE).gaps == (
            "sim_fail_horizon_config_missing",
        )
    assert counts(env) == (0, 0, 0)
    assert not apply(env, sid, BASE).changed
    point = BASE + dt.timedelta(hours=1)
    edge = receipt(env, point, 3)
    with pytest.raises(RuntimeError, match="synthetic rollback"), env[1].begin() as c:
        assert apply_receipt(c, env[2], env[6], edge, cfg, now=point).changed
        raise RuntimeError("synthetic rollback")
    assert counts(env) == (1, 0, 0)
    assert state(env).status == "active"
    with env[0].begin() as c:
        c.execute(trading_calendar.delete())
    before = counts(env)
    assert apply(env, edge, point).gaps == ("calendar_not_covered",)
    assert counts(env) == before
    assert state(env).status == "active"
    # A user's pause remains authoritative even with no calendar available.
    with env[1].begin() as c:
        operate(c, env[2], env[6], InstanceOp.PAUSE)
    later = dt.datetime(2026, 11, 9, 10, tzinfo=TZ)
    user_edge = receipt(env, later, 3)
    result = apply(env, user_edge, later)
    assert not result.changed
    assert not result.gaps
    assert state(env).paused_by == "user"
    with env[1].begin() as c:
        assert not resume_due(c, env[2], env[6], cfg, now=later).changed
        operate(c, env[2], env[6], InstanceOp.RESUME)
    assert not apply(env, user_edge, later).changed
    # A disabled control consumes observations, never fabricates a pending pause.
    with env[0].begin() as c:
        c.execute(
            insert(risk_control_settings).values(
                scope="user",
                user_id=env[2],
                control="loss_streak_drawdown",
                enabled=False,
                params={},
            )
        )
    later += dt.timedelta(minutes=1)
    assert not apply(env, receipt(env, later, 4), later).changed
    with env[0].begin() as c:
        c.execute(
            update(risk_control_settings)
            .where(risk_control_settings.c.user_id == env[2])
            .values(enabled=True)
        )
    later += dt.timedelta(minutes=1)
    assert not apply(env, receipt(env, later, 4), later).changed
    assert state(env).status == "active"


def test_count_extension_drawdown_crossing_and_max_not_additive(env: Any) -> None:
    apply(env, receipt(env, BASE, 2), BASE)
    first = BASE + dt.timedelta(hours=1)
    assert apply(env, receipt(env, first, 3), first).changed
    original = state(env).paused_until
    # A user shortening future pauses cannot shorten an already running term.
    with env[0].begin() as c:
        c.execute(
            insert(risk_control_settings).values(
                scope="user",
                user_id=env[2],
                control="loss_streak_drawdown",
                enabled=True,
                params={"pause_days": 1},
            )
        )
    second = BASE + dt.timedelta(days=1)
    result = apply(env, receipt(env, second, 4), second)
    assert result.edge
    assert not result.changed
    assert state(env).paused_until == original
    # Return future terms to five days; a new count increase extends to max,
    # never existing_until + N days.
    with env[0].begin() as c:
        c.execute(
            update(risk_control_settings)
            .where(risk_control_settings.c.user_id == env[2])
            .values(params={"pause_days": 5})
        )
    third = BASE + dt.timedelta(days=2)
    assert apply(env, receipt(env, third, 5), third).changed
    assert state(env).paused_until == dt.datetime(2026, 11, 11, 15, tzinfo=TZ)
    # Drawdown is a crossing, not every increase above the already-hit cap.
    fourth = BASE + dt.timedelta(days=3)
    assert apply(env, receipt(env, fourth, 5, drawdown="10"), fourth).changed
    until = state(env).paused_until
    fifth = BASE + dt.timedelta(days=4)
    assert not apply(env, receipt(env, fifth, 5, drawdown="12"), fifth).changed
    assert state(env).paused_until == until
