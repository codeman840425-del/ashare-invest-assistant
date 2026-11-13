# ruff: noqa: S101, ANN401, F811
"""Real isolated worker→DSL→P1→candidate→suggestion, using a visibly fictional test card."""

from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import insert, select

from app.db.tables.realtime import suggestions
from app.db.tables.reviews import data_snapshots
from app.db.tables.signals import candidate_signals
from app.db.tables.strategy import (
    strategies,
    strategy_card_versions,
    strategy_cards,
    strategy_instances,
    strategy_versions,
)
from app.engine_policies import load as load_policy
from app.engine_policies import seed
from app.replay.baseline import manifest_hash, payload
from app.tracking.worker import TASK as TRACKING
from app.workers.daily import ANALYZE, REPORT
from selfchecks.test_tb70_replay import integration, no_network  # noqa: F401
from selfchecks.test_tb74_candidates import ROOT, setup  # noqa: F401
from selfchecks.test_tb76_daily import enqueue


def prepare(setup: Any) -> uuid.UUID:
    engine, _, _, owner, _, account, *_ = setup
    ids = [uuid.uuid4() for _ in range(5)]
    card, cv, template, version, instance = ids
    source = payload()
    # Shift only generated dates to this synthetic replay day; never reuse an old close as current.
    delta = dt.date(2026, 10, 30) - dt.date.fromisoformat(source["sessions"][-1])

    def shift(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: shift(item) for key, item in value.items()}
        if isinstance(value, list):
            return [shift(item) for item in value]
        if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}(?:T|$)", value):
            return (dt.date.fromisoformat(value[:10]) + delta).isoformat() + value[10:]
        return value

    source = shift(source)
    factors = {
        r["security_code"]: r["factor"]
        for r in json.loads(
            (Path(__file__).parent / "fixtures/tb76_policy_factors.json").read_text()
        )
    }
    for instrument in source["instruments"]:
        instrument["factors"] = [
            {
                "date": source["sessions"][0],
                "value": factors[instrument["security_code"]],
                "available_at": source["sessions"][0] + "T07:00:00+00:00",
            }
        ]
    spec = {
        "params_schema": {},
        "rules": [
            {
                "id": key,
                "dimension": "technical",
                "role": role,
                "expr": expr,
                "eval_time": "daily_close",
                "weight": 1,
            }
            for key, role, expr in [
                ("E", "entry", "f.close_qfq > 0"),
                ("X", "exit", "f.close_qfq > 0"),
                ("C", "counter", "f.close_qfq < 0"),
                ("I", "invalidation", "f.close_qfq < 0"),
            ]
        ],
        "action_map": {
            "entry_all_core_pass": "buy",
            "held_hold": "hold",
            "exit": "sell",
            "else": "wait",
        },
        "dimension_view_thresholds": {"bullish": 0.67, "bearish": 0.33},
        "stops": {"stop_loss": None, "take_profit": None, "time_stop_days": 5},
        "valid_until": {"trading_days": 40},
    }
    fields = {
        "mount_policy": "user",
        "universe": {
            "pool": "持仓 ∪ 自选",
            "boards": {"star": True, "chinext": True},
            "security_types": ["stock"],
        },
    }
    with engine.begin() as conn:
        seed(conn, load_policy(ROOT / "config"))
        conn.execute(
            insert(data_snapshots).values(
                id=uuid.uuid4(),
                user_id=owner,
                purpose="report",
                items=source,
                hash=manifest_hash(source),
                created_at=dt.datetime.now(dt.UTC),
            )
        )
        conn.execute(
            insert(strategy_cards).values(
                id=card,
                key="fictional_" + card.hex,
                title="纯合成接线卡，非H01/W01正式卡",
                source_kind="user",
                owner_user_id=owner,
            )
        )
        conn.execute(
            insert(strategy_card_versions).values(id=cv, card_id=card, version_no=1, fields=fields)
        )
        conn.execute(
            insert(strategies).values(
                id=template,
                key="fictional_" + template.hex,
                name="纯合成接线卡",
                owner_user_id=owner,
                horizons=["swing"],
            )
        )
        conn.execute(
            insert(strategy_versions).values(
                id=version,
                strategy_id=template,
                card_version_id=cv,
                version_no=1,
                config=spec,
                config_hash=version.hex,
                param_hash=version.hex,
                lifecycle="published",
            )
        )
        conn.execute(
            insert(strategy_instances).values(
                id=instance,
                user_id=owner,
                strategy_version_id=version,
                scope="security",
                security_code="688018.SH",
                account_id=account,
                status="active",
                origin="user",
                horizon="swing",
            )
        )
    return instance


