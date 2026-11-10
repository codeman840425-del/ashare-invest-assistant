"""T-R42（T-R43 修订）：null / insufficient_data 参考层逻辑演示（**不构成 H18 证据**）。

**限制声明（T-R43，依 T-A83 B-1）**：本脚本**不读取夹具行情/特征来求值规则**——
不看 f.market_regime_idx、不按 features/series 数值计算 MA/ATR，也不比对夹具
expect.rule_ids_passed；它只按 K 线**根数**演示「预热不足 → passed=null →
insufficient_data」与「limit 价 null 不产生 LIMIT_LOCKED」这一参考层逻辑。
因此改动夹具 regime 或 rule_ids_passed 时本脚本**不会**失败（见输出 not_detected_by_design）。
G7 核对表 H18 据此保持「缺证据」；实盘/求值器 null 传播归编排者派后端。

输入：null_propagation_fixtures.json（从卡 validation 抽出的 H01-FX8 / S01-FX3，均【虚构】）。
`--mutate <name>`：对输入做真实篡改后走同一校验，须 exit 1 且原因对应被篡改项。
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FX_PATH = HERE / "null_propagation_fixtures.json"


class CheckFail(Exception):
    pass


def require(cond: object, msg: str) -> None:
    if not cond:
        raise CheckFail(msg)


def summarize(fx: dict) -> dict:
    require(str(fx.get("desc", "")).startswith("【虚构】"), f"fictitious:{fx.get('id')}")
    series = fx.get("series") or {}
    features = fx.get("features") or {}
    expect = fx.get("expect") or {}
    return {
        "id": fx["id"],
        "series_lens": {k: len(v) for k, v in series.items() if isinstance(v, list)},
        "limit_up": features.get("f.limit_up_price"),
        "limit_down": features.get("f.limit_down_price"),
        "expect": {"state": expect.get("state"), "action": expect.get("action")},
    }


def warmup_logic(n: int, warmup_bars: int, ready_state: str, action: str) -> dict:
    """只按根数：n < warmup → state=insufficient_data；预热相关规则 passed=null。"""
    return {"bars": n, "warmup_bars": warmup_bars, "warmup_rules_passed": None if n < warmup_bars else "not_evaluated",
            "state": "insufficient_data" if n < warmup_bars else ready_state, "action": action}


def check(data: dict) -> dict:
    require(data.get("fictitious") is True, "fictitious_flag")
    fx8 = summarize(data["fixtures"]["H01-FX8"])
    fx3 = summarize(data["fixtures"]["S01-FX3"])
    require(fx8["limit_up"] is None and fx8["limit_down"] is None, "H01-FX8:limit_null")
    require(fx8["series_lens"].get("f.close_qfq") == 3, "H01-FX8:bars")
    require(fx3["series_lens"].get("f.close_qfq") == 10, "S01-FX3:bars")
    h = warmup_logic(fx8["series_lens"]["f.close_qfq"], 62, "not_evaluated", "hold")  # H-01 MA60+缓冲
    s = warmup_logic(fx3["series_lens"]["f.close_qfq"], 25, "not_evaluated", "wait")  # 卡 st_pullback_ma:18
    require(h["state"] == fx8["expect"]["state"] and h["action"] == fx8["expect"]["action"], "H01-FX8:expect_state")
    require(s["state"] == fx3["expect"]["state"] and s["action"] == fx3["expect"]["action"], "S01-FX3:expect_state")
    return {"H01_FX8": h, "S01_FX3": s, "limit_null_produces_lock": False}


def _m(fid: str, path: tuple, value):
    def apply(d: dict) -> None:
        node = d["fixtures"][fid]
        for k in path[:-1]:
            node = node[k]
        node[path[-1]] = value
    return apply


MUTATIONS = {
    "fx8_limit_not_null": (_m("H01-FX8", ("features", "f.limit_up_price"), 36.52), "H01-FX8:limit_null"),
    "fx8_more_bars": (_m("H01-FX8", ("series", "f.close_qfq"), [30.0] * 70), "H01-FX8:bars"),
    "fx3_expect_not_triggered": (_m("S01-FX3", ("expect", "state"), "not_triggered"), "S01-FX3:expect_state"),
    "fx8_unfictitious": (_m("H01-FX8", ("desc",), "上市初期"), "fictitious:H01-FX8"),
}
NOT_DETECTED_BY_DESIGN = ["features.f.market_regime_idx 改动", "expect.rule_ids_passed 改动", "series 数值（非根数）改动"]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    data = json.loads(FX_PATH.read_text(encoding="utf-8"))
    if argv[:1] == ["--mutate"]:
        name = argv[1] if len(argv) > 1 else ""
        if name not in MUTATIONS:
            print(json.dumps({"error": "unknown mutation", "choices": sorted(MUTATIONS)}, ensure_ascii=False))
            return 2
        d = copy.deepcopy(data)
        MUTATIONS[name][0](d)
        try:
            check(d)
        except CheckFail as e:
            print(json.dumps({"result": "FAIL", "mutation": name, "reason": str(e)}, ensure_ascii=False))
            return 1
        print(json.dumps({"result": "MUTATION_NOT_DETECTED", "mutation": name}, ensure_ascii=False))
        return 0
    try:
        got = check(data)
        for name, (apply, tag) in MUTATIONS.items():
            d = copy.deepcopy(data)
            apply(d)
            try:
                check(d)
                reason = None
            except CheckFail as e:
                reason = str(e)
            require(reason == tag, f"mutation_not_rejected:{name}:{reason}")
    except CheckFail as e:
        print(json.dumps({"result": "FAIL", "reason": str(e)}, ensure_ascii=False))
        return 1
    print(json.dumps({
        "result": "PASS",
        "layer": "reference_logic_only_not_H18_evidence",
        "disclaimer": "不读取夹具行情/特征求值规则，只按根数演示预热→null→insufficient_data；不构成 H18 证据",
        "source": "docs/strategies/T-R42/null_propagation_fixtures.json",
        **got,
        "mutations_rejected": sorted(MUTATIONS),
        "not_detected_by_design": NOT_DETECTED_BY_DESIGN,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
