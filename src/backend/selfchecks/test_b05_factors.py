"""T-A158 HTTP null semantics, empty-category enforcement and synthetic leak negatives."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import uuid
from collections.abc import Iterator
from copy import deepcopy
from typing import Any

import pytest

from app.api.v1.security_factors import FactorsQuery, FactorsResponse, get_factors_reader
from app.auth.sessions import SESSION_COOKIE
from app.common.errors import AppError, ErrorCode
from app.schemas.enums import FactorCategory
from selfchecks.b03_shapes import validate as validate_b03_fixture
from selfchecks.b05_harness import (
    ETF,
    INDEX,
    STOCK,
    check_access,
    check_defaults,
    check_guard,
    environment,
)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    with environment(
        monkeypatch, "factors", get_factors_reader, lambda body, _query: body
    ) as value:
        value.seen_owners = []

        def empty_fixture(owner: uuid.UUID, code: str, query: FactorsQuery) -> dict[str, Any]:
            case = {STOCK: "stock", ETF: "etf", INDEX: "index"}.get(code)
            if case is None:
                raise AppError(ErrorCode.NOT_FOUND)
            value.seen_owners.append(owner)
            result = deepcopy(value.reader.bundle[case]["response"])
            # B-03 is input evidence only. Never publish its synthetic batch or category rows.
            result.update(
                items=[],
                sources=[],
                data_status="unavailable",
                data_as_of=None,
                trade_date=query.trade_date,
                factor_set_version=None,
                counts={"total": 0, "by_category": {}},
                gaps=[
                    {
                        "key": "factors",
                        "reason": "not_applicable" if case == "etf" else "no_source",
                        "message": "合成输入投影为可信空态",
                    }
                ],
            )
            return result

        monkeypatch.setattr(value.reader, "read", empty_fixture)
        yield value


def check_null_body(body: dict[str, Any], requested: str | None, reason: str) -> None:
    FactorsResponse.model_validate(body)
    assert set(body) == {
        "security_code",
        "name",
        "trade_date",
        "factor_set_version",
        "counts",
        "items",
        "sources",
        "data_status",
        "data_as_of",
        "gaps",
    }
    assert body["trade_date"] == requested
    assert body["factor_set_version"] is None
    assert body["counts"] == {"total": 0, "by_category": {}}
    assert body["items"] == []
    assert body["sources"] == []
    assert body["data_as_of"] is None
    assert body["data_status"] == "unavailable"
    assert body["gaps"][0]["key"] == "factors"
    assert body["gaps"][0]["reason"] == reason


@pytest.mark.parametrize(
    ("code", "reason"), [(STOCK, "no_source"), (ETF, "not_applicable"), (INDEX, "no_source")]
)
@pytest.mark.parametrize("requested", [None, "2026-11-03"])
def test_b05_factors_explicit_fixture_null_contract(
    env: Any,
    code: str,
    reason: str,
    requested: str | None,
) -> None:
    query = "" if requested is None else "?trade_date=" + requested
    response = env.client.get(env.path.replace(STOCK, code) + query)
    assert response.status_code == 200
    check_null_body(response.json(), requested, reason)
    assert response.headers["cache-control"] == "private, no-store"
    assert "synthetic-2-factors" not in response.text


@pytest.mark.parametrize(
    ("code", "reason"), [(STOCK, "no_source"), (ETF, "not_applicable"), (INDEX, "no_source")]
)
@pytest.mark.parametrize("requested", [None, "2026-11-03"])
def test_b05_factors_default_source_null_contract(
    env: Any,
    code: str,
    reason: str,
    requested: str | None,
) -> None:
    del env.app.dependency_overrides[get_factors_reader]
    query = "" if requested is None else "?trade_date=" + requested
    response = env.client.get(env.path.replace(STOCK, code) + query)
    assert response.status_code == 200
    check_null_body(response.json(), requested, reason)


@pytest.mark.parametrize(
    "query",
    [
        "?trade_date=2026-02-30",
        "?trade_date=20261103",
        "?trade_date=",
        "?trade_date=2026-11-03&trade_date=2026-11-04",
        "?category=momentum",
        "?category=liquidity",
        "?category=unknown",
        "?category=",
        "?category=a&category=b",
    ],
)
def test_b05_factors_invalid_date_or_category_400(env: Any, query: str) -> None:
    assert list(FactorCategory) == []
    response = env.client.get(env.path + query)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("case", ["raw_b03", "version", "counts", "date", "data_as_of"])
def test_b05_factors_rejects_synthetic_or_unproven_metadata(
    env: Any,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    if case == "raw_b03":
        body = deepcopy(env.reader.bundle["stock"]["response"])
        validate_b03_fixture("factors", body, set())
    else:
        body = env.client.get(env.path).json()
        if case == "version":
            body["factor_set_version"] = "synthetic-2-factors"
        elif case == "counts":
            body["counts"] = {"total": 0, "by_category": {"momentum": 0}}
        elif case == "date":
            body["trade_date"] = "2026-11-03"
        else:
            body["data_as_of"] = "2026-11-03T18:30:00+08:00"
    monkeypatch.setattr(env.reader, "read", lambda *_args: body)
    response = env.client.get(env.path)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "synthetic-2-factors" not in response.text
    assert "F-MOM-20D" not in response.text


def test_b05_factors_owner_derived_from_auth_and_etag(env: Any) -> None:
    first = env.client.get(env.path)
    assert first.status_code == 200
    cached = env.client.get(env.path, headers={"If-None-Match": first.headers["etag"]})
    assert cached.status_code == 304
    assert cached.headers["cache-control"] == "private, no-store"
    env.client.cookies.set(SESSION_COOKIE, "b")
    second = env.client.get(env.path + "?user_id=" + str(env.owners["a"]))
    assert second.status_code == 200
    assert env.seen_owners[-1] == env.owners["b"]
    env.client.cookies.clear()
    denied = env.client.get(env.path, headers={"If-None-Match": first.headers["etag"]})
    assert denied.status_code == 401


def test_b05_factors_auth_before_reader(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    check_access(env, monkeypatch)


def test_b05_factors_default_404_and_oldcode(env: Any) -> None:
    check_defaults(env)


@pytest.mark.parametrize("mode", ["staging", "production"])
def test_b05_factors_production_fixture_guard(env: Any, mode: str) -> None:
    check_guard(env, mode)
