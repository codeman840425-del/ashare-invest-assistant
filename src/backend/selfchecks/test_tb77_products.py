# ruff: noqa: S101, ANN401, F811
"""Owned, nonempty engine products through real isolated DB/worker/authenticated HTTP."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event, insert, select

from app.aggregates import products, service
from app.aggregates.calendar import market_clock
from app.aggregates.reconciliation import read
from app.db.tables.accounts import accounts, reconciliation_items, reconciliation_runs
from app.db.tables.realtime import suggestions
from app.db.tables.research import watchlist_items
from app.db.tables.signals import candidate_signals, non_executable_reasons, plan_drafts
from app.workers.daily import ANALYZE, REPORT
from selfchecks.test_tb70_replay import integration, no_network  # noqa: F401
from selfchecks.test_tb74_candidates import RULES, setup  # noqa: F401
from selfchecks.test_tb76_assembly import prepare
from selfchecks.test_tb76_daily import enqueue


def seed_differences(engine: Any, account: uuid.UUID, at: dt.datetime) -> uuid.UUID:
    rows = json.loads((Path(__file__).parent / "fixtures/tb77_reconciliation.json").read_text())
    run = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            insert(reconciliation_runs).values(
                id=run, account_id=account, status="diff", created_at=at
            )
        )
        for item in rows:
            conn.execute(
                insert(reconciliation_items).values(
                    id=uuid.uuid4(),
                    run_id=run,
                    kind=item["kind"],
                    security_code="688018.SH",
                    ours={"value": item["ours"]},
                    broker={"value": item["broker"]},
                    diff={"value": item["diff"]},
                    resolution=item["resolution"],
                    possible_causes=["完全虚构的差异夹具"],
                )
            )
    return run


@pytest.fixture
def assembled(setup: Any) -> Any:
    _engine, _client, _stranger, owner, _other, _account, *_ = setup
    instance = prepare(setup)
    assert enqueue(ANALYZE, owner) == [(ANALYZE, "ok")]
    return setup, instance


def test_real_nonempty_products_reconciliation_scope_etag_and_fixed_queries(assembled: Any) -> None:
    fixture, instance = assembled
    engine, client, stranger, owner, other, account, *_ = fixture
    now = dt.datetime.now(dt.UTC)
    seed_differences(engine, account, now - dt.timedelta(minutes=1))
    with engine.begin() as conn:
        candidate = conn.execute(
            select(candidate_signals).where(candidate_signals.c.instance_id == instance)
        ).one()
        reason_id, draft_id = uuid.uuid4(), uuid.uuid4()
        conn.execute(
            insert(non_executable_reasons).values(
                id=reason_id,
                signal_id=candidate.id,
                user_id=owner,
                code="INSUFFICIENT_CASH",
                status="active",
                detected_at=now,
            )
        )
        conn.execute(
            insert(plan_drafts).values(
                id=draft_id,
                user_id=owner,
                instance_id=instance,
                signal_ids=[candidate.id],
                security_code="688018.SH",
                action="sell",
                expires_at=now + dt.timedelta(days=1),
            )
        )
        foreign_account = uuid.uuid4()
        conn.execute(
            insert(accounts).values(
                id=foreign_account,
                user_id=other,
                name="虚构账户",
                base_currency="CNY",
            )
        )
    response = client.get("/api/v1/terminal")
    assert response.status_code == 200
    terminal = response.json()
    row = next(r for r in terminal["rows"] if r["security_code"] == "688018.SH")
    assert row["suggestion"]["id"]
    assert row["suggestion"]["actions"][0]["lifecycle"] == "published"
    assert row["active_reason_count"] >= 1
    assert row["quote"] is None
    assert terminal["gaps"]
    assert client.get("/api/v1/suggestions/" + row["suggestion"]["id"]).status_code == 200
    assert (
        client.get(
            "/api/v1/terminal", headers={"If-None-Match": response.headers["etag"]}
        ).status_code
        == 304
    )
    today = client.get("/api/v1/today")
    assert today.status_code == 200
    body = today.json()
    assert any(r["security_code"] == "688018.SH" for r in body["focus"]["items"]), (
        "unfocused holding must still appear"
    )
    assert str(draft_id) in [r["id"] for r in body["pending_plan_drafts"]["items"]]
    assert body["evidence"]
    with engine.connect() as conn:
        actual_flags = conn.execute(
            select(suggestions.c.risk_flags).where(suggestions.c.user_id == owner)
        ).scalar_one()
    assert len(body["risk_flags"]["items"]) == len(actual_flags or [])
    evidence_ids = {r["id"] for r in body["evidence"]}
    assert all(set(f["evidence_ids"]) <= evidence_ids for f in body["risk_flags"]["items"])
    assert (
        client.get("/api/v1/today", headers={"If-None-Match": today.headers["etag"]}).status_code
        == 304
    )
    recon = client.get("/api/v1/reconciliation")
    assert recon.status_code == 200
    assert len(recon.json()["items"]) == 6
    assert all(isinstance(r["ours"], str) for r in recon.json()["items"])
    important = sum(r["important"] for r in recon.json()["items"])
    assert important == 3
    assert body["reconciliation"]["diff_count"] == 6
    assert body["reconciliation"]["important_count"] == important
    assert enqueue(REPORT, owner) == [(REPORT, "ok")]
    report = client.get("/api/v1/daily-reports/2026-10-30")
    assert report.status_code == 200
    assert report.json()["reconciliation"]["important_count"] == important
    for path in ["/terminal", "/today", "/reconciliation"]:
        assert (
            stranger.get("/api/v1" + path, params={"account_id": str(account)}).status_code == 404
        )
        assert (
            client.get("/api/v1" + path, params={"account_id": str(foreign_account)}).status_code
            == 404
        )
    # Fixed SQL count for one vs four real owned rows, not fabricated engine products.
    statements = []

    def count(*args: Any) -> None:
        statements.append(1)

    def measured() -> int:
        statements.clear()
        with engine.connect() as conn:
            service.terminal(conn, owner, account, market_clock(conn, now, RULES), now, "all")
        return len(statements)

    event.listen(engine, "before_cursor_execute", count)
    try:
        one = measured()
        with engine.begin() as conn:
            for code in ["688073.SH", "300364.SZ", "301218.SZ"]:
                conn.execute(insert(watchlist_items).values(user_id=owner, security_code=code))
        four = measured()
        assert one == four
    finally:
        event.remove(engine, "before_cursor_execute", count)
    rows = client.get("/api/v1/terminal").json()["rows"]
    assert len(rows) == 4
    # Algorithm-only >300 boundary: repeated rows are not DB securities or engine acceptance.
    held = rows[0]
    from app.aggregates.models import TerminalRow

    holding = TerminalRow.model_validate_json(json.dumps(held))
    unfocused = holding.model_copy(update={"holding": None, "focus": False})
    selected, more = products.focus_rows([unfocused] * 300 + [holding])
    assert selected == [holding]
    assert not more
    selected, more = products.focus_rows([holding] * 301)
    assert len(selected) == 50
    assert more


def test_reconciliation_generated_time_cutoff_and_resolution(assembled: Any) -> None:
    fixture, _ = assembled
    engine, _, _, _, _, account, *_ = fixture
    now = dt.datetime.now(dt.UTC)
    seed_differences(engine, account, now - dt.timedelta(minutes=1))
    with engine.begin() as conn:
        conn.execute(
            insert(reconciliation_runs).values(
                id=uuid.uuid4(),
                account_id=account,
                status="matched",
                created_at=now + dt.timedelta(days=1),
            )
        )
        result = read(conn, account, now)
        assert result["diff_count"] == 6
        assert result["important_count"] == 3
        assert read(conn, account, now + dt.timedelta(days=2))["diff_count"] == 0
        assert read(conn, None, now)["items"] == []
