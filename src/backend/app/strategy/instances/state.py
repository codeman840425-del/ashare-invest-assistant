"""策略实例状态机（契约 §6.0A，v0.2.7）——纯函数，不碰数据库。

端点（T-B32）在行锁内读出实例、调用 :func:`apply_user_op`，``changed`` 为真时写回新状态、写一条
``strategy_instance_events`` 并更新 ``updated_at``；为假时（幂等空操作）原样返回 200，不写事件、
不改 ``updated_at``。

- 合法转换：confirm proposed→active；pause active→paused（``paused_by="user"``）；
  resume paused→active；archive proposed/active/paused→archived。
- 幂等：当前已是目标态 → 空操作（系统暂停不会被用户 pause 改写成用户暂停）。
- 非法 → ``409 INVALID_STATE_TRANSITION{from, to, allowed}``；
  ``allowed`` 见 :func:`allowed_targets`。
- ``origin=system`` 的实例用户不能归档（``allowed`` 不含 ``archived``）。
- confirm/resume 时版本不可运行 → ``409 STRATEGY_VERSION_NOT_RUNNABLE{lifecycle}``，状态不变。
  可运行的 ``lifecycle`` 取 ``published``、``observing``（契约举例 ``retired``、``simulating``
  不可运行；``draft`` 同理）。
- resume 系统暂停（``LOSS_STREAK_PAUSE``）的实例：清空暂停字段，事件 ``detail`` 记
  ``{released_reason_code: "LOSS_STREAK_PAUSE"}``。
- archived 实例 PATCH → ``409 IMMUTABLE_RESOURCE``（:func:`ensure_patchable`）。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, Final

from app.common.errors import AppError, ErrorCode
from app.schemas.enums import (
    InstanceEventKind,
    InstanceOrigin,
    InstancePausedBy,
    InstanceStatus,
    Lifecycle,
    ReasonCode,
)

S = InstanceStatus

RUNNABLE_LIFECYCLES: Final = frozenset({Lifecycle.PUBLISHED, Lifecycle.OBSERVING})


class InstanceOp(StrEnum):
    CONFIRM = "confirm"
    PAUSE = "pause"
    RESUME = "resume"
    ARCHIVE = "archive"


TARGET: Final[dict[InstanceOp, InstanceStatus]] = {
    InstanceOp.CONFIRM: S.ACTIVE,
    InstanceOp.PAUSE: S.PAUSED,
    InstanceOp.RESUME: S.ACTIVE,
    InstanceOp.ARCHIVE: S.ARCHIVED,
}
LEGAL_FROM: Final[dict[InstanceOp, frozenset[InstanceStatus]]] = {
    InstanceOp.CONFIRM: frozenset({S.PROPOSED}),
    InstanceOp.PAUSE: frozenset({S.ACTIVE}),
    InstanceOp.RESUME: frozenset({S.PAUSED}),
    InstanceOp.ARCHIVE: frozenset({S.PROPOSED, S.ACTIVE, S.PAUSED}),
}
EVENT_KIND: Final[dict[InstanceOp, InstanceEventKind]] = {
    InstanceOp.CONFIRM: InstanceEventKind.CONFIRMED,
    InstanceOp.PAUSE: InstanceEventKind.PAUSED,
    InstanceOp.RESUME: InstanceEventKind.RESUMED,
    InstanceOp.ARCHIVE: InstanceEventKind.ARCHIVED,
}
_ALLOWED: Final[dict[InstanceStatus, tuple[InstanceStatus, ...]]] = {
    S.PROPOSED: (S.ACTIVE, S.ARCHIVED),
    S.ACTIVE: (S.PAUSED, S.ARCHIVED),
    S.PAUSED: (S.ACTIVE, S.ARCHIVED),
    S.ARCHIVED: (),
}


@dataclass(frozen=True, slots=True)
class InstanceState:
    status: InstanceStatus
    origin: InstanceOrigin
    paused_by: InstancePausedBy | None = None
    pause_reason_code: ReasonCode | None = None
    paused_until: datetime | None = None
    archived_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:  # 与迁移 0009 的 CHECK 同口径
        if self.status is S.PAUSED:
            if self.paused_by is None:
                raise ValueError("paused 实例必须有 paused_by")
            if self.paused_by is InstancePausedBy.USER and (
                self.pause_reason_code is not None or self.paused_until is not None
            ):
                raise ValueError("用户暂停不带 pause_reason_code / paused_until")
        elif any(
            v is not None for v in (self.paused_by, self.pause_reason_code, self.paused_until)
        ):
            raise ValueError("status != paused 时暂停字段必须全为 null")
        if (self.status is S.ARCHIVED) != (self.archived_at is not None):
            raise ValueError("archived_at 与 status=archived 必须同时出现")


@dataclass(frozen=True, slots=True)
class Transition:
    changed: bool
    state: InstanceState
    event_kind: InstanceEventKind | None = None
    event_detail: dict[str, Any] | None = None


def allowed_targets(status: InstanceStatus, origin: InstanceOrigin) -> list[str]:
    """``409 INVALID_STATE_TRANSITION`` 的 ``allowed``（契约 §6.0A 第 3 条）。"""
    out = _ALLOWED[status]
    if origin is InstanceOrigin.SYSTEM:
        out = tuple(t for t in out if t is not S.ARCHIVED)
    return [t.value for t in out]


def _invalid(state: InstanceState, to: InstanceStatus) -> AppError:
    return AppError(
        ErrorCode.INVALID_STATE_TRANSITION,
        details={
            "from": state.status.value,
            "to": to.value,
            "allowed": allowed_targets(state.status, state.origin),
        },
    )


def apply_user_op(
    state: InstanceState,
    op: InstanceOp,
    *,
    now: datetime,
    lifecycle: Lifecycle | None = None,
    note: str | None = None,
) -> Transition:
    """用户发起的 confirm/pause/resume/archive。``lifecycle`` 为实例实际运行版本的生命周期。"""
    target = TARGET[op]
    if state.status is target:
        return Transition(changed=False, state=state)  # 幂等：不写事件、不改 updated_at
    if state.status not in LEGAL_FROM[op]:
        raise _invalid(state, target)
    if op is InstanceOp.ARCHIVE and state.origin is InstanceOrigin.SYSTEM:
        raise _invalid(state, target)
    if op in (InstanceOp.CONFIRM, InstanceOp.RESUME) and (
        lifecycle is None or lifecycle not in RUNNABLE_LIFECYCLES
    ):
        raise AppError(
            ErrorCode.STRATEGY_VERSION_NOT_RUNNABLE,
            details={"lifecycle": lifecycle.value if lifecycle is not None else None},
        )

    detail: dict[str, Any] = {}
    if note is not None:
        detail["note"] = note
    if op is InstanceOp.PAUSE:
        new = replace(state, status=S.PAUSED, paused_by=InstancePausedBy.USER, updated_at=now)
    elif op is InstanceOp.ARCHIVE:
        new = replace(
            state,
            status=S.ARCHIVED,
            paused_by=None,
            pause_reason_code=None,
            paused_until=None,
            archived_at=now,
            updated_at=now,
        )
    else:  # CONFIRM / RESUME → active
        if op is InstanceOp.RESUME and state.pause_reason_code is not None:
            detail["released_reason_code"] = state.pause_reason_code.value
        new = replace(
            state,
            status=S.ACTIVE,
            paused_by=None,
            pause_reason_code=None,
            paused_until=None,
            updated_at=now,
        )
    return Transition(
        changed=True, state=new, event_kind=EVENT_KIND[op], event_detail=detail or None
    )


def system_pause(
    state: InstanceState,
    *,
    now: datetime,
    reason_code: ReasonCode = ReasonCode.LOSS_STREAK_PAUSE,
    paused_until: datetime | None = None,
) -> Transition:
    """系统暂停（如连续亏损）。只对 active 生效；已暂停（含用户暂停）或其他状态为空操作。"""
    if state.status is not S.ACTIVE:
        return Transition(changed=False, state=state)
    new = replace(
        state,
        status=S.PAUSED,
        paused_by=InstancePausedBy.SYSTEM,
        pause_reason_code=reason_code,
        paused_until=paused_until,
        updated_at=now,
    )
    return Transition(
        changed=True,
        state=new,
        event_kind=InstanceEventKind.PAUSED,
        event_detail={"reason_code": reason_code.value},
    )


def system_resume_due(state: InstanceState, *, now: datetime) -> Transition:
    """系统暂停到期后由系统恢复；用户暂停的实例**不会**被系统自动恢复。"""
    if (
        state.status is not S.PAUSED
        or state.paused_by is not InstancePausedBy.SYSTEM
        or state.paused_until is None
        or state.paused_until > now
    ):
        return Transition(changed=False, state=state)
    reason = state.pause_reason_code
    new = replace(
        state,
        status=S.ACTIVE,
        paused_by=None,
        pause_reason_code=None,
        paused_until=None,
        updated_at=now,
    )
    return Transition(
        changed=True,
        state=new,
        event_kind=InstanceEventKind.RESUMED,
        event_detail={"released_reason_code": reason.value} if reason is not None else None,
    )


def ensure_patchable(state: InstanceState) -> None:
    """契约 §6.0A 第 7 条：archived 实例 PATCH → ``409 IMMUTABLE_RESOURCE``。"""
    if state.status is S.ARCHIVED:
        raise AppError(ErrorCode.IMMUTABLE_RESOURCE)


def generates_signals(state: InstanceState) -> bool:
    """第 6 条：只有 active 实例生成新的候选信号（暂停、待确认、归档都不生成）。"""
    return state.status is S.ACTIVE
