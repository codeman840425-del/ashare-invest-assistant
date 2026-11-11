"""Fund flows endpoint checks, including a fully explicit synthetic open-day calendar."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text

from app.api.v1.security_fund_flows import FlowsQuery, get_flows_reader, validate_range
from app.auth import deps
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


def flows_window(body: dict[str, Any], query: FlowsQuery) -> dict[str, Any]:
    rows = [
        row
        for row in body["items"]
        if (query.start is None or row["trade_date"] >= query.start.isoformat())
        and (query.end is None or row["trade_date"] <= query.end.isoformat())
    ]
    body["items"] = rows[-query.days :] if query.days is not None else rows
    return empty_window(body)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    with environment(monkeypatch, "fund-flows", get_flows_reader, flows_window) as value:
        engine = value.app.dependency_overrides[deps.get_engine]()
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE market.trading_calendar (date DATE PRIMARY KEY, is_open BOOLEAN)"
                )
            )
            # Every civil date here is explicitly synthetic/open, not an inferred real calendar.
            conn.execute(
                text("INSERT INTO market.trading_calendar VALUES (:d, :o)"),
                [
                    {"d": (dt.date(2026, 1, 1) + dt.timedelta(days=i)).isoformat(), "o": True}
                    for i in range(365)
                ],
            )

        def checked(body: dict[str, Any], query: FlowsQuery) -> dict[str, Any]:
            validate_range(engine, query)
            return flows_window(body, query)

        value.reader.transform = checked
        value.engine = engine
        yield value


def test_b05_flows_shape_decimal_and_missing_values(env: Any) -> None:
    result = env.client.get(env.path)
    assert result.status_code == 200
    body = result.json()
    validate("fund-flows", body, set())
    assert [row["trade_date"] for row in body["items"]] == ["2026-11-02", "2026-11-03"]
    assert body["items"][0]["main_net"] == "1500000.00"
    assert body["items"][1]["main_net"] is None
    assert body["items"][1]["is_final"] is False
    limited = env.client.get(env.path + "?days=1").json()
    assert [row["trade_date"] for row in limited["items"]] == ["2026-11-03"]
    bounded = env.client.get(env.path + "?from=2026-11-02&to=2026-11-02").json()
    assert len(bounded["items"]) == 1
    assert bounded["items"][0]["trade_date"] == "2026-11-02"
    empty = env.client.get(env.path + "?from=2026-01-01&to=2026-01-02").json()
    assert empty["items"] == []
    assert empty["data_as_of"] is None


def test_b05_flows_actual_calendar_limit_and_hole(env: Any) -> None:
    start = dt.date(2026, 1, 1)
    day250 = (start + dt.timedelta(days=249)).isoformat()
    day251 = (start + dt.timedelta(days=250)).isoformat()
    assert env.client.get(env.path + "?from=2026-01-01&to=" + day250).status_code == 200
    too_long = env.client.get(env.path + "?from=2026-01-01&to=" + day251)
    assert too_long.status_code == 400
    with env.engine.begin() as conn:
        conn.execute(
            text("UPDATE market.trading_calendar SET is_open=0 WHERE date=:d"), {"d": day251}
        )
    assert env.client.get(env.path + "?from=2026-01-01&to=" + day251).status_code == 200
    with env.engine.begin() as conn:
        conn.execute(text("DELETE FROM market.trading_calendar WHERE date=:d"), {"d": day250})
    hole = env.client.get(env.path + "?from=2026-01-01&to=" + day251)
    assert hole.status_code == 503
    assert hole.json()["error"]["code"] == "CALENDAR_NOT_COVERED"


@pytest.mark.parametrize(
    "query",
    [
        "?days=0",
        "?days=251",
        "?days=no",
        "?days=1.2",
        "?days=" + "9" * 5000,
        "?days=1&days=2",
        "?from=2026-02-30&to=2026-03-01",
        "?from=2026-11-02",
        "?to=2026-11-02",
        "?from=2026-11-03&to=2026-11-02",
        "?days=1&from=2026-11-02&to=2026-11-03",
        "?from=2026-11-02&from=2026-11-03&to=2026-11-03",
    ],
)
def test_b05_flows_invalid_400(env: Any, query: str) -> None:
    response = env.client.get(env.path + query)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.headers["cache-control"] == "private, no-store"


def test_b05_flows_auth(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    check_access(env, monkeypatch)


def test_b05_flows_owner_etag(env: Any) -> None:
    check_scope(env)


def test_b05_flows_default_and_oldcode(env: Any) -> None:
    check_defaults(env)


@pytest.mark.parametrize("mode", ["staging", "production"])
def test_b05_flows_production_guard(env: Any, mode: str) -> None:
    check_guard(env, mode)


@pytest.mark.parametrize(("code", "reason"), [(ETF, "not_applicable"), (INDEX, "no_source")])
def test_b05_flows_empty_types(env: Any, code: str, reason: str) -> None:
    response = env.client.get(env.path.replace(STOCK, code))
    assert response.status_code == 200
    validate("fund-flows", response.json(), set())
    assert response.json()["items"] == []
    assert response.json()["gaps"][0]["reason"] == reason
