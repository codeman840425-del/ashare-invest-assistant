"""Collect S2-6 owned daily-cache and ingest assertions in the backend CI scope."""

from selfchecks.test_s2_owned_daily_bars import (
    test_authorized_ingest_persists_same_grant_and_default_reader_consumes,
    test_daily_dates_pagination_and_no_relabelling,
    test_default_reader_returns_owned_daily_prices,
    test_invalid_grant_never_reaches_transport,
    test_read_never_writes_and_sql_errors_propagate,
    test_registered_http_uses_default_owned_reader,
    test_suspension_incomplete_future_and_calendar_gap,
    test_unavailable_or_replaced_certificate_cannot_reuse_cache,
    test_unowned_and_wrong_source_rows_are_never_used,
    world,
)

__all__ = [
    "test_authorized_ingest_persists_same_grant_and_default_reader_consumes",
    "test_daily_dates_pagination_and_no_relabelling",
    "test_default_reader_returns_owned_daily_prices",
    "test_invalid_grant_never_reaches_transport",
    "test_read_never_writes_and_sql_errors_propagate",
    "test_registered_http_uses_default_owned_reader",
    "test_suspension_incomplete_future_and_calendar_gap",
    "test_unavailable_or_replaced_certificate_cannot_reuse_cache",
    "test_unowned_and_wrong_source_rows_are_never_used",
    "world",
]
