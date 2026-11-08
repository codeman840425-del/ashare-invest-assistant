"""T-B91 closing only: actual isolated API/PG; all inputs synthetic."""

# ruff: noqa: S101, ANN401, F811
from __future__ import annotations

import datetime as dt
import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import insert, select, update

from app.db.tables.research import action_plans, plan_versions
from app.db.tables.signals import candidate_signals, non_executable_reasons, plan_drafts
from app.db.tables.strategy import strategy_instances
from app.plans.budgets import BudgetUnknownError, allocations
from app.schemas.enums import Action
from selfchecks import test_tb74_candidates as producer
from selfchecks import test_tb91_fixes as old91
from selfchecks.test_tb91_fixes import database, env, no_network  # noqa: F401


@pytest.fixture
def buy_fixture(env: Any, monkeypatch: Any, request: Any) -> Any:
    action = getattr(request, "param", "buy")
    _engine, client, *_ = env
    response = client.put(
        "/api/v1/risk-controls",
        json=[
            {
                "control": "position_cap",
                "enabled": False,
                "params": {"single_position_max_pct": "20"},
            }
        ],
    )
    assert response.status_code == 200, response.text
    if action == "no_stop":
        action = "buy"
        cfg = next(
            r for r in client.get("/api/v1/risk-controls").json() if r["control"] == "stop_take"
        )
        response = client.put(
            "/api/v1/risk-controls",
            json=[{"control": "stop_take", "enabled": False, "params": cfg["params"]}],
        )
        assert response.status_code == 200, response.text
        actual_stops = old91.Stops
        monkeypatch.setattr(
            old91,
            "Stops",
            lambda **_: actual_stops(stop_loss=None, take_profit=None, time_stop_days=None),
        )
    original = producer.signal

    def supplied(_action: str, code: str = "688018.SH") -> Any:
        value = original("buy", code)
        return value.model_copy(update={"proposed_action": Action(action)})

    monkeypatch.setattr(producer, "signal", supplied)
    return old91.generated_draft.__wrapped__(env)


@pytest.mark.parametrize("buy_fixture", ["buy", "add"], indirect=True)
def test_actual_buy_add_null_budget_to_confirmation_and_number(buy_fixture: Any) -> None:
    env, draft, answer = buy_fixture
    engine, client, other, owner, *_ = env
    assert draft["action"] in {"buy", "add"}
    assert draft["user_context_snapshot"]["budget_amount"] is None
    assert Decimal(draft["max_loss_amount"]) > 0
    with engine.connect() as conn:
        signal = conn.execute(
            select(candidate_signals).where(
                candidate_signals.c.id == uuid.UUID(draft["signal_ids"][0])
            )
        ).one()
        instance = conn.execute(
            select(strategy_instances).where(strategy_instances.c.id == signal.instance_id)
        ).one()
    detail = client.get("/api/v1/candidate-signals/" + str(signal.id))
    assert detail.status_code == 200, detail.text
    assert isinstance(detail.json()["confidence"]["value"], (int, float))
    assert not isinstance(detail.json()["confidence"]["value"], str)
    path = "/api/v1/plan-drafts/" + draft["id"] + "/confirm"
    assert other.post(path, json=answer).status_code == 404
    success = client.post(path, json=answer)
    assert success.status_code == 201, success.text
    assert client.post(path, json=answer).json() == success.json()
    with engine.begin() as conn:
        conn.execute(
            update(strategy_instances)
            .where(strategy_instances.c.id == instance.id)
            .values(budget_amount=100000)
        )
        refreshed = conn.execute(
            select(strategy_instances).where(strategy_instances.c.id == instance.id)
        ).one()
        used = allocations(conn, owner, [refreshed], dt.datetime.now(dt.UTC))
        with pytest.raises(BudgetUnknownError, match="budget_instance_owner"):
            allocations(conn, uuid.uuid4(), [refreshed], dt.datetime.now(dt.UTC))
        assert used[0]["plan_ids"] == [success.json()["plan_id"]]
        assert Decimal(used[0]["budget_used"]) == Decimal(answer["chosen_qty"]) * Decimal(
            answer["chosen_price"]
        )
        plan = conn.execute(
            select(action_plans).where(action_plans.c.id == uuid.UUID(success.json()["plan_id"]))
        ).one()
        version = conn.execute(
            select(plan_versions).where(plan_versions.c.id == plan.current_version_id)
        ).one()
        assert set(version.completeness["candidate_signal_ids"]) == set(draft["signal_ids"])


