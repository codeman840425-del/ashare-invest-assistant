"""Offline, reproducible T-B81 evidence. Never imports or invokes the live runner."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any


def amount_check(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Scale discrimination conditional on daily volume being lots (100 shares)."""
    usable = [r for r in rows if Decimal(str(r["v"])) > 0]
    scales = ("0.0001", "0.001", "0.01", "1", "10", "100", "1000", "10000")
    return {
        "rows": len(usable),
        "volume_assumption": "lots_100_shares_from_feature_spec_V1",
        "price_bounds_pass": {
            scale: sum(
                Decimal(str(r["l"]))
                <= Decimal(str(r["a"])) * Decimal(scale) / (Decimal(str(r["v"])) * 100)
                <= Decimal(str(r["h"]))
                for r in usable
            )
            for scale in scales
        },
        "absolute_unit_caveat": (
            "price bounds identify amount/volume ratio, not their independent absolute scales"
        ),
    }


def flow_check(rows: list[dict[str, Any]], window: list[str]) -> dict[str, Any]:
    by_date = {r["t"]: r for r in rows}
    missing = [d for d in window if d not in by_date]
    keys = (("zmbtdcje", 1), ("zmbddcje", 1), ("zmstdcje", -1), ("zmsddcje", -1))
    missing_fields = sum(
        any(r.get(k) is None for k, _ in keys) for d, r in by_date.items() if d in window
    )
    complete = not missing and not missing_fields and len(window) == 20
    total = (
        sum((Decimal(str(by_date[d][k])) * sign for d in window for k, sign in keys), Decimal(0))
        if complete
        else None
    )
    return {
        "window_start": window[0] if window else None,
        "window_end": window[-1] if window else None,
        "expected_days": len(window),
        "missing_days": len(missing),
        "missing_field_days": missing_fields,
        "sum_raw_units": str(total) if total is not None else None,
        "unit": "unverified_raw_units",
    }


def analyze(run: Path) -> dict[str, Any]:
    results = Path(__file__).resolve().parent / "results"
    run = run.resolve()
    if not run.is_relative_to(results.resolve()) or not run.is_dir():
        raise ValueError("expected_local_ignored_probe_run_directory")

    def load(name: str) -> Any:  # noqa: ANN401
        return json.loads((run / (name + ".raw")).read_bytes())

    calendar = json.loads(
        (Path(__file__).resolve().parents[3] / "config/trading_calendar.json").read_text()
    )["open_days"]
    window = [d for d in calendar if d <= "2026-11-06"][-20:]
    data: dict[str, Any] = {
        tag: {
            "amount": amount_check(load("daily_" + tag)),
            "flow20": flow_check(load("flow_" + tag), window),
        }
        for tag in ("star", "chinext")
    }
    factor = Decimal(str(load("factor20")["data"][0]["value"]))
    star_sum = data["star"]["flow20"]["sum_raw_units"]
    daily = load("flow_day")[0]
    history = next(r for r in load("flow_star") if r["t"] == daily["t"])
    fields = ("zmbtdcje", "zmbddcje", "zmstdcje", "zmsddcje")
    data["comparison"] = {
        "factor20_raw": str(factor),
        "factor_minus_sum": str(factor - Decimal(star_sum)) if star_sum is not None else None,
        "single_day_equals_history": all(
            Decimal(str(daily[k])) == Decimal(str(history[k])) for k in fields
        ),
        "csi300_catalog_exact_match": any(
            r == {"dm": "000300.SH", "mc": "沪深300", "jys": "SH"} for r in load("index_catalog")
        ),
        "csi300_daily_rows": len(load("index300")),
        "industry_daily_history_verified": False,
        "matrix_modified": False,
    }
    return data


if __name__ == "__main__":
    import sys

    run = Path(sys.argv[1])
    evidence = analyze(run)
    (run / "analysis.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
    print(json.dumps(evidence, ensure_ascii=False))
