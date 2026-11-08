"""Only synthetic identities, receipts and dedicated PostgreSQL/Redis, no provider IO."""

# ruff: noqa: S101, S108, ANN401, F811
from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
import redis
from sqlalchemy import func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.tables.accounts import trades
from app.db.tables.market import trading_calendar
from app.db.tables.research import action_plans
from app.db.tables.reviews import data_snapshots
from app.plans.models import PlanInput
from app.plans.worker import SCHEMA, TASK
from app.workers import jobs
from app.workers.assembly import canonical
from selfchecks import test_p2n03_tracking as base
from selfchecks.test_p2n02_risk_controls import env, no_network  # noqa: F401

AT = dt.datetime(2026, 11, 9, 10, 0, tzinfo=dt.timezone(dt.timedelta(hours=8)))
RECEIPTS = itertools.count()
OPERANDS = json.loads((Path(__file__).parent / "fixtures/p2n07_operands.json").read_text())


@pytest.fixture(scope="module")
def database() -> Any:
    old = base.SOCKET, base.REDIS
    base.SOCKET, base.REDIS = "/tmp/tb70-p2n07-pg-socket", "unix:///tmp/p2n07-redis/redis.sock?db=0"
    try:
        yield from base.database.__wrapped__()
    finally:
        base.SOCKET, base.REDIS = old


def manual(**changes: Any) -> dict[str, Any]:
    return dict(
        security_code="688018.SH",
        account_id=None,
        action="hold",
        rationale="纯合成研究记录",
        risks=None,
        review_date=None,
        conditions=[],
        **changes,
    )


def payload(**changes: Any) -> dict[str, Any]:
    p = manual()
    p.update(changes)
    return p


def run(settings: Any, owner: uuid.UUID, at: dt.datetime = AT + dt.timedelta(seconds=10)) -> Any:
    r = redis.Redis.from_url("unix:///tmp/p2n07-redis/redis.sock?db=0")
    try:
        assert r.llen(jobs.QUEUE_KEY) == 0
        jobs._push(r, TASK, {"user_id": str(owner), "as_of": at.isoformat()})
        return jobs.worker_tick(settings, client=r)
    finally:
        r.close()


def calendar(engine: Any) -> None:
    with engine.begin() as conn:
        stmt = pg_insert(trading_calendar).values(date=AT.date(), is_open=True)
        conn.execute(stmt.on_conflict_do_update(index_elements=["date"], set_={"is_open": True}))


@pytest.mark.parametrize("row", OPERANDS, ids=lambda r: str(r["index"]))
def test_reviewed_public_form_operands(row: dict[str, Any]) -> None:
    p = PlanInput.model_validate(payload(qty=row["qty"], price=row["price"]))
    assert p.qty == row["qty"]
    assert p.price == row["price"]
    assert isinstance(p.price, str)


