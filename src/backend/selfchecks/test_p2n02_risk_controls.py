"""Only fictional identities and four authorized synthetic symbols; Unix DB/Redis.

Provision network=none p2n02-isolated-pg/redis explicitly; no live tests or API calls.
DeepSeek draft returned empty: discarded, all assertions derived locally from contract.
"""

# ruff: noqa: S101, S108, ANN401
from __future__ import annotations

import copy
import datetime as dt
import secrets
import socket
import uuid
from argparse import Namespace
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from psycopg import sql
from pydantic import SecretStr, ValidationError
from sqlalchemy import create_engine, func, insert, select, text

from app.config import Settings
from app.db.tables.accounts import (
    accounts,
    broker_position_snapshot_items,
    broker_position_snapshots,
    import_batches,
)
from app.db.tables.market import securities
from app.db.tables.strategy import risk_control_settings_history, risk_events
from app.db.tables.users import users
from app.main import create_app
from app.risk.evaluation import Inputs, assessed, inputs
from app.risk.events import record
from app.schemas.enums import Action, Horizon
from app.signals.models import Stops
from app.suggestions.risk import CONTROL_FIELDS, evaluate_risk
from selfchecks.test_ta15_risk import CHINEXT, STAR, context
from selfchecks.test_ta15_risk import config as hook_config
from selfchecks.test_tb89_full_migrations import deploy_grants

ROOT = Path(__file__).resolve().parents[3]
SOCKET = "/tmp/tb70-p2n02-pg-socket"
REDIS = "unix:///tmp/p2n02-redis/redis.sock?db=0"
CODES = ("688018.SH", "688073.SH", "300364.SZ", "301218.SZ")
EMPTY = Stops(stop_loss=None, take_profit=None, time_stop_days=None)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    original = socket.socket.connect

    def guarded(sock: socket.socket, address: Any) -> Any:
        assert sock.family == socket.AF_UNIX, "P2N02 permits dedicated Unix sockets only"
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture(scope="module")
def database() -> Iterator[str]:
    if not Path(SOCKET + "/.s.PGSQL.5432").exists():
        pytest.skip("dedicated networkless PostgreSQL socket not provisioned")
    name = "tb70_p2n02_" + uuid.uuid4().hex
    url = "postgresql+psycopg://postgres@/" + name + "?host=" + SOCKET
    with psycopg.connect(dbname="postgres", user="postgres", host=SOCKET, autocommit=True) as admin:
        assert admin.execute("SHOW listen_addresses").fetchone() == ("",)
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            cfg = Config()
            cfg.set_main_option("script_location", str(ROOT / "src/backend/migrations"))
            cfg.cmd_opts = Namespace(x=["url=" + url])
            command.upgrade(cfg, "head")
            owner = create_engine(url)
            with owner.begin() as conn:
                deploy_grants(conn)
                for code in CODES:
                    conn.execute(
                        insert(securities).values(
                            code=code,
                            name="纯合成标的",
                            type="stock",
                            exchange=code[-2:],
                            board="star" if code in CODES[:2] else "chinext",
                            listing_status="listed",
                        )
                    )
            owner.dispose()
            yield url.replace("postgres@", "aia_api@")
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def env(database: str, tmp_path: Path) -> Iterator[Any]:
    settings = Settings(
        _env_file=None,
        database_url=SecretStr(database),
        redis_url=REDIS,
        app_env="test",
        app_master_key=SecretStr(secrets.token_urlsafe(32)),
        session_cookie_secure=False,
        import_storage_path=tmp_path,
    )
    engine = create_engine(database, hide_parameters=True)
    clients = [TestClient(create_app(settings)), TestClient(create_app(settings))]
    ids = [uuid.uuid4(), uuid.uuid4()]
    password = secrets.token_urlsafe(24) + "7a"
    for uid, client in zip(ids, clients, strict=True):
        username = "synthetic_" + uid.hex[:16]
        with engine.begin() as conn:
            conn.execute(
                insert(users).values(
                    id=uid,
                    username=username,
                    display_name="纯合成",
                    password_hash=PasswordHasher().hash(password),
                    role="user",
                    status="approved",
                )
            )
        response = client.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )
        assert response.status_code == 200
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    yield engine, clients[0], clients[1], ids[0], ids[1], settings
    for client in clients:
        client.close()
    engine.dispose()


def patch(control: str, params: dict[str, Any], enabled: bool = True) -> dict[str, Any]:
    return {"control": control, "enabled": enabled, "params": params}


def count(conn: Any, table: Any, owner: uuid.UUID) -> int:
    return int(
        conn.execute(
            select(func.count()).select_from(table).where(table.c.user_id == owner)
        ).scalar_one()
    )


