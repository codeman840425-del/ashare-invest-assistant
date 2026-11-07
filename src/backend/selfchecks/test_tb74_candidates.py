# ruff: noqa: S101, ANN401, F811
"""Synthetic producer -> real isolated PostgreSQL -> authenticated HTTP, not mocks."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import func, insert, select, update

from app.aggregates.calendar import seed_calendar
from app.db.tables.accounts import (
    accounts,
    broker_position_snapshot_items,
    broker_position_snapshots,
    import_batches,
)
from app.db.tables.market import securities
from app.db.tables.reviews import data_snapshots
from app.db.tables.signals import candidate_signal_events, candidate_signals
from app.db.tables.strategy import strategies, strategy_instances, strategy_versions
from app.features.evaluation import RuleEvaluator
from app.reference_files import CalendarReference, load_reference_file
from app.signals.models import MarketFacts, SignalInput
from app.signals.service import post_close_for_user, snapshot_items, write_candidate
from selfchecks.test_tb70_replay import integration, no_network  # noqa: F401
from selfchecks.test_tb72_features import REGISTRY, RULES

ROOT = Path(__file__).resolve().parents[3]
AT = dt.datetime(2026, 11, 6, 2, tzinfo=dt.UTC)
ROWS = json.loads((Path(__file__).parent / "fixtures/tb74_synthetic.json").read_text())


SPEC = {
    "params_schema": {},
    "rules": [
        {
            "id": "synthetic-entry",
            "role": "entry",
            "dimension": "technical",
            "eval_time": "daily",
            "expr": "f.close_qfq > 30",
        },
        {
            "id": "synthetic-weakening",
            "role": "weakening",
            "dimension": "technical",
            "eval_time": "daily",
            "expr": "f.close_qfq < 20 and f.close_qfq >= 10",
        },
        {
            "id": "synthetic-exit",
            "role": "exit",
            "dimension": "technical",
            "eval_time": "daily",
            "expr": "f.close_qfq < 10",
        },
        {
            "id": "synthetic-counter",
            "role": "counter",
            "dimension": "technical",
            "eval_time": "daily",
            "expr": "f.close_qfq < 0",
        },
        {
            "id": "synthetic-invalidation",
            "role": "invalidation",
            "dimension": "technical",
            "eval_time": "daily",
            "expr": "f.close_qfq < 1",
        },
    ],
    "action_map": {
        "entry_all_core_pass": "buy",
        "weakening": "reduce",
        "exit": "sell",
        "else": "wait",
    },
}


def signal(action: str = "buy", code: str = "688018.SH") -> SignalInput:
    held = action in {"reduce", "sell"}
    value = {"buy": 40, "reduce": 15, "sell": 5}[action]
    result = RuleEvaluator().evaluate(
        card={},
        spec=SPEC,
        frame={
            "features": {"f.close_qfq": value},
            "series": {},
            "context": {},
            "as_of": AT,
            "data_as_of": AT,
            "gaps": [],
            "feature_set_version": "tb72-pit-1",
        },
        holding={"qty": 300, "sellable": 300} if held else {},
        security={"board": "star"},
        market_rules=RULES,
        registry=REGISTRY,
    )
    return SignalInput.model_validate(
        {
            "security_code": code,
            "proposed_action": result["action"],
            "t_leg": None,
            "score": None,
            "confidence": {"level": "high", "value": "0.8"},
            "stops": {"stop_loss": None, "take_profit": None, "time_stop_days": None},
            "rule_refs": result["rule_refs"],
            "evidence": result["evidence"],
            "counter_evidence": [
                {
                    "text": "虚构反证规则的实际计算结果为false",
                    "expr": "f.close_qfq < 0",
                    "evidence_ids": result["rule_refs"][3]["evidence_ids"],
                }
            ],
            "invalidation": [
                {
                    "text": "虚构失效条件",
                    "expr": "f.close_qfq < 1",
                    "evidence_ids": result["rule_refs"][4]["evidence_ids"],
                }
            ],
            "model_refs": [],
            "risk_flags": [],
            "valid_until": None,
            "snapshot_id": uuid.uuid4(),
            "feature_set_version": "tb72-pit-1",
            "created_at": AT,
            "data_status": "fresh",
            "data_as_of": AT,
            "gaps": [],
        }
    )


@pytest.fixture
def setup(integration: Any, no_network: Any) -> Any:
    engine, client, stranger, owner, other = integration
    account, version, template, instance = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    row = ROWS[0]
    qty = Decimal(row["qty"])
    price = Decimal(row["price"])
    batch, snapshot = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        seed = load_reference_file(ROOT / "config", "trading_calendar.json")
        assert isinstance(seed, CalendarReference)
        seed_calendar(conn, seed)
        conn.execute(insert(accounts).values(id=account, user_id=owner, name="纯合成账户"))
        conn.execute(
            insert(import_batches).values(
                id=batch, user_id=owner, account_id=account, status="committed", kind="positions"
            )
        )
        conn.execute(
            insert(broker_position_snapshots).values(
                id=snapshot,
                account_id=account,
                import_batch_id=batch,
                as_of=AT,
                cash_balance=max(Decimal(row["cash"]), price * 400),
                cash_available=max(Decimal(row["cash"]), price * 400),
                version_no=1,
                created_at=AT,
            )
        )
        conn.execute(
            insert(broker_position_snapshot_items).values(
                id=uuid.uuid4(),
                snapshot_id=snapshot,
                security_code="688018.SH",
                quantity=qty,
                sellable_quantity=qty,
                broker_cost_price=price,
                last_price_ref=price,
            )
        )
        conn.execute(
            insert(strategies).values(
                id=template,
                key="tb74_synthetic_" + template.hex,
                name="纯合成测试模板",
                owner_user_id=owner,
                horizons=["swing"],
            )
        )
        conn.execute(
            insert(strategy_versions).values(
                id=version,
                strategy_id=template,
                version_no=1,
                config={
                    "spec": SPEC,
                    "universe": {
                        "pool": "持仓 ∪ 自选",
                        "boards": {"star": True, "chinext": True},
                        "security_types": ["stock"],
                    },
                },
                config_hash=template.hex,
                lifecycle="published",
                param_hash=template.hex,
            )
        )
        conn.execute(
            insert(strategy_instances).values(
                id=instance,
                user_id=owner,
                strategy_version_id=version,
                scope="security",
                security_code="688018.SH",
                account_id=account,
                status="active",
                origin="user",
                horizon="swing",
            )
        )
    return engine, client, stranger, owner, other, account, instance, version, snapshot


def persist(setup: Any, content: SignalInput, *, facts: MarketFacts | None = None) -> Any:
    engine, _, _, owner, _, _, instance, _, _ = setup
    facts = facts or MarketFacts(
        price=25,
        required_cash=5001,
        is_suspended=False,
        list_days=100,
        limit_locked_up=False,
        limit_locked_down=False,
    )
    with engine.begin() as conn:
        if not conn.execute(
            select(data_snapshots.c.id).where(data_snapshots.c.id == content.snapshot_id)
        ).first():
            conn.execute(
                insert(data_snapshots).values(
                    id=content.snapshot_id,
                    user_id=owner,
                    licence_id=None,
                    purpose="signal",
                    hash=content.snapshot_id.hex,
                    created_at=AT,
                    items=snapshot_items(content, facts),
                )
            )
        return write_candidate(
            conn,
            user_id=owner,
            instance_id=instance,
            content=content,
            facts=facts,
            market_rules=RULES,
        )


@pytest.mark.parametrize("action", ["buy", "reduce", "sell"])
def test_deterministic_paths_idempotency_and_real_routes(setup: Any, action: str) -> None:
    engine, client, stranger, owner, _, _, instance, _, _ = setup
    content = signal(action)
    assert content.proposed_action == action
    outcome = persist(setup, content)
    assert outcome["id"] is not None
    assert outcome["diagnostic"] == "open"
    assert persist(setup, content)["id"] == outcome["id"]
    identifier = outcome["id"]
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(func.count())
                .select_from(candidate_signals)
                .where(
                    candidate_signals.c.user_id == owner,
                    candidate_signals.c.snapshot_id == content.snapshot_id,
                )
            ).scalar_one()
            == 1
        )
    detail = client.get("/api/v1/candidate-signals/" + identifier)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["proposed_action"] == action
    assert all(body[key] for key in ["rule_refs", "evidence", "counter_evidence", "invalidation"])
    assert (
        client.get("/api/v1/candidate-signals", params={"instance_id": str(instance)}).json()[
            "items"
        ][0]["id"]
        == identifier
    )
    for suffix in ["", "/events"]:
        assert stranger.get("/api/v1/candidate-signals/" + identifier + suffix).status_code == 404
    history = client.get("/api/v1/candidate-signals/" + identifier + "/events").json()["items"]
    assert history[0]["cause"] == "executability_check"
    assert history[0]["from"] is None
    assert "detail" not in history[0]
    assert (
        stranger.post(
            "/api/v1/candidate-signals/" + identifier + "/dismiss", json={"note": None}
        ).status_code
        == 404
    )
    assert client.post(
        "/api/v1/candidate-signals/" + identifier + "/dismiss", json={"note": None}
    ).json() == {"state": "dismissed"}


@pytest.mark.parametrize("action", ["hold", "wait"])
def test_hold_wait_never_written(setup: Any, action: str) -> None:
    content = signal().model_copy(update={"proposed_action": action})
    assert persist(setup, content)["id"] is None


def test_cash_t1_and_release_conditions_and_machine_denial(setup: Any) -> None:
    engine, client, stranger, _, _, _, _, _, snap = setup
    with engine.begin() as conn:
        prior = conn.execute(
            select(broker_position_snapshots).where(broker_position_snapshots.c.id == snap)
        ).one()
        new_snapshot = uuid.uuid4()
        values = dict(prior._mapping)
        values.update(id=new_snapshot, version_no=2, cash_available=0)
        conn.execute(insert(broker_position_snapshots).values(**values))
        item = conn.execute(
            select(broker_position_snapshot_items).where(
                broker_position_snapshot_items.c.snapshot_id == snap
            )
        ).one()
        values = dict(item._mapping)
        values.update(id=uuid.uuid4(), snapshot_id=new_snapshot, sellable_quantity=0)
        conn.execute(insert(broker_position_snapshot_items).values(**values))
    for action, code in [("buy", "INSUFFICIENT_CASH"), ("sell", "T1_NOT_SELLABLE")]:
        result = persist(setup, signal(action))
        identifier = result["id"]
        assert result["diagnostic"] == "blocked"
        response = client.get("/api/v1/non-executable-reasons", params={"signal_ids": identifier})
        assert response.status_code == 200, response.text
        rows = response.json()["items"]
        row = next(row for row in rows if row["code"] == code)
        assert row["release_condition"]["human_text"]
        assert row["release_condition"]["check_on"]
        assert row["release_condition"]["machine_checkable"] is True
        assert "next_cursor" not in response.json()
        assert stranger.get("/api/v1/non-executable-reasons/" + row["id"]).status_code == 404
        assert (
            client.post(
                "/api/v1/non-executable-reasons/" + row["id"] + "/release",
                json={"confirm": True, "note": None},
            ).status_code
            == 409
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("listing_status", "delisted"), ("listing_status", "missing_from_list"), ("type", "etf")],
)
def test_master_denies_without_candidates(setup: Any, field: str, value: str) -> None:
    engine, *_ = setup
    with engine.connect() as conn:
        transaction = conn.begin()
        conn.execute(
            update(securities).where(securities.c.code == "688018.SH").values(**{field: value})
        )
        try:
            # Reuse persisted snapshot setup, but same connection keeps guard mutation isolated.
            content = signal()
            conn.execute(
                insert(data_snapshots).values(
                    id=content.snapshot_id,
                    user_id=setup[3],
                    purpose="signal",
                    hash="synthetic",
                    created_at=AT,
                    items={},
                )
            )
            result = write_candidate(
                conn,
                user_id=setup[3],
                instance_id=setup[6],
                content=content,
                facts=MarketFacts(),
                market_rules=RULES,
            )
            assert result["id"] is None
        finally:
            transaction.rollback()


def test_suspension_universe_paused_and_user_branch(setup: Any) -> None:
    engine, _, _, owner, _, _, instance, _version, _ = setup
    result = persist(
        setup,
        signal(),
        facts=MarketFacts(
            price=25,
            required_cash=5001,
            is_suspended=True,
            list_days=100,
            limit_locked_up=False,
            limit_locked_down=False,
        ),
    )
    assert result["diagnostic"] == "blocked"
    content = signal(code="688073.SH")
    assert persist(setup, content)["diagnostic"] == "scope_mismatch"
    with engine.begin() as conn:
        # Published config is immutable; verify universe using a copied synthetic version instead.
        conn.execute(
            update(strategy_instances)
            .where(strategy_instances.c.id == instance)
            .values(status="paused", paused_by="user")
        )
    assert persist(setup, signal())["diagnostic"] == "instance_not_active"
    with engine.begin() as conn:
        calls = []
        assert (
            post_close_for_user(
                conn,
                user_id=owner,
                produce=lambda row: calls.append(row.id) or [],
                market_rules=RULES,
            )
            == []
        )
        assert calls == []


def test_p1_and_future_evidence_rejected_before_write() -> None:
    body = signal().model_dump()
    for key in ["rule_refs", "evidence", "counter_evidence", "invalidation"]:
        changed = {**body, key: []}
        with pytest.raises(ValidationError, match=key):
            SignalInput.model_validate(changed)
    body["rule_refs"][0]["evidence_ids"] = ["not_in_document"]
    with pytest.raises(ValidationError, match="unresolved_evidence"):
        SignalInput.model_validate(body)


def test_blocked_risk_and_bidirectional_conflict_manual_release(setup: Any) -> None:
    engine, client, _, owner, _, account, _instance, version, _ = setup
    other_instance = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            insert(strategy_instances).values(
                id=other_instance,
                user_id=owner,
                strategy_version_id=version,
                scope="security",
                security_code="688018.SH",
                account_id=account,
                status="active",
                origin="user",
                horizon="swing",
            )
        )
    buy = persist(setup, signal())
    other_setup = list(setup)
    other_setup[6] = other_instance
    sell = persist(tuple(other_setup), signal("sell"))
    assert sell["diagnostic"] == "blocked"
    for identifier in [buy["id"], sell["id"]]:
        assert client.get("/api/v1/candidate-signals/" + identifier).json()["state"] == "blocked"
        rows = client.get(
            "/api/v1/non-executable-reasons", params={"signal_ids": identifier}
        ).json()["items"]
        conflict = next(row for row in rows if row["code"] == "STRATEGY_CONFLICT")
        assert conflict["evidence"][0]["key"] == "signal.conflict_signal_id"
        assert conflict["release_condition"]["machine_checkable"] is False
    response = client.post(
        "/api/v1/non-executable-reasons/" + conflict["id"] + "/release",
        json={"confirm": True, "note": "虚构测试：选择该方"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["released_by"] == "user"
    assert client.get("/api/v1/candidate-signals/" + sell["id"]).json()["state"] == "released"
    content = signal()
    content = content.model_copy(
        update={
            "risk_flags": [
                {
                    "control": "position_cap",
                    "level": "warning",
                    "message": "虚构风险测试",
                    "gated_actions": ["buy"],
                    "quantity_cap": "0",
                    "evidence_ids": [content.evidence[0].id],
                }
            ]
        }
    )
    # Validate typed risk flags, no bypass via model_copy.
    content = SignalInput.model_validate(content.model_dump())
    blocked = persist(setup, content)
    assert blocked["diagnostic"] == "blocked"


def test_universe_and_user_branch_rollback_without_phantom_ids(setup: Any) -> None:
    engine, _, _, owner, _, _, instance, _version, _ = setup
    with engine.begin() as conn:
        conn.execute(
            update(strategy_instances)
            .where(strategy_instances.c.id == instance)
            .values(scope="account", security_code=None)
        )
    assert persist(setup, signal(code="301218.SZ"))["diagnostic"] == "outside_universe"
    first, bad = signal(), signal()
    facts = MarketFacts(
        price=25,
        required_cash=5001,
        is_suspended=False,
        list_days=100,
        limit_locked_up=False,
        limit_locked_down=False,
    )
    with engine.begin() as conn:
        for content, items in [(first, snapshot_items(first, facts)), (bad, {})]:
            conn.execute(
                insert(data_snapshots).values(
                    id=content.snapshot_id,
                    user_id=owner,
                    purpose="signal",
                    hash=content.snapshot_id.hex,
                    created_at=AT,
                    items=items,
                )
            )
        result = post_close_for_user(
            conn,
            user_id=owner,
            produce=lambda row: [(first, facts), (bad, facts)],
            market_rules=RULES,
        )
        assert len(result) == 1
        assert result[0]["diagnostic"] == "instance_failed"
        assert result[0]["id"] is None
        assert (
            conn.execute(
                select(func.count())
                .select_from(candidate_signals)
                .where(candidate_signals.c.user_id == owner)
            ).scalar_one()
            == 0
        )


def test_pagination_binding_csrf_and_reason_batch_limit(setup: Any) -> None:
    _, client, stranger, _, _, _, _, _, _ = setup
    first = persist(setup, signal())
    second = persist(setup, signal())
    page = client.get("/api/v1/candidate-signals", params={"limit": 1}).json()
    assert page["next_cursor"]
    after = client.get(
        "/api/v1/candidate-signals", params={"limit": 1, "cursor": page["next_cursor"]}
    )
    assert after.status_code == 200
    assert {page["items"][0]["id"], after.json()["items"][0]["id"]} == {first["id"], second["id"]}
    assert (
        stranger.get(
            "/api/v1/candidate-signals", params={"cursor": page["next_cursor"]}
        ).status_code
        == 400
    )
    assert (
        client.get(
            "/api/v1/candidate-signals", params={"cursor": page["next_cursor"], "state": "open"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/candidate-signals/" + first["id"] + "/dismiss",
            headers={"X-CSRF-Token": "invalid"},
            json={"note": None},
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/api/v1/non-executable-reasons", params={"signal_ids": ",".join([first["id"]] * 101)}
        ).status_code
        == 400
    )
    client.cookies.clear()
    assert client.get("/api/v1/candidate-signals").status_code == 401


def test_concurrent_same_snapshot_one_signal_one_creation_event(setup: Any) -> None:
    from concurrent.futures import ThreadPoolExecutor

    engine, _, _, owner, _, _, instance, _, _ = setup
    content = signal()
    facts = MarketFacts(
        price=25,
        required_cash=5001,
        is_suspended=False,
        list_days=100,
        limit_locked_up=False,
        limit_locked_down=False,
    )
    with engine.begin() as conn:
        conn.execute(
            insert(data_snapshots).values(
                id=content.snapshot_id,
                user_id=owner,
                purpose="signal",
                hash=content.snapshot_id.hex,
                created_at=AT,
                items=snapshot_items(content, facts),
            )
        )

    def run() -> Any:
        with engine.begin() as conn:
            return write_candidate(
                conn,
                user_id=owner,
                instance_id=instance,
                content=content,
                facts=facts,
                market_rules=RULES,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: run(), range(2)))
    assert len({row["id"] for row in outcomes}) == 1
    with engine.connect() as conn:
        identifier = uuid.UUID(outcomes[0]["id"])
        assert (
            conn.execute(
                select(func.count())
                .select_from(candidate_signal_events)
                .where(candidate_signal_events.c.signal_id == identifier)
            ).scalar_one()
            == 1
        )


def test_missing_facts_and_nontrading_time_never_open(setup: Any) -> None:
    _, client, *_ = setup
    missing = persist(setup, signal(), facts=MarketFacts())
    assert missing["diagnostic"] == "blocked"
    rows = client.get(
        "/api/v1/non-executable-reasons", params={"signal_ids": missing["id"]}
    ).json()["items"]
    assert "KEY_DATA_MISSING" in {row["code"] for row in rows}
    late = signal().model_copy(update={"created_at": AT + dt.timedelta(hours=8)})
    outcome = persist(setup, late)
    assert outcome["diagnostic"] == "blocked"
    rows = client.get(
        "/api/v1/non-executable-reasons", params={"signal_ids": outcome["id"]}
    ).json()["items"]
    reason = next(row for row in rows if row["code"] == "NON_TRADING_TIME")
    assert reason["release_condition"]["kind"] == "time"
    assert reason["release_condition"]["at"] is not None
