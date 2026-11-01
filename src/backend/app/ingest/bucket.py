"""每证书令牌桶与北京时间日计数（plan §2.1B 第 2 点）。时钟由调用方传入（单调秒数）。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

BEIJING = ZoneInfo("Asia/Shanghai")


@dataclass
class TokenBucket:
    """``per_minute`` 次/分钟匀速补充；``capacity`` 为突发上限（默认 10 秒的量，至少 1）。"""

    per_minute: int
    capacity: float = 0.0
    tokens: float = field(default=-1.0)
    updated: float | None = None

    def __post_init__(self) -> None:
        if self.per_minute <= 0:
            raise ValueError("per_minute 必须为正")
        if self.capacity <= 0:
            self.capacity = max(1.0, self.per_minute / 6)
        if self.tokens < 0:
            self.tokens = self.capacity

    @property
    def rate_per_s(self) -> float:
        return self.per_minute / 60.0

    def _refill(self, now: float) -> None:
        if self.updated is not None and now > self.updated:
            self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate_per_s)
        if self.updated is None or now > self.updated:
            self.updated = now

    def available(self, now: float) -> bool:
        self._refill(now)
        return self.tokens >= 1.0

    def try_take(self, now: float, n: float = 1.0) -> bool:
        self._refill(now)
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False

    def wait_s(self, now: float) -> float:
        """距离下一枚令牌的秒数（0 表示现在就有）。"""
        self._refill(now)
        return 0.0 if self.tokens >= 1.0 else (1.0 - self.tokens) / self.rate_per_s

    def set_rate(self, per_minute: int) -> None:
        """热调档位/管理员覆盖：保留已有令牌，不超过新容量。"""
        if per_minute <= 0:
            raise ValueError("per_minute 必须为正")
        self.per_minute = per_minute
        self.capacity = max(1.0, per_minute / 6)
        self.tokens = min(self.tokens, self.capacity)


@dataclass
class DailyCounter:
    """北京时间自然日计数（钻石版过期后每日 2 万次，plan §2.1B 第 6 点）。"""

    limit: int
    day: dt.date | None = None
    used: int = 0

    def _roll(self, now: dt.datetime) -> None:
        today = now.astimezone(BEIJING).date()
        if self.day != today:
            self.day, self.used = today, 0

    def remaining(self, now: dt.datetime) -> int:
        self._roll(now)
        return max(0, self.limit - self.used)

    def try_take(self, now: dt.datetime) -> bool:
        self._roll(now)
        if self.used >= self.limit:
            return False
        self.used += 1
        return True
