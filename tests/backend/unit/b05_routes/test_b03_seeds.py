"""Collect the original test_b03_seeds assertions in the backend CI scope."""

from selfchecks.test_b03_seeds import (
    bundle as bundle,
    no_network as no_network,
    test_b03_contract_and_semantic_negatives as test_b03_contract_and_semantic_negatives,
    test_b03_does_not_trust_a_tampered_bundle as test_b03_does_not_trust_a_tampered_bundle,
    test_b03_endpoint_skeleton_is_bounded as test_b03_endpoint_skeleton_is_bounded,
    test_b03_generator_is_reproducible_and_never_replaces_existing_data as test_b03_generator_is_reproducible_and_never_replaces_existing_data,
    test_b03_json_to_endpoint_skeleton_round_trip as test_b03_json_to_endpoint_skeleton_round_trip,
    test_b03_permission_negatives_never_expose_fixture_items as test_b03_permission_negatives_never_expose_fixture_items,
    test_b03_unreviewed_model_draft_is_not_accepted as test_b03_unreviewed_model_draft_is_not_accepted,
)
