"""T-R31：F21 readiness 阈值锁定 + 篡改/覆盖拒绝（离线，无库、无凭证）。"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
import check_f21_ready as m  # noqa: E402


def test_load_ok():
    th = m.load_locked_thresholds()
    assert th["min_stocks"] == 5 and th["min_days"] == 15 and th["window_days"] == 20
    assert th["factor_id"] == "main_20d_net"
    assert th["feature_key"] == "f.main_net_20d"


def test_hash_tamper_rejected():
    raw = json.loads(m.THRESHOLDS_PATH.read_text())
    raw["min_stocks"] = 1  # tamper
    # Point loader at temp copies
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        p = td / "f21_ready_thresholds.json"
        h = td / "f21_ready_thresholds.sha256"
        p.write_text(json.dumps(raw, ensure_ascii=False, indent=2))
        # keep ORIGINAL hash → mismatch
        h.write_text(m.THRESHOLDS_HASH_PATH.read_text())
        old_p, old_h = m.THRESHOLDS_PATH, m.THRESHOLDS_HASH_PATH
        m.THRESHOLDS_PATH, m.THRESHOLDS_HASH_PATH = p, h
        try:
            try:
                m.load_locked_thresholds()
            except SystemExit as e:
                assert "hash mismatch" in str(e)
            else:
                raise AssertionError("tampered thresholds accepted")
        finally:
            m.THRESHOLDS_PATH, m.THRESHOLDS_HASH_PATH = old_p, old_h


def test_cli_override_rejected():
    for flag in ("--min-stocks", "--min-days", "--window-days", "--factor-id", "--thresholds"):
        try:
            m.reject_override_attempts([flag, "1"])
        except SystemExit as e:
            assert "rejected" in str(e), flag
        else:
            raise AssertionError(flag)


def test_env_override_rejected():
    k = "F21_READY_MIN_STOCKS"
    old = os.environ.get(k)
    os.environ[k] = "1"
    try:
        try:
            m.reject_override_attempts([])
        except SystemExit as e:
            assert k in str(e)
        else:
            raise AssertionError("env override accepted")
    finally:
        if old is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = old


def test_decide_ready_boundary():
    th = m.load_locked_thresholds()
    assert m.decide_ready({"stocks_with_min_days": 5}, th) is True
    assert m.decide_ready({"stocks_with_min_days": 4}, th) is False


def main() -> int:
    test_load_ok()
    test_hash_tamper_rejected()
    test_cli_override_rejected()
    test_env_override_rejected()
    test_decide_ready_boundary()
    print(json.dumps({
        "normal_threshold_load": "pass",
        "mutation_hash_rejected": 1,
        "mutation_cli_override_rejected": 5,
        "mutation_env_override_rejected": 1,
        "decide_ready_boundary": "5_pass_4_fail",
        "f21_status": "declared",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
