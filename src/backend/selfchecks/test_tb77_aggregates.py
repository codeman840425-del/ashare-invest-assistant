# ruff: noqa: S101, ANN401, F811
"""Only synthetic inputs; clock injection verifies skeleton, NOT real calendar acceptance."""

from __future__ import annotations

import datetime as dt
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import insert

from app.aggregates import products
from app.aggregates.calendar import seed_calendar
from app.aggregates.models import EmptyBlock, MarketClock, Terminal, TerminalRow
from app.db.tables.notify import notifications
from app.db.tables.research import alerts
from app.reference_files import CalendarReference, load_reference_file
from app.replay.baseline import positions_file
from app.schemas.enums import DataStatus, MarketSession, NotificationKind, Severity
from selfchecks.test_tb70_replay import integration, no_network  # noqa: F401


def test_strict_empty_and_row_limit() -> None:
    assert EmptyBlock(items=(), more=False).model_dump(mode="json") == {"items": [], "more": False}
    with pytest.raises(ValidationError):
        EmptyBlock(items=({"id": "pretend"},), more=False)
    with pytest.raises(ValidationError):
        MarketClock(trade_date="2026-11-06", session="closed")
    row = TerminalRow(
        security_code="688018.SH",
        name="合成",
        in_watchlist=False,
        focus=False,
        quote=None,
        holding=None,
        suggestion=None,
        active_reason_count=0,
        max_risk_level=None,
        data_status=DataStatus.PARTIAL,
        data_as_of=None,
    )
    with pytest.raises(ValidationError):
        Terminal(
            server_time=dt.datetime.now(dt.UTC),
            trade_date=dt.date(2026, 11, 6),
            session=MarketSession.CLOSED,
            account=None,
            account_id=None,
            rows=[row] * 301,
            truncated=True,
            unread_notifications=0,
            data_status=row.data_status,
            data_as_of=None,
            gaps=[],
        )


