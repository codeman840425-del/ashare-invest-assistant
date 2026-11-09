"""把状态机、令牌桶与调度器组合成“下一次该发哪一个调用”。

外呼循环（后续任务）的用法::

    core.tick(now)                      # 到期/暂停期满
    d = core.next_call(now)             # None → 等待
    ...发出请求，得到 http_status/body...
    transitions = core.complete(d, classify(status, body), now)

T-A75：IP 限流升级计数按 ``user_id`` 共享，并可持久化到 ``ops.data_licence_events``。
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.engine import Engine

from app.config_files import IngestLicences
from app.ingest import ip_limit as ipl
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
    user_id: uuid.UUID


@dataclass
class IngestCore:
    cfg: IngestLicences
    licences: dict[uuid.UUID, _Licence] = field(default_factory=dict)
    user_ip: dict[uuid.UUID, ipl.UserIpLimitMemory] = field(default_factory=dict)
    engine: Engine | None = None
    scheduler: Scheduler[Call] = field(init=False)

    def __post_init__(self) -> None:
        self.scheduler = Scheduler(
            global_max=self.cfg.global_max_concurrency,
            per_licence_max=self.cfg.per_licence_max_concurrency,
            quantum=self.cfg.drr_quantum,
        )

    def per_minute(self, tier: DataLicenceTier, override: int | None = None) -> int:
        return override if override is not None else int(getattr(self.cfg.tier_per_minute, tier))

    def _user_mem(self, user_id: uuid.UUID) -> ipl.UserIpLimitMemory:
        mem = self.user_ip.get(user_id)
        if mem is None:
            mem = ipl.UserIpLimitMemory()
            self.user_ip[user_id] = mem
        return mem

    def rehydrate(self, user_id: uuid.UUID, now: dt.datetime) -> None:
        """Fill user IP-limit memory from the store; fail-closed → escalated.

        B-1: merge ``escalated_until`` with ``later`` so an in-memory fail-closed
        pause is never shortened by an empty DB snapshot after recovery.
        L-2: after a successful read, one-shot flush of any pending pause mark.
        """
        esc = self.cfg.ip_limited_escalate
        mem = self._user_mem(user_id)
        if self.engine is None:
            return
        try:
            with self.engine.connect() as conn:
                loaded = ipl.rehydrate(
                    conn,
                    user_id,
                    window_s=esc.window_s,
                    pause_s=esc.pause_s,
                    now=now,
                )
            ipl.merge_rehydrated(mem, loaded)
        except Exception:  # noqa: BLE001 — fail-closed
            mem.hits.clear()
            mem.escalated_until = ipl.later(
                mem.escalated_until, ipl.fail_closed_until(now, esc.pause_s)
            )
            return
        # L-2: one attempt to durable-write a prior fail-closed pause (no loop).
        if mem.pending_escalation is not None:
            try:
                with self.engine.begin() as conn:
                    ipl.flush_pending_escalation(conn, mem)
            except Exception:  # noqa: BLE001 — keep pending; still refuse
                return

    def upsert(
        self,
        licence_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        tier: DataLicenceTier,
        status: DataLicenceStatus,
        expires_on: dt.date | None = None,
        per_minute_override: int | None = None,
        now: dt.datetime | None = None,
    ) -> None:
        rate = self.per_minute(tier, per_minute_override)
        lic = self.licences.get(licence_id)
        if lic is None:
            self.licences[licence_id] = _Licence(
                LicenceState(self.cfg, tier, status=status, expires_on=expires_on),
                TokenBucket(rate),
                user_id,
            )
            if now is not None:
                self.rehydrate(user_id, now)
            elif self.engine is not None:
                self.rehydrate(user_id, dt.datetime.now(dt.UTC))
            return
        lic.state.tier, lic.state.expires_on, lic.state.status = tier, expires_on, status
        lic.user_id = user_id
        lic.bucket.set_rate(rate)

    def remove(self, licence_id: uuid.UUID) -> list[Call]:
        self.licences.pop(licence_id, None)
        return self.scheduler.drop_licence(licence_id)

    def state(self, licence_id: uuid.UUID) -> LicenceState:
        return self.licences[licence_id].state

    def user_escalated_until(self, licence_id: uuid.UUID) -> dt.datetime | None:
        lic = self.licences[licence_id]
        return self._user_mem(lic.user_id).escalated_until

    def submit(self, licence_id: uuid.UUID, priority: Priority, call: Call) -> None:
        if licence_id not in self.licences:
            raise KeyError("unknown licence_id")
        self.scheduler.submit(licence_id, priority, call)

    def tick(self, now: dt.datetime) -> list[tuple[uuid.UUID, Transition]]:
        out: list[tuple[uuid.UUID, Transition]] = []
        for lid, lic in self.licences.items():
            until = self._user_mem(lic.user_id).escalated_until
            for t in lic.state.tick(now, user_escalated_until=until):
                out.append((lid, t))
        return out

    def next_call(self, now: dt.datetime) -> Dispatch[Call] | None:
        ts = now.timestamp()

        def eligible(lid: uuid.UUID, p: Priority) -> bool:
            lic = self.licences.get(lid)
            if lic is None:
                return False
            head = self.scheduler.peek(lid, p)
            verify = head is not None and head.verify
            until = self._user_mem(lic.user_id).escalated_until
            if not lic.state.allows(p, now, verify=verify, user_escalated_until=until):
                return False
            if not lic.bucket.available(ts):
                return False
            if not lic.state.take_daily(now):
                return False
            return lic.bucket.try_take(ts)

        return self.scheduler.acquire(eligible)

    def user_reset(self, licence_id: uuid.UUID, now: dt.datetime) -> list[Transition]:
        lic = self.licences[licence_id]
        # Rehydrate so escalate deadline survives reset / PUT / test button.
        self.rehydrate(lic.user_id, now)
        return lic.state.user_reset()

    def apply_ip_limited(
        self,
        licence_id: uuid.UUID,
        now: dt.datetime,
        *,
        upstream_code: str = "103",
    ) -> list[Transition]:
        lic = self.licences[licence_id]
        st = lic.state
        esc = self.cfg.ip_limited_escalate
        mem = self._user_mem(lic.user_id)
        from_status = st.status.value
        try:
            if self.engine is None:
                escalated, until = ipl.apply_hit_memory(
                    mem,
                    now,
                    window_s=esc.window_s,
                    count=esc.count,
                    pause_s=esc.pause_s,
                    single_pause_s=self.cfg.ip_limited_pause_s,
                )
            else:
                with self.engine.begin() as conn:
                    escalated, until = ipl.record_hit(
                        conn,
                        mem,
                        user_id=lic.user_id,
                        licence_id=licence_id,
                        from_status=from_status,
                        upstream_code=upstream_code,
                        now=now,
                        window_s=esc.window_s,
                        count=esc.count,
                        pause_s=esc.pause_s,
                        single_pause_s=self.cfg.ip_limited_pause_s,
                    )
        except Exception:  # noqa: BLE001 — fail-closed
            until = ipl.fail_closed_until(now, esc.pause_s)
            mem.escalated_until = ipl.later(mem.escalated_until, until)
            st.paused_until = ipl.later(st.paused_until, until)
            # L-2: queue pause mark for next successful store call (bounded: 1/call).
            ipl.queue_pending_escalation(
                mem,
                licence_id=licence_id,
                user_id=lic.user_id,
                from_status=from_status,
                upstream_code=upstream_code,
                at=now,
            )
            return st._move(
                DataLicenceStatus.IP_LIMITED,
                "ip_limited_escalated",
                notify_user=True,
                notify_admin=True,
                until=until,
            )
        st.paused_until = until
        if escalated:
            return st._move(
                DataLicenceStatus.IP_LIMITED,
                "ip_limited_escalated",
                notify_user=True,
                notify_admin=True,
                until=until,
            )
        return st._move(DataLicenceStatus.IP_LIMITED, "ip_limited", until=until)

    def complete(self, d: Dispatch[Call], signal: Signal, now: dt.datetime) -> list[Transition]:
        self.scheduler.release(d.licence_id)
        lic = self.licences.get(d.licence_id)
        if lic is None:
            return []
        if signal == Signal.IP_LIMITED:
            return self.apply_ip_limited(d.licence_id, now)
        return lic.state.on_result(signal, now, verify=d.item.verify)

    def allows(
        self,
        licence_id: uuid.UUID,
        priority: Priority,
        now: dt.datetime,
        *,
        verify: bool = False,
    ) -> bool:
        lic = self.licences[licence_id]
        until = self._user_mem(lic.user_id).escalated_until
        return lic.state.allows(priority, now, verify=verify, user_escalated_until=until)
