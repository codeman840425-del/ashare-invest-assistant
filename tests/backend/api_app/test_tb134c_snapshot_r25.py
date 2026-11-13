"""Run original test_tb134c_snapshot assertions in the CI-owned migrated database harness."""

from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from sqlalchemy import Engine

from selfchecks.test_tb134c_snapshot import (
    conn as conn,
    test_tb134c_calendar_hole_is_conservatively_stale as test_tb134c_calendar_hole_is_conservatively_stale,
    test_tb134c_empty_calendar_is_conservatively_stale as test_tb134c_empty_calendar_is_conservatively_stale,
    test_tb134c_existing_sellable_values_unchanged as test_tb134c_existing_sellable_values_unchanged,
    test_tb134c_ledger_account_sellable_unchanged as test_tb134c_ledger_account_sellable_unchanged,
    test_tb134c_permission_negative_account_scope as test_tb134c_permission_negative_account_scope,
    test_tb134c_portfolio_sellable_zero_when_today_snapshot_lacks_sellable as test_tb134c_portfolio_sellable_zero_when_today_snapshot_lacks_sellable,
    test_tb134c_portfolio_snapshot_boundary as test_tb134c_portfolio_snapshot_boundary,
    test_tb134c_same_gap_deduplicated_across_codes as test_tb134c_same_gap_deduplicated_across_codes,
    test_tb134c_snapshot_stale_uses_previous_open_day as test_tb134c_snapshot_stale_uses_previous_open_day,
    test_tb134c_snapshot_time_without_zone_is_not_preopen as test_tb134c_snapshot_time_without_zone_is_not_preopen,
    test_tb134c_t_view_snapshot_matches_portfolio_safety as test_tb134c_t_view_snapshot_matches_portfolio_safety,
)

from .test_auth_t_b03 import authdb as authdb


@pytest.fixture(scope="module")
def engine(authdb: SimpleNamespace) -> Iterator[Engine]:
    assert authdb.name.startswith("tt01d_auth_")
    assert authdb.engine.url.database == authdb.name
    yield authdb.engine
