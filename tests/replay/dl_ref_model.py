"""每用户麦蕊证书的参考模型（T-T22；plan 2.1B、契约 v0.2.6 §9）。纯标准库，不联网、不碰真实证书。

本模块只描述**期望行为**，供 ``test_licence_t_t22.py`` 验证，也供后端（T-B04a 扩展）对照：
- :class:`SlidingWindowLimiter`：每证书“任意 60 秒内调用数 ≤ 上限”（plan 2.1B-2，档位默认值见 ingest.yaml ``licences.tier_per_minute``）；
- :class:`LicenceState`：降级状态机（plan 2.1B-6 表格：102/101/103·429/频率 503/数据缺失 503/网络与 5xx/过期/管理员暂停）；
- :class:`RefScheduler`：先比优先级（P0 > P1 > P2），同级按证书 DRR（quantum = 1 次调用）出队；每证书并发 1、全局并发 2；
- :class:`RefIngest`：按用户取数，**只用该用户本人的证书**，证书不可用时 0 次外呼、不回退到他人或管理员证书。

证书在模型里只以 ``licence_id``（虚构 id）出现，从不出现证书值。时间一律由注入的时钟给出（``replay_kit.FakeClock``）。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Protocol

BJ = timezone(timedelta(hours=8))
PRIORITIES = ("p0", "p1", "p2")
#: plan §6.1 ingest.yaml licences（v0.2.6）
TIER_PER_MINUTE = {"diamond": 3000, "annual": 1500, "monthly": 500, "trial": 500, "free": 150, "other": 150}
DIAMOND_AFTER_EXPIRY_PER_DAY = 20000
BACKOFF_S = (1, 2, 4, 8, 16, 32, 60)
BREAKER_CONSECUTIVE_503 = 5
BREAKER_OPEN_S = 300
IP_LIMITED_PAUSE_S = 120
IP_LIMITED_ESCALATE = {"count": 3, "window_s": 3600, "pause_s": 3600}
QUOTA_RESUME_AT = time(0, 1)
#: 证书不可用（不能为该用户取数）的状态
UNUSABLE = {"not_set", "invalid", "expired", "quota_exceeded", "ip_limited", "paused_by_admin"}


class Clock(Protocol):
    def now(self) -> datetime: ...


class SlidingWindowLimiter:
    """精确滑动窗口：任意 (t-60s, t] 内放行次数 ≤ ``per_minute``。"""

    def __init__(self, per_minute: int) -> None:
        if per_minute <= 0:
            raise ValueError("per_minute 必须为正")
        self.per_minute = per_minute
        self._log: deque[datetime] = deque()

    def _trim(self, now: datetime) -> None:
        while self._log and self._log[0] <= now - timedelta(seconds=60):
            self._log.popleft()

    def allow(self, now: datetime) -> bool:
        self._trim(now)
        return len(self._log) < self.per_minute

    def take(self, now: datetime) -> None:
        if not self.allow(now):
            raise RuntimeError("超过每分钟上限")
        self._log.append(now)


def next_quota_resume(now: datetime) -> datetime:
    """101 → 北京时间次日 00:01。"""
    bj = now.astimezone(BJ)
    return datetime.combine(bj.date() + timedelta(days=1), QUOTA_RESUME_AT, tzinfo=BJ)


@dataclass
class LicenceState:
    licence_id: str
    tier: str = "free"
    expires_on: date | None = None
    status: str = "pending_verification"
    paused_until: datetime | None = None
    last_error_code: str | None = None
    consecutive_failures: int = 0
    ip_limited_hits: deque = field(default_factory=deque)
    notifications: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    calls_today: int = 0

    # ---- 上游响应 → 状态（plan 2.1B-6） ----
    def on_upstream(self, signal: str, now: datetime) -> None:
        """``signal`` ∈ ok / 101 / 102 / 103 / 429 / 503_rate / 503_missing / network / http_5xx。"""
        if signal == "ok":
            if self.status in {"pending_verification", "quota_exceeded", "ip_limited", "active"}:
                self.status = "active"
            self.consecutive_failures = 0
            return
        if signal == "503_missing":  # 数据缺失型 503：不熔断、不计失败，只记缺失
            self.gaps.append("upstream_error")
            return
        self.last_error_code = {"503_rate": "503"}.get(signal, signal)
        if signal == "102":
            self.status = "invalid"
            self.paused_until = None
            self._notify("invalid")
        elif signal == "101":
            self.status = "quota_exceeded"
            self.paused_until = next_quota_resume(now)
        elif signal in {"103", "429"}:
            self.status = "ip_limited"
            win = timedelta(seconds=IP_LIMITED_ESCALATE["window_s"])
            self.ip_limited_hits.append(now)
            while self.ip_limited_hits and self.ip_limited_hits[0] <= now - win:
                self.ip_limited_hits.popleft()
            if len(self.ip_limited_hits) >= IP_LIMITED_ESCALATE["count"]:
                self.paused_until = now + timedelta(seconds=IP_LIMITED_ESCALATE["pause_s"])
                self._notify("ip_limited")
            else:
                self.paused_until = now + timedelta(seconds=IP_LIMITED_PAUSE_S)
        elif signal in {"503_rate", "network", "http_5xx"}:  # 状态不变，按证书退避；连续 5 次熔断 300 秒
            self.consecutive_failures += 1
            n = self.consecutive_failures
            wait = BREAKER_OPEN_S if n >= BREAKER_CONSECUTIVE_503 else BACKOFF_S[min(n - 1, len(BACKOFF_S) - 1)]
            self.paused_until = now + timedelta(seconds=wait)
        else:
            raise ValueError(f"未知上游信号 {signal}")

    def _notify(self, status: str) -> None:
        self.notifications.append({"kind": "data_licence", "status": status})

    # ---- 用户/管理员操作 ----
    def user_reset(self) -> None:
        """用户重新 PUT 或点“测试”：回到待验证。"""
        self.status, self.paused_until, self.consecutive_failures = "pending_verification", None, 0

    def admin_pause(self) -> None:
        self.status = "paused_by_admin"

    def admin_resume(self) -> None:
        self.user_reset()

    def check_expiry(self, now: datetime) -> None:
        if self.expires_on and now.astimezone(BJ).date() > self.expires_on and self.status not in {"invalid", "paused_by_admin"}:
            if self.status != "expired":
                self._notify("expired")
            self.status = "expired"

    # ---- 能否外呼 ----
    def can_call(self, now: datetime, priority: str = "p1") -> bool:
        self.check_expiry(now)
        if self.status in {"invalid", "paused_by_admin", "not_set"}:
            return False
        if self.status == "expired":  # 钻石版：只保留 P0，按过期后每日额度；其他档位停止
            return self.tier == "diamond" and priority == "p0" and self.calls_today < DIAMOND_AFTER_EXPIRY_PER_DAY
        return self.paused_until is None or now >= self.paused_until

    def usable_for_user(self, now: datetime) -> bool:
        """用户视角：证书是否可用（不可用时行情接口给 stale/unavailable + data_licence_unavailable）。"""
        self.check_expiry(now)
        if self.status in {"quota_exceeded", "ip_limited"} and self.paused_until and now >= self.paused_until:
            return True
        return self.status not in UNUSABLE


def user_data_block(state: LicenceState | None, now: datetime, has_cached: bool) -> dict[str, Any]:
    """契约 1.1 / v0.2.6 #8：本人证书不可用时读接口不报错，``data_status`` 为 stale（有旧数据）或 unavailable（从未取到）。"""
    if state is not None and state.usable_for_user(now):
        return {"data_status": "fresh" if has_cached else "pending", "gaps": []}
    return {"data_status": "stale" if has_cached else "unavailable",
            "gaps": [{"key": "quotes", "reason": "data_licence_unavailable"}]}


