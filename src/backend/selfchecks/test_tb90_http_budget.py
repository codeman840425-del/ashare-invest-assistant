"""Budget correction: synthetic proof of ZERO I/O until one-vs-three is ruled.

No DB, Redis, network, credential/environment reads or temporary file creation.
Do not monkeypatch the limit upward to claim deployment authorization.
"""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pytest

from app.ingest import daily_lists as ingest
from app.master import daily_delivery as daily


class NoIO:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError("unexpected I/O boundary: " + name)


def test_dispatch_one_is_not_http_one() -> None:
    assert len(daily.LISTS) == 3
    assert len(ingest.PATHS) == 3
    assert daily.DAILY_HTTP_LIMIT == 1
    assert daily.live_budget_issue() == "daily_http_budget_unresolved"


def test_no_receipt_can_start_dispatch_or_collection() -> None:
    io: Any = NoIO()
    now = dt.datetime(2031, 1, 2, 10, tzinfo=dt.UTC)
    # Even a supplied server-side grant object cannot authorize three requests.
    assert daily.request(io, io, now) is None
    assert daily.publish_pending(io, io) == 0
    assert ingest.tick(io, io, grant=io) == 0
    assert (
        ingest.process(io, uuid.uuid4(), io, clock=lambda: now, upstream=io, secret_loader=io)
        == "budget_contract_unresolved"
    )


def test_low_level_http_is_closed_before_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("must not construct HTTP connection")

    monkeypatch.setattr(ingest.http.client, "HTTPSConnection", forbidden)
    with pytest.raises(ingest.DailyHaltError, match=r"^daily_http_budget_unresolved$"):
        ingest.wire("/synthetic/", "synthetic-not-a-credential")
