# ruff: noqa: S101, ANN401, F811
"""Synthetic arithmetic/reference tests, not engine-loop acceptance."""

from __future__ import annotations

import copy
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.config import check_config_dir_files, load_yaml_dir
from app.db.tables.strategy import engine_policies
from app.engine_policies import EnginePolicyReference, check, load, seed
from app.suggestions.confidence import components, numeric
from selfchecks.test_tb70_replay import integration, no_network  # noqa: F401

CONFIG = Path(__file__).resolve().parents[3] / "config"


def confidence(
    expr: str = "f.value > 10",
    passed: bool | None = True,
    views: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return components(
        refs=[{"rule_id": "R", "role": "entry", "passed": passed}],
        views=views or [],
        rules=[{"id": "R", "role": "entry", "expr": expr, "eval_time": "daily_close", **extra}],
        frame={"features": {"f.value": 15}, "series": {}, "context": {}},
        params={},
        registry={"f.value": {"unit": "%"}},
    )


def test_missing_components_are_zero_without_renormalization() -> None:
    result = confidence("f.value > 0")
    assert result == {
        "value": 0.5,
        "level": "medium",
        "components": {
            "data_completeness": 1.0,
            "dimension_agreement": None,
            "condition_margin": None,
            "margin_rules": [],
        },
    }
    assert confidence(passed=None)["value"] == 0


def test_margin_declared_threshold_and_false_rules() -> None:
    result = confidence(passed=False)
    assert result["components"]["condition_margin"] == 0.5
    assert result["components"]["margin_rules"][0]["scale_kind"] == "abs_threshold"
    assert confidence(margin_scale=2)["components"]["condition_margin"] == 1
    assert confidence(weight=0)["components"]["condition_margin"] is None


@pytest.mark.parametrize(
    "expr",
    [
        "f.value > 10 and f.value < 20",
        "f.value == True",
        "cross_up(f.value, 10)",
        "f.value > 10 for 2 days",
    ],
)
def test_non_single_numeric_rules_do_not_inflate_margin(expr: str) -> None:
    assert confidence(expr)["components"]["condition_margin"] is None


def test_directional_majority_excludes_neutral_and_unknown() -> None:
    result = confidence(
        views=[{"view": v} for v in ["bullish", "bullish", "bearish", "neutral", "unknown"]]
    )
    assert result["components"]["dimension_agreement"] == pytest.approx(2 / 3)
    assert result["value"] == 0.8
    assert result["level"] == "high"
    assert confidence(views=[{"view": "bearish"}])["components"]["dimension_agreement"] is None


@pytest.mark.parametrize("value", [True, None, "NaN", "Infinity", "not-a-number"])
def test_nonfinite_or_boolean_is_not_numeric(value: Any) -> None:
    assert numeric(value) is None


def test_reference_registry_separates_business_and_hash_excludes_version() -> None:
    original = load(CONFIG)
    altered = EnginePolicyReference.model_validate({**original.model_dump(), "version_no": 2})
    assert original.digest() == altered.digest()
    found = load_yaml_dir(CONFIG)
    assert "engine_policy" not in found
    check_config_dir_files(found, CONFIG)
    bad = original.model_dump()
    bad["version_no"] = True
    with pytest.raises(ValidationError):
        EnginePolicyReference.model_validate(bad)
    assert numeric(Decimal("1.25")) == Decimal("1.25")


def test_actual_isolated_seed_idempotence_and_same_version_conflict(integration: Any) -> None:
    engine, *_ = integration
    original = load(CONFIG)
    # Transaction rolls back; don't leave this seed or synthetic versions in the test DB.
    with engine.connect() as conn:
        transaction = conn.begin()
        row = conn.execute(select(engine_policies).where(engine_policies.c.version_no == 1)).first()
        inserted = seed(conn, original)
        assert inserted is (row is None)
        assert seed(conn, original) is False
        check(conn, original)
        bad = copy.deepcopy(original.model_dump())
        bad["system_components"][0]["version_no"] = 2
        altered = EnginePolicyReference.model_validate(bad)
        with pytest.raises(ValueError, match="engine_policy_version_hash_conflict"):
            seed(conn, altered)
        with pytest.raises(ValueError, match="engine_policy_version_hash_conflict"):
            check(conn, altered)
        transaction.rollback()


def test_previous_open_day_not_same_day_revision_and_removed_cleared(integration: Any) -> None:
    import datetime as dt
    import uuid

    from sqlalchemy import insert
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.db.tables.market import trading_calendar
    from app.db.tables.realtime import daily_reports
    from app.reports.comparison import apply

    engine, _, _, owner, _ = integration
    day, prior_day = dt.date(2026, 10, 30), dt.date(2026, 10, 29)

    def stock(code: str, risk: str | None = None) -> dict[str, Any]:
        return {
            "security_code": code,
            "name": "合成",
            "close": "10",
            "change_pct": "1",
            "data_status": "partial",
            "suggestion_id": None,
            "suggestion": None,
            "max_risk_level": risk,
            "change_from_previous": None,
            "change_fields": [],
            "highlights": [{"text": "合成", "expr": None, "evidence_ids": []}],
            "invalidation": [],
            "next_watch": [],
        }

    with engine.connect() as conn:
        transaction = conn.begin()
        conn.execute(
            pg_insert(trading_calendar)
            .values([{"date": prior_day, "is_open": True}, {"date": day, "is_open": True}])
            .on_conflict_do_nothing()
        )
        # No previous finished report: neither "new" nor "removed" is asserted.
        initial = [stock("688018.SH")]
        assert apply(conn, owner, day, initial) is False
        assert initial[0]["change_from_previous"] is None
        base = [stock("688018.SH"), stock("688073.SH"), stock("300364.SZ")]
        conn.execute(
            insert(daily_reports).values(
                id=uuid.uuid4(),
                user_id=owner,
                trade_date=prior_day,
                revision=1,
                status="partial",
                body={"stocks": base},
            )
        )
        current = [stock("688018.SH", "warning"), stock("688073.SH"), stock("301218.SZ")]
        assert apply(conn, owner, day, current) is True
        indexed = {s["security_code"]: s for s in current}
        assert indexed["688018.SH"]["change_from_previous"] == "changed"
        assert indexed["688018.SH"]["change_fields"] == ["max_risk_level"]
        assert indexed["688073.SH"]["change_from_previous"] == "unchanged"
        assert indexed["301218.SZ"]["change_from_previous"] == "new"
        removed = indexed["300364.SZ"]
        assert removed["change_from_previous"] == "removed"
        assert removed["close"] is None
        assert removed["suggestion"] is None
        assert removed["highlights"] == []
        assert removed["change_fields"] == []
        conn.execute(
            insert(daily_reports).values(
                id=uuid.uuid4(),
                user_id=owner,
                trade_date=day,
                revision=1,
                status="partial",
                body={"stocks": current},
            )
        )
        rerun = [stock("688018.SH", "warning"), stock("688073.SH"), stock("301218.SZ")]
        assert apply(conn, owner, day, rerun) is True
        assert rerun == current
        transaction.rollback()


def test_atr_scale_comes_from_the_existing_wilder_dsl_and_declared_scale_wins() -> None:
    rule = {"id": "R", "role": "entry", "expr": "f.close_qfq > 10", "eval_time": "daily_close"}
    arguments = {
        "refs": [{"rule_id": "R", "role": "entry", "passed": True}],
        "views": [],
        "rules": [rule],
        "frame": {
            "features": {},
            "series": {"f.close_qfq": [15] * 30, "f.high_qfq": [16] * 30, "f.low_qfq": [14] * 30},
            "context": {},
        },
        "params": {},
        "registry": {"f.close_qfq": {"unit": "元"}},
    }
    detail = components(**arguments)["components"]["margin_rules"][0]
    assert detail["scale_kind"] == "atr14"
    assert Decimal(detail["scale"]) == 2
    rule["margin_scale"] = 100
    detail = components(**arguments)["components"]["margin_rules"][0]
    assert detail["scale_kind"] == "declared"
    assert detail["margin"] == 0.05
