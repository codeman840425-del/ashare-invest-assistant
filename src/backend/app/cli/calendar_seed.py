"""Explicit public calendar seed command; dry-run by default, no Settings/secrets loaded."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from sqlalchemy import create_engine

from app.aggregates.calendar import seed_calendar
from app.reference_files import CalendarReference, load_reference_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="T-A12 audited calendar seed (source commit e916d0b)"
    )
    parser.add_argument(
        "--config-dir", type=Path, default=Path(__file__).resolve().parents[4] / "config"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="explicitly write DATABASE_URL target; default validates only",
    )
    args = parser.parse_args(argv)
    seed = load_reference_file(args.config_dir, "trading_calendar.json")
    if not isinstance(seed, CalendarReference):
        raise ValueError("invalid calendar reference model")
    if not args.apply:
        print(f"calendar validated: {len(seed.open_days)} open days; dry-run; source e916d0b")
        return 0
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        parser.error("--apply requires DATABASE_URL in the environment")
    engine = create_engine(dsn)
    try:
        with engine.begin() as conn:
            count = seed_calendar(conn, seed)
        print(f"calendar seeded: {count} changed days; source e916d0b")
    finally:
        engine.dispose()
    return 0