def test_actual_http_version_worker_alert_idempotence_and_isolation(env: Any) -> None:
    engine, client, other, owner, _, settings = env
    calendar(engine)
    body = payload(
        conditions=[
            {
                "kind": "trigger",
                "type": "date",
                "params": {"on": AT.date().isoformat()},
                "description": "虚构日期验证",
            }
        ]
    )
    created = client.post(
        "/api/v1/plans", json=body, headers={"Idempotency-Key": "synthetic-create"}
    )
    assert created.status_code == 201, created.text
    plan = created.json()
    url = "/api/v1/plans/" + plan["id"]
    assert (
        client.post(
            "/api/v1/plans", json=body, headers={"Idempotency-Key": "synthetic-create"}
        ).json()
        == plan
    )
    assert client.post("/api/v1/plans", json=body).status_code == 409
    assert other.get(url).status_code == 404
    assert other.get("/api/v1/plans").json()["items"] == []
    frozen = client.get(url + "/versions/1").json()
    assert run(settings, owner) == [(TASK, "ok")]
    after = client.get(url).json()
    assert after["status"] == "triggered"
    assert len(after["pending_triggers"]) == 1
    alert = client.get("/api/v1/alerts").json()["items"][0]
    assert alert["evidence_ids"]
    assert len(alert["evidence"]) == 1
    assert other.get("/api/v1/alerts/" + alert["id"]).status_code == 404
    assert run(settings, owner) == [(TASK, "ok")]
    assert len(client.get("/api/v1/alerts").json()["items"]) == 1
    assert client.get(url + "/versions/1").json() == frozen
    with engine.connect() as conn:
        before = conn.execute(select(func.count()).select_from(trades)).scalar_one()
    marked = client.patch("/api/v1/alerts/" + alert["id"], json={"status": "acted"})
    assert marked.status_code == 200, marked.text
    assert (
        client.patch("/api/v1/alerts/" + alert["id"], json={"status": "acted"}).json()
        == marked.json()
    )
    assert client.patch("/api/v1/alerts/" + alert["id"], json={"status": "read"}).status_code == 409
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(trades)).scalar_one() == before
    rev = client.post(
        url + "/versions",
        json=dict(body, base_version_no=1, change_reason="纯合成修订"),
        headers={"Idempotency-Key": "synthetic-revise"},
    )
    assert rev.status_code == 201, rev.text
    assert rev.json()["status"] == "active"
    assert rev.json()["pending_triggers"] == []
    assert (
        client.post(
            url + "/versions", json=dict(body, base_version_no=1, change_reason="旧版本冲突")
        ).status_code
        == 409
    )
    assert client.get(url + "/versions/1").json() == frozen
    assert run(settings, owner) == [(TASK, "ok")]
    assert len(client.get("/api/v1/alerts?status=all").json()["items"]) == 2
    assert (
        client.post(url + "/close", json={"status": "done", "note": "虚构结案"}).status_code == 200
    )
    assert client.post(url + "/close", json={"status": "done", "note": None}).status_code == 409
    assert client.get(url).json()["pending_triggers"] == []
    assert (
        client.post(
            url + "/versions", json=dict(body, base_version_no=2, change_reason="终态不可改")
        ).status_code
        == 409
    )


def receipt(engine: Any, owner: uuid.UUID, price: str, **extra: Any) -> uuid.UUID:
    raw = {
        "schema_version": SCHEMA,
        "synthetic": True,
        "security_code": "688073.SH",
        "account_id": None,
        "data_as_of": AT.isoformat(),
        "available_at": AT.isoformat(),
        "expires_at": (AT + dt.timedelta(seconds=30)).isoformat(),
        "price": price,
        "data_status": "fresh",
        "is_suspended": False,
    }
    raw.update(extra)
    identifier = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            insert(data_snapshots).values(
                id=identifier,
                user_id=owner,
                purpose="signal",
                hash=hashlib.sha256(canonical(raw).encode()).hexdigest(),
                items=raw,
                created_at=AT + dt.timedelta(microseconds=next(RECEIPTS)),
            )
        )
    return identifier


def test_real_owned_receipt_price_pit_custom_pct_and_in_app_delivery(env: Any) -> None:
    engine, client, other, owner, stranger, settings = env
    calendar(engine)
    body = payload(
        security_code="688073.SH",
        conditions=[
            {
                "kind": "invalidation",
                "type": "price_below",
                "params": {"price": "10.00"},
                "description": "虚构价格条件",
            },
            {"kind": "trigger", "type": "custom", "params": {}, "description": "只记文字"},
            {
                "kind": "trigger",
                "type": "pct_change",
                "params": {"pct": "-2"},
                "description": "待裁定比较方向",
            },
        ],
    )
    resp = client.post("/api/v1/plans", json=body)
    assert resp.status_code == 201, resp.text
    url = "/api/v1/plans/" + resp.json()["id"]
    receipt(engine, stranger, "9.00")
    assert run(settings, owner) == [(TASK, "ok")]
    assert client.get(url).json()["status"] == "active"
    receipt(engine, owner, "9.00", available_at=(AT + dt.timedelta(seconds=20)).isoformat())
    assert run(settings, owner) == [(TASK, "ok")]
    assert client.get(url).json()["status"] == "active"
    receipt(engine, owner, "10.00")
    assert run(settings, owner) == [(TASK, "ok")]
    assert client.get(url).json()["status"] == "active"
    receipt(engine, owner, "9.99")
    assert run(settings, owner) == [(TASK, "ok")]
    body = client.get(url).json()
    assert body["status"] == "triggered"
    assert len(body["pending_triggers"]) == 1
    assert body["evidence"][0]["value"] == "9.99"
    assert other.get("/api/v1/alerts").json()["items"] == []
    assert client.get("/api/v1/notifications/unread-count").json() == {"count": 1}
    assert run(settings, owner) == [(TASK, "ok")]
    assert len(client.get("/api/v1/alerts").json()["items"]) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"qty": 1},
        {"price": "NaN"},
        {"price": "0"},
        {"rationale": " "},
        {"candidate_id": str(uuid.UUID(int=1))},
        {
            "conditions": [
                {"kind": "trigger", "type": "indicator", "params": {}, "description": "虚构"}
            ]
        },
        {
            "conditions": [
                {
                    "kind": "trigger",
                    "type": "price_above",
                    "params": {"price": "0"},
                    "description": "虚构",
                }
            ]
        },
    ],
)
def test_invalid_inputs_no_plan_writes(env: Any, change: dict[str, Any]) -> None:
    engine, client, _, owner, *_ = env
    with engine.connect() as conn:
        before = conn.execute(
            select(func.count()).select_from(action_plans).where(action_plans.c.user_id == owner)
        ).scalar_one()
    assert client.post("/api/v1/plans", json=payload(**change)).status_code == 400
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(func.count())
                .select_from(action_plans)
                .where(action_plans.c.user_id == owner)
            ).scalar_one()
            == before
        )


