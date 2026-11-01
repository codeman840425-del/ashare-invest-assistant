"""每证书三级队列 + 证书间 DRR + 并发上限（plan §2.1B 第 2 点）。

- 先比优先级：任何证书的 P0 先于其他证书的 P1，P1 先于 P2。
- 同一优先级内按**赤字轮转**（DRR，``quantum`` 次调用，默认 1，即逐证书轮流）出队；
  暂时不能发（被暂停、无令牌、并发已满）的证书跳过，不积累赤字。
- 并发：全局 ``global_max`` 与每证书 ``per_licence_max``；``acquire`` 出队即占用，
  完成后调用方必须 :meth:`release`。

是否可发由调用方的 ``eligible(licence_id, priority)`` 决定（状态机 + 令牌桶）；
它只在即将出队时为 True 一次，可以在里面消耗令牌。
"""

from __future__ import annotations

import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from app.ingest.state import Priority

LicenceId = uuid.UUID


@dataclass(frozen=True)
class Dispatch[T]:
    licence_id: LicenceId
    priority: Priority
    item: T


class Scheduler[T]:
    def __init__(self, *, global_max: int = 2, per_licence_max: int = 1, quantum: int = 1) -> None:
        if global_max < 1 or per_licence_max < 1 or quantum < 1:
            raise ValueError("并发与 quantum 必须 ≥ 1")
        if per_licence_max > global_max:
            raise ValueError("per_licence_max 不能大于 global_max")
        self.global_max = global_max
        self.per_licence_max = per_licence_max
        self.quantum = quantum
        self._queues: dict[tuple[LicenceId, Priority], deque[T]] = {}
        self._rings: dict[Priority, deque[LicenceId]] = {p: deque() for p in Priority}
        self._deficit: dict[tuple[LicenceId, Priority], int] = {}
        self._inflight: dict[LicenceId, int] = {}

    # ------------------------------------------------------------ 入队/查询

    def submit(self, licence_id: LicenceId, priority: Priority, item: T) -> None:
        key = (licence_id, priority)
        q = self._queues.setdefault(key, deque())
        if not q:
            self._rings[priority].append(licence_id)
            self._deficit[key] = 0
        q.append(item)

    def peek(self, licence_id: LicenceId, priority: Priority) -> T | None:
        q = self._queues.get((licence_id, priority))
        return q[0] if q else None

    def depth(self, licence_id: LicenceId) -> dict[str, int]:
        return {f"p{int(p)}": len(self._queues.get((licence_id, p), ())) for p in Priority}

    @property
    def inflight_total(self) -> int:
        return sum(self._inflight.values())

    def inflight(self, licence_id: LicenceId) -> int:
        return self._inflight.get(licence_id, 0)

    def drop_licence(self, licence_id: LicenceId) -> list[T]:
        """证书删除/失效：丢弃其全部排队项并返回（不跨证书转交，plan §2.1B 第 4 点）。"""
        dropped: list[T] = []
        for p in Priority:
            q = self._queues.pop((licence_id, p), None)
            if q:
                dropped.extend(q)
                self._rings[p] = deque(x for x in self._rings[p] if x != licence_id)
            self._deficit.pop((licence_id, p), None)
        return dropped

    # ------------------------------------------------------------ 出队

    def acquire(
        self, eligible: Callable[[LicenceId, Priority], bool] = lambda _l, _p: True
    ) -> Dispatch[T] | None:
        if self.inflight_total >= self.global_max:
            return None
        for p in Priority:
            ring = self._rings[p]
            for _ in range(len(ring)):
                lid = ring[0]
                key = (lid, p)
                if self.inflight(lid) >= self.per_licence_max or not eligible(lid, p):
                    ring.rotate(-1)
                    continue
                if self._deficit[key] < 1:
                    self._deficit[key] += self.quantum
                q = self._queues[key]
                item = q.popleft()
                self._deficit[key] -= 1
                if not q:
                    ring.popleft()
                    del self._queues[key]
                    self._deficit[key] = 0
                elif self._deficit[key] < 1:
                    ring.rotate(-1)
                self._inflight[lid] = self.inflight(lid) + 1
                return Dispatch(lid, p, item)
        return None

    def release(self, licence_id: LicenceId) -> None:
        n = self.inflight(licence_id)
        if n <= 0:
            raise RuntimeError("release without acquire")
        if n == 1:
            del self._inflight[licence_id]
        else:
            self._inflight[licence_id] = n - 1


__all__ = ["Dispatch", "LicenceId", "Scheduler"]
