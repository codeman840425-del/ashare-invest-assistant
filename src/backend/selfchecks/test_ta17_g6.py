# ruff: noqa: S101
"""Only new null/empty-set/comparison boundaries, not the prior 26 golden fixtures."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.strategy.g6 import Overlap, compare, missing_history_gate
from app.strategy.promotions import public_review


@pytest.mark.parametrize("days", [None, 0, 119])
def test_short_history_never_becomes_zero(days: int | None) -> None:
    report = compare(days, {"688018.SH"}, [{"688018.SH"}])
    assert report.max_jaccard is None
    assert report.max_jaccard_null_reason == "no_history"
    assert missing_history_gate(True, report)["result"] == "warn"
    assert missing_history_gate(False, report)["result"] == "fail"


@pytest.mark.parametrize(
    ("own", "others"),
    [(set(), []), ({"688018.SH"}, []), ({"688018.SH"}, [set()]), (set(), [{"688073.SH"}])],
)
def test_empty_comparable_sets(own: set[str], others: list[set[str]]) -> None:
    report = compare(120, own, others)
    assert report.max_jaccard is None
    assert report.max_jaccard_null_reason == "no_comparable_set"
    assert (
        missing_history_gate(True, report)["detail"]["max_jaccard_null_reason"]
        == "no_comparable_set"
    )


def test_real_zero_and_strict_duplicate_threshold() -> None:
    assert compare(120, {"688018.SH"}, [{"688073.SH"}]).max_jaccard == "0"
    hits = {"688018.SH:2026-10-" + str(i) for i in range(1, 11)}
    boundary = compare(120, hits, [set(sorted(hits)[:9])])
    assert boundary.max_jaccard == "0.9"
    assert boundary.duplicate is False
    assert compare(120, hits, [set(), hits]).duplicate is True


@pytest.mark.parametrize(
    ("value", "reason"),
    [(None, None), ("0", "no_history"), ("NaN", None), (0, None), ("1.1", None), (None, "other")],
)
def test_invalid_null_pairs(value: object, reason: object) -> None:
    with pytest.raises(ValidationError):
        Overlap.model_validate({"max_jaccard": value, "max_jaccard_null_reason": reason})


def test_public_null_serialization_without_old_503() -> None:
    report = compare(None, set(), [])
    row = SimpleNamespace(
        decision="pending",
        gate_results=[missing_history_gate(True, report)],
        fixture_runs=[],
        g6_report={**report.model_dump(), "quota_delta_per_min": 0},
    )
    result = public_review(row)
    assert result["g6_report"]["max_jaccard"] is None
    assert result["g6_report"]["max_jaccard_null_reason"] == "no_history"
    assert result["gate_results"][0]["result"] == "warn"


def test_public_legacy_unexamined_reason_and_known_zero() -> None:
    legacy = {
        "max_jaccard": None,
        "trigger_rate": {"n": 0},
        "contract_gaps": [
            {"issue": "contract_requires_nonnull_decimal_but_unexamined_history_has_no_value"}
        ],
    }
    row = SimpleNamespace(
        decision="pending",
        gate_results=[{"gate": "G6", "result": "warn", "detail": {}}],
        fixture_runs=[],
        g6_report=legacy,
    )
    output = public_review(row)
    assert output["g6_report"]["max_jaccard_null_reason"] == "no_history"
    assert output["gate_results"][0]["detail"]["max_jaccard_null_reason"] == "no_history"
    assert "contract_gaps" in legacy
    row.g6_report = {"max_jaccard": "0"}
    assert public_review(row)["g6_report"]["max_jaccard_null_reason"] is None