def test_unknown_signal_draft_is_400_not_foreign_404(env: Any) -> None:
    _, client, *_ = env
    response = client.post("/api/v1/plan-drafts", json={"signal_ids": [str(uuid.uuid4())]})
    assert response.status_code == 400, response.text
    assert response.json()["error"]["details"]["fields"][0]["issue"] == "not_found"


@pytest.fixture
def draft_seed(env: Any) -> Any:
    from app.api.v1.portfolio import _account
    from app.config_files import MarketRuleSegment
    from app.db.tables.signals import plan_drafts
    from app.db.tables.strategy import market_rule_versions
    from selfchecks import test_tb74_candidates as old

    engine, client, other, owner, stranger, settings = env
    setup = old.setup.__wrapped__((engine, client, other, owner, stranger), None)
    content = old.signal().model_copy(
        update={"valid_until": dt.datetime.now(dt.UTC) + dt.timedelta(days=2)}
    )
    persisted = old.persist(setup, content)
    assert persisted["id"] is not None
    signal_id = uuid.UUID(persisted["id"])
    with engine.begin() as conn:
        now = dt.datetime.now(dt.UTC)
        from app.db.tables.signals import candidate_signals
        from app.signals.service import transition

        signal_row = conn.execute(
            select(candidate_signals).where(candidate_signals.c.id == signal_id)
        ).one()
        transition(conn, signal_row, "drafted", "user", now)
        account = setup[5]
        a = _account(conn, account, now.astimezone(AT.tzinfo).date())
        p = a.positions["688018.SH"]
        ctx = {
            "holding_qty": str(p.qty),
            "sellable_qty": str(p.sellable),
            "cash": str(a.cash),
            "sector_pct": "0",
        }
        segment = settings.business.market_rules.segment_for(now.astimezone(AT.tzinfo).date())
        assert isinstance(segment, MarketRuleSegment)
        rule = conn.execute(
            select(market_rule_versions.c.id).where(
                market_rule_versions.c.effective_from == segment.effective_from
            )
        ).scalar_one_or_none()
        if rule is None:
            rule = uuid.uuid4()
            conn.execute(
                insert(market_rule_versions).values(
                    id=rule,
                    effective_from=segment.effective_from,
                    rules=segment.model_dump(mode="json"),
                )
            )
        raw = {
            "schema_version": "p2n07-draft-input-v1",
            "plan_draft_context": dict(ctx, account_id=str(account), quantity_cap="1000"),
        }
        snap = uuid.uuid4()
        conn.execute(
            insert(data_snapshots).values(
                id=snap,
                user_id=owner,
                purpose="signal",
                hash=hashlib.sha256(canonical(raw).encode()).hexdigest(),
                items=raw,
            )
        )
        identifier = uuid.uuid4()
        conn.execute(
            insert(plan_drafts).values(
                id=identifier,
                user_id=owner,
                signal_ids=[signal_id],
                security_code="688018.SH",
                action="buy",
                qty_range={"min": "200", "max": "400", "lot": "1"},
                price_range={"low": "20", "high": "30"},
                stops={"stop_loss": "18", "take_profit": None, "time_stop_days": None},
                fee_estimate={"amount": "1", "epistemic_type": "estimate"},
                max_loss_amount="100",
                max_loss_pct="1",
                user_context_snapshot=ctx,
                judgment_checklist=[
                    {"id": "fiction", "question": "纯合成人工问题", "required": True}
                ],
                market_rule_version_id=rule,
                snapshot_id=snap,
                expires_at=now + dt.timedelta(hours=1),
            )
        )
    answer = {
        "checklist_answers": [{"id": "fiction", "answer": "yes", "note": None}],
        "risk_ack": True,
        "chosen_qty": "200",
        "chosen_price": "25",
        "deviation_ack": False,
    }
    return env, setup, identifier, signal_id, answer


