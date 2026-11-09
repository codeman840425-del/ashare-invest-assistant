"""T-R43：S-01（st_pullback_ma v1）夹具确定性复算（研究侧参考求值器，非业务代码）。

读取 cards/st_pullback_ma.md 的 strategy-spec（参数默认值、规则 expr）与 validation.fixtures，
**按夹具 series/features/holding/ctx/plan 实际求值**每条规则，复算 state/action/rule_ids_passed/
reason_codes，并与卡上 expect 逐项比对。用于 G7 核对表 S7（C1/C2 正例 S01-FX9/FX10）。

- 规则 expr 文本须与本求值器实现的文本逐字一致（卡上 expr 被改动 → 失败 expr_mismatch:<id>）。
- 求值语义只取卡面：pct_change(x,n)=x[-1]/x[-1-n]-1；ma(x,n)=末 n 根均值；窗口不足 → null；
  未持有时 X1–X3 不进入结论（X2/X3 缺 plan/ctx → null）；优先级见卡:13。
- 不读库、不调麦蕊、不 import 业务代码；夹具数值均【虚构】。参考层复算 ≠ T-B71 执行器实跑。
- 校验不用 assert（python -O 一致）；`--mutate <name>` 对输入做真实篡改后走同一校验，须 exit 1 且报对应原因。
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CARD = HERE.parent / "cards" / "st_pullback_ma.md"

EXPR = {
    "E1": "pct_change(f.close_qfq, 20) >= p.rs_min",
    "E2": "ma(f.close_qfq, 5) > ma(f.close_qfq, 10) and ma(f.close_qfq, 10) > ma(f.close_qfq, 20)",
    "E3": "f.low_qfq <= ma(f.close_qfq, 10) * (1 + p.touch_pct) and f.close_qfq >= ma(f.close_qfq, 10)",
    "E4": "f.amount < ma(f.amount, 5) * p.shrink_ratio",
    "F1": "ma(f.amount, 20) >= p.min_amount",
    "F2": "f.list_days >= p.min_list_days",
    "V1": "f.market_regime_idx == 'downtrend'",
    "C1": "pct_change(f.close_qfq, 1) < -0.05",
    "C2": "f.amount > ma(f.amount, 20) * 1.5",
    "I1": "ma(f.close_qfq, 5) < ma(f.close_qfq, 10)",
    "X1": "f.close_qfq < ma(f.close_qfq, 10) for p.exit_confirm_days days",
    "X2": "f.close_qfq <= plan.entry_price_qfq * (1 - p.hard_stop_pct)",
    "X3": "ctx.holding_days >= p.time_stop and ctx.max_r_reached < 1",
}
WARMUP = 25  # 卡:18「warmup 25 根有效日 K」


class CheckFail(Exception):
    pass


def require(cond: object, msg: str) -> None:
    if not cond:
        raise CheckFail(msg)


def load_card(text: str) -> tuple[dict, dict]:
    spec = re.findall(r"```yaml strategy-spec\n(.*?)```", text, re.S)
    val = re.findall(r"```yaml validation\n(.*?)```", text, re.S)
    require(len(spec) == 1 and len(val) == 1, "blocks")
    return yaml.safe_load(spec[0]), yaml.safe_load(val[0])


def ma(x: list, n: int, end: int | None = None):
    x = x if end is None else x[: end + 1]
    return None if len(x) < n else sum(x[-n:]) / n


def pct(x: list, n: int):
    return None if len(x) < n + 1 else x[-1] / x[-1 - n] - 1


def AND(*v):
    if any(a is False for a in v):
        return False
    return None if any(a is None for a in v) else True


def cmp(a, b, op):
    if a is None or b is None:
        return None
    return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]


def evaluate(fx: dict, p: dict) -> dict:
    s, f = fx["series"], fx["features"]
    c, lo, am = s["f.close_qfq"], s["f.low_qfq"], s["f.amount"]
    held = "holding" in fx
    ctx, plan = fx.get("ctx") or {}, fx.get("plan") or {}
    m5, m10, m20 = ma(c, 5), ma(c, 10), ma(c, 20)
    r = {}
    r["E1"] = cmp(pct(c, 20), p["rs_min"], ">=")
    r["E2"] = AND(cmp(m5, m10, ">"), cmp(m10, m20, ">"))
    r["E3"] = AND(cmp(lo[-1], None if m10 is None else m10 * (1 + p["touch_pct"]), "<="), cmp(c[-1], m10, ">="))
    a5 = ma(am, 5)
    r["E4"] = cmp(am[-1], None if a5 is None else a5 * p["shrink_ratio"], "<")
    r["F1"] = cmp(ma(am, 20), p["min_amount"], ">=")
    r["F2"] = cmp(f.get("f.list_days"), p["min_list_days"], ">=")
    reg = f.get("f.market_regime_idx")
    r["V1"] = None if reg is None else reg == "downtrend"
    r["C1"] = cmp(pct(c, 1), -0.05, "<")
    a20 = ma(am, 20)
    r["C2"] = cmp(am[-1], None if a20 is None else a20 * 1.5, ">")
    r["I1"] = cmp(m5, m10, "<")
    k = p["exit_confirm_days"]
    r["X1"] = AND(*[cmp(c[i], ma(c, 10, i), "<") for i in range(len(c) - k, len(c))]) if len(c) >= k else None
    ep = plan.get("plan.entry_price_qfq")
    r["X2"] = None if ep is None else c[-1] <= ep * (1 - p["hard_stop_pct"])
    hd, mr = ctx.get("ctx.holding_days"), ctx.get("ctx.max_r_reached")
    r["X3"] = None if hd is None or mr is None else (hd >= p["time_stop"] and mr < 1)
    passed = [rid for rid in r if r[rid] is True]
    codes: list[str] = []
    if held:
        state = "exit_signal" if any(r[x] for x in ("X1", "X2", "X3")) else "hold_ok"
        action = "sell" if state == "exit_signal" else "hold"
        if action == "sell":
            if f.get("f.is_suspended"):
                codes.append("SUSPENDED")
            if f.get("f.limit_locked_down"):
                codes.append("LIMIT_LOCKED")
            if (fx["holding"].get("sellable") or 0) < fx["holding"].get("qty", 0):
                codes.append("T1_NOT_SELLABLE")
    else:
        core = [r[x] for x in ("E1", "E2", "E3", "E4", "F1", "F2", "V1")]
        if r["V1"] is True:
            state = "vetoed"
        elif len(c) < WARMUP or any(v is None for v in core):
            state = "insufficient_data"
        elif all(r[x] for x in ("E1", "E2", "E3", "E4", "F1", "F2")):
            state = "entry_ok"
        else:
            state = "not_triggered"
        action = "buy" if state == "entry_ok" else "wait"
        if action == "buy":
            if f.get("f.limit_locked_up"):
                codes.append("LIMIT_LOCKED")
            if f.get("f.is_suspended"):
                codes.append("SUSPENDED")
    return {"state": state, "action": action, "rule_ids_passed": passed, "reason_codes": codes, "rules": r}


def check(text: str) -> dict:
    spec, val = load_card(text)
    rules = {x["id"]: x["expr"] for x in spec["rules"]}
    require(set(rules) == set(EXPR), f"rule_set {sorted(rules)}")
    for rid, e in EXPR.items():
        require(rules[rid] == e, f"expr_mismatch:{rid}")
    p = {k: v["default"] for k, v in spec["params_schema"].items()}
    rows, counter_hits = [], {"C1": [], "C2": []}
    for fx in val["fixtures"]:
        require(str(fx.get("desc", "")).startswith("【虚构】"), f"fictitious:{fx.get('id')}")
        got = evaluate(fx, p)
        ex = fx["expect"]
        for key in ("state", "action", "rule_ids_passed"):
            require(got[key] == ex[key], f"{fx['id']}:{key} got={got[key]} expect={ex[key]}")
        require(got["reason_codes"] == ex.get("reason_codes", []), f"{fx['id']}:reason_codes got={got['reason_codes']}")
        for cid in counter_hits:
            if cid in got["rule_ids_passed"]:
                counter_hits[cid].append(fx["id"])
        rows.append({"id": fx["id"], "state": got["state"], "rule_ids_passed": got["rule_ids_passed"]})
    require(counter_hits["C1"], "no_C1_positive_fixture")
    require(counter_hits["C2"], "no_C2_positive_fixture")
    return {"fixtures": rows, "counter_positive": counter_hits}


def _set_last(fid: str, key: str, value: float):
    def m(v: dict) -> None:
        fx = next(x for x in v["fixtures"] if x["id"] == fid)
        fx["series"][key][-1] = value
    return m


def _set(fid: str, path: tuple, value):
    def m(v: dict) -> None:
        node = next(x for x in v["fixtures"] if x["id"] == fid)
        for k in path[:-1]:
            node = node[k]
        node[path[-1]] = value
    return m


# name -> (mutation on validation dict | expr text replace, expected failure substring)
MUTATIONS = {
    "fx9_no_drop": (_set_last("S01-FX9", "f.close_qfq", 14.4), "S01-FX9:"),
    "fx10_no_volume": (_set_last("S01-FX10", "f.amount", 100000000.0), "S01-FX10:"),
    "fx4_regime_range": (_set("S01-FX4", ("features", "f.market_regime_idx"), "range"), "S01-FX4:state"),
    "fx1_expect_drop_e4": (_set("S01-FX1", ("expect", "rule_ids_passed"), ["E1", "E2", "E3", "F1", "F2"]), "S01-FX1:rule_ids_passed"),
    "fx3_expect_state": (_set("S01-FX3", ("expect", "state"), "not_triggered"), "S01-FX3:state"),
    "fx5_drop_reason": (_set("S01-FX5", ("expect", "reason_codes"), []), "S01-FX5:reason_codes"),
    "fx2_unfictitious": (_set("S01-FX2", ("desc",), "入场"), "fictitious:S01-FX2"),
    "c1_expr": ("pct_change(f.close_qfq, 1) < -0.05", "expr_mismatch:C1"),
}


def mutated_text(text: str, name: str) -> str:
    how, _ = MUTATIONS[name]
    if isinstance(how, str):
        return text.replace(how, how.replace("-0.05", "-0.03"), 1)
    head, body, tail = re.split(r"(?<=```yaml validation\n)(.*?)(?=```)", text, maxsplit=1, flags=re.S)
    v = copy.deepcopy(yaml.safe_load(body))
    how(v)
    return head + yaml.safe_dump(v, allow_unicode=True, sort_keys=False) + tail


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    text = CARD.read_text(encoding="utf-8")
    if argv[:1] == ["--mutate"]:
        name = argv[1] if len(argv) > 1 else ""
        if name not in MUTATIONS:
            print(json.dumps({"error": "unknown mutation", "choices": sorted(MUTATIONS)}, ensure_ascii=False))
            return 2
        try:
            check(mutated_text(text, name))
        except CheckFail as e:
            print(json.dumps({"result": "FAIL", "mutation": name, "reason": str(e)}, ensure_ascii=False))
            return 1
        print(json.dumps({"result": "MUTATION_NOT_DETECTED", "mutation": name}, ensure_ascii=False))
        return 0
    try:
        out = check(text)
        rejected = {}
        for name, (_, tag) in MUTATIONS.items():
            try:
                check(mutated_text(text, name))
                reason = None
            except CheckFail as e:
                reason = str(e)
            require(reason is not None and tag in reason, f"mutation_not_rejected:{name}:{reason}")
            rejected[name] = reason
    except CheckFail as e:
        print(json.dumps({"result": "FAIL", "reason": str(e)}, ensure_ascii=False))
        return 1
    print(json.dumps({"result": "PASS", "layer": "reference_recompute_from_fixture_inputs", **out,
                      "mutations_rejected": len(rejected), "limit": "参考层复算，不等于 T-B71 执行器实跑"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
