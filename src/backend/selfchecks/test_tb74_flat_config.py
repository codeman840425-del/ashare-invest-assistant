# ruff: noqa: S101, ANN401, F811
"""Regression for the formal importer top-level spec shape, using synthetic data only."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import insert, select, update

from app.db.tables.strategy import strategy_instances, strategy_versions
from selfchecks.test_tb70_replay import integration, no_network  # noqa: F401
from selfchecks.test_tb74_candidates import persist, setup, signal  # noqa: F401


def test_tb74_flat_imported_spec_shape(setup: Any) -> None:
    engine, client, _, _, _, _, instance, version, _ = setup
    new = uuid.uuid4()
    with engine.begin() as conn:
        prior = conn.execute(
            select(strategy_versions).where(strategy_versions.c.id == version)
        ).one()
        config = {**prior.config["spec"], "universe": prior.config["universe"]}
        conn.execute(
            insert(strategy_versions).values(
                id=new,
                strategy_id=prior.strategy_id,
                version_no=2,
                config=config,
                config_hash=new.hex,
                param_hash=new.hex,
                lifecycle="published",
            )
        )
        conn.execute(
            update(strategy_instances)
            .where(strategy_instances.c.id == instance)
            .values(strategy_version_id=new)
        )
    outcome = persist(setup, signal())
    assert outcome["id"] is not None
    assert outcome["diagnostic"] == "open"
    assert client.get("/api/v1/candidate-signals/" + outcome["id"]).status_code == 200
