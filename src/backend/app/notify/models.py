"""Public projections shared by HTTP and SSE."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import (
    NotificationKind,
    NotificationRefType,
    NotificationTargetType,
    Severity,
    SignalKind,
)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Target(Strict):
    type: NotificationTargetType
    id: str | None
    route: str | None


class Ref(Strict):
    route: str | None
    type: NotificationRefType
    id: str
    at: dt.datetime


class Notification(Strict):
    version: int = Field(ge=1)
    id: str
    kind: NotificationKind
    severity: Severity
    title: str
    body: str | None
    created_at: dt.datetime
    updated_at: dt.datetime
    read_at: dt.datetime | None
    security_code: str | None
    name: str | None
    merged_count: int = Field(ge=1)
    refs: list[Ref] = Field(max_length=20)
    target: Target


class SignalEvent(Strict):
    signal_event_id: str
    security_code: str
    name: str
    kind: SignalKind
    at: dt.datetime
    message: str
    strategy_key: str | None
    instance_id: str | None
    rule_id: str | None
    price: str | None
    candidate_signal_id: str | None
