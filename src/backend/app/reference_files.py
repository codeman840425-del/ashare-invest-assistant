"""Typed public reference registry, separate from business YAML and credentials."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, StrictStr, model_validator

from app.engine_policies import EnginePolicyReference
from app.financial_basis import TradingCalendar


class CalendarReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    coverage_start: StrictStr
    coverage_end: StrictStr
    open_days: list[StrictStr]
    source: StrictStr

    @model_validator(mode="after")
    def validate_calendar(self) -> Self:
        if self.open_days != sorted(set(self.open_days)):
            raise ValueError("calendar days must be sorted and unique")
        calendar = TradingCalendar.from_mapping(self.model_dump())
        if any(dt.date.fromisoformat(day).weekday() >= 5 for day in calendar.open_days):
            raise ValueError("A-share weekends cannot be open days")
        return self


REFERENCE_FILES: dict[str, type[BaseModel]] = {
    "trading_calendar.json": CalendarReference,
    "engine_policy.yaml": EnginePolicyReference,
}


def load_reference_file(directory: Path, name: str) -> BaseModel:
    model = REFERENCE_FILES[name]
    raw = (directory / name).read_text(encoding="utf-8")
    if name.endswith(".yaml"):
        import yaml

        return model.model_validate(yaml.safe_load(raw))
    return model.model_validate(json.loads(raw))
