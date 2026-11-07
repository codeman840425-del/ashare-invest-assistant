# ruff: noqa: S101, ANN401, F811
"""Read-only research input→real importer; formal negative gates, never real G7."""

from __future__ import annotations

import copy
from typing import Any

import pytest
import yaml
from sqlalchemy import select

from app.db.tables.realtime import suggestions
from app.db.tables.strategy import feature_catalog, strategy_cards, strategy_versions
from app.strategy.cards.persistence import import_batch
from app.strategy.cards.preflight import feature_registry
from app.strategy.cards.source_reviews import (
    DECLARED_KEYS,
    DOC_KEYS,
    load_reviews,
    persist_reviews,
    required_features,
    source_issues,
)
from app.workers.daily import ANALYZE
from selfchecks.test_tb70_replay import integration, no_network  # noqa: F401
from selfchecks.test_tb74_candidates import ROOT
from selfchecks.test_tb78_acceptance import chain, mount, run  # noqa: F401


@pytest.fixture
def inputs() -> Any:
    document = (ROOT / "docs/strategies/feature_spec.md").read_text()
    registry = feature_registry(document)
    matrix = (ROOT / "docs/strategies/T-R18_source_matrix.yaml").read_text()
    return registry, matrix


def test_reviewed_provenance_and_canonical_visibility(inputs: Any) -> None:
    registry, matrix = inputs
    reviews = load_reviews(registry, matrix)
    assert set(reviews) == DOC_KEYS | DECLARED_KEYS
    assert all(
        reviews[k].status == "verified_doc" and reviews[k].ceiling == "simulating" for k in DOC_KEYS
    )
    assert all(reviews[k].status == "declared" for k in DECLARED_KEYS)
    assert reviews["f.np_yoy_latest"].pit_rule is not None
    assert reviews["f.np_yoy_latest"].pit_rule["available_at"] == "next_trading_day(plrq) 09:30"
    assert "insufficient_data" in reviews["f.list_days"].basis["null_when"]
    assert reviews["f.close_qfq"].basis["gaps"]
    for key in reviews:
        assert reviews[key].source_matrix_sha256


@pytest.mark.parametrize(
    "mutation", ["missing", "unknown", "duplicate", "upgrade", "ceiling", "visibility", "reference"]
)
def test_source_input_rejection(inputs: Any, mutation: str) -> None:
    registry, matrix = inputs
    registry = copy.deepcopy(registry)
    parsed = yaml.safe_load(matrix)
    if mutation == "unknown":
        parsed["features"][0]["feature_key"] = "f.unknown"
    elif mutation == "duplicate":
        parsed["features"].append(parsed["features"][0])
    elif mutation == "upgrade":
        registry["f.amount"]["status"] = "verified_live"
    elif mutation == "ceiling":
        registry["f.close_qfq"]["status_basis"]["ceiling"] = "published"
    elif mutation == "visibility":
        registry["f.np_yoy_latest"]["pit_rule"]["available_at"] = "plrq 09:30"
    elif mutation == "reference":
        registry["f.list_days"]["status_basis"]["matrix"] = "other"
    with pytest.raises(ValueError, match=r"source_|reviewed_"):
        load_reviews(registry, None if mutation == "missing" else yaml.safe_dump(parsed))


def catalog(conn: Any) -> dict[str, dict[str, Any]]:
    return {
        r.feature_key: {"status": r.status, "source": r.source}
        for r in conn.execute(
            select(
                feature_catalog.c.feature_key, feature_catalog.c.status, feature_catalog.c.source
            )
        )
    }


def test_real_import_is_idempotent_five_scoped_four_declared_and_formal_g2_fails(
    integration: Any, inputs: Any
) -> None:
    engine, *_ = integration
    registry, matrix = inputs
    keys = ["hold_risk_monitor", "sw_ma_trend_pullback"]
    documents = [(ROOT / "docs/strategies/cards" / (k + ".md")).read_text() for k in keys]
    with engine.connect() as conn:
        transaction = conn.begin()
        first = import_batch(conn, documents, registry, source_matrix=matrix)
        before = catalog(conn)
        assert import_batch(conn, documents, registry, source_matrix=matrix) == first
        assert catalog(conn) == before
        assert not source_issues(before, set(DOC_KEYS), "simulating")
        assert len(source_issues(before, set(DOC_KEYS), "published")) == 5
        assert len(source_issues(before, set(DECLARED_KEYS), "simulating")) == 4
        for item in first:
            version = conn.execute(
                select(strategy_versions).where(strategy_versions.c.id == item["version_id"])
            ).one()
            assert version.lifecycle == "draft"
            card = conn.execute(
                select(strategy_cards).where(strategy_cards.c.id == item["card_id"])
            ).one()
            assert card.completeness == "draft"
            spec = version.config.get("spec", version.config)
            from app.db.tables.strategy import strategy_card_versions

            fields = conn.execute(
                select(strategy_card_versions.c.fields).where(
                    strategy_card_versions.c.id == version.card_version_id
                )
            ).scalar_one()
            issues = source_issues(before, required_features(spec, fields), "simulating")
            assert issues
            assert {r["path"] for r in issues} <= DECLARED_KEYS
        tampered = copy.deepcopy(before)
        tampered["f.amount"]["status"] = "verified_live"
        assert (
            source_issues(tampered, {"f.amount"}, "simulating")[0]["issue"]
            == "reviewed_source_missing_or_status_conflict"
        )
        transaction.rollback()


@pytest.mark.parametrize(
    ("lifecycle", "feature"), [("published", "f.close_qfq"), ("simulating", "f.amount")]
)
def test_actual_worker_refuses_formal_like_fictional_source_bypass(
    chain: Any, inputs: Any, lifecycle: str, feature: str
) -> None:
    fixture, _ = chain
    engine, client, _, owner, *_ = fixture
    registry, matrix = inputs
    with engine.begin() as conn:
        persist_reviews(conn, registry, load_reviews(registry, matrix))
    mount(chain, version_no=2, lifecycle=lifecycle, source_gate_key=feature)
    run(owner, "2026-10-30", ANALYZE)
    with engine.connect() as conn:
        assert (
            conn.execute(select(suggestions.c.id).where(suggestions.c.user_id == owner)).all() == []
        )
    assert client.get("/api/v1/terminal").status_code == 200