def test_synthetic_confirmation_atomic_idempotent_lot_cap_checklist_and_freeze(
    draft_seed: Any,
) -> None:
    from app.db.tables.signals import plan_draft_confirmations

    (engine, client, other, _owner, *_), _setup, identifier, signal_id, answer = draft_seed
    url = "/api/v1/plan-drafts/" + str(identifier)
    original = client.get(url).json()
    assert other.get(url).status_code == 404
    assert client.post(url + "/confirm", json=dict(answer, checklist_answers=[])).status_code == 422
    assert client.post(url + "/confirm", json=dict(answer, risk_ack=False)).status_code == 422
    bad = client.post(url + "/confirm", json=dict(answer, chosen_qty="199", deviation_ack=True))
    assert bad.status_code == 400, bad.text
    bad = client.post(url + "/confirm", json=dict(answer, chosen_qty="1001", deviation_ack=True))
    assert bad.status_code == 400, bad.text
    bad = client.post(url + "/confirm", json=dict(answer, chosen_price="31"))
    assert bad.status_code == 422, bad.text
    assert client.get(url).json() == original
    result = client.post(url + "/confirm", json=answer)
    assert result.status_code == 201, result.text
    assert client.post(url + "/confirm", json=answer).json() == result.json()
    assert client.post(url + "/confirm", json=dict(answer, chosen_qty="201")).status_code == 409
    plan = client.get("/api/v1/plans/" + result.json()["plan_id"]).json()
    assert plan["origin"] == "plan_draft"
    assert plan["current_version"]["checklist_answers"][0]["question"] == "纯合成人工问题"
    assert plan["current_version"]["qty"] == "200"
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(func.count())
                .select_from(plan_draft_confirmations)
                .where(plan_draft_confirmations.c.draft_id == identifier)
            ).scalar_one()
            == 1
        )
    saved = client.get(url).json()
    saved["status"] = original["status"]
    assert saved == original

    from app.db.tables.signals import candidate_signal_events, candidate_signals

    with engine.connect() as conn:
        assert (
            conn.execute(
                select(candidate_signals.c.state).where(candidate_signals.c.id == signal_id)
            ).scalar_one()
            == "confirmed"
        )
        assert (
            conn.execute(
                select(func.count())
                .select_from(candidate_signal_events)
                .where(
                    candidate_signal_events.c.signal_id == signal_id,
                    candidate_signal_events.c.to_state == "confirmed",
                )
            ).scalar_one()
            == 1
        )


def test_draft_candidate_priority_simulating_before_block_and_ownership_first(
    draft_seed: Any,
) -> None:
    from sqlalchemy import update

    from app.db.tables.signals import candidate_signals
    from app.db.tables.strategy import strategy_versions

    (engine, client, _, _owner, *_), setup, identifier, signal_id, answer = draft_seed
    with engine.begin() as conn:
        conn.execute(
            update(strategy_versions)
            .where(strategy_versions.c.id == setup[7])
            .values(lifecycle="simulating")
        )
        conn.execute(
            update(candidate_signals)
            .where(candidate_signals.c.id == signal_id)
            .values(state="blocked")
        )
    missing = client.post(
        "/api/v1/plan-drafts", json={"signal_ids": [str(signal_id), str(uuid.uuid4())]}
    )
    assert missing.status_code == 400, missing.text
    r = client.post("/api/v1/plan-drafts", json={"signal_ids": [str(signal_id)]})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "STRATEGY_VERSION_NOT_RUNNABLE"
    assert (
        client.post("/api/v1/plan-drafts/" + str(identifier) + "/confirm", json=answer).status_code
        == 409
    )


