"""T-R58d §2.1/§7: pre-announced calendar determines sessions, index only verifies."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .errors import DataFormatError
from .sim import Segment

CUTOFF = date(2026, 8, 7)


def merged_calendar(
    csv_path: Path,
    calendar_path: Path,
    start: date,
    end: date,
    index_dates: Iterable[date],
    *,
    expected_days: int | None = None,
) -> tuple[list[date], dict[str, Any]]:
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    hf: dict[date, bool] = {}
    for row in rows:
        day = date.fromisoformat(row["date"])
        raw = row["is_trading_day"].lower()
        if raw not in ("true", "false"):
            raise DataFormatError("invalid calendar boolean")
        if day in hf and hf[day] != (raw == "true"):
            raise DataFormatError("conflicting duplicate calendar date")
        hf[day] = raw == "true"
    announced = json.loads(calendar_path.read_text(encoding="utf-8"))
    low, high = [date.fromisoformat(announced[key]) for key in ("coverage_start", "coverage_end")]
    published = [date.fromisoformat(value) for value in announced["open_days"]]
    if len(published) != len(set(published)) or any(not low <= d <= high for d in published):
        raise DataFormatError("invalid pre-announced calendar coverage")
    if end > CUTOFF and not low <= CUTOFF < end <= high:
        raise DataFormatError("pre-announced calendar does not cover the source switch")
    shared = [day for day in hf if low <= day <= min(CUTOFF, end)]
    published_set = set(published)
    if any(hf[day] != (day in published_set) for day in shared):
        raise DataFormatError("HF and pre-announced calendars disagree")
    hf_end = min(CUTOFF, end)
    cursor = start
    while cursor <= hf_end:
        if cursor not in hf:
            raise DataFormatError(f"missing calendar date: {cursor}")
        cursor += timedelta(days=1)
    days = sorted(
        {d for d, opened in hf.items() if start <= d <= hf_end and opened}
        | {d for d in published if max(CUTOFF, start - timedelta(days=1)) < d <= end}
    )
    observed = {d for d in index_dates if start <= d <= end}
    if set(days) != observed:
        raise DataFormatError(
            "index daily dates differ from independently defined trading calendar"
        )
    if expected_days is not None and len(days) != expected_days:
        raise DataFormatError(f"calendar count {len(days)} differs from {expected_days}")
    return days, {
        "trading_days": len(days),
        "index_dates_match": True,
        "index_defines_calendar": False,
        "hf_calendar_end": hf_end.isoformat(),
        "pre_announced_start": max(start, CUTOFF + timedelta(days=1)).isoformat(),
        "calendar_source": announced.get("source"),
    }


def segments(config: dict[str, Any], days: list[date]) -> tuple[list[Segment], dict[str, Any]]:
    bounds = config["segments"]
    output = [
        Segment(f"fold{i + 1}", date.fromisoformat(a), date.fromisoformat(b))
        for i, (a, b) in enumerate(bounds["folds"])
    ]
    output.append(
        Segment("holdout", *[date.fromisoformat(d) for d in bounds["holdout"]], embargo=False)
    )
    warm = [date.fromisoformat(d) for d in bounds["warmup"]]
    windows = [("warmup", warm[0], warm[1]), *[(s.name, s.start, s.end) for s in output]]
    counts: dict[str, Any] = {}
    assigned = set()
    expected = [305, 126, 126, 125, 125, 125, 242]
    for (name, start, end), wanted in zip(windows, expected, strict=True):
        selected = {d for d in days if start <= d <= end}
        if len(selected) != wanted or selected & assigned:
            raise DataFormatError(f"segment {name}: wrong size or overlap")
        if not selected or min(selected) != start or max(selected) != end:
            raise DataFormatError(f"segment {name}: boundary is not a session")
        assigned.update(selected)
        counts[name] = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "trading_days": len(selected),
            "embargo": name.startswith("fold"),
        }
    if assigned != set(days):
        raise DataFormatError("unassigned trading dates outside the seven windows")
    return output, counts
