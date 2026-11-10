"""Budget correction: synthetic proof of ZERO I/O until one-vs-three is ruled.

No DB, Redis, network, credential/environment reads or temporary file creation.
Do not monkeypatch the limit upward to claim deployment authorization.
"""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

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


def test_low_level_http_is_closed_before_connection() -> None:
    """T-B116b B-3 / T-A89: wire removed; budget still blocks before any transport."""
    assert not hasattr(ingest, "wire"), "daily_lists.wire must stay deleted (B-2)"
    assert daily.live_budget_issue() == "daily_http_budget_unresolved"
    assert daily.DAILY_HTTP_LIMIT == 1
    # process returns budget token without touching upstream/secret_loader I/O.
    assert (
        ingest.process(
            NoIO(),
            uuid.uuid4(),
            NoIO(),
            clock=lambda: dt.datetime(2031, 1, 2, 10, tzinfo=dt.UTC),
            upstream=NoIO(),
            secret_loader=NoIO(),
        )
        == "budget_contract_unresolved"
    )