def test_routes_real_ownership_unread_and_imported_holdings(
    integration: Any, no_network: Any
) -> None:
    engine, client, stranger, user_id, other_id = integration
    account = client.post("/api/v1/accounts", json={"broker_name": "合成券商", "alias": "合成"})
    assert account.status_code == 201
    account_id = account.json()["id"]
    assert stranger.get("/api/v1/terminal", params={"account_id": account_id}).status_code == 404
    with engine.begin() as conn:
        seed = load_reference_file(
            Path(__file__).resolve().parents[3] / "config", "trading_calendar.json"
        )
        assert isinstance(seed, CalendarReference)
        seed_calendar(conn, seed)
    with engine.begin() as conn:
        for owner in (user_id, other_id):
            conn.execute(
                insert(notifications).values(
                    id=uuid.uuid4(),
                    user_id=owner,
                    kind=next(iter(NotificationKind)).value,
                    severity=next(iter(Severity)).value,
                    title="合成通知",
                )
            )
    for path in ("/terminal", "/today", "/market/overview"):
        response = client.get("/api/v1" + path)
        assert response.status_code == 200, response.status_code
        value = response.json()
        assert value["data_status"] in {"partial", "unavailable"}
        assert value["gaps"]
        cached = client.get("/api/v1" + path, headers={"If-None-Match": response.headers["etag"]})
        assert cached.status_code == 304
        if path != "/market/overview":
            assert value["unread_notifications"] == 1
        else:
            assert value["breadth"] is None
            assert value["regime"] is None
            assert value["indices"] == []
    today = client.get("/api/v1/today").json()
    for key in (
        "alerts",
        "plan_triggers",
        "risk_flags",
        "released_reasons",
        "pending_plan_drafts",
        "invalidations_today",
    ):
        assert today[key] == {"items": [], "more": False}
    assert today["daily_report"]["status"] == "not_yet"
    uploaded = client.post(
        "/api/v1/imports",
        data={
            "account_id": account_id,
            "kind": "positions",
            "snapshot_as_of": "2026-10-21T08:00:00Z",
        },
        files={"file": ("synthetic.txt", positions_file(), "text/plain")},
    )
    assert uploaded.status_code == 201
    confirmed = client.post(
        f"/api/v1/imports/{uploaded.json()['batch_id']}/confirm",
        json={"mode": "all", "acknowledge_warnings": True},
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    assert confirmed.status_code == 200
    terminal = client.get("/api/v1/terminal").json()
    assert {row["security_code"] for row in terminal["rows"]} == {
        "688018.SH",
        "688073.SH",
        "300364.SZ",
        "301218.SZ",
    }
    assert all(
        row["holding"] and row["quote"] is None and row["suggestion"] is None
        for row in terminal["rows"]
    )
    assert terminal["account"]["pnl_day"] is None
    assert client.get("/api/v1/terminal", params={"scope": "invalid"}).status_code == 400
    second = client.post(
        "/api/v1/accounts", json={"broker_name": "合成券商", "alias": "另一个合成"}
    )
    assert second.status_code == 201
    chosen = client.get("/api/v1/terminal")
    assert chosen.status_code == 200
    assert chosen.json()["account_id"] == account_id
    assert (
        client.get("/api/v1/today", params={"account_id": second.json()["id"]}).status_code == 200
    )
    assert client.get("/api/v1/terminal", params={"account_id": account_id}).status_code == 200
    with engine.begin() as conn:
        conn.execute(
            insert(alerts).values(
                id=uuid.uuid4(),
                user_id=user_id,
                severity=next(iter(Severity)).value,
                triggered_at=dt.datetime.now(dt.UTC),
            )
        )
    # ce32484 / T-B77 删除 ensure_empty_products；T-A149（a281095）确认：
    # /terminal 有没有产品都返回 200；alerts 表不参与 /terminal 聚合。
    # 没有记录时是空集合：suggestion 为 null，active_reason_count 为 0，max_risk_level 为 null。
    nonempty = client.get("/api/v1/terminal", params={"account_id": account_id})
    assert nonempty.status_code == 200
    assert "nonempty_products_require_full_aggregation" not in nonempty.text
    body = nonempty.json()
    assert body["account_id"] == account_id
    assert body["data_status"] == "partial"
    assert {row["security_code"] for row in body["rows"]} == {
        "688018.SH",
        "688073.SH",
        "300364.SZ",
        "301218.SZ",
    }
    now = dt.datetime.now(dt.UTC)
    with engine.connect() as conn:
        owned = products.owned_suggestions(conn, user_id, uuid.UUID(account_id), now)
        reason_counts = Counter(
            r.security_code
            for r in products.reasons(conn, user_id, uuid.UUID(account_id), now)
            if r.status == "active"
        )
    for row in body["rows"]:
        code = row["security_code"]
        # 本例未写入 suggestions / reasons，应对空集合；与库中实际一致（T-A149）。
        assert (code in owned) == (row["suggestion"] is not None)
        assert row["active_reason_count"] == reason_counts[code]
        if code not in owned:
            assert row["suggestion"] is None
        # 无有效 reasons 时 max_risk_level 为 null（T-A149 空集合），与是否有 suggestion 独立。
        if reason_counts[code] == 0:
            assert row["max_risk_level"] is None
        assert row["holding"]
        assert row["quote"] is None
    assert not owned
    assert all(reason_counts[code] == 0 for code in (row["security_code"] for row in body["rows"]))
    assert body["account"]["pnl_day"] is None
    assert {"aggregation", "account.pnl_day"} <= {item["key"] for item in body["gaps"]}
    # 未验证: cash / positions.cost 是否进入 gaps 取决于导入持仓的现金与成本是否可核实，本段不写死。
    # 未验证: trade_date、session、total_assets、unread_notifications 的具体取值本段不新写死。
    from fastapi.testclient import TestClient

    with TestClient(client.app) as anonymous:
        assert anonymous.get("/api/v1/terminal").status_code == 401
    assert no_network == []
