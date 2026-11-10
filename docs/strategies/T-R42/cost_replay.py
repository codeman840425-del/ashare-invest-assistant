"""T-R42：H-01/S-01 成本滑点确定性回放（【虚构】序列 + 手算 oracle）。

参数仅取自卡上/正文已声明值；佣金「用户费率」卡上未写死 → 用例声明【虚构】测试费率，
并单独标注该缺口。不替代服务端；普通与 -O 一致。

T-R43：删除 abandon_on_cost 死分支（原 :87-94，恒为 False）；本模型**不含**冲击成本
（卡 hold_risk_monitor.md:86-88 impact_tiers/max_participation_pct 未建模）与「成本过高放弃」
阈值（卡上未定义），二者登记为 gaps。`--mutate <name>` 对用例输入/期望做真实篡改后走同一校验，
须 exit 1 且原因指向被篡改用例与字段。
"""
from __future__ import annotations

import copy
import json
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES = HERE / "cost_replay_cases.json"


class CheckFail(Exception):
    """Explicit failure that survives python -O (unlike assert)."""


def require(cond: object, msg: str) -> None:
    if not cond:
        raise CheckFail(msg)


D = Decimal
Q2 = Decimal("0.01")


def money(x: Decimal) -> Decimal:
    return x.quantize(Q2, rounding=ROUND_HALF_UP)


def estimate_costs(
    *,
    side: str,
    qty: int,
    ref_price: Decimal,
    commission_rate: Decimal | None,
    stamp_duty_sell: Decimal,
    transfer_fee: Decimal,
    slippage_bp: Decimal,
    limit_up: Decimal | None,
    limit_down: Decimal | None,
    limit_locked: bool,
    sellable: int | None,
) -> dict:
    """Deterministic cost estimate for one 【虚构】 fill attempt.

    Returns actionability + fee breakdown. No cost-based abandonment exists in this model
    (H-01 card prose: 离场不因成本放弃卖出); impact cost is not modelled (gap).
    """
    require(side in ("buy", "sell"), f"side:{side}")
    notional = money(D(qty) * ref_price)
    slip = money(notional * (slippage_bp / D(10000)))
    transfer = money(notional * transfer_fee)
    stamp = money(notional * stamp_duty_sell) if side == "sell" else D("0.00")
    commission_gap = commission_rate is None
    if commission_rate is None:
        commission = None
    else:
        raw = money(notional * commission_rate)
        commission = max(raw, D("5.00"))  # 卡/正文：单笔最低 5 元
    fees = {
        "notional": str(notional),
        "slippage": str(slip),
        "transfer_fee": str(transfer),
        "stamp_duty": str(stamp),
        "commission": None if commission is None else str(commission),
        "commission_rate_gap": commission_gap,
    }
    reasons: list[str] = []
    executable = True
    if limit_locked:
        executable = False
        reasons.append("LIMIT_LOCKED")
    if side == "buy" and limit_up is not None and ref_price > limit_up:
        executable = False
        reasons.append("ABOVE_LIMIT_UP")
    if side == "sell" and limit_down is not None and ref_price < limit_down:
        executable = False
        reasons.append("BELOW_LIMIT_DOWN")
    if side == "sell" and sellable is not None and sellable < qty:
        executable = False
        reasons.append("T1_NOT_SELLABLE")
    return {
        "executable": executable,
        "reasons": reasons,
        "fees": fees,
    }


def oracle(case: dict) -> dict:
    return estimate_costs(
        side=case["side"],
        qty=case["qty"],
        ref_price=D(case["ref_price"]),
        commission_rate=None if case.get("commission_rate") is None else D(case["commission_rate"]),
        stamp_duty_sell=D(case["stamp_duty_sell"]),
        transfer_fee=D(case["transfer_fee"]),
        slippage_bp=D(case["slippage_bp"]),
        limit_up=None if case.get("limit_up") is None else D(case["limit_up"]),
        limit_down=None if case.get("limit_down") is None else D(case["limit_down"]),
        limit_locked=bool(case.get("limit_locked", False)),
        sellable=case.get("sellable"),
    )


def run_cases(cases: list) -> int:
    passed = 0
    for c in cases:
        require(str(c.get("desc", "")).startswith("【虚构】"), f'{c["id"]}:fictitious')
        got = oracle(c)
        exp = c["expect"]
        require(got["executable"] == exp["executable"], f'{c["id"]}:executable got={got["executable"]}')
        require(got["reasons"] == exp["reasons"], f'{c["id"]}:reasons got={got["reasons"]}')
        for k, v in exp.get("fees", {}).items():
            require(got["fees"].get(k) == v, f'{c["id"]}:fee.{k} got={got["fees"].get(k)} expect={v}')
        passed += 1
    return passed


def _m(cid: str, path: tuple, value):
    def apply(cases: list) -> None:
        node = next(c for c in cases if c["id"] == cid)
        for k in path[:-1]:
            node = node[k]
        node[path[-1]] = value
    return apply


# name -> (in-place mutation on a deep copy of cases, exact expected failure)
MUTATIONS = {
    "h14_1_stamp_expect": (_m("CR-H14-1", ("expect", "fees", "stamp_duty"), "6.26"), "CR-H14-1:fee.stamp_duty got=6.25 expect=6.26"),
    "h14_2_floor_removed": (_m("CR-H14-2", ("expect", "fees", "commission"), "0.30"), "CR-H14-2:fee.commission got=5.00 expect=0.30"),
    "h14_3_unlock": (_m("CR-H14-3", ("limit_locked",), False), "CR-H14-3:executable got=True"),
    "h14_4_sellable_full": (_m("CR-H14-4", ("sellable",), 100000), "CR-H14-4:executable got=True"),
    "s14_2_reason_dropped": (_m("CR-S14-2", ("expect", "reasons"), []), "CR-S14-2:reasons got=['LIMIT_LOCKED']"),
    "s14_1_unfictitious": (_m("CR-S14-1", ("desc",), "买入可成交"), "CR-S14-1:fictitious"),
}


def run_mutation(cases: list, name: str) -> str | None:
    mc = copy.deepcopy(cases)
    MUTATIONS[name][0](mc)
    try:
        run_cases(mc)
    except CheckFail as e:
        return str(e)
    return None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    data = json.loads(CASES.read_text(encoding="utf-8"))
    cases = data["cases"]
    if argv[:1] == ["--mutate"]:
        name = argv[1] if len(argv) > 1 else ""
        if name not in MUTATIONS:
            print(json.dumps({"error": "unknown mutation", "choices": sorted(MUTATIONS)}, ensure_ascii=False))
            return 2
        reason = run_mutation(cases, name)
        print(json.dumps({"result": "FAIL" if reason else "MUTATION_NOT_DETECTED", "mutation": name, "reason": reason}, ensure_ascii=False))
        return 1 if reason else 0
    try:
        require(data.get("fictitious") is True, "cases.fictitious")
        passed = run_cases(cases)
        for name, (_, tag) in MUTATIONS.items():
            reason = run_mutation(cases, name)
            require(reason is not None and reason.startswith(tag), f"mutation_not_rejected:{name}:{reason}")
    except CheckFail as e:
        print(json.dumps({"result": "FAIL", "reason": str(e)}, ensure_ascii=False))
        return 1
    print(json.dumps({
        "result": "PASS",
        "cases_passed": passed,
        "param_sources": data["param_sources"],
        "gaps": data.get("gaps", []),
        "mutations_rejected": sorted(MUTATIONS),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