def test_close_releases_only_its_machine_checkable_same_direction_reason(env: Any) -> None:
    from app.db.tables.signals import (
        candidate_signals,
        non_executable_reasons,
        reason_status_events,
    )
    from selfchecks import test_tb74_candidates as old

    engine, client, other, owner, stranger, _ = env
    setup = old.setup.__wrapped__((engine, client, other, owner, stranger), None)
    created = client.post("/api/v1/plans", json=payload(action="buy"))
    assert created.status_code == 201, created.text
    written = old.persist(setup, old.signal())
    assert written["id"] is not None
    sid = uuid.UUID(written["id"])
    with engine.connect() as conn:
        reasons = conn.execute(
            select(non_executable_reasons).where(
                non_executable_reasons.c.signal_id == sid,
                non_executable_reasons.c.code == "SAME_DIRECTION_PLAN_EXISTS",
            )
        ).all()
        assert len(reasons) == 1
        rid = reasons[0].id
    response = client.post(
        "/api/v1/plans/" + created.json()["id"] + "/close",
        json={"status": "cancelled", "note": None},
    )
    assert response.status_code == 200, response.text
    with engine.connect() as conn:
        r = conn.execute(
            select(non_executable_reasons).where(non_executable_reasons.c.id == rid)
        ).one()
        assert r.status == "released"
        assert r.released_by == "system"
        assert (
            conn.execute(
                select(func.count())
                .select_from(reason_status_events)
                .where(
                    reason_status_events.c.reason_id == rid,
                    reason_status_events.c.to_status == "released",
                )
            ).scalar_one()
            == 1
        )
        assert (
            conn.execute(
                select(candidate_signals.c.state).where(candidate_signals.c.id == sid)
            ).scalar_one()
            == "released"
        )


def test_concurrent_manual_duplicate_and_version_conflict_are_serialized(env: Any) -> None:
    from concurrent.futures import ThreadPoolExecutor

    _, client, _, _, *_ = env
    p = payload(security_code="300364.SZ")
    with ThreadPoolExecutor(max_workers=2) as executor:
        answers = list(executor.map(lambda _: client.post("/api/v1/plans", json=p), range(2)))
    assert sorted(r.status_code for r in answers) == [201, 409]
    plan = next(r.json() for r in answers if r.status_code == 201)
    url = "/api/v1/plans/" + plan["id"] + "/versions"
    v = dict(p, base_version_no=1, change_reason="虚构并发修订")
    with ThreadPoolExecutor(max_workers=2) as executor:
        answers = list(executor.map(lambda _: client.post(url, json=v), range(2)))
    assert sorted(r.status_code for r in answers) == [201, 409]
    assert client.get(url).json()["items"][0]["version_no"] == 2


@pytest.mark.parametrize(
    ("price", "expected"), [("9.99", False), ("10.00", False), ("10.01", True)]
)
def test_price_above_strict_boundary_and_assessment_receipt(
    env: Any, price: str, expected: bool
) -> None:
    engine, client, _, owner, _, settings = env
    calendar(engine)
    response = client.post(
        "/api/v1/plans",
        json=payload(
            security_code="688073.SH",
            conditions=[
                {
                    "kind": "trigger",
                    "type": "price_above",
                    "params": {"price": "10.00"},
                    "description": "纯合成边界",
                }
            ],
        ),
    )
    assert response.status_code == 201, response.text
    snapshot = receipt(engine, owner, price)
    assert run(settings, owner) == [(TASK, "ok")]
    p = client.get("/api/v1/plans/" + response.json()["id"]).json()
    assert (p["status"] == "triggered") is expected
    with engine.connect() as conn:
        stored = conn.execute(
            select(data_snapshots.c["items"]).where(
                data_snapshots.c.user_id == owner,
                data_snapshots.c.purpose == "plan",
                data_snapshots.c["items"]["schema_version"].astext
                == "p2n07-condition-assessment-v1",
            )
        ).scalar_one()
        assert stored["observations"][0]["passed"] is expected
        assert stored["observations"][0]["source_snapshot_id"] == str(snapshot)