def test_simulating_owned_409_unknown_other_uniform_400(buy_fixture: Any) -> None:
    env, draft, _ = buy_fixture
    engine, client, other, *_ = env
    with engine.begin() as conn:
        from app.db.tables.strategy import strategy_versions

        version = conn.execute(
            select(candidate_signals.c.strategy_version_id).where(
                candidate_signals.c.id == uuid.UUID(draft["signal_ids"][0])
            )
        ).scalar_one()
        conn.execute(
            update(strategy_versions)
            .where(strategy_versions.c.id == version)
            .values(lifecycle="simulating")
        )
    request = {"signal_ids": draft["signal_ids"]}
    result = client.post("/api/v1/plan-drafts", json=request)
    assert result.status_code == 409, result.text
    assert result.json()["error"]["code"] == "STRATEGY_VERSION_NOT_RUNNABLE"
    a = other.post("/api/v1/plan-drafts", json=request)
    b = other.post("/api/v1/plan-drafts", json={"signal_ids": [str(uuid.uuid4())]})
    assert a.status_code == b.status_code == 400
    assert a.json()["error"]["details"] == b.json()["error"]["details"]


def test_budget_exhausted_reason_commit_and_recheck(buy_fixture: Any) -> None:
    env, draft, answer = buy_fixture
    engine, client, _, owner, *_ = env
    with engine.begin() as conn:
        iid = conn.execute(
            select(candidate_signals.c.instance_id).where(
                candidate_signals.c.id == uuid.UUID(draft["signal_ids"][0])
            )
        ).scalar_one()
        conn.execute(
            update(strategy_instances).where(strategy_instances.c.id == iid).values(budget_amount=0)
        )
    result = client.post("/api/v1/plan-drafts", json={"signal_ids": draft["signal_ids"]})
    assert result.status_code == 409, result.text
    assert result.json()["error"]["code"] == "SIGNAL_NOT_EXECUTABLE"
    reasons = result.json()["error"]["details"]["reason_ids"]
    with engine.begin() as conn:
        rows = conn.execute(
            select(non_executable_reasons).where(
                non_executable_reasons.c.id.in_([uuid.UUID(x) for x in reasons])
            )
        ).all()
        assert rows
        assert all(r.user_id == owner and r.code == "STRATEGY_BUDGET_EXHAUSTED" for r in rows)
        conn.execute(
            update(strategy_instances)
            .where(strategy_instances.c.id == iid)
            .values(budget_amount=None)
        )
    retry = client.post("/api/v1/plan-drafts", json={"signal_ids": draft["signal_ids"]})
    assert retry.status_code == 201, retry.text
    with engine.begin() as conn:
        conn.execute(
            update(strategy_instances)
            .where(strategy_instances.c.id == iid)
            .values(budget_amount=100000)
        )
    chosen = retry.json()
    answer["chosen_qty"] = chosen["qty_range"]["min"]
    answer["checklist_answers"] = [
        {"id": q["id"], "answer": "yes", "note": None} for q in chosen["judgment_checklist"]
    ]
    stale = client.post("/api/v1/plan-drafts/" + chosen["id"] + "/confirm", json=answer)
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["code"] == "PLAN_DRAFT_STALE"


