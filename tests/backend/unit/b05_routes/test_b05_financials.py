"""Collect the original test_b05_financials assertions in the backend CI scope."""

from selfchecks.test_b05_financials import (
    env as env,
    test_b05_financials_auth as test_b05_financials_auth,
    test_b05_financials_default_404_and_not_applicable as test_b05_financials_default_404_and_not_applicable,
    test_b05_financials_filters_and_limits as test_b05_financials_filters_and_limits,
    test_b05_financials_fixture_type_empty as test_b05_financials_fixture_type_empty,
    test_b05_financials_http_shape_and_asof as test_b05_financials_http_shape_and_asof,
    test_b05_financials_invalid_400 as test_b05_financials_invalid_400,
    test_b05_financials_owner_etag as test_b05_financials_owner_etag,
    test_b05_financials_production_fixture_guard as test_b05_financials_production_fixture_guard,
)
