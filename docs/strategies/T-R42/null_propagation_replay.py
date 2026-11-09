"""T-R42：null / insufficient_data 参考层回放（H18 及类似）。

输入：null_propagation_fixtures.json（从卡 validation 抽出的 H01-FX8 / S01-FX3，均【虚构】）。
确定性参考实现展示：预热不足 → rule passed=null → state=insufficient_data；
limit 价 null 不产生 LIMIT_LOCKED。覆盖参考层；实盘传播归编排者。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FX_PATH = HERE / "null_propagation_fixtures.json"


def fail(msg: object = "") -> None:
    raise AssertionError(msg)


def require(cond: object, msg: object = "") -> None:
    if not cond:
        fail(msg)


def summarize(fx: dict) -> dict:
    require(str(fx.get("desc", "")).startswith("【虚构】"), fx.get("id"))
    series = fx.get("series") or {}
    features = fx.get("features") or {}
    expect = fx.get("expect") or {}
    return {
        "id": fx["id"],
        "desc": fx["desc"],
        "series_lens": {k: len(v) for k, v in series.items() if isinstance(v, list)},
        "features": {
            "f.limit_up_price": features.get("f.limit_up_price"),
            "f.limit_down_price": features.get("f.limit_down_price"),
            "f.list_days": features.get("f.list_days"),
        },
        "expect": {"state": expect.get("state"), "action": expect.get("action")},
    }


def ref_eval_h01(fx: dict, warmup_bars: int = 62) -> dict:
    n = fx["series_lens"].get("f.close_qfq", 0)
    limit_up = fx["features"].get("f.limit_up_price")
    limit_down = fx["features"].get("f.limit_down_price")
    rules = {
        "X1": None,
        "X2": None if n < 15 else False,
        "W1": None if n < warmup_bars else False,
        "W2": False,
        "W3": False,
        "C1": True,
        "C2": None if n < 20 else False,
        "I1": None if n < warmup_bars else False,
    }
    warm_gap = n < warmup_bars
    return {
        "bars": n,
        "warmup_bars": warmup_bars,
        "limit_up_price": limit_up,
        "limit_down_price": limit_down,
        "limit_null": limit_up is None and limit_down is None,
        "limit_null_propagates_to_lock": False,
        "rule_passed": rules,
        "state": "insufficient_data" if warm_gap else "hold_ok",
        "action": "hold",
    }


def ref_eval_s01(fx: dict, warmup_bars: int = 25) -> dict:
    n = fx["series_lens"].get("f.close_qfq", 0)
    warm_gap = n < warmup_bars
    rules = {
        "E1": None if n < 21 else False,
        "E2": None if n < 20 else False,
        "E3": True if n >= 1 else None,
        "E4": None if n < 5 else False,
        "F1": None if n < 1 else True,
        "F2": True,
        "V1": True,
    }
    return {
        "bars": n,
        "warmup_bars": warmup_bars,
        "rule_passed": rules,
        "state": "insufficient_data" if warm_gap else "not_triggered",
        "action": "wait",
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    mutate = "--mutate" in argv
    data = json.loads(FX_PATH.read_text(encoding="utf-8"))
    require(data.get("fictitious") is True, "fictitious")
    fx8 = summarize(data["fixtures"]["H01-FX8"])
    fx3 = summarize(data["fixtures"]["S01-FX3"])
    require(fx8["features"]["f.limit_up_price"] is None, "FX8 limit_up null")
    require(fx8["features"]["f.limit_down_price"] is None, "FX8 limit_down null")
    require(fx8["series_lens"]["f.close_qfq"] == 3, "FX8 bars")
    require(fx3["series_lens"]["f.close_qfq"] == 10, "FX3 bars")

    h_got = ref_eval_h01(fx8)
    s_got = ref_eval_s01(fx3)
    require(h_got["state"] == fx8["expect"]["state"], f'H FX8 state {h_got["state"]}')
    require(h_got["action"] == fx8["expect"]["action"], "H FX8 action")
    require(s_got["state"] == fx3["expect"]["state"], f'S FX3 state {s_got["state"]}')
    require(s_got["action"] == fx3["expect"]["action"], "S FX3 action")
    require(h_got["rule_passed"]["W1"] is None, "W1 null")
    require(h_got["rule_passed"]["X2"] is None, "X2 null")
    require(s_got["rule_passed"]["E1"] is None, "E1 null")
    require(h_got["limit_null"] is True, "limit null flag")

    if mutate:
        require(h_got["state"] == "hold_ok", "mutation planted mismatch")
        fail("mutation_accepted")

    out = {
        "result": "PASS",
        "layer": "reference_only",
        "disclaimer": "覆盖参考层；实盘/求值器 null 传播归编排者（未改 src）",
        "source": "docs/strategies/T-R42/null_propagation_fixtures.json",
        "H01_FX8": {"fixture": fx8, "ref_eval": h_got},
        "S01_FX3": {"fixture": fx3, "ref_eval": s_got},
        "note": "run with --mutate to force exit≠0 under normal/-O",
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