def test_budget_multi_full_allocation_latest_unknown_and_stale(buy_fixture: Any) -> None:
    env, draft, answer = buy_fixture
    engine, client, other, owner, other_id, _ = env
    with engine.begin() as conn:
        first = conn.execute(
            select(candidate_signals).where(
                candidate_signals.c.id == uuid.UUID(draft["signal_ids"][0])
            )
        ).one()
        inst = conn.execute(
            select(strategy_instances).where(strategy_instances.c.id == first.instance_id)
        ).one()
        second_id = uuid.uuid4()
        values = dict(inst._mapping)
        values.update(id=second_id, budget_amount=6000)
        conn.execute(
            update(strategy_instances)
            .where(strategy_instances.c.id == inst.id)
            .values(budget_amount=8000)
        )
        conn.execute(insert(strategy_instances).values(**values))
        content = producer.signal("buy").model_copy(
            update={
                "snapshot_id": uuid.uuid4(),
                "valid_until": dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
                "stops": old91.Stops(
                    stop_loss=Decimal(22), take_profit=Decimal(28), time_stop_days=5
                ),
            }
        )
    setup = (
        engine,
        client,
        other,
        owner,
        other_id,
        inst.account_id,
        second_id,
        inst.strategy_version_id,
        None,
    )
    new = producer.persist(setup, content)
    combined = client.post(
        "/api/v1/plan-drafts", json={"signal_ids": [draft["signal_ids"][0], new["id"]]}
    )
    assert combined.status_code == 201, combined.text
    merged = combined.json()
    maximum = Decimal(merged["qty_range"]["max"])
    high = Decimal(merged["price_range"]["high"])
    assert maximum * high <= 6000
    assert (maximum + 1) * high > 6000
    answer["checklist_answers"] = [
        {"id": q["id"], "answer": "yes", "note": None} for q in merged["judgment_checklist"]
    ]
    answer["chosen_qty"] = merged["qty_range"]["min"]
    over = dict(
        answer, chosen_qty=merged["qty_range"]["max"], chosen_price="30", deviation_ack=True
    )
    denied = client.post("/api/v1/plan-drafts/" + merged["id"] + "/confirm", json=over)
    assert denied.status_code == 400, denied.text
    assert denied.json()["error"]["details"]["fields"][0]["issue"] == "strategy_budget_exceeded"
    approved = client.post("/api/v1/plan-drafts/" + merged["id"] + "/confirm", json=answer)
    assert approved.status_code == 201, approved.text
    with engine.begin() as conn:
        conn.execute(
            update(strategy_instances)
            .where(strategy_instances.c.id == inst.id)
            .values(budget_amount=100000)
        )
        both = conn.execute(
            select(strategy_instances).where(strategy_instances.c.id.in_([inst.id, second_id]))
        ).all()
        rows = allocations(conn, owner, both, dt.datetime.now(dt.UTC))
        expected = Decimal(answer["chosen_qty"]) * Decimal(answer["chosen_price"])
        assert len(rows) == 2
        assert all(Decimal(r["budget_used"]) == expected for r in rows)
        plan = conn.execute(
            select(action_plans).where(action_plans.c.id == uuid.UUID(approved.json()["plan_id"]))
        ).one()
        previous = conn.execute(
            select(plan_versions).where(plan_versions.c.id == plan.current_version_id)
        ).one()
        payload = dict(previous.completeness)
        payload.update(qty=None, price=None)
        clone = dict(previous._mapping)
        clone.update(
            id=uuid.uuid4(),
            version_no=2,
            completeness=payload,
            size_amount=None,
            created_at=dt.datetime.now(dt.UTC),
        )
        conn.execute(insert(plan_versions).values(**clone))
        conn.execute(
            update(action_plans)
            .where(action_plans.c.id == plan.id)
            .values(current_version_id=clone["id"])
        )
        with pytest.raises(BudgetUnknownError):
            allocations(conn, owner, both, dt.datetime.now(dt.UTC))
        operands = json.loads((Path(__file__).parent / "fixtures/tb91_operands.json").read_text())
        assert len(operands) == 24
        fallback_amount = Decimal(operands[0]["last"]) * 100
        assert fallback_amount.is_finite()
        assert fallback_amount > 0
        fallback = dict(clone)
        fallback.update(
            id=uuid.uuid4(),
            version_no=3,
            size_amount=fallback_amount,
            created_at=dt.datetime.now(dt.UTC),
        )
        conn.execute(insert(plan_versions).values(**fallback))
        conn.execute(
            update(action_plans)
            .where(action_plans.c.id == plan.id)
            .values(current_version_id=fallback["id"])
        )
        amounts = allocations(conn, owner, both, dt.datetime.now(dt.UTC))
        assert all(Decimal(r["budget_used"]) == fallback_amount for r in amounts)
    stale = client.post("/api/v1/plan-drafts/" + draft["id"] + "/confirm", json=answer)
    assert stale.status_code == 409, stale.text


def test_missing_quote_refuses_without_plan(buy_fixture: Any) -> None:
    env, draft, _ = buy_fixture
    engine, client, _, owner, *_ = env
    with engine.begin() as conn:
        from app.db.tables.licences import user_data_licences

        conn.execute(
            update(user_data_licences)
            .where(user_data_licences.c.user_id == owner)
            .values(status="paused_by_admin")
        )
        before = conn.execute(select(plan_drafts.c.id).where(plan_drafts.c.user_id == owner)).all()
    result = client.post("/api/v1/plan-drafts", json={"signal_ids": draft["signal_ids"]})
    assert result.status_code == 503, result.text
    assert "owned_raw_quote" in result.json()["error"]["details"]["gaps"]
    with engine.connect() as conn:
        assert (
            conn.execute(select(plan_drafts.c.id).where(plan_drafts.c.user_id == owner)).all()
            == before
        )


@pytest.mark.parametrize("buy_fixture", ["no_stop"], indirect=True)
def test_rc1_disabled_null_loss_and_positive_below_lot_budget(buy_fixture: Any) -> None:
    env, draft, _ = buy_fixture
    engine, client, _, _, *_ = env
    cfg = next(r for r in client.get("/api/v1/risk-controls").json() if r["control"] == "stop_take")
    update_body = {"control": "stop_take", "enabled": False, "params": cfg["params"]}
    response = client.put("/api/v1/risk-controls", json=[update_body])
    assert response.status_code == 200, response.text
    out = client.post("/api/v1/plan-drafts", json={"signal_ids": draft["signal_ids"]})
    assert out.status_code == 201, out.text
    assert out.json()["max_loss_amount"] is None
    assert out.json()["max_loss_pct"] is None
    assert any(
        f["control"] == "stop_take" and not f["gated_actions"] for f in out.json()["risk_flags"]
    )
    with engine.begin() as conn:
        iid = conn.execute(
            select(candidate_signals.c.instance_id).where(
                candidate_signals.c.id == uuid.UUID(draft["signal_ids"][0])
            )
        ).scalar_one()
        conn.execute(
            update(strategy_instances).where(strategy_instances.c.id == iid).values(budget_amount=1)
        )
    failed = client.post("/api/v1/plan-drafts", json={"signal_ids": draft["signal_ids"]})
    assert failed.status_code == 503, failed.text
    assert "cash_or_quantity_cap_below_minimum" in failed.json()["error"]["details"]["gaps"]


