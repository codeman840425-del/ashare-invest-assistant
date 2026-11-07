# ruff: noqa: S101, ANN401, F811
"""Only synthetic four-code fixtures; actual isolated storage, HTTP and locking."""

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import DBAPIError

from app.common.errors import AppError
from app.config import Settings
from app.db.tables.realtime import suggestions
from app.db.tables.reviews import data_snapshots
from app.db.tables.strategy import risk_control_settings, strategies, strategy_versions
from app.schemas.enums import Action, DimensionView
from app.signals.models import Evidence, MarketFacts, Stops
from app.signals.service import snapshot_items as signal_snapshot
from app.suggestions.aggregate import assemble
from app.suggestions.models import Conclusion, SuggestionInput
from app.suggestions.risk import RiskContext, apply_risk, effective_config, evaluate_risk
from app.suggestions.service import archive, snapshot_items
from selfchecks.test_tb70_replay import integration, no_network  # noqa: F401
from selfchecks.test_tb74_candidates import AT, SPEC, persist, setup, signal  # noqa: F401

ROWS = json.loads((Path(__file__).parent / "fixtures/tb75_synthetic.json").read_text())


def conclusion(component: Any, action: str = "buy", override: Any = None) -> Conclusion:
    engine, _, _, _, _, _, instance, version, _ = component
    content = signal(action if action not in {"hold", "wait"} else "buy")
    if action in {"hold", "wait"}:
        content = type(content).model_validate({**content.model_dump(), "proposed_action": action})
    if action in {"hold", "wait"}:
        with engine.begin() as conn:
            conn.execute(
                insert(data_snapshots).values(
                    id=content.snapshot_id,
                    user_id=component[3],
                    purpose="signal",
                    hash=content.snapshot_id.hex,
                    items=signal_snapshot(content, MarketFacts()),
                    created_at=AT,
                )
            )
    content = override if override is not None else content
    outcome = persist(component, content)
    with engine.connect() as conn:
        ver = conn.execute(select(strategy_versions).where(strategy_versions.c.id == version)).one()
        strategy = conn.execute(select(strategies).where(strategies.c.id == ver.strategy_id)).one()
    return Conclusion.model_validate(
        {
            "strategy_version_id": str(version),
            "strategy_key": strategy.key,
            "strategy_name": strategy.name,
            "version_no": 1,
            "instance_id": str(instance),
            "horizon": "swing",
            "lifecycle": "published",
            "state": "entry_ok",
            "signal": content,
            "candidate_signal_id": outcome["id"],
            "priority_weight": "1",
            "priority_downweighted": False,
            "dimension_views": [
                {
                    "dimension": "technical",
                    "view": "bullish",
                    "score": content.score,
                    "rules": content.rule_refs,
                }
            ],
            "reasons": [content.counter_evidence[0]],
        }
    )


def prepared(component: Any, conclusions: list[Conclusion]) -> SuggestionInput:
    engine, _, _, owner, *_ = component
    content = SuggestionInput.model_validate(
        {
            "security_code": "688018.SH",
            "snapshot_id": str(uuid.uuid4()),
            "feature_set_version": conclusions[0].signal.feature_set_version,
            "conclusions": conclusions,
            "data_status": "fresh",
            "data_as_of": AT,
            "gaps": [],
            "suitable": ["swing"],
            "user_overridden": False,
            "created_at": AT,
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
                created_at=AT,
            )
        )
    return content


def write(component: Any, content: SuggestionInput) -> dict[str, Any]:
    with component[0].begin() as conn:
        return archive(conn, user_id=component[3], content=content)


