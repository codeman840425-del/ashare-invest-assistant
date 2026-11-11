"""O-CI1: production type boundaries, with every network connection denied."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import redis
from fastapi import Request
from pydantic import ValidationError
from redis.client import PubSub
from sqlalchemy import Connection

from app.api.v1 import promotions
from app.config import Settings
from app.intraday.consumer import Consumer
from app.master import daily_delivery
from app.plans import api as plans
from app.plans.models import PlanInput
from app.strategy.cards.applicability import regime_source


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name, value in {
        "APP_ENV": "test",
        "DATABASE_URL": "",
        "REDIS_URL": "",
        "MAIRUI_MODE": "replay",
        "MAIRUI_BASE_URL": "http://127.0.0.1:9",
        "MAIRUI_PRO_BASE_URL": "http://127.0.0.1:9",
    }.items():
        monkeypatch.setenv(name, value)
    with patch("socket.socket.connect", side_effect=AssertionError("network denied")):
        yield


def require(condition: bool, message: str) -> None:
    if not condition:
        pytest.fail(message)


def test_regime_declared_source_and_missing_or_mixed_rejection() -> None:
    require(regime_source({}, {}) is None, "absent applicability must remain absent")
    for source in ("f.market_regime", "f.market_regime_idx"):
        card = {"data_needs": [{"feature_key": source}]}
        spec = {"applicability": {"market_regime": ["range"]}}
        require(regime_source(card, spec) == source, "declared source changed")
        from_rule = {**spec, "rules": [{"required_features": [source]}]}
        require(regime_source({}, from_rule) == source, "rule source changed")
        with pytest.raises(ValueError, match="bound_source_mismatch"):
            regime_source(card, {**spec, "applicability_eval_source": "different"})
    spec = {"applicability": {"market_regime": ["range"]}}
    with pytest.raises(ValueError, match="source_missing_or_mixed"):
        regime_source({}, spec)
    with pytest.raises(ValueError, match="source_missing_or_mixed"):
        regime_source(
            {},
            {**spec, "rules": [{"required_features": ["f.market_regime", "f.market_regime_idx"]}]},
        )


def cached_plan(*, revise: bool, cached: object) -> object:
    body = Mock(spec=PlanInput)
    body.model_dump.return_value = {"synthetic": True}
    auth, engine, rds = Mock(), Mock(), Mock()
    auth.user_id = uuid.uuid4()
    with patch.object(plans.idempotency, "run", return_value=(201, cached)) as run:
        if revise:
            result = plans.revise(uuid.uuid4(), body, auth, engine, rds, key="type-check")
        else:
            result = plans.create(body, auth, engine, rds, key="type-check")
        run.assert_called_once()
        require(run.call_args.kwargs["key"] == "type-check", "idempotency key changed")
        require(run.call_args.kwargs["payload"] == {"synthetic": True}, "payload changed")
        engine.begin.assert_not_called()
        return result


@pytest.mark.parametrize("revise", [False, True])
def test_cached_create_and_revision_keep_nested_values(revise: bool) -> None:
    cached = {"id": "synthetic", "optional": None, "nested": {"value": [1, False]}}
    require(cached_plan(revise=revise, cached=cached) == cached, "cached values changed")


@pytest.mark.parametrize("revise", [False, True])
@pytest.mark.parametrize("cached", [None, [], "invalid", {1: "invalid-key"}])
def test_cached_create_and_revision_reject_invalid_objects(revise: bool, cached: object) -> None:
    with pytest.raises(ValidationError):
        cached_plan(revise=revise, cached=cached)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("invalid", None),
        ("192.0.2.42", "192.0.2.0/24"),
        ("2001:db8:1234:5678::42", "2001:db8:1234:5678::/64"),
    ],
)
def test_coarse_ip_missing_invalid_ipv4_ipv6(raw: str | None, expected: str | None) -> None:
    request, settings = Mock(spec=Request), Mock(spec=Settings)
    with patch.object(promotions, "client_ip", return_value=raw):
        require(promotions.coarse_ip(request, settings) == expected, "coarse IP branch changed")


def test_coarse_ip_preserves_existing_value_error_boundary() -> None:
    with patch.object(promotions, "client_ip", side_effect=ValueError("invalid proxy")):
        require(
            promotions.coarse_ip(Mock(spec=Request), Mock(spec=Settings)) is None,
            "client IP ValueError must remain contained",
        )


@pytest.mark.parametrize("identifier", [1, 2**62])
def test_requested_outbox_preserves_database_integer_identity(identifier: int) -> None:
    conn = Mock(spec=Connection)
    conn.execute.return_value.first.side_effect = [
        SimpleNamespace(status="requested", master_run_id=identifier),
        SimpleNamespace(id=identifier, stats={"task": daily_delivery.KIND}, finished_at=None),
    ]
    result = daily_delivery.apply_batch(
        conn,
        uuid.uuid4(),
        now=dt.datetime.now(dt.UTC),
        cfg=Mock(),
        root=Path("."),
    )
    require(type(result) is int, "database ID must remain an integer")
    require(result == identifier, "database ID changed")
    require(conn.execute.call_count == 2, "requested batch unexpectedly applied")


def test_consumer_keeps_real_redis_client_and_pubsub_factory() -> None:
    client = redis.Redis(host="127.0.0.1", port=9)
    try:
        with patch.object(PubSub, "subscribe", autospec=True) as subscribe:
            consumer = Consumer(Settings(_env_file=None, app_env="test"), client)
            try:
                require(consumer.client is client, "Redis client identity changed")
                require(isinstance(consumer.pubsub, PubSub), "factory did not return real PubSub")
                require(consumer.pubsub.ignore_subscribe_messages, "subscribe filter changed")
                subscribe.assert_called_once_with(consumer.pubsub, "market.updated")
            finally:
                consumer.close()
    finally:
        client.close()
