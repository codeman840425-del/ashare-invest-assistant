# ruff: noqa: S101, ANN401, F811
"""Formal imports use only dedicated offline DB, not publication."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from app.db.tables.strategy import strategy_versions
from app.strategy.cards.persistence import generate_files, import_batch, validate_batch
from app.strategy.cards.preflight import feature_registry
from selfchecks.test_tb70_replay import integration, no_network  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
FORMAL_REV = "3895963"


def formal_catalog() -> str:
    return subprocess.check_output(  # noqa: S603 - fixed approved local revision, no remote access
        ["/usr/bin/git", "show", FORMAL_REV + ":docs/strategies/feature_spec.md"],
        cwd=ROOT,
        text=True,
    )


def test_formal_import_idempotence_generation_queries(
    integration: Any, tmp_path: Path, no_network: Any
) -> None:
    engine, client, _, _, _ = integration
    docs = [
        (ROOT / "docs/strategies/cards" / name).read_text()
        for name in ("hold_risk_monitor.md", "sw_ma_trend_pullback.md")
    ]
    registry = feature_registry(formal_catalog())
    staged = validate_batch(docs, registry)
    files = generate_files(staged, tmp_path)
    assert generate_files(staged, tmp_path) == files
    hashes = [path.read_bytes() for path in files]
    with engine.begin() as conn:
        first = import_batch(
            conn,
            docs,
            registry,
            source_matrix=(ROOT / "docs/strategies/T-R18_source_matrix.yaml").read_text(),
        )
    with engine.begin() as conn:
        second = import_batch(
            conn,
            docs,
            registry,
            source_matrix=(ROOT / "docs/strategies/T-R18_source_matrix.yaml").read_text(),
        )
        assert first == second
        for row in first:
            version = conn.execute(
                select(strategy_versions).where(
                    strategy_versions.c.id == uuid.UUID(row["version_id"])
                )
            ).one()
            assert (
                version.version_no
                == {"hold_risk_monitor": 3, "sw_ma_trend_pullback": 2}[row["key"]]
            )
            assert version.lifecycle == "draft"
            assert len(version.config["gates_missing"]) == 7
    assert [path.read_bytes() for path in files] == hashes
    with pytest.raises(ValueError, match="immutable"), engine.begin() as conn:
        import_batch(
            conn,
            [docs[0].replace("持仓风险体检", "持仓风险校验"), docs[1]],
            registry,
            source_matrix=(ROOT / "docs/strategies/T-R18_source_matrix.yaml").read_text(),
        )
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(func.count())
                .select_from(strategy_versions)
                .where(strategy_versions.c.id.in_([uuid.UUID(row["version_id"]) for row in first]))
            ).scalar_one()
            == 2
        )
    cards = client.get("/api/v1/strategy-cards")
    assert cards.status_code == 200
    assert {row["key"] for row in cards.json()["items"]} >= {
        "hold_risk_monitor",
        "sw_ma_trend_pullback",
    }
    for row in first:
        detail = client.get(f"/api/v1/strategy-cards/{row['card_id']}")
        assert detail.status_code == 200
        assert len(detail.json()["gates_missing"]) == 7
        version = client.get(
            f"/api/v1/strategies/{row['strategy_id']}/versions/{row['version_id']}"
        )
        assert version.status_code == 200
        assert version.json()["lifecycle"] == "draft"
        assert version.json()["internal_check"] == {
            "done": False,
            "method_types": [],
            "checked_on": None,
        }
    assert (
        client.get(
            f"/api/v1/strategies/{uuid.uuid4()}/versions/{first[0]['version_id']}"
        ).status_code
        == 404
    )
    listing = client.get("/api/v1/strategies")
    assert listing.status_code == 200
    assert all(row["health"] is None for row in listing.json()["items"])
    assert client.get("/api/v1/feature-catalog").status_code == 200
    account = client.post(
        "/api/v1/accounts", json={"alias": "合成", "broker_name": "合成券商"}
    ).json()["id"]
    rejected = client.post(
        "/api/v1/strategy-instances",
        json={
            "strategy_version_id": first[0]["version_id"],
            "scope": "account",
            "account_id": account,
            "security_code": None,
            "horizon": "short",
            "param_overrides": None,
            "budget_amount": None,
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "STRATEGY_SYSTEM_ONLY"
    assert no_network == []


def test_version_local_applicability_unknown_and_no_cross_version_fallback() -> None:
    from app.strategy.cards.applicability import evaluate, regime_source

    spec = {"applicability": {"market_regime": ["uptrend", "range"]}, "rules": []}
    old = {"data_needs": [{"feature_key": "f.market_regime"}]}
    new = {"data_needs": [{"feature_key": "f.market_regime_idx"}]}
    values = {"f.market_regime": "downtrend", "f.market_regime_idx": "uptrend"}
    for card, inputs, expected in [
        (old, values, False),
        (new, values, True),
        (new, {"f.market_regime": "uptrend"}, None),
        (old, {"f.market_regime_idx": "uptrend"}, None),
    ]:
        result = evaluate(card, spec, inputs)
        assert result is not None
        assert result["matched"] is expected
    with pytest.raises(ValueError, match="mixed"):
        regime_source({"data_needs": old["data_needs"] + new["data_needs"]}, spec)


def test_formal_v2_real_gates_no_g7(integration: Any, tmp_path: Path) -> None:
    import json

    from app.config_files import MarketRulesConfig
    from app.db.tables.strategy import strategies
    from app.strategy.cards.fixtures import run_fixtures
    from app.strategy.cards.importing import _block

    engine, client, _, owner, _ = integration
    registry = feature_registry(formal_catalog())
    docs = [
        (ROOT / "docs/strategies/cards" / (key + ".md")).read_text()
        for key in ["hold_risk_monitor", "sw_ma_trend_pullback"]
    ]
    staged = validate_batch(docs, registry)
    market = MarketRulesConfig.model_validate(
        _block((ROOT / "config/market_rules.yaml").read_text())
    )
    assert (
        sum(
            len(
                run_fixtures(
                    item.blocks["strategy-card"],
                    item.blocks["strategy-spec"],
                    item.blocks["validation"]["fixtures"],
                    market,
                    set(registry),
                )
            )
            for item in staged
        )
        == 26
    )
    from app.engine_policies import load as load_policy
    from app.engine_policies import seed

    with engine.begin() as conn:
        seed(conn, load_policy(ROOT / "config"))
        imported = import_batch(
            conn,
            docs,
            registry,
            source_matrix=(ROOT / "docs/strategies/T-R18_source_matrix.yaml").read_text(),
        )
    output = []
    for row in imported:
        from app.db.tables.strategy import strategy_promotion_reviews
        from app.strategy.promotions import prepare, public_review

        # Fresh real execution; never reuse an earlier pending review as new evidence.
        # Roll back this verification report only; the formal v2 import stays committed.
        with engine.connect() as conn:
            transaction = conn.begin()
            identifier = prepare(
                conn,
                owner,
                uuid.UUID(row["card_id"]),
                client.app.state.settings,
                version_id=uuid.UUID(row["version_id"]),
            )
            review = conn.execute(
                select(strategy_promotion_reviews).where(
                    strategy_promotion_reviews.c.id == identifier
                )
            ).one()
            item = public_review(review)
            item["reviewer_id"] = review.reviewer_id
            transaction.rollback()
        gate = {g["gate"]: g for g in item["gate_results"]}
        assert len(gate) == 7
        assert gate["G7"]["result"] == "skipped"
        assert item["decision"] == "pending"
        assert item["reviewer_id"] is None
        assert all(r["passed"] for r in item["fixture_runs"])
        with engine.connect() as conn:
            version = conn.execute(
                select(strategy_versions).where(
                    strategy_versions.c.id == uuid.UUID(row["version_id"])
                )
            ).one()
            key = conn.execute(
                select(strategies.c.key).where(strategies.c.id == version.strategy_id)
            ).scalar_one()
            assert version.version_no == {"hold_risk_monitor": 3, "sw_ma_trend_pullback": 2}[key]
            assert version.lifecycle == "draft"
            assert version.config["applicability_eval_source"] in {None, "f.market_regime_idx"}
        output.append(
            {
                "key": key,
                "version_no": {"hold_risk_monitor": 3, "sw_ma_trend_pullback": 2}[key],
                "verification_review_id_rolled_back": str(identifier),
                "gates": {k: v["result"] for k, v in gate.items()},
                "g2_issues": gate["G2"]["detail"]["issues"],
                "fixture_passed": len(item["fixture_runs"]),
            }
        )
    print("T-B84_REAL_GATES=" + json.dumps(output, ensure_ascii=False))