def test_real_immutable_idempotence_chain_actions_and_owner(setup: Any, no_network: Any) -> None:
    engine, client, stranger, owner, *_ = setup
    c = conclusion(setup)
    content = prepared(setup, [c])
    first = write(setup, content)
    assert first["changed"] is True
    assert write(setup, content)["changed"] is False
    assert write(setup, prepared(setup, [c]))["changed"] is False  # new envelope isn't new input
    original = client.get("/api/v1/suggestions/" + first["suggestion"]["id"]).json()
    assert original["consensus"] == {"status": "single", "actions": {"buy": 1}}
    assert original["explanation"]["source"] == "template"
    assert isinstance(original["strategies"][0]["confidence"]["value"], float)
    assert original["plan_draft_ids"] == []
    assert original["executability"]["status"] == "executable"
    ids = {e["id"] for e in original["evidence"]}
    assert all(set(r["evidence_ids"]) <= ids for r in original["strategies"][0]["rule_refs"])
    c2 = c.model_copy(update={"priority_weight": Decimal("0.85"), "priority_downweighted": True})
    second = write(setup, prepared(setup, [c2]))
    assert second["changed"] is True
    assert second["superseded_id"] == original["id"]
    old = client.get("/api/v1/suggestions/" + original["id"]).json()
    assert old["status"] == "superseded"
    assert old["superseded_by_id"] == second["suggestion"]["id"]
    assert old["evidence"] == original["evidence"]
    chain = client.get("/api/v1/suggestions/" + original["id"] + "/chain")
    assert chain.status_code == 200
    assert [r["id"] for r in chain.json()] == [original["id"], second["suggestion"]["id"]]
    listing = client.get(
        "/api/v1/suggestions", params={"security_code": "688018", "status": "active"}
    )
    assert listing.status_code == 200
    assert [r["id"] for r in listing.json()["items"]] == [second["suggestion"]["id"]]
    assert stranger.get("/api/v1/suggestions/" + original["id"]).status_code == 404
    assert stranger.get("/api/v1/suggestions/" + original["id"] + "/chain").status_code == 404
    endpoint = "/api/v1/suggestions/" + second["suggestion"]["id"] + "/actions"
    assert (
        client.post(
            endpoint, json={"kind": "dismissed", "trade_id": None, "note": None}
        ).status_code
        == 204
    )
    assert (
        client.post(
            "/api/v1/suggestions/" + original["id"] + "/actions",
            json={"kind": "viewed", "trade_id": None, "note": None},
        ).status_code
        == 409
    )
    assert (
        stranger.post(endpoint, json={"kind": "viewed", "trade_id": None, "note": None}).status_code
        == 404
    )
    assert (
        client.post(
            endpoint,
            json={"kind": "acted_trade_linked", "trade_id": str(uuid.uuid4()), "note": None},
        ).status_code
        == 400
    )
    csrf = client.headers.pop("X-CSRF-Token")
    assert (
        client.post(endpoint, json={"kind": "viewed", "trade_id": None, "note": None}).status_code
        == 403
    )
    client.headers["X-CSRF-Token"] = csrf
    assert (
        client.post("/api/v1/suggestions/refresh", json={"security_code": "688018.SH"}).status_code
        == 409
    )
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(
            update(suggestions)
            .where(suggestions.c.id == uuid.UUID(original["id"]))
            .values(explanation_text="Synthetic attempted mutation")
        )
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(func.count())
                .select_from(suggestions)
                .where(
                    suggestions.c.user_id == owner,
                    suggestions.c.security_code == "688018.SH",
                    suggestions.c.status == "active",
                )
            ).scalar_one()
            == 1
        )
    assert no_network == []


def test_concurrent_same_input_does_not_duplicate(setup: Any) -> None:
    content = prepared(setup, [conclusion(setup)])
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(lambda _: write(setup, content), range(2)))
    assert sum(r["changed"] for r in result) == 1
    assert result[0]["suggestion"]["id"] == result[1]["suggestion"]["id"]


