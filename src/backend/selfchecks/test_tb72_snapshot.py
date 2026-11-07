# ruff: noqa: S101, ANN401, F811
"""Synthetic dedicated DB adapter isolation, without factors pretending to be real."""

from typing import Any

import pytest

from app.common.errors import AppError
from app.features.evaluation import evaluate_snapshot
from app.replay.baseline import CLOCK, load
from selfchecks.test_tb70_replay import integration, no_network  # noqa: F401
from selfchecks.test_tb72_features import REGISTRY, RULES


def test_owned_four_code_snapshot_unknown_adjustment_is_insufficient(
    integration: Any, no_network: Any
) -> None:
    engine, _, _, owner, other = integration
    with engine.begin() as conn:
        snapshot = load(conn, owner, app_env="test")
    spec = {
        "params_schema": {},
        "rules": [
            {
                "id": "synthetic_rule",
                "dimension": "technical",
                "role": "entry",
                "eval_time": "daily",
                "expr": "ma(f.close_qfq,60) > 0",
            }
        ],
        "action_map": {"entry_all_core_pass": "buy", "else": "wait"},
    }
    with engine.connect() as conn:
        for code in ["688018.SH", "688073.SH", "300364.SZ", "301218.SZ"]:
            result = evaluate_snapshot(
                conn,
                user_id=owner,
                snapshot_id=snapshot,
                security_code=code,
                as_of=CLOCK,
                card={},
                spec=spec,
                registry=REGISTRY,
                market_rules=RULES,
                factors=[],
            )
            assert result["state"] == "insufficient_data"
            assert result["action"] == "wait"
            assert result["simulation"] is True
        with pytest.raises(AppError):
            evaluate_snapshot(
                conn,
                user_id=other,
                snapshot_id=snapshot,
                security_code="688018.SH",
                as_of=CLOCK,
                card={},
                spec=spec,
                registry=REGISTRY,
                market_rules=RULES,
                factors=[],
            )
