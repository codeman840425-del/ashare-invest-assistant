"""Collect the original test_b05_fund_flows assertions in the backend CI scope."""

from selfchecks.test_b05_fund_flows import (
    env as env,
    test_b05_flows_actual_calendar_limit_and_hole as test_b05_flows_actual_calendar_limit_and_hole,
    test_b05_flows_auth as test_b05_flows_auth,
    test_b05_flows_calendar_error_details as test_b05_flows_calendar_error_details,
    test_b05_flows_default_and_oldcode as test_b05_flows_default_and_oldcode,
    test_b05_flows_empty_types as test_b05_flows_empty_types,
    test_b05_flows_invalid_400 as test_b05_flows_invalid_400,
    test_b05_flows_owner_etag as test_b05_flows_owner_etag,
    test_b05_flows_production_guard as test_b05_flows_production_guard,
    test_b05_flows_shape_decimal_and_missing_values as test_b05_flows_shape_decimal_and_missing_values,
)