def test_hold_wait_missing_market_and_draft_never_bypass(setup: Any) -> None:
    engine, _, _, owner, _, _, _, version, _ = setup
    c = conclusion(setup, "hold")
    result = write(setup, prepared(setup, [c]))
    assert result["suggestion"]["candidate_signal_ids"] == []
    assert result["suggestion"]["executability"]["status"] == "not_applicable"
    content = prepared(setup, [c])
    with engine.begin() as conn:
        conn.execute(
            update(strategy_versions)
            .where(strategy_versions.c.id == version)
            .values(lifecycle="draft")
        )
    with pytest.raises(AppError, match="STRATEGY_VERSION_NOT_RUNNABLE"):
        write(setup, content)
    with pytest.raises(ValidationError):
        Conclusion.model_validate({**c.model_dump(), "lifecycle": "draft"})
    with pytest.raises(AppError), engine.begin() as conn:
        archive(conn, user_id=setup[4], content=content)
    assert owner != setup[4]


def test_conflicting_actions_matrix_counts_without_synthesis(setup: Any) -> None:
    c = conclusion(setup)
    other = c.model_copy(
        update={
            "instance_id": uuid.uuid4(),
            "strategy_key": "synthetic_opposite",
            "signal": c.signal.model_copy(update={"proposed_action": Action.SELL}),
            "candidate_signal_id": uuid.uuid4(),
            "dimension_views": [
                c.dimension_views[0].model_copy(update={"view": DimensionView.BEARISH})
            ],
        }
    )
    content = prepared(setup, [c, other])
    candidates = {
        str(row.candidate_signal_id): {"blocked": True, "reason_ids": []} for row in [c, other]
    }
    result = assemble(content, candidates)
    assert result["consensus"] == {"status": "divergent", "actions": {"buy": 1, "sell": 1}}
    assert result["dimension_matrix"][0]["divergent"] is True
    assert result["executability"]["status"] == "blocked"
    assert "action" not in result
    assert len({e["id"] for e in result["evidence"]}) == len(result["evidence"])


def observation(key: str, value: Any) -> Evidence:
    return Evidence.model_validate(
        {
            "id": key,
            "key": key,
            "value": value,
            "unit": None,
            "provider": "system",
            "endpoint": None,
            "data_as_of": AT,
            "fetched_at": AT,
            "epistemic_type": "hypothesis",
        }
    )


@pytest.mark.parametrize("row", ROWS)
def test_risk_inputs_are_synthetic_and_missing_never_zero(row: dict[str, str]) -> None:
    config = Settings(_env_file=None).business.risk_controls
    metrics = {
        "price": row["price"],
        "total_assets": row["assets"],
        "security_value": row["security_value"],
        "proposed_quantity": row["proposed_quantity"],
        "total_value": row["total_value"],
    }
    context = RiskContext.model_validate(
        {
            "observations": {k: observation(k, v) for k, v in metrics.items()},
            "regime": None,
            "trade_action": None,
            "plan_action": None,
            "invalidated": None,
            "plan_stop_loss": None,
        }
    )
    stops = Stops(stop_loss=None, take_profit=None, time_stop_days=None)
    outcome = evaluate_risk(config, context, action="buy", horizon="swing", stops=stops)
    assert "market_regime" in outcome.gaps
    assert "closed_loss_streak" in outcome.gaps
    assert "plan_trade_context" in outcome.gaps
    assert all(set(f.evidence_ids) <= {e.id for e in outcome.evidence} for f in outcome.flags)
    cap = max(
        Decimal(0), Decimal(row["assets"]) * Decimal("0.2") - Decimal(row["security_value"])
    ) / Decimal(row["price"])
    assert outcome.quantity_cap == cap // 1
    missing = context.model_copy(update={"observations": {}})
    assert (
        evaluate_risk(config, missing, action="buy", horizon="swing", stops=stops).quantity_cap
        is None
    )


