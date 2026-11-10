"""制度与费用，出处：方案 §6。"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from math import floor

TRANSFER_RATE = 0.00001
SLIPPAGE_BP = 10


def stamp_duty_rate(d: date) -> float:
    return 0.001 if d < date(2023, 8, 28) else 0.0005


def commission(amount: float, rate: float) -> float:
    return max(rate * amount, 5.0)


def impact_bp(participation_pct: float | None) -> int:
    if participation_pct is not None:
        for cap, bp in ((0.1, 0), (0.5, 5), (1.0, 15), (2.0, 30)):
            if participation_pct <= cap:
                return bp
    return 60


def board(exchange: str, symbol: str) -> str:
    if exchange == "SH" and symbol.startswith(("688", "689")):
        return "star"
    if exchange == "SZ" and symbol.startswith(("300", "301")):
        return "chinext"
    return "main"


def limit_pct(board: str, st: bool, d: date) -> float:
    if board in ("chinext", "star"):
        return 0.20
    return 0.05 if st and d < date(2026, 7, 6) else 0.10


def round_tick(x: float) -> float:
    return float(Decimal(repr(float(x))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def limit_prices(pc: float, pct: float) -> tuple[float, float]:
    return round_tick(pc * (1 + pct)), max(round_tick(pc * (1 - pct)), 0.01)


def lot_floor(board: str, notional: float, price: float) -> int:
    if board == "star":
        n = floor(notional / price)
        return n if n >= 200 else 0
    return floor(notional / price / 100) * 100


def ref_price(pc_raw: float, cash: float, pp: float, s: float, r: float) -> float:
    return (pc_raw - cash + pp * r) / (1 + s + r)