def test_legacy_known_components_null_root_projected_readonly(env: Any) -> None:
    from app.db.tables.realtime import daily_reports
    from app.reports.service import build
    from selfchecks.test_p2n03_tracking import produced
    from selfchecks.test_p2n04_daily_dimensions import DATE, source

    prepared = produced.__wrapped__(env)
    source(prepared, bad_fund=True)
    engine, client, _, owner, *_ = env
    now = dt.datetime.now(dt.UTC)
    with engine.begin() as conn:
        rid = build(conn, owner, DATE, now)
        original = conn.execute(
            select(daily_reports.c.body).where(daily_reports.c.id == rid)
        ).scalar_one()
        known = [
            dt.datetime.fromisoformat(d["data_as_of"])
            for s in original["stocks"]
            for d in s["dimensions"]
            if d["facts"] and d["data_as_of"]
        ]
        assert known
        archived = dict(original, data_as_of=None)
        legacy = uuid.uuid4()
        conn.execute(
            insert(daily_reports).values(
                id=legacy,
                user_id=owner,
                trade_date=DATE,
                revision=100,
                status="partial",
                summary={"input_hash": uuid.uuid4().hex},
                body=archived,
                generated_at=now,
            )
        )
    result = client.get("/api/v1/daily-reports/" + DATE.isoformat())
    assert result.status_code == 200, result.text
    assert dt.datetime.fromisoformat(result.json()["data_as_of"]) == min(known)
    assert result.json()["data_status"] == "partial"
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(daily_reports.c.body).where(daily_reports.c.id == legacy)
            ).scalar_one()
            == archived
        )


def test_unknown_assets_null_pct_not_invented_zero(buy_fixture: Any) -> None:
    from sqlalchemy import delete

    from app.db.tables.accounts import broker_position_snapshot_items as items
    from app.db.tables.accounts import broker_position_snapshots as snapshots
    from app.db.tables.accounts import import_batches
    from app.db.tables.market import daily_bars, realtime_quotes

    env, draft, _ = buy_fixture
    engine, client, _, owner, *_ = env
    now = dt.datetime.now(dt.UTC)
    with engine.begin() as conn:
        instance_id = conn.execute(
            select(candidate_signals.c.instance_id).where(
                candidate_signals.c.id == uuid.UUID(draft["signal_ids"][0])
            )
        ).scalar_one()
        aid = conn.execute(
            select(strategy_instances.c.account_id).where(strategy_instances.c.id == instance_id)
        ).scalar_one()
        previous = conn.execute(select(snapshots).where(snapshots.c.account_id == aid)).one()
        batch, sid = uuid.uuid4(), uuid.uuid4()
        conn.execute(
            insert(import_batches).values(
                id=batch, user_id=owner, account_id=aid, kind="positions", status="committed"
            )
        )
        conn.execute(
            insert(snapshots).values(
                id=sid,
                account_id=aid,
                import_batch_id=batch,
                version_no=2,
                cash_balance=previous.cash_balance,
                as_of=now,
                created_at=now,
            )
        )
        for row in conn.execute(select(items).where(items.c.snapshot_id == previous.id)).all():
            value = dict(row._mapping)
            value.update(id=uuid.uuid4(), snapshot_id=sid)
            conn.execute(insert(items).values(**value))
        conn.execute(
            insert(items).values(
                id=uuid.uuid4(),
                snapshot_id=sid,
                security_code="688073.SH",
                quantity=200,
                sellable_quantity=200,
                broker_cost_price=None,
                last_price_ref=None,
            )
        )
        conn.execute(delete(daily_bars).where(daily_bars.c.code == "688073.SH"))
        conn.execute(delete(realtime_quotes).where(realtime_quotes.c.code == "688073.SH"))
    response = client.post("/api/v1/plan-drafts", json={"signal_ids": draft["signal_ids"]})
    assert response.status_code == 201, response.text
    assert response.json()["max_loss_amount"] is not None
    assert response.json()["max_loss_pct"] is None
    assert any(
        g["key"] == "max_loss_pct" and g["reason"] == "no_source"
        for g in response.json()["user_context_snapshot"]["gaps"]
    )