def test_all_six_controls_boundaries_and_disabled() -> None:
    config = Settings(_env_file=None).business.risk_controls
    metrics = {
        "price": "40",
        "total_assets": "100000",
        "security_value": "20000",
        "proposed_quantity": "1",
        "total_value": "95000",
        "limit_down_price": "32",
        "limit_up_price": "48",
        "sector_memberships": json.dumps(["sw_l1.synthetic", "concept.synthetic"]),
        "sw_l1.synthetic": "41",
        "sw_l1.未分类": "99",
        "concept.synthetic": "51",
        "closed_loss_streak": 3,
        "drawdown_from_peak_pct": "10",
        "strategy_sim_fail_streak": 5,
        "traded_quantity": "201",
        "planned_quantity": "200",
        "holding_quantity": "200",
        "market_regime": "uptrend",
        "plan_trade_context": json.dumps(
            {
                "trade_action": "buy",
                "plan_action": "wait",
                "invalidated": True,
                "plan_stop_loss": None,
            }
        ),
    }
    context = RiskContext.model_validate(
        {
            "observations": {k: observation(k, v) for k, v in metrics.items()},
            "regime": "uptrend",
            "sector_memberships": ["sw_l1.synthetic", "concept.synthetic"],
            "trade_action": "buy",
            "plan_action": "wait",
            "invalidated": True,
            "plan_stop_loss": None,
        }
    )
    result = evaluate_risk(
        config,
        context,
        action="buy",
        horizon="long",
        stops=Stops(stop_loss=None, take_profit=Decimal(100), time_stop_days=None),
    )
    assert result.stops.stop_loss == Decimal("32")
    assert result.stops.take_profit == Decimal("48")
    assert result.quantity_cap == 0
    assert result.pause_required is True
    assert result.pause_days == 5
    assert {f.control for f in result.flags} == {
        "position_cap",
        "total_exposure",
        "sector_concentration",
        "loss_streak_drawdown",
        "plan_violation",
    }
    assert len([f for f in result.flags if f.control == "sector_concentration"]) == 2
    assert context.trade_action == "buy"
    assert result.gaps == []
    assert len(result.gate_details) == 3
    disabled = config.model_dump()
    for key, value in disabled.items():
        if key.startswith("rc"):
            value["enabled"] = False
    result = evaluate_risk(
        type(config).model_validate(disabled),
        context.model_copy(update={"observations": {}}),
        action="buy",
        horizon="long",
        stops=Stops(stop_loss=None, take_profit=None, time_stop_days=None),
    )
    assert result.flags == []
    assert result.gaps == []


def test_settings_precedence_and_risk_candidate_suggestion_path(setup: Any) -> None:
    engine, _, _, owner, *_ = setup
    defaults = Settings(_env_file=None).business.risk_controls
    with engine.begin() as conn:
        conn.execute(
            insert(risk_control_settings).values(
                scope="user",
                user_id=owner,
                control="position_cap",
                enabled=True,
                params={"single_position_max_pct": 10},
            )
        )
        chosen = effective_config(conn, owner, defaults)
        assert chosen.rc2_position_cap.single_position_max_pct == 10
        assert defaults.rc2_position_cap.single_position_max_pct == 20
    with pytest.raises(ValidationError), engine.begin() as conn:  # noqa: PT012
        conn.execute(
            update(risk_control_settings)
            .where(risk_control_settings.c.user_id == owner)
            .values(params={"single_position_max_pct": 99})
        )
        effective_config(conn, owner, defaults)
    values = chosen.model_dump()
    for key, value in values.items():
        if key.startswith("rc") and key != "rc2_position_cap":
            value["enabled"] = False
    config = type(chosen).model_validate(values)
    metrics = {
        "price": "25",
        "total_assets": "100000",
        "security_value": "10000",
        "proposed_quantity": "200",
    }
    context = RiskContext.model_validate(
        {
            "observations": {k: observation(k, v) for k, v in metrics.items()},
            "regime": None,
            "trade_action": None,
            "plan_action": None,
            "invalidated": None,
            "plan_stop_loss": None,
        }
    )
    base = signal()
    result = evaluate_risk(
        config, context, action=base.proposed_action, horizon="swing", stops=base.stops
    )
    enriched = apply_risk(base, result, gaps=[])
    assert enriched.proposed_action == base.proposed_action
    assert enriched.score == base.score
    output = write(setup, prepared(setup, [conclusion(setup, override=enriched)]))["suggestion"]
    assert output["executability"]["status"] == "blocked"
    assert output["risk_flags"][0]["control"] == "position_cap"
    assert output["strategies"][0]["action"] == "buy"
    with pytest.raises(ValueError, match="risk_gap_classification_incomplete"):
        apply_risk(base, result.model_copy(update={"gaps": ["total_assets"]}), gaps=[])


