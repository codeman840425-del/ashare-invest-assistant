"""Run original test_tb134_t_view_db assertions in the CI-owned migrated database harness."""

from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from sqlalchemy import Engine

from selfchecks.test_tb134_t_view_db import (
    test_t_view_history_cached_once_per_day as test_t_view_history_cached_once_per_day,
    test_t_view_ignores_tdx_local as test_t_view_ignores_tdx_local,
    test_t_view_volume_ratio_null_not_cached as test_t_view_volume_ratio_null_not_cached,
    test_t_view_volume_ratio_skips_suspended_days as test_t_view_volume_ratio_skips_suspended_days,
)

from .test_auth_t_b03 import authdb as authdb


@pytest.fixture(scope="module")
def db(authdb: SimpleNamespace) -> Iterator[Engine]:
    assert authdb.name.startswith("tt01d_auth_")
    assert authdb.engine.url.database == authdb.name
    yield authdb.engine
