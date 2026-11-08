"""Public draft contract types; no invented thresholds or exposure state."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import JsonValue

from app.schemas.enums import DataStatus, RiskControl
from app.signals.models import Evidence, Gap, Model, RiskFlag


class ControlEvaluation(Model):
    control: RiskControl
    enabled: bool
    state: Literal["ok", "triggered", "unknown", "disabled"]
    flags: list[RiskFlag]
    gaps: list[Gap]


class RiskEvaluation(Model):
    account_id: uuid.UUID | None
    security_code: str
    name: str
    snapshot_id: uuid.UUID | None
    evaluated_at: dt.datetime
    controls: list[ControlEvaluation]
    evidence: list[Evidence]
    data_status: DataStatus
    data_as_of: dt.datetime | None
    gaps: list[Gap]


class RiskEvent(RiskFlag):
    id: uuid.UUID
    security_code: str | None
    name: str | None
    status: Literal["active", "cleared"]
    triggered_at: dt.datetime
    cleared_at: dt.datetime | None
    suggestion_id: uuid.UUID | None
    evidence: list[Evidence]


class RiskSetting(Model):
    control: RiskControl
    enabled: bool
    params: dict[str, JsonValue]
    source: Literal["system", "user"]
    # Backward-compatible sibling of params; keys/shape match every parameter.
    default: dict[str, JsonValue]
