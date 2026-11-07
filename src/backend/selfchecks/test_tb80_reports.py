# ruff: noqa: S101, ANN401, F811
"""Formal automatic reports only; never gives either real card G7 or lifecycle approval."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.db.tables.strategy import strategy_cards, strategy_promotion_reviews, strategy_versions
from app.strategy.cards.persistence import import_batch
from app.strategy.cards.preflight import feature_registry
from app.strategy.promotions import prepare, public_review
from selfchecks.test_tb70_replay import integration, no_network  # noqa: F401
from selfchecks.test_tb76_daily import settings

ROOT = Path(__file__).resolve().parents[3]


def test_formal_26_real_gate_reports_remain_draft_with_explicit_unknown_g6(
    integration: Any,
) -> None:
    engine, _, _, owner, _ = integration
    keys = ["hold_risk_monitor", "sw_ma_trend_pullback"]
    documents = [(ROOT / "docs/strategies/cards" / (key + ".md")).read_text() for key in keys]
    registry = feature_registry((ROOT / "docs/strategies/feature_spec.md").read_text())
    reports = []
    with engine.connect() as conn:
        transaction = conn.begin()
        import_batch(conn, documents, registry)
        for key in keys:
            card = conn.execute(select(strategy_cards).where(strategy_cards.c.key == key)).one()
            rid = prepare(conn, owner, card.id, settings())
            row = conn.execute(
                select(strategy_promotion_reviews).where(strategy_promotion_reviews.c.id == rid)
            ).one()
            version = conn.execute(
                select(strategy_versions).where(
                    strategy_versions.c.id == row.target_strategy_version_id
                )
            ).one()
            assert version.lifecycle == "draft"
            assert row.decision == "pending"
            assert row.reviewer_id is None
            gates = {g["gate"]: g["result"] for g in row.gate_results}
            assert [gates["G" + str(n)] for n in [1, 3, 4, 5]] == ["pass"] * 4
            # Real importer leaves unverified source fields declared: G2 must actually fail.
            assert gates["G2"] == "fail"
            assert next(g["detail"]["issues"] for g in row.gate_results if g["gate"] == "G2")
            assert gates["G6"] == "warn"
            assert gates["G7"] == "skipped"
            assert all(r["passed"] for r in row.fixture_runs)
            assert row.g6_report["trigger_rate"]["n"] == 0
            assert row.g6_report["max_jaccard"] is None
            public = public_review(row)
            assert public["g6_report"]["max_jaccard"] is None
            assert public["g6_report"]["max_jaccard_null_reason"] == "no_history"
            reports.append(
                {
                    "strategy_key": key,
                    "decision": row.decision,
                    "lifecycle": version.lifecycle,
                    "gate_results": row.gate_results,
                    "fixture_runs": row.fixture_runs,
                    "g6_report": row.g6_report,
                }
            )
        assert sum(len(r["fixture_runs"]) for r in reports) == 26
        transaction.rollback()
    Path("/workspace/team/reports/T-B80-gates.json").write_text(
        json.dumps(reports, ensure_ascii=False, indent=2)
    )
