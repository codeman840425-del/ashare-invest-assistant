"""Explicit offline master-term rebuild; dry-run default, no Settings or provider client."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

import yaml
from sqlalchemy import create_engine

from app.config_files import SecuritiesConfig
from app.master.terms import rebuild


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild public security search terms")
    parser.add_argument(
        "--config-dir", type=Path, default=Path(__file__).resolve().parents[4] / "config"
    )
    parser.add_argument(
        "--codes", help="comma-separated canonical codes; omitted = all public master rows"
    )
    parser.add_argument("--apply", action="store_true", help="write explicit DATABASE_URL target")
    args = parser.parse_args(argv)
    cfg = SecuritiesConfig.model_validate(
        yaml.safe_load(
            (args.config_dir / "securities.yaml").read_text(encoding="utf-8"),
        )
    )
    codes = (
        None
        if args.codes is None
        else sorted({code.strip().upper() for code in args.codes.split(",")})
    )
    if codes is not None and any(not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", code) for code in codes):
        parser.error("--codes requires canonical six-digit codes with SH/SZ/BJ suffix")
    if not args.apply:
        print("search terms configuration validated; dry-run; no database access")
        return 0
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        parser.error("--apply requires DATABASE_URL")
    engine = create_engine(dsn, hide_parameters=True)
    try:
        with engine.begin() as conn:
            result = rebuild(conn, codes, maximum=cfg.search.initials_max_variants)
        print(json.dumps(result))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
