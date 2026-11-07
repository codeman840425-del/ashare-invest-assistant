# ruff: noqa: S101, ANN401, F811
"""Independent T-A16 assertions via real isolated services; formal G2/G6 remain pending.

No P1, candidate, suggestion or report body is hand-assembled. Only fictional cards,
owned cached bars and generated import/watch inputs are supplied to the real workers.
"""

from __future__ import annotations

import copy
import datetime as dt
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pytest
import redis
from sqlalchemy import insert, select, update

from app.aggregates.calendar import seed_calendar
from app.db.tables.realtime import daily_reports, suggestions
from app.db.tables.research import watchlist_items
from app.db.tables.signals import plan_drafts
from app.db.tables.strategy import engine_policies, strategy_instances, strategy_versions
from app.db.tables.users import users
from app.reference_files import CalendarReference, load_reference_file
from app.replay.baseline import positions_file
from app.workers import jobs
from app.workers.daily import ANALYZE, REPORT
from selfchecks.test_tb70_replay import REDIS, integration, no_network  # noqa: F401
from selfchecks.test_tb74_candidates import ROOT
from selfchecks.test_tb76_assembly import prepare
from selfchecks.test_tb76_daily import settings
from selfchecks.test_tb77_products import seed_differences


def run(owner: uuid.UUID, date: str, task: str) -> None:
    client = redis.Redis.from_url(REDIS)
    try:
        assert client.llen(jobs.QUEUE_KEY) == 0
        jobs._push(client, task, {"trade_date": date, "user_id": str(owner)})
        assert jobs.worker_tick(settings(), client=client) == [(task, "ok")]
    finally:
        client.close()