def test_six_defaults_strict_atomic_partial_and_history(env: Any) -> None:
    engine, client, stranger, owner, _, _ = env
    original = client.get("/api/v1/risk-controls").json()
    assert [r["control"] for r in original] == list(CONTROL_FIELDS)
    assert all(r["source"] == "system" for r in original)
    assert all(set(r["default"]) == set(r["params"]) for r in original)
    assert original[1]["default"] == {"single_position_max_pct": "20"}
    valid = patch("position_cap", {"single_position_max_pct": "21.25"})
    result = client.put("/api/v1/risk-controls", json=[valid])
    assert result.status_code == 200, result.text
    assert result.json()[1]["params"]["single_position_max_pct"] == "21.25"
    assert result.json()[1]["source"] == "user"
    assert result.json()[1]["default"] == original[1]["default"]
    assert result.json()[0] == original[0]
    assert stranger.get("/api/v1/risk-controls").json() == original
    for body, expected in [
        ([valid, valid], 400),
        ([patch("position_cap", {"single_position_max_pct": 20})], 400),
        ([patch("position_cap", {"single_position_max_pct": "20", "unknown": 1})], 400),
        (
            [
                patch("position_cap", {"single_position_max_pct": "25"}),
                patch(
                    "stop_take",
                    {"long_horizon_default_stop_pct": "-4", "clamp_to_price_limit": True},
                ),
            ],
            422,
        ),
        ([patch("position_cap", {"single_position_max_pct": "21.250"})], 422),
        ([patch("position_cap", {"single_position_max_pct": "NaN"})], 400),
    ]:
        failed = client.put("/api/v1/risk-controls", json=body)
        assert failed.status_code == expected, failed.text
        if expected == 422:
            assert failed.json()["error"]["details"]["fields"]
    assert client.get("/api/v1/risk-controls").json() == result.json()
    assert client.put("/api/v1/risk-controls", json=[valid]).status_code == 200
    with engine.connect() as conn:
        assert count(conn, risk_control_settings_history, owner) == 1
        assert conn.execute(text("SELECT current_user")).scalar_one() == "aia_api"


# All numeric rows are exactly T-A25's bounds; no guessed investment thresholds.
BOUNDS = [
    ("stop_take", "long_horizon_default_stop_pct", "-50", "-5", "-50.01", "-4.99"),
    ("position_cap", "single_position_max_pct", "5", "50", "4.99", "50.01"),
    ("total_exposure", "regime_confirm_days", 1, 5, 0, 6),
    ("sector_concentration", "sw_l1_max_pct", "10", "100", "9.99", "100.01"),
    ("sector_concentration", "concept_max_pct", "10", "100", "9.99", "100.01"),
    ("loss_streak_drawdown", "closed_loss_streak", 2, 10, 1, 11),
    ("loss_streak_drawdown", "drawdown_from_peak_pct", "3", "50", "2.99", "50.01"),
    ("loss_streak_drawdown", "strategy_sim_fail_streak", 3, 20, 2, 21),
    ("loss_streak_drawdown", "pause_days", 1, 20, 0, 21),
]


def test_all_ta25_boundaries_and_rc5_settings_without_gates(env: Any) -> None:
    _, client, _, _, _, _ = env
    defaults = {r["control"]: r for r in client.get("/api/v1/risk-controls").json()}
    for control, key, lo, hi, below, above in BOUNDS:
        for value, status in [(lo, 200), (hi, 200), (below, 422), (above, 422)]:
            row = copy.deepcopy(defaults[control])
            row.pop("source")
            row.pop("default")
            row["params"][key] = value
            response = client.put("/api/v1/risk-controls", json=[row])
            assert response.status_code == status, (control, key, response.text)
    for ranges, status in [
        ({"uptrend": ["0", "100"], "range": ["0.25", "99.75"], "downtrend": ["0", "0"]}, 200),
        ({"uptrend": ["90", "60"], "range": ["40", "60"], "downtrend": ["0", "30"]}, 422),
    ]:
        response = client.put(
            "/api/v1/risk-controls",
            json=[patch("total_exposure", {"regime_ranges": ranges, "regime_confirm_days": 2})],
        )
        assert response.status_code == status, response.text
    body = client.get("/api/v1/risk-controls/evaluation?security_code=688018.SH").json()
    assert body["controls"][4]["state"] == "unknown"
    assert body["controls"][4]["flags"] == []
    assert body["controls"][5]["state"] == "unknown"


