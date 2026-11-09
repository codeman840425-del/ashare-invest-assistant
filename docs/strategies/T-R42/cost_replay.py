"""T-R42：H-01/S-01 成本滑点确定性回放（【虚构】序列 + 手算 oracle）。

参数仅取自卡上/正文已声明值；佣金「用户费率」卡上未写死 → 用例声明【虚构】测试费率，
并单独标注该缺口。不替代服务端；普通与 -O 一致；含篡改用例。
"""
from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES = HERE / "cost_replay_cases.json"


def fail(msg: object = "") -> None:
    """Explicit failure that survives python -O (unlike assert)."""
    raise AssertionError(msg)


def require(cond: object, msg: object = "") -> None:
    if not cond:
        fail(msg)


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
    abandon_on_cost: bool,
) -> dict:
    """Deterministic cost estimate for one 【虚构】 fill attempt.

    Returns actionability + fee breakdown. Exit/sell never abandons solely due to cost
    when abandon_on_cost is False (H-01 card prose).
    """
    require(side in ("buy", "sell"), side)
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
    # 离场不因成本放弃卖出
    if side == "sell" and not abandon_on_cost:
        cost_block = False
    else:
        cost_block = False  # 本模型无「成本过高则放弃」阈值（卡上未定义）
    if cost_block:
        executable = False
        reasons.append("COST_ABANDON")
    return {
        "executable": executable,
        "reasons": reasons,
        "fees": fees,
        "abandon_on_cost": abandon_on_cost,
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
        abandon_on_cost=bool(case.get("abandon_on_cost", False)),
    )


def run_cases(cases: list) -> int:
    passed = 0
    for c in cases:
        require(str(c.get("desc", "")).startswith("【虚构】"), c["id"])
        got = oracle(c)
        exp = c["expect"]
        require(got["executable"] == exp["executable"], f'{c["id"]} executable {got} != {exp}')
        require(got["reasons"] == exp["reasons"], f'{c["id"]} reasons {got["reasons"]} != {exp["reasons"]}')
        for k, v in exp.get("fees", {}).items():
            require(got["fees"].get(k) == v, f'{c["id"]} fee {k}: {got["fees"].get(k)} != {v}')
        passed += 1
    return passed


def main(argv: list[str] | None = None) -> int:
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    mutate = "--mutate" in argv
    data = json.loads(CASES.read_text(encoding="utf-8"))
    require(data.get("fictitious") is True, "cases.fictitious")
    cases = json.loads(json.dumps(data["cases"]))
    if mutate:
        # Plant wrong expect: under -O this path must exit≠0
        cases[0]["expect"] = dict(cases[0]["expect"])
        cases[0]["expect"]["executable"] = not cases[0]["expect"]["executable"]
        run_cases(cases)
        fail("mutation_accepted")
    passed = run_cases(cases)
    # embedded negative: flipped expect must diverge from oracle
    bad = json.loads(json.dumps(data["cases"][0]))
    bad["expect"] = dict(bad["expect"])
    bad["expect"]["executable"] = not bad["expect"]["executable"]
    got = oracle(data["cases"][0])
    require(got["executable"] != bad["expect"]["executable"], "planted expect flip must differ")
    out = {
        "result": "PASS",
        "cases_passed": passed,
        "param_sources": data["param_sources"],
        "gaps": data.get("gaps", []),
        "mutation_reject": True,
        "note": "run with --mutate to force exit≠0 under normal/-O",
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