def manual_refresh(state: LicenceState | None, now: datetime) -> tuple[int, dict[str, Any]]:
    """需要触发拉取的写操作：证书不可用 → 409 DATA_LICENCE_UNAVAILABLE，details {status}。"""
    if state is None or not state.usable_for_user(now):
        return 409, {"code": "DATA_LICENCE_UNAVAILABLE", "details": {"status": state.status if state else "not_set"}}
    return 202, {}


@dataclass
class Job:
    licence_id: str
    priority: str
    payload: Any = None


class RefScheduler:
    """先比优先级，同级按证书 DRR（quantum=1）；每证书滑动窗口限额、每证书并发、全局并发。"""

    def __init__(self, clock: Clock, states: dict[str, LicenceState], *, limits: dict[str, int] | None = None,
                 per_licence_concurrency: int = 1, global_concurrency: int = 2, quantum: int = 1) -> None:
        self.clock = clock
        self.states = states
        self.limiters = {lid: SlidingWindowLimiter((limits or {}).get(lid) or TIER_PER_MINUTE.get(s.tier, 150))
                         for lid, s in states.items()}
        self.queues: dict[str, dict[str, deque[Job]]] = {lid: {p: deque() for p in PRIORITIES} for lid in states}
        self.deficit = {(lid, p): 0 for lid in states for p in PRIORITIES}
        self.ring: dict[str, deque[str]] = {p: deque(states) for p in PRIORITIES}
        self.in_flight: dict[str, int] = {lid: 0 for lid in states}
        self.per_licence_concurrency = per_licence_concurrency
        self.global_concurrency = global_concurrency
        self.quantum = quantum
        self.dispatched: list[tuple[datetime, Job]] = []

    def submit(self, licence_id: str, priority: str, payload: Any = None) -> None:
        self.queues[licence_id][priority].append(Job(licence_id, priority, payload))

    def _eligible(self, lid: str, p: str, now: datetime) -> bool:
        return (bool(self.queues[lid][p]) and self.in_flight[lid] < self.per_licence_concurrency
                and self.states[lid].can_call(now, p) and self.limiters[lid].allow(now))

    def next(self) -> Job | None:
        """出队一个调用（不满足任何条件返回 None）；调用方完成后须 ``complete``。"""
        now = self.clock.now()
        if sum(self.in_flight.values()) >= self.global_concurrency:
            return None
        for p in PRIORITIES:
            ring = self.ring[p]
            if not any(self._eligible(lid, p, now) for lid in ring):
                continue
            for _ in range(len(ring)):
                lid = ring[0]
                if not self._eligible(lid, p, now):
                    self.deficit[(lid, p)] = 0  # 空队列/不可调度的证书不累积赤字
                    ring.rotate(-1)
                    continue
                self.deficit[(lid, p)] += self.quantum
                job = self.queues[lid][p].popleft()
                self.deficit[(lid, p)] -= 1
                if self.deficit[(lid, p)] <= 0:
                    ring.rotate(-1)
                self.limiters[lid].take(now)
                self.in_flight[lid] += 1
                self.states[lid].calls_today += 1
                self.dispatched.append((now, job))
                return job
        return None

    def complete(self, job: Job) -> None:
        self.in_flight[job.licence_id] -= 1


