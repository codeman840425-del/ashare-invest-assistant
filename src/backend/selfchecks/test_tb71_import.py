# ruff: noqa: S101, ANN401, F811
"""Formal imports use only dedicated offline DB, not publication."""

from __future__ import annotations

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


def test_formal_import_idempotence_generation_queries(
    integration: Any, tmp_path: Path, no_network: Any
) -> None:
    engine, client, _, _, _ = integration
    docs = [
        (ROOT / "docs/strategies/cards" / name).read_text()
        for name in ("hold_risk_monitor.md", "sw_ma_trend_pullback.md")
    ]
    registry = feature_registry((ROOT / "docs/strategies/feature_spec.md").read_text())
    staged = validate_batch(docs, registry)
    files = generate_files(staged, tmp_path)
    assert generate_files(staged, tmp_path) == files
    hashes = [path.read_bytes() for path in files]
    with engine.begin() as conn:
        first = import_batch(conn, docs, registry)
    with engine.begin() as conn:
        second = import_batch(conn, docs, registry)
        assert first == second
        for row in first:
            version = conn.execute(
                select(strategy_versions).where(
                    strategy_versions.c.id == uuid.UUID(row["version_id"])
                )
            ).one()
            assert version.lifecycle == "draft"
            assert len(version.config["gates_missing"]) == 7
    assert [path.read_bytes() for path in files] == hashes
    with pytest.raises(ValueError, match="immutable"), engine.begin() as conn:
        import_batch(conn, [docs[0].replace("持仓风险体检", "持仓风险校验"), docs[1]], registry)
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