@pytest.fixture
def chain(integration: Any) -> Any:
    engine, client, stranger, owner, other = integration
    response = client.post(
        "/api/v1/accounts", json={"broker_name": "完全虚构券商", "alias": "独立验收"}
    )
    assert response.status_code == 201
    account = uuid.UUID(response.json()["id"])
    # A single generated holding; other universe membership comes from real watch rows.
    content = b"\r\n".join(positions_file().splitlines()[:5]) + b"\r\n"
    response = client.post(
        "/api/v1/imports",
        data={
            "account_id": str(account),
            "kind": "positions",
            "snapshot_as_of": "2026-10-28T07:00:00Z",
        },
        files={"file": ("fictional.txt", content, "text/plain")},
    )
    assert response.status_code == 201
    batch = response.json()["batch_id"]
    preview = client.get("/api/v1/imports/" + batch)
    assert preview.status_code == 200
    assert preview.json()["status"] == "previewed"
    response = client.post(
        "/api/v1/imports/" + batch + "/confirm",
        json={"mode": "all", "acknowledge_warnings": True},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 200
    assert response.json()["written"]["snapshot_positions"] == 1
    assert stranger.get("/api/v1/imports/" + batch).status_code == 404
    with engine.begin() as conn:
        calendar = load_reference_file(ROOT / "config", "trading_calendar.json")
        assert isinstance(calendar, CalendarReference)
        seed_calendar(conn, calendar)
    fixture = (engine, client, stranger, owner, other, account)
    initial = prepare(fixture)
    # prepare supplies only a fictional test card/cache. Mount execution goes through HTTP.
    with engine.connect() as conn:
        source = conn.execute(
            select(strategy_versions)
            .join(
                strategy_instances,
                strategy_instances.c.strategy_version_id == strategy_versions.c.id,
            )
            .where(strategy_instances.c.id == initial)
        ).one()
    assert client.post(f"/api/v1/strategy-instances/{initial}/pause").status_code == 200
    return fixture, source


def mount(
    chain: Any, *, version_no: int, lifecycle: str = "published", exit_expr: str | None = None
) -> str:
    fixture, source = chain
    engine, client, _, owner, _, account = fixture
    identifier = uuid.uuid4()
    spec = copy.deepcopy(source.config)
    if exit_expr:
        next(r for r in spec["rules"] if r["id"] == "X")["expr"] = exit_expr
    with engine.begin() as conn:
        conn.execute(
            insert(strategy_versions).values(
                id=identifier,
                strategy_id=source.strategy_id,
                card_version_id=source.card_version_id,
                version_no=version_no,
                config={"spec": spec, "horizons": ["swing"]},
                config_hash=identifier.hex,
                param_hash=identifier.hex,
                lifecycle=lifecycle,
            )
        )
    payload = {
        "strategy_version_id": str(identifier),
        "scope": "security",
        "account_id": str(account),
        "security_code": "688018.SH",
        "horizon": "swing",
    }
    if lifecycle == "simulating":
        denied = client.post("/api/v1/strategy-instances", json=payload)
        assert denied.status_code == 409
        assert denied.json()["error"]["code"] == "STRATEGY_VERSION_NOT_RUNNABLE"
        with engine.begin() as conn:
            # Only this synthetic user's test role changes; never a formal card/G7 approval.
            conn.execute(update(users).where(users.c.id == owner).values(role="admin"))
    response = client.post("/api/v1/strategy-instances", json=payload)
    assert response.status_code == 201, response.json()
    return str(response.json()["id"])


def confidence_and_policy(engine: Any, owner: uuid.UUID, client: Any) -> None:
    with engine.connect() as conn:
        rows = conn.execute(select(suggestions).where(suggestions.c.user_id == owner)).all()
        assert rows
        for row in rows:
            policy = conn.execute(
                select(engine_policies).where(engine_policies.c.id == row.engine_policy_id)
            ).one()
            body = client.get("/api/v1/suggestions/" + str(row.id)).json()
            assert body["engine_policy"] is not None
            assert body["engine_policy"]["version_no"] == policy.version_no
            assert body["engine_policy"]["content_sha256"] == policy.config["content_sha256"]
            for conclusion in body["strategies"]:
                confidence = conclusion["confidence"]
                components = confidence["components"]
                value = sum(
                    (
                        Decimal(str(components[key] or 0)) * Decimal(weight)
                        for key, weight in [
                            ("data_completeness", ".5"),
                            ("dimension_agreement", ".3"),
                            ("condition_margin", ".2"),
                        ]
                    ),
                    Decimal(0),
                ).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
                assert value == Decimal(str(confidence["value"]))
                assert confidence["level"] == (
                    "high"
                    if value >= Decimal(".7")
                    else "medium"
                    if value >= Decimal(".4")
                    else "low"
                )
                rule_ids = {r["rule_id"] for r in conclusion["rule_refs"]}
                assert all(r["rule_id"] in rule_ids for r in components["margin_rules"])


def test_independent_assertions_one_to_four_real_import_worker_and_cross_day(chain: Any) -> None:
    fixture, _ = chain
    engine, client, _, owner, _, account = fixture
    instance = mount(chain, version_no=2)
    with engine.begin() as conn:
        for code in ["688073.SH", "300364.SZ"]:
            conn.execute(insert(watchlist_items).values(user_id=owner, security_code=code))
    seed_differences(engine, account, dt.datetime.now(dt.UTC))
    for task in [ANALYZE, REPORT]:
        run(owner, "2026-10-29", task)
    response = client.get("/api/v1/daily-reports/2026-10-29")
    assert response.status_code == 200
    first = response.json()
    assert first["stocks"]
    assert all(r["change_from_previous"] is None for r in first["stocks"])
    assert any("previous" in g["key"] for g in first["gaps"])
    assert client.post(f"/api/v1/strategy-instances/{instance}/pause").status_code == 200
    mount(chain, version_no=3, exit_expr="f.close_qfq < 0")
    with engine.begin() as conn:
        conn.execute(
            update(watchlist_items)
            .where(
                watchlist_items.c.user_id == owner, watchlist_items.c.security_code == "300364.SZ"
            )
            .values(removed_at=dt.datetime.now(dt.UTC))
        )
        conn.execute(insert(watchlist_items).values(user_id=owner, security_code="301218.SZ"))
    for task in [ANALYZE, REPORT]:
        run(owner, "2026-10-30", task)
    response = client.get("/api/v1/daily-reports/2026-10-30")
    assert response.status_code == 200
    second = response.json()
    stocks = {r["security_code"]: r for r in second["stocks"]}
    assert stocks["688018.SH"]["change_from_previous"] == "changed"
    assert "actions" in stocks["688018.SH"]["change_fields"]
    assert stocks["688073.SH"]["change_from_previous"] == "unchanged"
    assert stocks["301218.SZ"]["change_from_previous"] == "new"
    assert stocks["300364.SZ"]["change_from_previous"] == "removed"
    assert stocks["300364.SZ"]["suggestion_id"] is None
    confidence_and_policy(engine, owner, client)
    recon = client.get("/api/v1/reconciliation")
    today = client.get("/api/v1/today")
    assert recon.status_code == today.status_code == 200
    important = sum(i["important"] for i in recon.json()["items"])
    assert important == 3
    assert first["reconciliation"]["important_count"] == important
    assert second["reconciliation"]["important_count"] == important
    assert today.json()["reconciliation"]["important_count"] == important
    assert client.get("/api/v1/terminal").status_code == 200
    # Report serialization is persisted, not a mocked HTTP adapter.
    with engine.connect() as conn:
        persisted = conn.execute(
            select(daily_reports.c.body).where(
                daily_reports.c.user_id == owner,
                daily_reports.c.trade_date == dt.date(2026, 10, 30),
            )
        ).scalar_one()
        assert persisted["stocks"] == second["stocks"]


def test_independent_assertion_five_fictional_simulating_visible_without_drafts(chain: Any) -> None:
    fixture, _ = chain
    engine, client, _, owner, *_ = fixture
    mount(chain, version_no=2, lifecycle="simulating")
    run(owner, "2026-10-30", ANALYZE)
    terminal = client.get("/api/v1/terminal")
    today = client.get("/api/v1/today")
    assert terminal.status_code == today.status_code == 200
    row = next(r for r in terminal.json()["rows"] if r["security_code"] == "688018.SH")
    assert row["suggestion"]["actions"][0]["lifecycle"] == "simulating"
    assert (
        today.json()["focus"]["items"][0]["suggestion"]["actions"][0]["lifecycle"] == "simulating"
    )
    assert today.json()["pending_plan_drafts"]["items"] == []
    with engine.connect() as conn:
        assert (
            conn.execute(select(plan_drafts.c.id).where(plan_drafts.c.user_id == owner)).all() == []
        )
    confidence_and_policy(engine, owner, client)


@pytest.mark.parametrize(
    "dependency", ["G2_formal_verified_sources", "G6_formal_history_and_overlap"]
)
def test_formal_system_chain_pending_external_inputs(dependency: str) -> None:
    pytest.skip(
        dependency
        + ": pending orchestrator input integration; no declared upgrade, mock products or agent G7"
    )
