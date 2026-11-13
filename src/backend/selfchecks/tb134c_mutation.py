"""T-B134c negative control: restore the two former unsafe behaviors in this pytest process."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import Connection

from app.api.v1 import portfolio as pf

_original_account = pf._account
_patch = pytest.MonkeyPatch()


def inflated_account(conn: Connection, account_id: uuid.UUID, today: dt.date) -> pf._Acc:
    account = _original_account(conn, account_id, today)
    if any(gap["message"] == pf.UNKNOWN_SELLABLE for gap in account.gaps):
        for position in account.positions.values():
            position.sellable = position.qty
    return account


def pytest_configure(config: pytest.Config) -> None:
    _patch.setattr(pf, "_account", inflated_account)
    _patch.setattr(pf, "snapshot_stale_message", lambda snapshot_at, previous_open: None)


def pytest_unconfigure(config: pytest.Config) -> None:
    _patch.undo()