def test_confirmation_cash_and_expiry_failures_never_write_plan(draft_seed: Any) -> None:
    from sqlalchemy import update

    from app.db.tables.signals import plan_drafts

    (engine, client, _, owner, *_), _setup, identifier, _, answer = draft_seed
    url = "/api/v1/plan-drafts/" + str(identifier) + "/confirm"
    response = client.post(url, json=dict(answer, chosen_price="99999999", deviation_ack=True))
    assert response.status_code == 400, response.text
    with engine.begin() as conn:
        assert (
            conn.execute(
                select(func.count())
                .select_from(action_plans)
                .where(action_plans.c.user_id == owner)
            ).scalar_one()
            == 0
        )
        conn.execute(
            update(plan_drafts).where(plan_drafts.c.id == identifier).values(status="expired")
        )
    response = client.post(url, json=answer)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "PLAN_DRAFT_STALE"


def test_changed_holdings_cash_stales_draft_with_immutable_old_snapshot(draft_seed: Any) -> None:
    from app.db.tables.accounts import broker_position_snapshots

    (engine, client, _, owner, *_), setup, identifier, _, answer = draft_seed
    with engine.begin() as conn:
        prior = conn.execute(
            select(broker_position_snapshots).where(broker_position_snapshots.c.id == setup[8])
        ).one()
        values = dict(prior._mapping)
        values.update(
            id=uuid.uuid4(),
            version_no=2,
            as_of=dt.datetime.now(dt.UTC),
            created_at=dt.datetime.now(dt.UTC),
            cash_balance=prior.cash_balance + 1,
            cash_available=prior.cash_available + 1,
        )
        conn.execute(insert(broker_position_snapshots).values(**values))
    response = client.post("/api/v1/plan-drafts/" + str(identifier) + "/confirm", json=answer)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "PLAN_DRAFT_STALE"
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(func.count())
                .select_from(action_plans)
                .where(action_plans.c.user_id == owner)
            ).scalar_one()
            == 0
        )


def test_draft_mixed_direction_rejected_before_state_gate(draft_seed: Any) -> None:
    from selfchecks import test_tb74_candidates as old

    (_engine, client, _, _owner, *_), setup, _, signal_id, _ = draft_seed
    opposite = old.persist(setup, old.signal("sell"))
    assert opposite["id"] is not None
    result = client.post(
        "/api/v1/plan-drafts", json={"signal_ids": [str(signal_id), opposite["id"]]}
    )
    assert result.status_code == 400, result.text
    assert result.json()["error"]["details"]["fields"][0]["issue"] == "mismatch"


def test_signed_pct_and_custom_unknown_receipt_no_false_trigger(env: Any) -> None:
    engine, client, _, owner, _, settings = env
    calendar(engine)
    response = client.post(
        "/api/v1/plans",
        json=payload(
            conditions=[
                {
                    "kind": "trigger",
                    "type": "pct_change",
                    "params": {"pct": "2"},
                    "description": "待明文定义比较",
                },
                {
                    "kind": "trigger",
                    "type": "custom",
                    "params": {},
                    "description": "纯文字不自动判断",
                },
            ]
        ),
    )
    assert response.status_code == 201, response.text
    assert run(settings, owner) == [(TASK, "ok")]
    assert client.get("/api/v1/plans/" + response.json()["id"]).json()["status"] == "active"
    with engine.connect() as conn:
        raw = conn.execute(
            select(data_snapshots.c["items"]).where(
                data_snapshots.c.user_id == owner, data_snapshots.c.purpose == "plan"
            )
        ).scalar_one()
        assert any(x.endswith(":signed_pct_comparator_undefined") for x in raw["gaps"])
        assert all(o["passed"] is None for o in raw["observations"])
    assert client.get("/api/v1/alerts").json()["items"] == []