def test_missing_cash_or_quote_blocks_real_candidate(setup: Any) -> None:
    engine, _, _, owner, *_ = setup
    base = signal()
    outcome = persist(
        setup,
        base,
        facts=MarketFacts(
            price=None,
            required_cash=None,
            is_suspended=False,
            list_days=100,
            limit_locked_up=False,
            limit_locked_down=False,
        ),
    )
    assert outcome["id"] is not None
    with engine.connect() as conn:
        from app.db.tables.signals import candidate_signals

        row = conn.execute(
            select(candidate_signals).where(candidate_signals.c.id == uuid.UUID(outcome["id"]))
        ).one()
        assert row.state == "blocked"
    assert owner is not None


def test_partial_risk_provenance_and_zero_price_never_fabricate_stop() -> None:
    config = Settings(_env_file=None).business.risk_controls
    context = RiskContext.model_validate(
        {
            "observations": {
                "closed_loss_streak": observation("closed_loss_streak", 3),
                "drawdown_from_peak_pct": observation("drawdown_from_peak_pct", None),
                "price": observation("price", 0),
            },
            "regime": None,
            "trade_action": None,
            "plan_action": None,
            "invalidated": None,
            "plan_stop_loss": None,
        }
    )
    outcome = evaluate_risk(
        config,
        context,
        action="buy",
        horizon="long",
        stops=Stops(stop_loss=None, take_profit=None, time_stop_days=None),
    )
    assert outcome.stops.stop_loss is None
    assert "price" in outcome.gaps
    assert outcome.pause_required is True
    ids = {e.id for e in outcome.evidence}
    assert all(set(flag.evidence_ids) <= ids for flag in outcome.flags)
    with pytest.raises(ValidationError):
        RiskContext.model_validate(
            {
                **context.model_dump(),
                "observations": {"a": observation("same", 1), "b": observation("same", 2)},
            }
        )


def test_loss_pause_gates_candidate_without_rewriting_action(setup: Any) -> None:
    config = Settings(_env_file=None).business.risk_controls
    values = config.model_dump()
    for key, value in values.items():
        if key.startswith("rc") and key != "rc5_loss_streak_drawdown":
            value["enabled"] = False
    config = type(config).model_validate(values)
    metrics = {"closed_loss_streak": 3, "drawdown_from_peak_pct": 0, "strategy_sim_fail_streak": 0}
    context = RiskContext.model_validate(
        {
            "observations": {k: observation(k, v) for k, v in metrics.items()},
            "regime": None,
            "trade_action": None,
            "plan_action": None,
            "invalidated": None,
            "plan_stop_loss": None,
        }
    )
    base = signal()
    result = evaluate_risk(
        config, context, action=base.proposed_action, horizon="swing", stops=base.stops
    )
    assert result.pause_required is True
    enriched = apply_risk(base, result, gaps=[])
    assert enriched.proposed_action == base.proposed_action
    output = write(setup, prepared(setup, [conclusion(setup, override=enriched)]))["suggestion"]
    assert output["executability"]["status"] == "blocked"
    assert output["strategies"][0]["action"] == "buy"
    reason_id = output["executability"]["reason_ids"][0]
    response = setup[1].get("/api/v1/non-executable-reasons/" + reason_id)
    assert response.status_code == 200
    assert response.json()["code"] == "LOSS_STREAK_PAUSE"