def account(
    conn: Any, owner: uuid.UUID, *, cash: Decimal | None = None, qty: int = 200
) -> uuid.UUID:
    aid, batch, sid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    at = dt.datetime.now(dt.UTC) - dt.timedelta(days=2)
    conn.execute(insert(accounts).values(id=aid, user_id=owner, name="虚构账户", created_at=at))
    conn.execute(
        insert(import_batches).values(
            id=batch, user_id=owner, account_id=aid, status="committed", kind="positions"
        )
    )
    conn.execute(
        insert(broker_position_snapshots).values(
            id=sid,
            account_id=aid,
            import_batch_id=batch,
            cash_balance=cash,
            version_no=1,
            as_of=at,
            created_at=at,
        )
    )
    conn.execute(
        insert(broker_position_snapshot_items).values(
            id=uuid.uuid4(),
            snapshot_id=sid,
            security_code=CODES[0],
            quantity=qty,
            broker_cost_price=Decimal("8"),
            last_price_ref=Decimal("10"),
        )
    )
    return aid


def test_evaluation_real_ownership_unknown_cash_readonly_and_disabled(env: Any) -> None:
    engine, client, stranger, owner, other, settings = env
    with engine.begin() as conn:
        aid = account(conn, owner)
        foreign = account(conn, other, cash=Decimal("8000"))
    endpoint = "/api/v1/risk-controls/evaluation?security_code=688018.SH"
    assert client.get(endpoint + "&account_id=" + str(foreign)).status_code == 404
    assert stranger.get(endpoint + "&account_id=" + str(aid)).status_code == 404
    with TestClient(create_app(settings)) as anon:
        assert anon.get(endpoint).status_code == 401
    for _ in range(2):
        response = client.get(endpoint)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["account_id"] == str(aid)
        assert body["snapshot_id"] is None
        assert body["controls"][1]["state"] == "unknown"
        assert body["controls"][2]["state"] == "unknown"
        assert body["controls"][3]["state"] == "unknown"
        assert body["data_status"] == "partial"
        assert all(
            not f["gated_actions"] and f["quantity_cap"] is None
            for c in body["controls"]
            for f in c["flags"]
        )
        assert "cash" in {g["key"] for g in body["gaps"]}
        assert "market_regime" in {g["key"] for g in body["gaps"]}
    row = client.get("/api/v1/risk-controls").json()[0]
    row.pop("source")
    row.pop("default")
    row["enabled"] = False
    assert client.put("/api/v1/risk-controls", json=[row]).status_code == 200
    disabled = client.get(endpoint).json()["controls"][0]
    assert disabled["state"] == "disabled"
    assert disabled["flags"]
    assert disabled["flags"][0]["gated_actions"] == []
    with engine.connect() as conn:
        assert count(conn, risk_events, owner) == 0
        source = inputs(conn, owner, CODES[0], aid, settings, dt.datetime.now(dt.UTC))
        assert "total_assets" not in source.context.observations
        assert source.context.sector_memberships is None


@pytest.mark.parametrize("action", [Action.BUY, Action.ADD, Action.SELL, Action.REDUCE])
def test_decimal_lots_rc2_rc3_rc4_action_set(action: Action) -> None:
    for field in ["rc2_position_cap", "rc3_total_exposure", "rc4_sector_concentration"]:
        cfg = hook_config(field)
        ctx = context(total="90000", sector="45")
        ctx.observations["security_value"] = ctx.observations["total_value"].model_copy(
            update={"id": "synthetic:security_value", "key": "security_value", "value": "30000"}
        )
        result = evaluate_risk(
            cfg, ctx, action=action, horizon=Horizon.SWING, stops=EMPTY, lot=STAR
        )
        flags = [
            f
            for f in result.flags
            if f.control == list(CONTROL_FIELDS)[list(CONTROL_FIELDS.values()).index(field)]
        ]
        assert bool(any(f.gated_actions for f in flags)) == (action in {Action.BUY, Action.ADD})
    cfg = hook_config("rc2_position_cap")
    ctx = context()
    ctx.observations["security_value"] = ctx.observations["total_value"].model_copy(
        update={"id": "synthetic:security_value", "key": "security_value", "value": "18010"}
    )
    result = evaluate_risk(
        cfg, ctx, action=Action.BUY, horizon=Horizon.SWING, stops=EMPTY, lot=CHINEXT
    )
    assert result.quantity_cap == 100


