"""Explicit T-B71 formal document importer; no implicit promotion or credential files."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine

from app.config_files import MarketRulesConfig
from app.strategy.cards.feature_meta import load_metadata
from app.strategy.cards.fixtures import run_fixtures
from app.strategy.cards.importing import _block
from app.strategy.cards.persistence import generate_files, import_batch, validate_batch
from app.strategy.cards.preflight import feature_registry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import formal cards as drafts only")
    parser.add_argument("--card", type=Path, action="append", required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--market-rules", type=Path, required=True)
    parser.add_argument("--feature-meta", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    documents = [path.read_text(encoding="utf-8") for path in args.card]
    registry = feature_registry(args.catalog.read_text(encoding="utf-8"))
    metadata_path = args.feature_meta or args.catalog.parent / "feature_catalog_meta.yaml"
    metadata_rows = load_metadata(
        metadata_path.read_text(encoding="utf-8"),
        args.catalog.read_text(encoding="utf-8"),
        registry,
    )
    staged = validate_batch(documents, registry)
    market = MarketRulesConfig.model_validate(_block(args.market_rules.read_text()))
    count = 0
    for item in staged:
        block: dict[str, Any] = dict(item.blocks)
        runs = run_fixtures(
            block["strategy-card"],
            block["strategy-spec"],
            block["validation"]["fixtures"],
            market,
            set(registry),
        )
        if not all(run.passed for run in runs):
            raise ValueError("formal fixture mismatch; no import or generation")
        count += len(runs)
    if args.apply:
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            parser.error("--apply requires DATABASE_URL environment")
        engine = create_engine(dsn)
        try:
            with engine.begin() as conn:
                import_batch(conn, documents, registry, metadata_rows=metadata_rows)
        finally:
            engine.dispose()
    if args.output_dir:
        generate_files(staged, args.output_dir)
    print(
        f"formal cards validated: {len(staged)}; golden passed: {count}; "
        "lifecycle remains draft; no gates granted"
    )
    return 0
