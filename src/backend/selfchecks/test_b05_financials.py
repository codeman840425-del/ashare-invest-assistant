"""Financials route/ownership/as-of checks using reviewed B-03 synthetic fixtures only."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from app.api.v1.security_financials import FinancialsQuery, get_financials_reader
from selfchecks.b03_shapes import validate
from selfchecks.b05_harness import (
    ETF,
    INDEX,
    STOCK,
    check_access,
    check_defaults,
    check_guard,
    check_scope,
    empty_window,
    environment,
)


def financial_window(body: dict[str, Any], query: FinancialsQuery) -> dict[str, Any]:
    rows = [
        row
        for row in body["items"]
        if (not query.periods or row["report_period"] in query.periods)
        and (
            query.as_of is None
            or (
                row["available_from"] is not None
                and row["available_from"] <= query.as_of.isoformat()
            )
        )
    ]
    body["items"] = sorted(rows, key=lambda row: row["period_end"], reverse=True)[: query.limit]
    return empty_window(body)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    with environment(monkeypatch, "financials", get_financials_reader, financial_window) as value:
        yield value


def test_b05_financials_http_shape_and_asof(env: Any) -> None:
    result = env.client.get(env.path)
    assert result.status_code == 200
    validate("financials", result.json(), set())
    row = result.json()["items"][0]
    assert row["revenue"] == "1234567890.00"
    assert row["net_profit_yoy_pct"] == "6.20"
    assert row["period_end"] < row["available_from"]
    hidden = env.client.get(env.path + "?as_of=2026-11-01").json()
    assert hidden["items"] == []
    assert hidden["data_as_of"] is None
    shown = env.client.get(env.path + "?as_of=2026-11-02").json()
    assert shown["items"] == [row]
    unknown = env.reader.bundle["stock"]["response"]["items"][0]
    unknown["available_from"] = None
    assert env.client.get(env.path + "?as_of=2026-11-02").json()["items"] == []


def test_b05_financials_filters_and_limits(env: Any) -> None:
    assert env.client.get(env.path + "?report_period=q1").json()["items"] == []
    mixed = env.client.get(env.path + "?report_period=q1&report_period=q3&limit=1")
    assert mixed.status_code == 200
    assert len(mixed.json()["items"]) == 1
    assert env.client.get(env.path + "?report_period=q1,q3").json()["items"]
    assert env.client.get(env.path + "?limit=40").status_code == 200


@pytest.mark.parametrize(
    "query",
    [
        "?limit=0",
        "?limit=41",
        "?limit=no",
        "?limit=1.2",
        "?limit=" + "9" * 5000,
        "?limit=1&limit=2",
        "?as_of=2026-02-30",
        "?as_of=20261102",
        "?as_of=2026-11-01&as_of=2026-11-02",
        "?report_period=unknown",
        "?report_period=",
    ],
)
def test_b05_financials_invalid_400(env: Any, query: str) -> None:
    result = env.client.get(env.path + query)
    assert result.status_code == 400
    assert result.json()["error"]["code"] == "VALIDATION_ERROR"
    assert result.headers["cache-control"] == "private, no-store"


def test_b05_financials_auth(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    check_access(env, monkeypatch)


def test_b05_financials_owner_etag(env: Any) -> None:
    check_scope(env)


def test_b05_financials_default_404_and_not_applicable(env: Any) -> None:
    check_defaults(env)


@pytest.mark.parametrize("mode", ["staging", "production"])
def test_b05_financials_production_fixture_guard(env: Any, mode: str) -> None:
    check_guard(env, mode)


@pytest.mark.parametrize(("code", "reason"), [(ETF, "not_applicable"), (INDEX, "no_source")])
def test_b05_financials_fixture_type_empty(env: Any, code: str, reason: str) -> None:
    result = env.client.get(env.path.replace(STOCK, code))
    assert result.status_code == 200
    validate("financials", result.json(), set())
    assert result.json()["items"] == []
    assert result.json()["gaps"][0]["reason"] == reason
