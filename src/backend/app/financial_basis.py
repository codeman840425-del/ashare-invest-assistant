"""公开财务口径：明确交易日历、份额名单区间、逐证券 CDR 签收（T-B59）。

不采集数据；缺日历或名单生效日期时保留未确认，不以自然日或快照日替代。
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CDR_UNIT_SIGNOFF = {
    "689009": "team/reports/p13-signoff.md 11–13；plan 2.12.1 T-R13 2：c×zgb，逐只清除",
}


@dataclass(frozen=True)
class TradingCalendar:
    start: str
    end: str
    open_days: tuple[str, ...]
    source: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> TradingCalendar:
        start, end = data["coverage_start"], data["coverage_end"]
        if (
            not isinstance(start, str)
            or not isinstance(end, str)
            or not isinstance(data["source"], str)
        ):
            raise ValueError("日历覆盖范围及来源必须为明确字符串")
        dt.date.fromisoformat(start)
        dt.date.fromisoformat(end)
        source = data["source"].strip()
        if start > end or not source or not isinstance(data["open_days"], list):
            raise ValueError("交易日历缺少可信来源、明确覆盖范围或开市日列表")
        days = tuple(sorted(set(data["open_days"])))
        for day in days:
            dt.date.fromisoformat(day)
            if not start <= day <= end:
                raise ValueError("开市日超出日历覆盖范围")
        return cls(start, end, days, source)

    def next_day(self, day: str) -> str | None:
        """严格晚于 day 的下一开市日；覆盖不足不猜测。"""
        if not self.start <= day < self.end:
            return None
        return next((d for d in self.open_days if d > day), None)


def load_calendar(path: Path) -> TradingCalendar | None:
    if not path.is_file():
        return None
    return TradingCalendar.from_mapping(json.loads(path.read_text(encoding="utf-8")))


def validate_share_classes(data: Mapping[str, Any]) -> None:
    """正式记录必须有上市生效日期；缺证草稿仅允许作为来源元数据保存。"""
    if type(data.get("list_version")) is not int or data["list_version"] < 1:
        raise ValueError("名单版本必须为正整数")
    dt.date.fromisoformat(data["as_of"])
    if not isinstance(data.get("sources"), dict) or not isinstance(data.get("records"), list):
        raise ValueError("名单需要来源和记录")
    seen: set[tuple[str, str, str | None]] = set()
    for row in data["records"]:
        required = {
            "code",
            "class",
            "paired_code",
            "paired_market",
            "effective_from",
            "effective_to",
            "source",
            "verified",
        }
        if set(row) != required or type(row["verified"]) is not bool:
            raise ValueError("名单记录字段或核实状态非法")
        if not re.fullmatch(r"[0-9]{6}\.(SH|SZ)", row["code"]):
            raise ValueError("名单证券代码非法")
        kind = row["class"]
        if kind not in {"B", "H"} or not re.fullmatch(
            r"[0-9]{5}" if kind == "H" else r"[0-9]{6}", row["paired_code"]
        ):
            raise ValueError("配对代码必须为交易所原码，不带后缀")
        if row["paired_market"] not in ({"HK"} if kind == "H" else {"SH", "SZ"}):
            raise ValueError("配对交易所非法")
        begin, end = row["effective_from"], row["effective_to"]
        if begin is None:
            raise ValueError("正式名单记录不能缺上市生效日期；草稿只可保存在来源元数据")
        if begin is not None:
            dt.date.fromisoformat(begin)
        if end is not None:
            dt.date.fromisoformat(end)
            if begin is None or end <= begin:
                raise ValueError("名单生效区间非法")
        identity = (row["code"], kind, begin)
        if identity in seen or not row["source"]:
            raise ValueError("名单记录重复或缺少来源")
        seen.add(identity)


def load_share_classes(path: Path) -> dict[str, Any]:
    # JSON is a strict YAML subset; the checked-in file deliberately uses it so
    # standard-library-only probes and the application read exactly the same data.
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    validate_share_classes(data)
    return data


def share_class_at(data: Mapping[str, Any], code: str, day: str) -> dict[str, Any]:
    rows = data["records"]
    # Missing a listing date means interval-safe list integration is incomplete.
    ready = bool(rows) and not data["sources"].get("pending_records")
    eligible = [
        r
        for r in rows
        if r["code"] == code
        and r["effective_from"] is not None
        and r["effective_from"] <= day
        and (r["effective_to"] is None or day < r["effective_to"])
    ]
    return {
        "share_class_check": "list" if ready else "unavailable",
        "member": ("A+" + eligible[0]["class"]) if eligible else None,
        "share_class_list_version": data["list_version"],
        "records": eligible,
    }


def v5g_conditions(data: Mapping[str, Any], sample_checks: Mapping[str, Any]) -> dict[str, bool]:
    rows = data["records"]
    integrated = bool(rows) and not data["sources"].get("pending_records")
    conditions = {
        "list_integrated": integrated,
        "a_h_and_a_b_zgb_verified": all(
            sample_checks.get(c, {}).get("verdict") == "includes_non_a"
            for c in ("601318_A+H", "000550_A+B")
        ),
        "all_records_verified": bool(rows) and all(r["verified"] for r in rows),
        "discrepancy_211_209_resolved": data["sources"].get("discrepancy_211_209_resolved") is True
        and data["sources"].get("union_complete") is True,
    }
    return conditions