class RefIngest:
    """按用户取数：只用本人证书；证书不可用 → 0 次外呼、记 data_licence_unavailable，不回退到他人或管理员证书。"""

    def __init__(self, clock: Clock, states: dict[str, LicenceState], user_licence: dict[str, str | None],
                 upstream: Callable[[str, str], str]) -> None:
        self.clock = clock
        self.states = states
        self.user_licence = user_licence
        self.upstream = upstream
        self.calls: list[tuple[str, str, str]] = []  # (为谁取数的用户, 实际使用的 licence_id, endpoint)
        self.rows: list[dict[str, Any]] = []

    def fetch_for(self, user_id: str, endpoint: str, priority: str = "p1") -> str:
        now = self.clock.now()
        lid = self.user_licence.get(user_id)
        st = self.states.get(lid) if lid else None
        if st is None or not st.can_call(now, priority):
            return "data_licence_unavailable"
        self.calls.append((user_id, lid, endpoint))
        signal = self.upstream(lid, endpoint)
        st.on_upstream(signal, now)
        if signal == "ok":
            self.rows.append({"endpoint": endpoint, "source_licence_id": lid})
        return signal

    def rows_visible_to(self, user_id: str) -> list[dict[str, Any]]:
        """per_licence：只返回本人证书取到的行。"""
        lid = self.user_licence.get(user_id)
        return [r for r in self.rows if r["source_licence_id"] == lid]