def test_rc1_prices_clamp_null_time_stop_gap_and_rc4_hundred() -> None:
    cfg = hook_config("rc1_stop_take")
    ctx = context()
    for key, value in [("limit_down_price", "8"), ("limit_up_price", "12")]:
        ctx.observations[key] = ctx.observations["price"].model_copy(
            update={"id": "synthetic:" + key, "key": key, "value": value}
        )
    source = Inputs(None, ctx, STAR, True, [])
    result, controls = assessed(
        cfg,
        source,
        action=Action.HOLD,
        horizon=Horizon.LONG,
        stops=Stops(stop_loss=Decimal("6"), take_profit=Decimal("15"), time_stop_days=10),
        at=dt.datetime.now(dt.UTC),
    )
    assert (result.stops.stop_loss, result.stops.take_profit, result.stops.time_stop_days) == (
        Decimal("8"),
        Decimal("12"),
        10,
    )
    assert controls[0]["state"] == "unknown"
    assert "rc1.holding_segment_start" in {g["key"] for g in controls[0]["gaps"]}
    del ctx.observations["limit_up_price"]
    assert (
        "limit_up_price"
        in evaluate_risk(
            cfg, ctx, action=Action.HOLD, horizon=Horizon.LONG, stops=result.stops
        ).gaps
    )
    cfg4 = hook_config("rc4_sector_concentration")
    raw4 = cfg4.model_dump()
    raw4["rc4_sector_concentration"]["sw_l1_max_pct"] = Decimal(100)
    cfg4 = type(cfg4).model_validate(raw4)
    assert not evaluate_risk(
        cfg4, context(sector="100"), action=Action.BUY, horizon=Horizon.SWING, stops=EMPTY, lot=STAR
    ).flags
    # Startup defaults are validated by the same models, not user-editable bounds.
    raw = Settings(_env_file=None).business.risk_controls.model_dump()
    raw["rc5_loss_streak_drawdown"]["pause_days"] = 21
    with pytest.raises(ValidationError):
        type(cfg4).model_validate(raw)


def test_business_event_append_idempotence_clear_unknown_and_user_cursor(env: Any) -> None:
    engine, client, stranger, owner, _, _ = env
    at = dt.datetime.now(dt.UTC)
    cfg = hook_config("rc3_total_exposure")
    result, controls = assessed(
        cfg,
        Inputs(None, context(), STAR, True, []),
        action=Action.BUY,
        horizon=Horizon.SWING,
        stops=EMPTY,
        at=at,
    )
    kwargs = {
        "owner": owner,
        "account_id": None,
        "instance_id": uuid.uuid4(),
        "code": CODES[0],
        "name": "虚构标的",
        "controls": controls,
        "evidence": [e.model_dump(mode="json") for e in result.evidence],
        "at": at,
    }
    with engine.begin() as conn:
        record(conn, **kwargs)
        record(conn, **kwargs)
        assert count(conn, risk_events, owner) == 2  # RC1 disabled warning + RC3
    body = client.get(
        "/api/v1/risk-controls/events?status=active&control=total_exposure&limit=1"
    ).json()
    assert len(body["items"]) == 1
    assert stranger.get("/api/v1/risk-controls/events?status=active").json()["items"] == []
    original = body["items"][0]
    rc3 = controls[2]
    rc3.update(state="unknown", flags=[])
    with engine.begin() as conn:
        record(conn, **kwargs)
        assert count(conn, risk_events, owner) == 2
    rc3["state"] = "ok"
    with engine.begin() as conn:
        record(conn, **{**kwargs, "at": at + dt.timedelta(seconds=1)})
        assert count(conn, risk_events, owner) == 3
    cleared = client.get(
        "/api/v1/risk-controls/events?status=cleared&control=total_exposure"
    ).json()["items"]
    assert len(cleared) == 1
    assert cleared[0]["id"] == original["id"]
    assert cleared[0]["triggered_at"] == original["triggered_at"]