def test_real_worker_policy_bound_candidate_suggestion_and_idempotence(setup: Any) -> None:
    engine, client, stranger, owner, *_ = setup
    expected = load_policy(ROOT / "config")
    alternate_version = expected.version_no + 1
    instance = prepare(setup)
    assert enqueue(ANALYZE, owner) == [(ANALYZE, "ok"), (TRACKING, "ok")]
    with engine.connect() as conn:
        candidate = conn.execute(
            select(candidate_signals).where(candidate_signals.c.instance_id == instance)
        ).one()
        row = conn.execute(select(suggestions).where(suggestions.c.user_id == owner)).one()
        assert row.engine_policy_id is not None
        snapshot = conn.execute(
            select(data_snapshots).where(data_snapshots.c.id == candidate.snapshot_id)
        ).one()
        assert snapshot.items["engine_policy_version_no"] == expected.version_no
        assert snapshot.items["content_sha256"]
        assert Decimal(snapshot.items["market_facts"]["price"]) > 0
        sid, cid = str(row.id), str(candidate.id)
    response = client.get("/api/v1/suggestions/" + sid)
    assert response.status_code == 200
    body = response.json()
    assert body["engine_policy"]["content_sha256"] == snapshot.items["content_sha256"]
    confidence = body["strategies"][0]["confidence"]
    c = confidence["components"]
    value = (
        Decimal(".5") * Decimal(str(c["data_completeness"]))
        + Decimal(".3") * Decimal(str(c["dimension_agreement"] or 0))
        + Decimal(".2") * Decimal(str(c["condition_margin"] or 0))
    ).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    assert Decimal(str(confidence["value"])) == value
    assert body["strategies"][0]["candidate_signal_id"] == cid
    assert stranger.get("/api/v1/suggestions/" + sid).status_code == 404
    assert enqueue(ANALYZE, owner) == [(ANALYZE, "ok"), (TRACKING, "ok")]
    with engine.connect() as conn:
        assert (
            len(conn.execute(select(suggestions).where(suggestions.c.user_id == owner)).all()) == 1
        )
        assert (
            len(
                conn.execute(
                    select(candidate_signals).where(candidate_signals.c.instance_id == instance)
                ).all()
            )
            == 1
        )
    assert enqueue(REPORT, owner) == [(REPORT, "ok")]
    report = client.get("/api/v1/daily-reports/2026-10-30").json()
    assert report["stocks"][0]["suggestion_id"] == sid
    assert report["evidence"]
    assert all(e["id"].startswith("688018.SH:") for e in report["evidence"])

    # Try rebinding actual engine output to a different policy: immutable source evidence wins.
    from app.engine_policies import EnginePolicyReference
    from app.suggestions.models import SuggestionInput
    from app.suggestions.service import archive, snapshot_items

    with engine.connect() as conn:
        transaction = conn.begin()
        original = conn.execute(
            select(data_snapshots).where(data_snapshots.c.id == row.snapshot_id)
        ).one()
        raw = load_policy(ROOT / "config").model_dump()
        raw["version_no"] = alternate_version
        raw["system_components"][0]["version_no"] += 1
        policy = EnginePolicyReference.model_validate(raw)
        seed(conn, policy)
        from app.db.tables.strategy import engine_policies

        pid = conn.execute(
            select(engine_policies.c.id).where(engine_policies.c.version_no == alternate_version)
        ).scalar_one()
        content = SuggestionInput.model_validate(
            {**original.items["input"], "engine_policy_id": pid, "snapshot_id": uuid.uuid4()}
        )
        conn.execute(
            insert(data_snapshots).values(
                id=content.snapshot_id,
                user_id=owner,
                purpose="signal",
                hash=content.snapshot_id.hex,
                items=snapshot_items(content),
                created_at=content.created_at,
            )
        )
        with pytest.raises(ValueError, match="candidate_policy_snapshot_mismatch"):
            archive(conn, user_id=owner, content=content)
        transaction.rollback()
