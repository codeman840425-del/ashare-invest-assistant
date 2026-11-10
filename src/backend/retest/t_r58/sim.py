"""真实腿与同持有期随机对照，出处：方案 §3、§4、§5、§7.2。"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import numpy as np

from . import features, rules

OK = 0
SUSPENDED = 1
EXCLUDED = 2
WARMUP = 3


@dataclass
class Event:
    ex_date: date
    cash: float
    pp: float
    s: float
    r: float


@dataclass
class StockInput:
    exchange: str
    symbol: str
    dates: list[date]
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray  # noqa: E741  §1 行情接口字段
    c: np.ndarray
    v: np.ndarray
    a: np.ndarray
    day_kind: np.ndarray
    st: np.ndarray
    events: list[Event]


@dataclass
class Segment:
    name: str
    start: date
    end: date
    embargo: bool = True


@dataclass
class Params:
    group: str
    k: float | None = None
    floor: float = 0.0
    d: float | None = None
    v: float | None = None
    revert_band: float = 0.5
    stop_mult: float = 1.5
    trend_abs_pct: float = 0.05
    min_edge_cost_mult: float = 2.0
    entry_start: str = "09:45"
    entry_end: str = "14:30"
    time_stop: str = "14:50"
    last_fill: str = "14:56"
    confirm: int = 2
    sigma_warmup: int = 30
    commission_rate: float = 0.00025
    notional: float = 50000.0
    fill_delay: int = 1
    directions: tuple[str, ...] = ("sell_first", "buy_first")


@dataclass
class Leg:
    symbol: str
    segment: str
    entry_day: int
    direction: str
    trigger_slot: int
    entry_slot: int
    entry_price: float
    exit_trigger_day: int
    exit_trigger_slot: int
    exit_day: int | None
    exit_slot: int | None
    exit_price: float | None
    reason: str
    q: int
    notional: float
    planned_amount: float
    participation_pct: float | None
    impact_bp_frozen: int
    theta: float
    sigma: float
    dev: float
    vr: Decimal | None
    commission: float
    stamp: float
    transfer: float
    slippage: float
    impact: float
    pnl_yuan: float
    pnl_bp: float
    cons_pnl_yuan: float
    cons_pnl_bp: float
    cons_mark_price: float | None
    prior_anomaly: bool
    exec_anomaly: bool
    hold_bars: int | None
    board: str
    mae_bp: float = 0.0


@dataclass
class EntryOrder:
    """信号收盘冻结的单笔入场委托；cursor 只按后续 bar 的开盘递增。"""

    leg: Leg
    segment: Segment
    remaining: int
    cursor: int
    state: str = "pending"


@dataclass
class RLeg:
    entry_day: int
    direction: str
    mean_bp: float
    mean_cons_bp: float
    n_ok: int


class Market:
    """§4：两组共用同一份逐根特征、前收和成交判定。"""

    def __init__(self, stock: StockInput, params: Params) -> None:
        self.stock = stock
        self.params = params
        self.board = rules.board(stock.exchange, stock.symbol)
        self.days = [
            features.day_features(
                *bars,
                volume_quantum=100 if stock.dates[d] >= date(2026, 4, 13) else 0,
            )
            for d, bars in enumerate(
                zip(stock.o, stock.h, stock.l, stock.c, stock.v, stock.a, strict=True)
            )
        ]
        self.traded = np.array(
            [
                bool(np.any(day["valid"] & (stock.v[d] > 0))) and stock.day_kind[d] != SUSPENDED
                for d, day in enumerate(self.days)
            ]
        )
        self.v5, self.adv, self.adv_cnt = features.lookbacks(
            stock.dates,
            np.array([day["cumvol"][-1] for day in self.days]),
            np.array([day["cumamt"][-1] for day in self.days]),
            self.traded,
            stock.events,
        )
        self.pc = np.full(len(stock.dates), np.nan)
        self.limits: list[tuple[float, float]] = []
        self.previous: list[tuple[int, int] | None] = []
        previous = None
        last_close = float("nan")
        for d, current in enumerate(stock.dates):
            self.previous.append(previous)
            pc = last_close
            for event in stock.events:
                if event.ex_date == current:
                    pc = rules.ref_price(pc, event.cash, event.pp, event.s, event.r)
            self.pc[d] = pc
            pct = rules.limit_pct(self.board, bool(stock.st[d]), current)
            self.limits.append(
                rules.limit_prices(pc, pct) if not np.isnan(pc) else (float("nan"),) * 2
            )
            present = np.flatnonzero(~np.isnan(stock.o[d]))
            if present.size:
                previous = (d, int(present[-1]))
            valid = np.flatnonzero(self.days[d]["valid"])
            if valid.size:
                last_close = float(stock.c[d, valid[-1]])

    def theta(self, d: int, t: int) -> float:
        p = self.params
        if p.group == "B" or p.k is None:
            return float("nan") if p.d is None else p.d
        return max(p.k * float(self.days[d]["sigma"][t]), p.floor)

    def vr(self, d: int, t: int) -> Decimal | None:
        return features.vr_rounded(
            float(self.days[d]["cumvol"][t]),
            features.minutes_elapsed(features.SLOT_END[t]),
            float(self.v5[d]),
        )

    def can_fill(self, d: int, f: int, q: int, buy: bool) -> bool:
        s = self.stock
        if not 0 <= f < len(features.SLOT_END) or features.SLOT_END[f] > self.params.last_fill:
            return False
        if np.isnan(s.o[d, f]) or not s.v[d, f] > 0:
            return False
        prev = (d, f - 1) if f else self.previous[d]
        if prev is None:
            return False
        pd, pt = prev
        if not self.days[pd]["valid"][pt] or not s.v[pd, pt] >= q:
            return False
        limit = self.limits[d][0 if buy else 1]
        return rules.round_tick(float(s.o[d, f])) != limit

    def fill_slot(self, d: int, after: int, q: int, buy: bool, ordinal: int) -> int:
        """仅供事后 R 候选筛选；真实信号层须用 entry_order/advance_entry。"""
        if ordinal < 1:
            raise ValueError("fill ordinal must be positive")
        for slot in range(after + 1, len(features.SLOT_END)):
            if self.can_fill(d, slot, q, buy):
                ordinal -= 1
                if ordinal == 0:
                    return slot
        return len(features.SLOT_END)

    def entry_order(self, segment: Segment, d: int, t: int, direction: str) -> EntryOrder:
        """只读信号时点信息；成交槽和价格须由后续开盘逐根揭示。"""
        s, p = self.stock, self.params
        if p.fill_delay < 1:
            raise ValueError("fill delay must be positive")
        q = rules.lot_floor(self.board, p.notional, float(s.c[d, t]))
        planned = q * float(s.c[d, t])
        participation = (
            float(planned / self.adv[d] * 100)
            if self.adv_cnt[d] >= 5 and not np.isnan(self.adv[d])
            else None
        )
        leg = Leg(
            symbol=s.symbol,
            segment=segment.name,
            entry_day=d,
            direction=direction,
            trigger_slot=t,
            entry_slot=len(features.SLOT_END),
            entry_price=float("nan"),
            exit_trigger_day=d,
            exit_trigger_slot=t,
            exit_day=None,
            exit_slot=None,
            exit_price=None,
            reason="deferred",
            q=q,
            notional=p.notional,
            planned_amount=planned,
            participation_pct=participation,
            impact_bp_frozen=rules.impact_bp(participation),
            theta=self.theta(d, t),
            sigma=float(self.days[d]["sigma"][t]),
            dev=float(self.days[d]["dev"][t]),
            vr=self.vr(d, t),
            commission=0.0,
            stamp=0.0,
            transfer=0.0,
            slippage=0.0,
            impact=0.0,
            pnl_yuan=0.0,
            pnl_bp=0.0,
            cons_pnl_yuan=0.0,
            cons_pnl_bp=0.0,
            cons_mark_price=None,
            prior_anomaly=bool(np.any(~self.days[d]["valid"][:t])),
            exec_anomaly=False,
            hold_bars=None,
            board=self.board,
        )
        return EntryOrder(leg, segment, p.fill_delay, t)

    def advance_entry(self, order: EntryOrder, slot: int) -> str:
        """只处理紧接 cursor 的一个开盘；失败委托终态出队，不回到旧信号。"""
        if order.state != "pending":
            raise ValueError("entry order is terminal")
        if slot != order.cursor + 1 or not 0 <= slot < len(features.SLOT_END):
            raise ValueError("entry order cursor must advance one bar")
        order.cursor = slot
        leg = order.leg
        if self.can_fill(leg.entry_day, slot, leg.q, leg.direction == "buy_first"):
            order.remaining -= 1
            if order.remaining == 0:
                leg.entry_slot = slot
                leg.entry_price = float(self.stock.o[leg.entry_day, slot])
                leg.exec_anomaly = not bool(self.days[leg.entry_day]["valid"][slot])
                order.state = "filled"
        if order.state == "pending" and (
            self.params.fill_delay == 1
            or features.SLOT_END[slot] >= self.params.last_fill
            or slot == len(features.SLOT_END) - 1
        ):
            order.state = "abandoned"
        return order.state

    def entry(self, segment: Segment, d: int, t: int, direction: str) -> Leg:
        """R 对照与单腿自检入口；沿单个已冻结委托前进，不调用信号选择层。"""
        order = self.entry_order(segment, d, t, direction)
        for slot in range(t + 1, len(features.SLOT_END)):
            if self.advance_entry(order, slot) != "pending":
                break
        return order.leg


def _costs(
    amount: float,
    day: date,
    buy: bool,
    rate: float,
    impact: int,
) -> tuple[float, float, float, float, float]:
    # §6：仅卖出收印花税，每笔按实际额计费。
    return (
        rules.commission(amount, rate),
        0.0 if buy else rules.stamp_duty_rate(day) * amount,
        rules.TRANSFER_RATE * amount,
        rules.SLIPPAGE_BP / 1e4 * amount,
        impact / 1e4 * amount,
    )


def _settle(m: Market, leg: Leg, d: int, f: int, reason: str) -> None:
    # 了结发生在开盘，该bar收盘已在持有期之外。
    _mae(m, leg, d, f - 1)
    price = float(m.stock.o[d, f])
    leg.exit_day, leg.exit_slot, leg.exit_price, leg.reason = d, f, price, reason
    leg.exec_anomaly |= not bool(m.days[d]["valid"][f])
    costs, pnl = _account(m, leg, price, m.stock.dates[d])
    leg.commission, leg.stamp, leg.transfer, leg.slippage, leg.impact = costs
    leg.pnl_yuan = leg.cons_pnl_yuan = pnl
    leg.pnl_bp = leg.cons_pnl_bp = pnl / leg.notional * 1e4
    leg.cons_mark_price = price
    leg.hold_bars = (d - leg.entry_day) * len(features.SLOT_END) + f - leg.entry_slot


def _account(
    m: Market,
    leg: Leg,
    price: float,
    exit_date: date,
) -> tuple[tuple[float, ...], float]:
    buy_entry = leg.direction == "buy_first"
    entry_cost = _costs(
        leg.entry_price * leg.q,
        m.stock.dates[leg.entry_day],
        buy_entry,
        m.params.commission_rate,
        leg.impact_bp_frozen,
    )
    exit_cost = _costs(
        price * leg.q,
        exit_date,
        not buy_entry,
        m.params.commission_rate,
        leg.impact_bp_frozen,
    )
    costs = tuple(a + b for a, b in zip(entry_cost, exit_cost, strict=True))
    gross = (price - leg.entry_price) * leg.q * (1 if buy_entry else -1)
    return costs, gross - sum(costs)


def _unvaluable(m: Market, leg: Leg, reason: str, last_day: int) -> None:
    _mae(m, leg, last_day, len(features.SLOT_END) - 1)
    leg.reason = reason
    # §4 S3：阻断日之前的末根有效收盘，embargo/end 则含当日收盘。
    for d in range(last_day, leg.entry_day - 1, -1):
        valid = np.flatnonzero(m.days[d]["valid"])
        if valid.size:
            price = float(m.stock.c[d, valid[-1]])
            leg.cons_mark_price = price
            _, leg.cons_pnl_yuan = _account(m, leg, price, m.stock.dates[d])
            leg.cons_pnl_bp = leg.cons_pnl_yuan / leg.notional * 1e4
            return


def _mae(m: Market, leg: Leg, last_day: int, last_slot: int) -> None:
    # §8.1：入场至了结或阻断前，含顺延日的有效收盘浮亏，不含费用。
    for d in range(leg.entry_day, last_day + 1):
        start = leg.entry_slot if d == leg.entry_day else 0
        end = last_slot + 1 if d == last_day else len(features.SLOT_END)
        valid = m.days[d]["valid"][start:end]
        close = m.stock.c[d, start:end][valid]
        if close.size:
            adverse = (
                leg.entry_price - float(close.max())
                if leg.direction == "sell_first"
                else float(close.min()) - leg.entry_price
            )
            leg.mae_bp = min(leg.mae_bp, adverse * leg.q / leg.notional * 1e4)


def _resolve(
    m: Market,
    leg: Leg,
    segment: Segment,
    *,
    random: bool = False,
    h: int | None = None,
) -> int:
    """§4、§7.2：返回占用到的最后日索引，顺延了结日也不得重开。"""
    s, p = m.stock, m.params
    d = leg.entry_day
    reason = "deferred"
    boundary_reason = "unvaluable_embargo" if segment.embargo else "unvaluable_end"
    remaining = p.fill_delay
    for t in range(leg.entry_slot, len(features.SLOT_END)):
        if not m.days[d]["valid"][t]:
            continue
        leg.exit_trigger_slot = t
        dev, theta = float(m.days[d]["dev"][t]), m.theta(d, t)
        if random:
            if h is not None and t >= leg.entry_slot + h - 1:
                reason = "revert"
        elif abs(dev) <= p.revert_band * theta:
            reason = "revert"
        elif (dev if leg.direction == "sell_first" else -dev) >= p.stop_mult * theta:
            reason = "stop"
        if reason == "deferred" and features.SLOT_END[t] >= p.time_stop:
            reason = "time"
        if reason != "deferred":
            for f in range(t + 1, len(features.SLOT_END)):
                if m.can_fill(d, f, leg.q, leg.direction == "sell_first"):
                    remaining -= 1
                    if remaining == 0:
                        _settle(m, leg, d, f, reason)
                        return d
            break
    if s.dates[d] >= segment.end:
        _unvaluable(m, leg, boundary_reason, d)
        return d
    for d in range(leg.entry_day + 1, len(s.dates)):
        if s.dates[d] > segment.end:
            _unvaluable(m, leg, boundary_reason, d - 1)
            return d - 1
        # §2.4、§4：跨除权立即阻断，包括停牌期间的事件。
        crossed = [e.ex_date for e in s.events if s.dates[leg.entry_day] < e.ex_date <= s.dates[d]]
        if crossed:
            last_day = d - 1
            while last_day >= leg.entry_day and s.dates[last_day] >= min(crossed):
                last_day -= 1
            _unvaluable(m, leg, "unvaluable_exdate", last_day)
            return d
        if s.day_kind[d] == EXCLUDED:
            _unvaluable(m, leg, "unvaluable_excluded", d - 1)
            return d
        if s.day_kind[d] != SUSPENDED:
            # 不用全天valid/有成交统计决定早盘开盘能否成交；逐根判断。
            for f in range(len(features.SLOT_END)):
                if m.can_fill(d, f, leg.q, leg.direction == "sell_first"):
                    remaining -= 1
                    if remaining == 0:
                        _settle(m, leg, d, f, "deferred")
                        return d
        if s.dates[d] == segment.end:
            _unvaluable(m, leg, boundary_reason, d)
            return d
    last = len(s.dates) - 1
    _unvaluable(m, leg, "unvaluable_end", last)
    return last


def simulate(
    stock: StockInput,
    params: Params,
    segments: list[Segment],
    counters: dict[str, int] | None = None,
    market: Market | None = None,
) -> list[Leg]:
    # 同一股票多组参数共用逐根特征（与参数无关），只换 params。
    m = market if market is not None else Market(stock, params)
    m.params = params
    counts = {} if counters is None else counters
    for name in ("entry_abandoned", "signals", "gate_rejected", "trend_rejected"):
        counts.setdefault(name, 0)
    legs = []
    occupied_until = -1
    for d, current in enumerate(stock.dates):
        segment = next(
            (
                s
                for s in segments
                if s.start <= current <= s.end and (not s.embargo or current < s.end)
            ),
            None,
        )
        if (
            d <= occupied_until
            or stock.day_kind[d] != OK
            or segment is None
            or current < date(2023, 4, 10)
            or np.isnan(m.pc[d])
        ):
            continue
        confirm = dict.fromkeys(params.directions, 0)
        day = m.days[d]
        pending: EntryOrder | None = None
        for t, hhmm in enumerate(features.SLOT_END):
            # 当前 bar 开盘先处理已冻结委托，再用当前 bar 收盘判断新的信号。
            if pending is not None:
                state = m.advance_entry(pending, t)
                if state == "pending":
                    continue
                if state == "filled":
                    occupied_until = _resolve(m, pending.leg, pending.segment)
                    legs.append(pending.leg)
                    break
                counts["entry_abandoned"] += 1
                pending = None
                confirm = dict.fromkeys(params.directions, 0)
            if not day["valid"][t]:
                confirm = dict.fromkeys(params.directions, 0)
                continue
            theta, dev, vr = m.theta(d, t), float(day["dev"][t]), m.vr(d, t)
            for direction in params.directions:
                same_side = (dev if direction == "sell_first" else -dev) >= theta
                confirm[direction] = confirm[direction] + 1 if same_side else 0
            # §4：预热、入场时段和量比均在当前信号时刻检查。
            if (
                day["nbars"][t] < params.sigma_warmup
                or not params.entry_start <= hhmm <= params.entry_end
                or hhmm >= params.last_fill
                or t == len(features.SLOT_END) - 1
                or (params.v is not None and (vr is None or vr < Decimal(str(params.v))))
            ):
                continue
            direction = next((x for x in params.directions if confirm[x] >= params.confirm), None)
            if direction is None:
                continue
            counts["signals"] += 1
            if abs(float(stock.c[d, t]) / m.pc[d] - 1) > params.trend_abs_pct:
                counts["trend_rejected"] += 1
                continue
            order = m.entry_order(segment, d, t, direction)
            leg = order.leg
            if leg.q == 0:
                continue
            planned = leg.planned_amount
            estimate = (
                2 * rules.commission(planned, params.commission_rate)
                + rules.stamp_duty_rate(current) * planned
                + 2 * rules.TRANSFER_RATE * planned
                + 2 * rules.SLIPPAGE_BP / 1e4 * planned
                + 2 * leg.impact_bp_frozen / 1e4 * planned
            )
            if theta * planned < params.min_edge_cost_mult * estimate:
                counts["gate_rejected"] += 1
                continue
            pending = order
    return legs


def simulate_random(
    stock: StockInput,
    params: Params,
    segments: list[Segment],
    legs: list[Leg],
    draws: int = 20,
    seed: int = 0,
    market: Market | None = None,
) -> list[RLeg]:
    m = market if market is not None else Market(stock, params)
    m.params = params
    result = []
    for index, real in enumerate(legs):
        d = real.entry_day
        segment = next(s for s in segments if s.name == real.segment)
        candidates = []
        for t, hhmm in enumerate(features.SLOT_END):
            if params.entry_start <= hhmm <= params.entry_end and m.days[d]["valid"][t]:
                q = rules.lot_floor(m.board, params.notional, float(stock.c[d, t]))
                f = (
                    t + 1
                    if params.fill_delay == 1
                    else m.fill_slot(d, t, q, real.direction == "buy_first", params.fill_delay)
                )
                if q > 0 and m.can_fill(d, f, q, real.direction == "buy_first"):
                    candidates.append(t)
        bp, cons_bp = [], []
        # 无法估值的真实腿没有实际持有时长，不能伪造h后改跑时间止损。
        if candidates and real.hold_bars is not None:
            rng = np.random.default_rng([seed, index])
            for t in rng.choice(candidates, size=draws, replace=True):
                leg = m.entry(segment, d, int(t), real.direction)
                _resolve(m, leg, segment, random=True, h=real.hold_bars)
                bp.append(leg.pnl_bp)
                cons_bp.append(leg.cons_pnl_bp)
        result.append(
            RLeg(
                entry_day=d,
                direction=real.direction,
                mean_bp=float(np.mean(bp)) if bp else float("nan"),
                mean_cons_bp=float(np.mean(cons_bp)) if cons_bp else float("nan"),
                n_ok=len(bp),
            )
        )
    return result
