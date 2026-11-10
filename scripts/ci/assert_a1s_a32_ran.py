#!/usr/bin/env python3
"""T-O67：断言 junit 里 A1s–A32 正式用例与 t_t41 已执行且未因缺 PG/URL 被 skip。"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# 正式验收函数名（tests/backend/unit 中 A1s–A32 + 编排者点名的 t_t41 文件）
REQUIRED: dict[str, tuple[str, ...]] = {
    "A1s": (
        "test_a1s_s1_tree_frozen_list_and_http_allow",
        "test_a1s_s1_positive_new_file_and_combo_flagged",
        "test_a1s_s2_tree_app_has_no_private_refs",
        "test_a1s_s2_positive_forms_flagged",
        "test_a1s_s2b_tree_allowed_refs",
        "test_a1s_s2b_positive_forms_flagged",
        "test_a1s_s3_tree_and_registered_exceptions",
        "test_a1s_s3_positive_forbidden_imports_flagged",
        "test_a1s_s4_tree_mairui_literal_only_egress_or_netguard",
        "test_a1s_s4_positive_literal_flagged",
        "test_a1s_s5_tree_daily_lists_seam_only",
        "test_a1s_s5_positive_inject_and_process_upstream_flagged",
        "test_a1s_s6_tree_app_clean_registered_probes_selfchecks",
        "test_a1s_s6_positive_dynamic_constructs_flagged",
        "test_a1s_no_dynamic_bypass_stack_in_this_module",
    ),
    "A1r": (
        "test_a1r_importlib_https_get_without_window",
        "test_a1r_getattr_https_get",
        "test_a1r_dunder_import_requests_split_domain",
        "test_a1r_socket_literal_public_ip",
        "test_a1r_urllib3_poolmanager_mairui_host",
        "test_a1r_lease_held_but_outside_window",
        "test_a1r_lease_thread_a_window_thread_b",
        "test_a1r_subprocess_curl_os_system_posix_spawn",
        "test_a1r_ctypes_cdll_libc",
        "test_a1r_hostname_connect_blocked",
        "test_a1r_cdll_none_and_pythonapi_connect",
        "test_a1r_sendto_and_tfo_blocked",
        "test_a1r_window_requires_validate_and_lease",
        "test_a1r_positive_window_fake_ip_is_oserror_not_blocked",
        "test_a1r_private_and_unix_unaffected",
        "test_a1r_main_installs_first_line_and_reinstall_noop",
    ),
    "A2-A27": (
        "test_a1_superseded_by_a1s_a1r",
        "test_a2_core_none_denies_zero_transport",
        "test_a3_third_ip_limit_escalation_denies",
        "test_a4_fake_103_writes_event_and_halt",
        "test_a5_rehydrate_db_down_denies",
        "test_a6a_ip_limit_lock_no_pending_denies_within_3s",
        "test_a6b_forged_lease_denied",
        "test_a7_licence_missing_deleted_inactive_deny",
        "test_a8_count_write_fail_pending_then_deny",
        "test_a9_transport_timeout_network_temp_cleared",
        "test_a10_token_bucket_second_denied",
        "test_a11_halt_present_no_lock_no_db",
        "test_a12_upstream_halted_no_rehydrate",
        "test_a13_no_lease_denies",
        "test_a14_r13_temp_cleanup_halt_preserved",
        "test_a15_tick_process_concurrent_bounded",
        "test_a16_deny_logs_omit_secret_and_url",
        "test_a17_bootstrap_and_tick_bounded_on_blackhole",
        "test_a18_ingest_profile_nullpool_connect_args",
        "test_a19_bad_url_with_fake_password_rc78_no_leak",
        "test_a20_settings_validation_rc78_no_leak",
        "test_a21_try_acquire_removed_docstring_matches_bounded_flush",
        "test_a21_flush_pending_bounded_when_lock_held",
        "test_a22_regression_prior_suites_collect",
        "test_a23_dash_o_import_smoke",
        "test_a24_transport_counts_and_https_get_unused",
        "test_a25_upstream_102_then_always_licence_unavailable",
        "test_a26_status_write_fail_fail_closed",
        "test_a27_no_vacuous_asserts_in_egress_tests",
    ),
    "A28-A32": (
        "test_a28_inject_registry_forged_item_denied",
        "test_a28_replace_mac_or_thread_id_denied",
        "test_a28_other_thread_uses_real_lease_denied",
        "test_a28_advisory_unlock_object_still_present_denied",
        "test_a29_pending_lock_contention_le_3s_one_connection",
        "test_a29_pending_savepoint_clears_only_after_outer_commit",
        "test_a29_blackhole_admit_denied_within_3s",
        "test_a30_persist_fail_writes_halt_and_restart_halt_present",
        "test_a30_halt_dir_unwritable_exit_74",
        "test_a30_bootstrap_halt_dir_unwritable_rc78_keeps_existing_halt",
        "test_a31_l9_flush_inject_keeps_pending",
        "test_a31_l9_flush_success_clears_pending_after_outer_commit",
        "test_a31_flush_ok_outer_commit_fails_keeps_pending",
        "test_a32_existing_temp_second_batch_new_trade_day",
    ),
    "t_t41": (
        "test_ta75_t1_delete_readd_escalates_same_user",
        "test_ta75_t3_user_reset_keeps_escalation",
        "test_ta75_t3_other_licence_same_user_blocked_during_escalation",
        "test_ta75_t2_restart_rehydrates_and_escalates",
        "test_ta75_t4_isolation_and_post_mark_recount",
        "test_ta75_t4_window_boundary_at_equals_now_minus_window_counts",
        "test_ta75_t5_events_and_logs_have_no_licence_material",
        "test_ta75_t6_fail_closed_on_rehydrate_error",
        "test_ta75_t6_fail_closed_on_record_hit_error",
        "test_ta79_b1_write_fail_then_recover_user_reset_keeps_pause",
        "test_ta79_b1_write_fail_then_recover_readd_keeps_pause",
        "test_ta79_l2_refuse_while_down_then_flush_count_on_recover",
        "test_ta81_l9_flush_then_restart_still_refuses",
        "test_ta81_l9_flush_fail_keeps_pending",
    ),
}

SKIP_HINTS = ("PGHOST", "PGPORT", "PGUSER", "TT41_DATABASE_URL", "TB116D_DATABASE_URL")


def _cases(path: Path) -> dict[str, dict[str, str]]:
    root = ET.parse(path).getroot()
    out: dict[str, dict[str, str]] = {}
    for case in root.iter("testcase"):
        name = case.attrib.get("name", "")
        # parameterized names: test_foo[bar]
        base = name.split("[", 1)[0]
        status = "passed"
        msg = ""
        if case.find("skipped") is not None:
            status = "skipped"
            msg = (case.find("skipped").attrib.get("message") or "") + (case.find("skipped").text or "")
        elif case.find("failure") is not None or case.find("error") is not None:
            status = "failed"
            node = case.find("failure") if case.find("failure") is not None else case.find("error")
            msg = (node.attrib.get("message") or "") if node is not None else ""
        out[base] = {"status": status, "message": msg, "classname": case.attrib.get("classname", "")}
    return out


def check(path: Path) -> list[str]:
    errs: list[str] = []
    cases = _cases(path)
    for group, names in REQUIRED.items():
        for name in names:
            row = cases.get(name)
            if row is None:
                errs.append(f"{group}: {name} 未出现在 junit（未被收集或路径未纳入 pytest）")
                continue
            if row["status"] == "skipped":
                msg = row["message"]
                if any(h in msg for h in SKIP_HINTS):
                    errs.append(f"{group}: {name} 因缺少 CI 服务/URL 被 skip：{msg[:200]}")
                else:
                    errs.append(f"{group}: {name} 被 skip：{msg[:200]}")
            # failed 由 pytest 步骤本身非零退出；这里仍记下便于汇总
            if row["status"] == "failed":
                errs.append(f"{group}: {name} 失败")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("junit")
    args = ap.parse_args()
    path = Path(args.junit)
    if not path.is_file():
        print(f"::error title=a1s-a32::没有 junit 文件 {path}", file=sys.stderr)
        return 1
    errs = check(path)
    if errs:
        for e in errs:
            print(f"::error title=a1s-a32::{e}")
        print(f"a1s-a32: {len(errs)} 处问题")
        return 1
    print("a1s-a32: OK（正式用例与 t_t41 均已执行、未因缺库 skip）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
