"""T-A53: three list requests are budgeted, but budget/mode is never authorization."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from app.config_files import IngestProductDaily
from app.ingest import daily_lists as ingest
from app.master import daily_delivery as daily


class NoIO:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError("unexpected I/O boundary: " + name)


def test_three_http_is_exactly_one_list_batch() -> None:
    assert len(daily.LISTS) == len(ingest.PATHS) == daily.DAILY_HTTP_LIMIT == 3
    assert daily.live_budget_issue() is None
    for changes in (
        {"list_max_http_per_day": 4},
        {"min_interval_s": 59},
        {"upstream_retry": 1},
        {"not_before": "17:59"},
        {"exclusive_lock": "another-lock"},
    ):
        with pytest.raises(ValidationError):
            IngestProductDaily.model_validate(changes)


def test_budget_cannot_open_replay_or_bypass_missing_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    io: Any = NoIO()
    now = dt.datetime(2031, 1, 2, 10, tzinfo=dt.UTC)
    monkeypatch.setenv("MAIRUI_MODE", "replay")
    assert ingest.tick(io, io, grant=io) == 0
    assert ingest.process(io, uuid.uuid4(), io, clock=lambda: now) == "live_transport_closed"
    monkeypatch.setenv("MAIRUI_MODE", "live")
    monkeypatch.setattr(ingest, "read_grant", lambda: None)
    assert ingest.process(io, uuid.uuid4(), None, clock=lambda: now) == "authorization_unavailable"


def test_low_level_http_requires_a_shared_write_ahead_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("must not construct HTTP connection")

    monkeypatch.setenv("MAIRUI_MODE", "live")
    monkeypatch.setattr(ingest.http.client, "HTTPSConnection", forbidden)
    with pytest.raises(ingest.DailyHaltError, match="live_transport_closed"):
        ingest.wire("/synthetic/", "synthetic-not-a-credential")
