# ruff: noqa: S101, ANN401, F811
"""T-A13 targeted real migration/import/HTTP checks in the dedicated offline DB."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import inspect, select, text, update

from app.cli.cards_import import main
from app.db.tables.strategy import feature_catalog
from app.strategy.cards.feature_meta import FeatureMeta, import_metadata, load_metadata
from app.strategy.cards.persistence import import_batch
from app.strategy.cards.preflight import feature_registry
from selfchecks.test_tb70_replay import DB, integration, no_network  # noqa: F401
from selfchecks.test_tb71_import import (
    test_formal_import_idempotence_generation_queries as legacy_check,
)

ROOT = Path(__file__).resolve().parents[3]
CATALOG = (ROOT / "docs/strategies/feature_spec.md").read_text()
REGISTRY = feature_registry(CATALOG)
SOURCE = (ROOT / "docs/strategies/feature_catalog_meta.yaml").read_text()


def test_source_and_reviewed_synthetic_shapes() -> None:
    rows = load_metadata(SOURCE, CATALOG, REGISTRY)
    assert len(rows) == 19
    assert (
        sum(v is None for row in rows for k, v in row.model_dump().items() if k != "feature_key")
        == 16
    )
    synthetic = json.loads((Path(__file__).parent / "fixtures/ta13_metadata.json").read_text())
    for row in synthetic:
        FeatureMeta.model_validate(row)
        assert row["description"].startswith("Synthetic fixture")
    with pytest.raises(ValueError, match="unknown_metadata_feature_key"):
        load_metadata(yaml.safe_dump({"features": synthetic}), CATALOG, REGISTRY)
    blank = load_metadata("features: [{feature_key: f.amount}]", CATALOG, REGISTRY)[0]
    assert all(v is None for k, v in blank.model_dump().items() if k != "feature_key")


@pytest.mark.parametrize(
    "document",
    [
        "features: [{feature_key: f.amount, warmup_bars: true}]",
        "features: [{feature_key: f.amount, warmup_bars: -1}]",
        "features: [{feature_key: f.amount, dimension: synthetic}]",
        "features: [{feature_key: f.amount, epistemic_type: synthetic}]",
        "features: [{feature_key: f.amount, description: 7}]",
        "features: [{feature_key: f.amount, extra: 7}]",
        "features: [{feature_key: f.amount, spec_ref: F20}]",
        "features: [{feature_key: f.synthetic_unknown}]",
        "features: [{feature_key: f.amount}, {feature_key: f.amount}]",
        "features: [{feature_key: f.amount, warmup_bars: 0, warmup_bars: 1}]",
        "features: []\nextra: []",
    ],
)
def test_invalid_metadata_rejected(document: str) -> None:
    with pytest.raises((ValueError, ValidationError)):
        load_metadata(document, CATALOG, REGISTRY)


def migrate(revision: str, *, down: bool = False) -> None:
    cfg = Config(str(ROOT / "src/backend/alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "src/backend/migrations"))
    cfg.cmd_opts = argparse.Namespace(x=["url=" + DB])
    (command.downgrade if down else command.upgrade)(cfg, revision)


def test_real_add_columns_import_idempotence_and_queries(
    integration: Any,
    tmp_path: Path,
    no_network: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, client, stranger, _, _ = integration
    with engine.connect() as conn:
        before = {c["name"] for c in inspect(conn).get_columns("feature_catalog", schema="app")}
        old_pit = dict(
            conn.execute(select(feature_catalog.c.feature_key, feature_catalog.c.pit_rule)).all()
        )
    migrate("0022")
    try:
        migrate("0022")
        with engine.connect() as conn:
            columns = inspect(conn).get_columns("feature_catalog", schema="app")
            assert {c["name"] for c in columns} - before == {
                "dimension",
                "warmup_bars",
                "epistemic_type",
            }
            assert all(c["nullable"] for c in columns if c["name"] not in before)
            assert (
                conn.execute(
                    text(
                        "select count(*) from app.feature_catalog where dimension is not null "
                        "or warmup_bars is not null or epistemic_type is not null"
                    )
                ).scalar_one()
                == 0
            )
        args = [
            "--catalog",
            str(ROOT / "docs/strategies/feature_spec.md"),
            "--market-rules",
            str(ROOT / "config/market_rules.yaml"),
            "--apply",
        ]
        docs = []
        for name in ("hold_risk_monitor.md", "sw_ma_trend_pullback.md"):
            path = ROOT / "docs/strategies/cards" / name
            args.extend(["--card", str(path)])
            docs.append(path.read_text())
        monkeypatch.setenv("DATABASE_URL", DB)
        assert main(args) == 0  # Real CLI, default source path, real 26 synthetic golden checks.
        rows = load_metadata(SOURCE, CATALOG, REGISTRY)
        keys = [r.feature_key for r in rows]

        def state() -> dict[str, Any]:
            with engine.connect() as conn:
                return {
                    r.feature_key: r._asdict()
                    for r in conn.execute(
                        select(feature_catalog).where(feature_catalog.c.feature_key.in_(keys))
                    )
                }

        first = state()
        with engine.begin() as conn:
            conn.execute(
                update(feature_catalog)
                .where(feature_catalog.c.feature_key == "f.rsi14")
                .values(status="verified_live")
            )
        with engine.begin() as conn:
            import_batch(conn, docs, REGISTRY, metadata_rows=rows)
        second = state()
        assert all(first[k]["updated_at"] == second[k]["updated_at"] for k in keys)
        assert second["f.rsi14"]["status"] == "verified_live"
        assert all(second[k]["pit_rule"] == v for k, v in old_pit.items() if k in second)
        result = client.get("/api/v1/feature-catalog")
        assert result.status_code == 200
        actual = {r["feature_key"]: r for r in result.json()}
        for row in rows:
            for field in ("description", "dimension", "warmup_bars", "epistemic_type"):
                assert actual[row.feature_key][field] == getattr(row, field)
            assert actual[row.feature_key]["available_at"] == second[row.feature_key]["pit_rule"]
        assert stranger.get("/api/v1/feature-catalog").status_code == 200
        with engine.begin() as conn:
            import_metadata(conn, [FeatureMeta(feature_key="f.amount")], REGISTRY)
        blank = {r["feature_key"]: r for r in client.get("/api/v1/feature-catalog").json()}[
            "f.amount"
        ]
        assert all(
            blank[k] is None for k in ("description", "dimension", "warmup_bars", "epistemic_type")
        )
        with engine.begin() as conn:
            import_metadata(conn, rows, REGISTRY)
        baseline = state()
        with (
            pytest.raises(ValueError, match="unknown_metadata_feature_key"),
            engine.begin() as conn,
        ):
            import_metadata(
                conn,
                [
                    FeatureMeta(
                        feature_key="f.amount", description="Synthetic forbidden partial update"
                    ),
                    FeatureMeta(feature_key="f.synthetic_unknown"),
                ],
                REGISTRY,
            )
        assert state() == baseline
        legacy_check(integration, tmp_path, no_network)
        assert no_network == []
    finally:
        migrate("0020", down=True)
    with engine.connect() as conn:
        assert {
            c["name"] for c in inspect(conn).get_columns("feature_catalog", schema="app")
        } == before
        assert (
            conn.execute(text("select version_num from public.alembic_version")).scalar_one()
            == "0020"
        )
