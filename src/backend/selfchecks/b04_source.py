"""Explicit local/test-only B-03 fixture reader for the registered B-04 HTTP route."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from app.common.errors import AppError, ErrorCode
from app.config import ConfigError
from app.marketdata.bars_read import BarsQuery, empty_bars, get_bars_reader
from selfchecks.b03_shapes import validate

FIXTURE = Path(__file__).parent / "fixtures/b03/bars.json"
SYNTHETIC_CODE = "999999.SH"


class FixtureBarsReader:
    """Owner-scoped synthetic scenarios, never selected by production dependencies."""

    def __init__(self, scenarios: dict[uuid.UUID, str]) -> None:
        self._bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for case in self._bundle.values():
            validate("bars", case["response"], set())
        if not set(scenarios.values()) <= {"stock", "pending", "licence_unavailable"}:
            raise ValueError("only the B-04 daily unadjusted scenarios are supported")
        self._scenarios = dict(scenarios)

    def read(self, owner: uuid.UUID, code: str, query: BarsQuery) -> dict[str, Any]:
        if code != SYNTHETIC_CODE:
            raise AppError(ErrorCode.NOT_FOUND)
        if query.freq != "d" or query.adjust != "none":
            return empty_bars(code, "合成示例股份", query)
        case = self._scenarios.get(owner, "licence_unavailable")
        result = deepcopy(self._bundle[case]["response"])
        if result["items"]:
            rows = [
                row
                for row in result["items"]
                if (query.start is None or dt.date.fromisoformat(row["t"]) >= query.start)
                and (query.end is None or dt.date.fromisoformat(row["t"]) <= query.end)
                and (query.before is None or row["t"] < query.before)
            ]
            result["items"] = rows[-query.limit :]
            result["next_before"] = result["items"][0]["t"] if len(rows) > query.limit else None
            # T-A53: use the earliest actually selected closing time; an empty window is null.
            result["data_as_of"] = (
                result["items"][0]["t"] + "T15:00:00+08:00" if result["items"] else None
            )
            if not result["items"]:
                result["data_status"] = "unavailable"
                result["gaps"] = [
                    {"key": "bars", "reason": "no_source", "message": "合成区间无缓存数据"}
                ]
        validate("bars", result, set())
        return result


def install_fixture_reader(app: FastAPI, scenarios: dict[uuid.UUID, str]) -> FixtureBarsReader:
    """Opt in explicitly; even local apps keep the default placeholder until called."""
    if app.state.settings.app_env not in {"local", "test"}:
        raise ConfigError("synthetic bars are restricted to explicit local/test selfchecks")
    reader = FixtureBarsReader(scenarios)
    app.dependency_overrides[get_bars_reader] = lambda: reader
    return reader