def test_real_business_worker_settings_snapshot_events_and_readonly_projection(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.tables.realtime import suggestions
    from app.db.tables.reviews import data_snapshots
    from app.workers.daily import ANALYZE
    from selfchecks import test_tb76_daily as worker_fixture
    from selfchecks.test_tb74_candidates import setup as make_setup
    from selfchecks.test_tb76_assembly import prepare

    engine, client, _, owner, _, settings = env
    setup = make_setup.__wrapped__(env[:5], None)
    instance = prepare(setup)
    from sqlalchemy import update

    from app.db.tables.strategy import feature_catalog, strategy_instances

    with engine.begin() as conn:
        conn.execute(
            update(strategy_instances)
            .where(strategy_instances.c.id == setup[6])
            .values(status="paused", paused_by="user")
        )
        conn.execute(
            insert(feature_catalog).values(
                feature_key="f.close_qfq",
                status="verified_live",
                unit="CNY/share",
                source={"synthetic": True},
            )
        )
    monkeypatch.setattr(worker_fixture, "DB", settings.database_url.get_secret_value())
    monkeypatch.setattr(worker_fixture, "REDIS", REDIS)
    row = client.get("/api/v1/risk-controls").json()[0]
    row.pop("source")
    row.pop("default")
    row["enabled"] = False
    assert client.put("/api/v1/risk-controls", json=[row]).status_code == 200
    from app.workers import jobs

    jobs.TASKS[ANALYZE](settings, trade_date=str(worker_fixture.DATE), user_id=str(owner))
    assert worker_fixture.enqueue(ANALYZE, owner) == [(ANALYZE, "ok"), ("tracking", "ok")]
    with engine.connect() as conn:
        before = count(conn, risk_events, owner)
        assert before >= 1
        produced = conn.execute(select(suggestions).where(suggestions.c.user_id == owner)).one()
        signal = conn.execute(
            select(data_snapshots).where(
                data_snapshots.c.user_id == owner, data_snapshots.c.purpose == "signal"
            )
        ).all()
        source = [r for r in signal if "risk_control_evaluation" in r.items]
        assert source
        assert source[0].items["risk_account_id"] == str(setup[5])
        assert source[0].items["risk_control_evaluation"][0]["state"] == "disabled"
        assert any(s["instance_id"] == str(instance) for s in produced.strategies)
    assert worker_fixture.enqueue(ANALYZE, owner) == [(ANALYZE, "ok"), ("tracking", "ok")]
    evaluation = client.get("/api/v1/risk-controls/evaluation?security_code=688018.SH").json()
    assert evaluation["snapshot_id"] == str(produced.snapshot_id)
    ids = {e["id"] for e in evaluation["evidence"]}
    assert all(set(f["evidence_ids"]) <= ids for c in evaluation["controls"] for f in c["flags"])
    events = client.get("/api/v1/risk-controls/events?status=active&control=stop_take").json()[
        "items"
    ]
    assert len(events) == 1
    assert events[0]["suggestion_id"] == str(produced.id)
    with engine.connect() as conn:
        assert count(conn, risk_events, owner) == before


def test_contract_output_routes_default_schema_and_readonly_evaluation() -> None:
    app = create_app(Settings(_env_file=None, app_env="test"))
    schema = app.openapi()
    paths = schema["paths"]
    assert set(paths["/api/v1/risk-controls"]) == {"get", "put"}
    assert set(paths["/api/v1/risk-controls/evaluation"]) == {"get"}
    assert set(paths["/api/v1/risk-controls/events"]) == {"get"}
    model = schema["components"]["schemas"]["RiskSetting"]
    assert "default" in model["required"]
    assert model["properties"]["default"]["type"] == "object"


def test_f25_declared_null_and_exact_feature_version(env: Any) -> None:
    from sqlalchemy import event

    from app.db.tables.market import feature_bars_daily
    from app.db.tables.strategy import feature_catalog

    engine, _, _, owner, _, settings = env
    at = dt.datetime.now(dt.UTC)
    seen = []

    def capture(
        _conn: Any, _cursor: Any, statement: str, parameters: Any, _context: Any, _many: bool
    ) -> None:
        if "market.feature_bars_daily" in statement:
            seen.append((statement, parameters))

    with engine.begin() as conn:
        aid = account(conn, owner, cash=Decimal("8000"))
        conn.execute(
            insert(feature_catalog).values(
                feature_key="f.market_regime", status="declared", source={"synthetic": True}
            )
        )
        for version, regime in [("synthetic_v1", None), ("synthetic_v2", "uptrend")]:
            conn.execute(
                insert(feature_bars_daily).values(
                    code=CODES[0],
                    trade_date=at.date(),
                    feature_set_version=version,
                    values={"f.market_regime": regime, "f.card_market_regime": "uptrend"},
                    computed_at=at,
                )
            )
        event.listen(engine, "before_cursor_execute", capture)
        try:
            source = inputs(
                conn, owner, CODES[0], aid, settings, at, feature_set_version="synthetic_v1"
            )
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert source.context.regime is None
        assert "market_regime" not in source.context.observations
        assert any(
            "feature_set_version =" in statement and "synthetic_v1" in params.values()
            for statement, params in seen
        )
        result, controls = assessed(
            settings.business.risk_controls,
            source,
            action=Action.BUY,
            horizon=Horizon.SWING,
            stops=EMPTY,
            at=at,
        )
        assert controls[2]["state"] == "unknown"
        assert "market_regime" in result.gaps
        assert not any(f.control == "total_exposure" and f.gated_actions for f in result.flags)
