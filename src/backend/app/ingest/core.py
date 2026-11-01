"""把状态机、令牌桶与调度器组合成“下一次该发哪一个调用”（纯内存，时钟由调用方传入）。

外呼循环（后续任务）的用法::

    core.tick(now)                      # 到期/暂停期满
    d = core.next_call(now)             # None → 等待
    ...发出请求，得到 http_status/body...
    transitions = core.complete(d, classify(status, body), now)
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.config_files import IngestLicences
from app.ingest.bucket import TokenBucket
from app.ingest.scheduler import Dispatch, Scheduler
from app.ingest.state import LicenceState, Priority, Transition
from app.ingest.upstream import Signal
from app.schemas.enums import DataLicenceStatus, DataLicenceTier


@dataclass(frozen=True)
class Call:
    endpoint: str
    params: tuple[tuple[str, str], ...] = ()
    verify: bool = False
    meta: Any = None


@dataclass
class _Licence:
    state: LicenceState
    bucket: TokenBucket


@dataclass
class IngestCore:
    cfg: IngestLicences
    licences: dict[uuid.UUID, _Licence] = field(default_factory=dict)
    scheduler: Scheduler[Call] = field(init=False)

    def __post_init__(self) -> None:
        self.scheduler = Scheduler(
            global_max=self.cfg.global_max_concurrency,
            per_licence_max=self.cfg.per_licence_max_concurrency,
            quantum=self.cfg.drr_quantum,
        )

    # ------------------------------------------------------------ 证书登记

    def per_minute(self, tier: DataLicenceTier, override: int | None = None) -> int:
        return override if override is not None else int(getattr(self.cfg.tier_per_minute, tier))

    def upsert(
        self,
        licence_id: uuid.UUID,
        *,
        tier: DataLicenceTier,
        status: DataLicenceStatus,
        expires_on: dt.date | None = None,
        per_minute_override: int | None = None,
    ) -> None:
        rate = self.per_minute(tier, per_minute_override)
        lic = self.licences.get(licence_id)
        if lic is None:
            self.licences[licence_id] = _Licence(
                LicenceState(self.cfg, tier, status=status, expires_on=expires_on),
                TokenBucket(rate),
            )
            return
        lic.state.tier, lic.state.expires_on, lic.state.status = tier, expires_on, status
        lic.bucket.set_rate(rate)

    def remove(self, licence_id: uuid.UUID) -> list[Call]:
        self.licences.pop(licence_id, None)
        return self.scheduler.drop_licence(licence_id)

    def state(self, licence_id: uuid.UUID) -> LicenceState:
        return self.licences[licence_id].state

    # ------------------------------------------------------------ 调度

    def submit(self, licence_id: uuid.UUID, priority: Priority, call: Call) -> None:
        if licence_id not in self.licences:
            raise KeyError("unknown licence_id")
        self.scheduler.submit(licence_id, priority, call)

    def tick(self, now: dt.datetime) -> list[tuple[uuid.UUID, Transition]]:
        return [(lid, t) for lid, lic in self.licences.items() for t in lic.state.tick(now)]

    def next_call(self, now: dt.datetime) -> Dispatch[Call] | None:
        ts = now.timestamp()

        def eligible(lid: uuid.UUID, p: Priority) -> bool:
            lic = self.licences.get(lid)
            if lic is None:
                return False
            head = self.scheduler.peek(lid, p)
            verify = head is not None and head.verify
            if not lic.state.allows(p, now, verify=verify):
                return False
            if not lic.bucket.available(ts):
                return False
            if not lic.state.take_daily(now):
                return False
            return lic.bucket.try_take(ts)

        return self.scheduler.acquire(eligible)

    def complete(self, d: Dispatch[Call], signal: Signal, now: dt.datetime) -> list[Transition]:
        self.scheduler.release(d.licence_id)
        lic = self.licences.get(d.licence_id)
        if lic is None:
            return []
        return lic.state.on_result(signal, now, verify=d.item.verify)
