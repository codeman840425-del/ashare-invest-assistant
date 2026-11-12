"""Collect the original test_b05_factors assertions in the backend CI scope."""

from selfchecks.test_b05_factors import (
    env as env,
    test_b05_factors_auth_before_reader as test_b05_factors_auth_before_reader,
    test_b05_factors_default_404_and_oldcode as test_b05_factors_default_404_and_oldcode,
    test_b05_factors_default_source_null_contract as test_b05_factors_default_source_null_contract,
    test_b05_factors_explicit_fixture_null_contract as test_b05_factors_explicit_fixture_null_contract,
    test_b05_factors_invalid_date_or_category_400 as test_b05_factors_invalid_date_or_category_400,
    test_b05_factors_owner_derived_from_auth_and_etag as test_b05_factors_owner_derived_from_auth_and_etag,
    test_b05_factors_production_fixture_guard as test_b05_factors_production_fixture_guard,
    test_b05_factors_rejects_synthetic_or_unproven_metadata as test_b05_factors_rejects_synthetic_or_unproven_metadata,
)
