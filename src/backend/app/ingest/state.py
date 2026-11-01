"""按证书的状态机（plan §2.1B 第 6 点，配置 ``config/ingest.yaml`` 的 ``licences``）。

| 上游信号 | 状态 | 处理 |
|---|---|---|
| 102 | ``invalid`` | 停止全部调用，不自动重试；用户重新 PUT / 测试后才恢复 |
| 101 | ``quota_exceeded`` | 暂停到北京时间次日 ``quota_resume_at``（默认 00:01） |
| 103 / 429 | ``ip_limited`` | 暂停 120 秒；窗口内第 ``count`` 次 → ``pause_s`` + 通知 |
| 频率 503 / 5xx / 网络 | 不变 | 退避 ``backoff_s``；连续 N 次 → 熔断 ``open_s`` |
| 数据缺失 503 / 403 | 不变 | 不熔断 |
| 超过 ``expires_on`` | ``expired`` | 钻石版只留 P0 + 每日上限；其他档位停止 |
| 管理员暂停 | ``paused_by_admin`` | 停止，直到管理员恢复 |

所有方法都只改内存状态并返回 :class:`Transition` 列表；写库、发通知由调用方完成。
时间一律用带时区的 ``datetime``。
"""

from __future__ import annotations

import datetime as dt
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum

from app.config_files import IngestLicences
from app.ingest.bucket import BEIJING, DailyCounter
from app.ingest.upstream import BACKOFF_SIGNALS, Signal
from app.schemas.enums import DataLicenceStatus, DataLicenceTier

S = DataLicenceStatus


class Priority(IntEnum):
    P0 = 0  # 盘中实时
    P1 = 1  # 日批 / 按需
    P2 = 2  # 历史回补


@dataclass(frozen=True)
class Transition:
    """一次状态变化或需要告知的事件。``notify_user/notify_admin`` 对应通知 ``data_licence``。"""

    event: str
    from_status: S
    to_status: S
    notify_user: bool = False
    notify_admin: bool = False
    until: dt.datetime | None = None


def next_quota_resume(now: dt.datetime, resume_at: str) -> dt.datetime:
    """北京时间次日 ``HH:MM``（返回 UTC 时间）。"""
    hh, mm = (int(x) for x in resume_at.split(":"))
    day = now.astimezone(BEIJING).date() + dt.timedelta(days=1)
    return dt.datetime.combine(day, dt.time(hh, mm), tzinfo=BEIJING).astimezone(dt.UTC)