def test_plan_list_signed_pagination_owner_scope_and_read_only_versions(env: Any) -> None:
    from fastapi.testclient import TestClient

    engine, client, other, owner, _, _ = env
    for code in ["688018.SH", "300364.SZ", "301218.SZ"]:
        response = client.post("/api/v1/plans", json=payload(security_code=code))
        assert response.status_code == 201, response.text
    first = client.get("/api/v1/plans?limit=1").json()
    assert len(first["items"]) == 1
    assert first["next_cursor"]
    second = client.get("/api/v1/plans", params={"limit": 1, "cursor": first["next_cursor"]})
    assert second.status_code == 200, second.text
    assert second.json()["items"][0]["id"] != first["items"][0]["id"]
    assert other.get("/api/v1/plans", params={"cursor": first["next_cursor"]}).status_code == 400
    with TestClient(client.app) as anonymous:
        assert anonymous.get("/api/v1/plans").status_code == 401
        assert anonymous.post("/api/v1/plans", json={}).status_code == 401
    with engine.connect() as conn:
        rows = conn.execute(select(action_plans).where(action_plans.c.user_id == owner)).all()
    for r in rows:
        assert client.get("/api/v1/plans/" + str(r.id) + "/versions/1").status_code == 200
    with engine.connect() as conn:
        assert (
            conn.execute(select(action_plans).where(action_plans.c.user_id == owner)).all() == rows
        )


def test_production_quote_adapter_refuses_synthetic_receipt_and_unknown_owner(env: Any) -> None:
    from app.db.tables.research import alerts
    from app.plans.worker import check

    engine, client, _, owner, _, settings = env
    calendar(engine)
    body = payload(
        conditions=[
            {
                "kind": "trigger",
                "type": "price_above",
                "params": {"price": "10.0000"},
                "description": "纯合成生产适配缺失边界",
            }
        ]
    )
    response = client.post(
        "/api/v1/plans", json=body, headers={"X-Idempotency-Key": str(uuid.uuid4())}
    )
    assert response.status_code == 201, response.text
    pid = uuid.UUID(response.json()["id"])
    receipt(engine, owner, "11.0000", security_code="688018.SH")
    with pytest.raises(ValueError, match="replay requires"):
        jobs.TASKS[TASK](
            settings.model_copy(update={"app_env": "production"}),
            str(owner),
            (dt.datetime.now(dt.UTC) + dt.timedelta(days=1)).isoformat(),
        )
    assert jobs.TASKS[TASK](settings, str(uuid.uuid4())) == 0
    with engine.begin() as conn:
        result = check(conn, owner, AT + dt.timedelta(seconds=10), app_env="production")
        assert result["triggered"] == []
        assert any("production_quote_adapter_missing" in gap for gap in result["gaps"])
        assert (
            conn.execute(
                select(func.count())
                .select_from(alerts)
                .where(alerts.c.what_happened["plan_id"].astext == str(pid))
            ).scalar_one()
            == 0
        )
        rejected = check(conn, uuid.uuid4(), AT)
        assert rejected["triggered"] == []
        assert rejected["gaps"] == ["user_not_approved"]


def test_draft_no_explainable_true_rule_rejected(draft_seed: Any) -> None:
    from app.db.tables.signals import candidate_signals

    context, _setup, _draft, signal_id, _answer = draft_seed
    engine, client, *_ = context
    with engine.begin() as conn:
        row = dict(
            conn.execute(select(candidate_signals).where(candidate_signals.c.id == signal_id))
            .mappings()
            .one()
        )
        row["id"] = uuid.uuid4()
        row["created_at"] += dt.timedelta(microseconds=1)
        row["rule_refs"] = [dict(ref, passed=False) for ref in row["rule_refs"]]
        conn.execute(insert(candidate_signals).values(**row))
    result = client.post(
        "/api/v1/plan-drafts",
        json={"signal_ids": [str(row["id"])]},
        headers={"X-Idempotency-Key": str(uuid.uuid4())},
    )
    assert result.status_code == 422, result.text
    assert result.json()["error"]["code"] == "PLAN_REQUIRES_EXPLAINABLE_SIGNAL"
    # A delayed expiry worker must never make an already expired signal executable.
    with engine.begin() as conn:
        row["id"] = uuid.uuid4()
        row["created_at"] += dt.timedelta(microseconds=1)
        row["valid_until"] = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
        conn.execute(insert(candidate_signals).values(**row))
    result = client.post("/api/v1/plan-drafts", json={"signal_ids": [str(row["id"])]})
    assert result.status_code == 409, result.text
    assert result.json()["error"]["details"]["from"] == "expired"