@dataclass
class LicenceState:
    cfg: IngestLicences
    tier: DataLicenceTier
    status: S = S.PENDING_VERIFICATION
    expires_on: dt.date | None = None
    paused_until: dt.datetime | None = None  # quota / ip_limited / 熔断
    backoff_until: dt.datetime | None = None
    consecutive_failures: int = 0
    ip_limited_hits: deque[dt.datetime] = field(default_factory=deque)
    expired_daily: DailyCounter | None = None

    # ------------------------------------------------------------ 内部

    def _move(self, to: S, event: str, **kw: object) -> list[Transition]:
        if self.status == to and event not in {"ip_limited_escalated", "breaker_open"}:
            return []
        t = Transition(event=event, from_status=self.status, to_status=to, **kw)  # type: ignore[arg-type]
        self.status = to
        return [t]

    def _blocked_hard(self) -> bool:
        return self.status in (S.INVALID, S.PAUSED_BY_ADMIN, S.NOT_SET)

    # ------------------------------------------------------------ 时间推进

    def tick(self, now: dt.datetime) -> list[Transition]:
        """到期判定与暂停期满恢复。调度前调用。"""
        out: list[Transition] = []
        if (
            self.expires_on is not None
            and now.astimezone(BEIJING).date() > self.expires_on
            and self.status not in (S.EXPIRED, S.INVALID, S.PAUSED_BY_ADMIN, S.NOT_SET)
        ):
            out += self._move(S.EXPIRED, "expired", notify_user=True, notify_admin=True)
            if self.tier == DataLicenceTier.DIAMOND:
                self.expired_daily = DailyCounter(self.cfg.diamond_after_expiry_per_day)
        if (
            self.status in (S.QUOTA_EXCEEDED, S.IP_LIMITED)
            and self.paused_until is not None
            and now >= self.paused_until
        ):
            self.paused_until = None
            out += self._move(S.ACTIVE, "resumed")
        return out

    # ------------------------------------------------------------ 调度许可

    def allows(self, priority: Priority, now: dt.datetime, *, verify: bool = False) -> bool:
        """此刻是否允许为该证书发出一次 ``priority`` 调用（不消耗额度）。

        ``verify=True`` 为 ``verify_licence`` 意图：``pending_verification`` 只放行它。
        """
        if self._blocked_hard():
            return False
        if self.paused_until is not None and now < self.paused_until:
            return False
        if self.backoff_until is not None and now < self.backoff_until:
            return False
        if self.status == S.PENDING_VERIFICATION:
            return verify
        if self.status == S.EXPIRED:
            if self.tier != DataLicenceTier.DIAMOND or priority != Priority.P0:
                return False
            return self.expired_daily is not None and self.expired_daily.remaining(now) > 0
        return self.status == S.ACTIVE or verify

    def take_daily(self, now: dt.datetime) -> bool:
        """过期钻石版的日额度；其他状态恒 True。"""
        if self.status == S.EXPIRED and self.expired_daily is not None:
            return self.expired_daily.try_take(now)
        return True

    # ------------------------------------------------------------ 上游结果

    def on_result(
        self, signal: Signal, now: dt.datetime, *, verify: bool = False
    ) -> list[Transition]:
        cfg = self.cfg
        if signal == Signal.OK:
            self.consecutive_failures = 0
            self.backoff_until = None
            if self.status == S.PENDING_VERIFICATION or (verify and self.status != S.EXPIRED):
                return self._move(S.ACTIVE, "verified", notify_user=verify)
            return []
        if signal == Signal.INVALID:
            self.paused_until = self.backoff_until = None
            return self._move(S.INVALID, "invalid", notify_user=True, notify_admin=True)
        if signal == Signal.QUOTA:
            self.paused_until = next_quota_resume(now, cfg.quota_resume_at)
            return self._move(S.QUOTA_EXCEEDED, "quota_exceeded", until=self.paused_until)
        if signal == Signal.IP_LIMITED:
            esc = cfg.ip_limited_escalate
            window_start = now - dt.timedelta(seconds=esc.window_s)
            while self.ip_limited_hits and self.ip_limited_hits[0] < window_start:
                self.ip_limited_hits.popleft()
            self.ip_limited_hits.append(now)
            if len(self.ip_limited_hits) >= esc.count:
                self.ip_limited_hits.clear()
                self.paused_until = now + dt.timedelta(seconds=esc.pause_s)
                return self._move(
                    S.IP_LIMITED,
                    "ip_limited_escalated",
                    notify_user=True,
                    notify_admin=True,
                    until=self.paused_until,
                )
            self.paused_until = now + dt.timedelta(seconds=cfg.ip_limited_pause_s)
            return self._move(S.IP_LIMITED, "ip_limited", until=self.paused_until)
        if signal in BACKOFF_SIGNALS:
            self.consecutive_failures += 1
            br = cfg.breaker
            if self.consecutive_failures >= br.consecutive_503:
                self.consecutive_failures = 0
                self.backoff_until = None
                self.paused_until = now + dt.timedelta(seconds=br.open_s)
                return [
                    Transition(
                        "breaker_open",
                        self.status,
                        self.status,
                        notify_admin=True,
                        until=self.paused_until,
                    )
                ]
            step = br.backoff_s[min(self.consecutive_failures - 1, len(br.backoff_s) - 1)]
            self.backoff_until = now + dt.timedelta(seconds=step)
            return []
        # DATA_MISSING / NOT_ENTITLED / CLIENT_ERROR：不改状态、不计连续失败
        return []

    # ------------------------------------------------------------ 外部事件

    def admin_pause(self) -> list[Transition]:
        return self._move(S.PAUSED_BY_ADMIN, "admin_pause")

    def admin_resume(self) -> list[Transition]:
        """恢复后需重新验证（与 T-B45 resume 投递 ``verify_licence`` 一致）。"""
        if self.status != S.PAUSED_BY_ADMIN:
            return []
        return self._move(S.PENDING_VERIFICATION, "admin_resume")

    def user_reset(self) -> list[Transition]:
        """用户重新 PUT 或点“测试”：清掉 invalid/退避，进入待验证（管理员暂停不受影响）。"""
        if self.status == S.PAUSED_BY_ADMIN:
            return []
        self.paused_until = self.backoff_until = None
        self.consecutive_failures = 0
        return self._move(S.PENDING_VERIFICATION, "user_reset")
