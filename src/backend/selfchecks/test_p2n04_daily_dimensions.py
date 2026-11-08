"""P2N-04 scoped, synthetic-only model/PIT/actual queue/PG/HTTP checks."""

# ruff: noqa: S101, S108, ANN401, F811
from __future__ import annotations

import copy
import datetime as dt
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
import redis
from pydantic import ValidationError
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.tables.market import announcements, feature_bars_daily, financial_reports
from app.db.tables.realtime import daily_report_items, daily_reports
from app.db.tables.research import watchlist_items
from app.db.tables.reviews import data_snapshots
from app.db.tables.strategy import feature_catalog
from app.features.pipeline import FEATURE_SET_VERSION
from app.reports import dimensions as dim
from app.reports.models import DailyDimensionAnalysis, DailyReport
from app.reports.service import build
from app.workers import jobs
from app.workers.daily import REPORT
from selfchecks import test_p2n03_tracking as base
from selfchecks.test_p2n02_risk_controls import env, no_network  # noqa: F401
from selfchecks.test_p2n03_tracking import produced  # noqa: F401

DATE = dt.date(2026, 10, 30)
OPERANDS = json.loads((Path(__file__).parent / "fixtures/p2n04_operands.json").read_text())


def cache_values(**values: Any) -> Any:
    statement = pg_insert(feature_bars_daily).values(**values)
    return statement.on_conflict_do_update(
        index_elements=["code", "trade_date", "feature_set_version"],
        set_={
            "values": statement.excluded["values"],
            "computed_at": statement.excluded.computed_at,
        },
    )


@pytest.fixture(scope="module")
def database() -> Any:
    old = base.SOCKET, base.REDIS
    base.SOCKET, base.REDIS = "/tmp/tb70-p2n04-pg-socket", "unix:///tmp/p2n04-redis/redis.sock?db=0"
    try:
        yield from base.database.__wrapped__()
    finally:
        base.SOCKET, base.REDIS = old


@pytest.mark.parametrize("row", OPERANDS, ids=[str(r["group"]) + "_" + r["case"] for r in OPERANDS])
def test_reviewed_model_grid_values_not_llm_verdicts(row: Any) -> None:
    dimension = list(dim.GROUPS)[row["group"] - 1]
    known = row["case"] in {"present", "stale"}
    raw = {
        "dimension": dimension,
        "facts": (
            [
                {
                    "text": "纯合成操作数 " + row["value"],
                    "expr": None,
                    "evidence_ids": ["688018.SH:synthetic"],
                }
            ]
            if known
            else []
        ),
        "feature_refs": [
            {"feature_key": dim.GROUPS[dimension][0], "status": None, "evidence_ids": []}
        ],
        "data_status": "stale" if row["case"] == "stale" else "partial" if known else "unavailable",
        "data_as_of": "2026-10-30T17:20:00+08:00" if known else None,
        "gaps": [{"key": dimension, "reason": "no_source", "message": "纯合成schema输入"}],
    }
    model = DailyDimensionAnalysis.model_validate(raw)
    assert model.model_dump(mode="json") == raw
    assert model.feature_refs[0].status is None


def receipt(plrq: str = "2026-07-01", period: str = "2026-06-30") -> dict[str, Any]:
    return {
        "period": period,
        "plrq": plrq,
        "versions": ["synthetic-v1"],
        "pit_basis": "first_seen",
        "calc_version": "synthetic-known-scalar",
        "first_seen_at": "2026-07-02T10:00:00+08:00",
        "available_from": "2026-07-02T09:30:00+08:00",
        "verify_pending": ["synthetic-source-only"],
    }


def source(env: Any, *, bad_fund: bool = False, future: bool = False, marker: int = 0) -> uuid.UUID:
    engine, _, _, owner, *_ = env
    with engine.begin() as conn:
        raw = next(
            r
            for r in conn.execute(
                select(data_snapshots)
                .where(data_snapshots.c.user_id == owner)
                .order_by(data_snapshots.c.created_at.desc())
            )
            if r._mapping["items"].get("schema_version") == dim.VERSION
        )
        body = copy.deepcopy(raw._mapping["items"])
        for instrument in body["instruments"]:
            for bar in instrument["bars"]:
                bar["first_seen_at"] = bar["trade_date"] + "T17:20:00+08:00"
            if instrument["security_code"] == "688018.SH":
                instrument["announcements"] = [
                    {
                        "id": "synthetic-owned-title",
                        "title": "完全虚构本人公告",
                        "url": "https://example.org/owned-synthetic",
                        "published_at": "2026-10-30T08:00:00+08:00",
                        "first_seen_at": "2026-10-30T08:01:00+08:00",
                    }
                ]
            instrument["scalars"] = [
                {
                    "feature_key": "f.np_yoy_latest",
                    "unit": "wrong" if bad_fund else "pct",
                    "value": str(12 + marker),
                    "date": str(DATE),
                    "available_at": str(DATE) + "T17:21:00+08:00",
                    "basis": receipt("2026-11-02") if future else receipt(),
                }
            ]
        conn.execute(
            pg_insert(feature_catalog)
            .values(
                feature_key="f.np_yoy_latest",
                unit="pct",
                status="declared",
                source={"synthetic": True},
            )
            .on_conflict_do_update(
                index_elements=["feature_key"], set_={"unit": "pct", "status": "declared"}
            )
        )
        identifier = uuid.uuid4()
        conn.execute(
            insert(data_snapshots).values(
                id=identifier,
                user_id=owner,
                purpose="report",
                hash=dim.digest(body),
                items=body,
                created_at=dt.datetime.now(dt.UTC),
            )
        )
        return identifier


def report_job(env: Any) -> Any:
    r = redis.Redis.from_url(base.REDIS)
    try:
        assert r.llen(jobs.QUEUE_KEY) == 0
        jobs._push(r, REPORT, {"trade_date": str(DATE), "user_id": str(env[3])})
        return jobs.worker_tick(env[5], client=r)
    finally:
        r.close()


def test_actual_worker_report_snapshot_owner_evidence_and_replay(produced: Any) -> None:
    engine, client, stranger, owner, _, _, suggestion, _ = produced
    source(produced[:6])
    with engine.begin() as conn:
        conn.execute(
            insert(watchlist_items).values(
                id=uuid.uuid4(), user_id=owner, security_code="688073.SH"
            )
        )
        conn.execute(
            insert(announcements).values(
                id=uuid.uuid4(),
                code="688018.SH",
                title="全局无归属公告，绝不能进入日报",
                url="https://example.org/synthetic",
                published_at=dt.datetime(2026, 10, 30, 8, tzinfo=dim.BEIJING),
                first_seen_at=dt.datetime(2026, 10, 30, 8, 1, tzinfo=dim.BEIJING),
            )
        )
    assert report_job(produced[:6]) == [(REPORT, "ok")]
    url = "/api/v1/daily-reports/" + str(DATE)
    response = client.get(url)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data_status"] == "partial"
    assert "全局无归属公告" not in str(body)
    assert {r["security_code"] for r in body["stocks"]} == {"688018.SH", "688073.SH"}
    evidence = {e["id"]: e for e in body["evidence"]}
    for row in body["stocks"]:
        assert [d["dimension"] for d in row["dimensions"]] == list(dim.GROUPS)
        assert row["analysis_snapshot_id"]
        for d in row["dimensions"]:
            for item in d["facts"] + d["feature_refs"]:
                assert set(item["evidence_ids"]) <= evidence.keys()
                assert all(i.startswith(row["security_code"] + ":") for i in item["evidence_ids"])
        if row["security_code"] == "688018.SH":
            assert row["suggestion_id"] == str(suggestion.id)
            groups = {d["dimension"]: d for d in row["dimensions"]}
            assert groups["technical"]["facts"]
            assert groups["capital"]["facts"]
            assert any("f.np_yoy_latest" in t["text"] for t in groups["fundamental"]["facts"])
            assert groups["news"]["facts"]
            f23 = evidence["688018.SH:dimension:f.ann_risk_count_10d"]
            assert f23["value"] is None
    with engine.connect() as conn:
        saved = conn.execute(select(daily_reports).where(daily_reports.c.user_id == owner)).one()
        assert (
            len(
                conn.execute(
                    select(daily_report_items).where(daily_report_items.c.report_id == saved.id)
                ).all()
            )
            == 2
        )
        snapshots = [
            conn.execute(
                select(data_snapshots).where(
                    data_snapshots.c.id == uuid.UUID(row["analysis_snapshot_id"])
                )
            ).one()
            for row in body["stocks"]
        ]
        assert all(
            s.user_id == owner and dim.digest(s._mapping["items"]) == s.hash for s in snapshots
        )
        assert all(s._mapping["items"]["account_id"] == body["account_id"] for s in snapshots)
        assert all(s._mapping["items"]["sources"] for s in snapshots)
        assert snapshots[0]._mapping["items"]["basis"]["fundamental"]
    assert stranger.get(url).status_code == 404
    assert stranger.get("/api/v1/daily-reports").json()["items"] == []
    assert report_job(produced[:6]) == [(REPORT, "ok")]
    assert client.get(url).json() == body
    with engine.connect() as conn:
        assert (
            len(conn.execute(select(daily_reports).where(daily_reports.c.user_id == owner)).all())
            == 1
        )


def test_new_input_revision_retains_old_body_and_single_dimension_error(produced: Any) -> None:
    engine, client, _, owner, *_ = produced
    source(produced[:6])
    with engine.begin() as conn:
        first = build(conn, owner, DATE, dt.datetime.now(dt.UTC))
    with engine.connect() as conn:
        original = conn.execute(
            select(daily_reports.c.body).where(daily_reports.c.id == first)
        ).scalar_one()
    source(produced[:6], bad_fund=True, marker=1)
    with engine.begin() as conn:
        second = build(conn, owner, DATE, dt.datetime.now(dt.UTC))
    assert first != second
    new = client.get("/api/v1/daily-reports/" + str(DATE)).json()
    groups = {d["dimension"]: d for d in new["stocks"][0]["dimensions"]}
    assert groups["technical"]["facts"]
    assert groups["fundamental"]["facts"] == []
    assert groups["fundamental"]["data_status"] == "unavailable"
    assert any(g["reason"] == "upstream_error" for g in groups["fundamental"]["gaps"])
    assert any(g["reason"] == "upstream_error" for g in new["gaps"])
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(daily_reports.c.body).where(daily_reports.c.id == first)
            ).scalar_one()
            == original
        )
    assert original["stocks"][0]["analysis_snapshot_id"] != new["stocks"][0]["analysis_snapshot_id"]


def test_future_financial_f23_and_master_do_not_backfill(produced: Any) -> None:
    engine, _, _, owner, *_ = produced
    source(produced[:6], future=True)
    now = dt.datetime.now(dt.UTC)
    with engine.begin() as conn:
        # Real table future financial rows cannot turn a scalar's unproved PIT into facts.
        conn.execute(
            insert(financial_reports).values(
                id=uuid.uuid4(),
                code="688018.SH",
                report_type="income",
                period_end=dt.date(2026, 9, 30),
                announce_date=dt.date(2026, 11, 2),
                payload={"synthetic": True},
                payload_hash="synthetic",
                available_from=dt.datetime(2026, 11, 3, 9, 30, tzinfo=dim.BEIJING),
                first_seen_at=now,
                last_seen_at=now,
            )
        )
        conn.execute(
            cache_values(
                code="688018.SH",
                trade_date=DATE,
                feature_set_version=FEATURE_SET_VERSION,
                computed_at=dt.datetime(2026, 10, 30, 18, tzinfo=dim.BEIJING),
                values={
                    "f.ann_risk_count_10d": 0,
                    "f.is_st": False,
                    "f.is_delisting": False,
                    "basis": {"f.ann_risk_count_10d": {"frozen_at": "2026-10-30T10:00:00+08:00"}},
                },
            )
        )
        snapshot, groups, evidence = dim.build(conn, owner, None, "688018.SH", DATE, now)
        assert snapshot
        assert next(g for g in groups if g["dimension"] == "fundamental")["facts"] == []
        by_key = {e["key"]: e for e in evidence}
        assert by_key["f.np_yoy_latest"]["value"] is None
        assert by_key["f.ann_risk_count_10d"]["value"] is None
        assert "f.is_st" not in by_key
        assert "f.is_delisting" not in by_key
        assert by_key["f.market_regime"]["value"] is None
        assert all(k not in str(groups) for k in ["no_risk", "neutral"])


def test_no_sources_unknown_not_neutral_and_flat_rsi(produced: Any) -> None:
    engine, _, _, owner, *_ = produced
    source(produced[:6])
    with engine.begin() as conn:
        _, groups, evidence = dim.build(
            conn, owner, None, "301218.SZ", DATE, dt.datetime.now(dt.UTC)
        )
        assert len(groups) == 6
        sentiment = next(g for g in groups if g["dimension"] == "sentiment")
        assert sentiment["facts"] == []
        assert sentiment["data_as_of"] is None
        assert sentiment["data_status"] == "unavailable"
        assert all(e["value"] is None for e in evidence if e["key"] in dim.GROUPS["sentiment"])
        loaded = dim.load_inputs(conn, owner, "688018.SH", DATE, dt.datetime.now(dt.UTC))
        instrument = copy.deepcopy(loaded["raw"])
        for row in instrument["bars"]:
            row.update(open="10", high="10", low="10", close="10")
        instrument["factors"] = [
            {
                "date": instrument["bars"][0]["trade_date"],
                "value": "1",
                "available_at": instrument["bars"][0]["first_seen_at"],
            }
        ]
        # Same reviewed adapter used by reports; verify flat does not become RSI 100.
        body = {
            "schema_version": dim.VERSION,
            "sessions": [r["trade_date"] for r in instrument["bars"]],
            "instruments": [instrument],
        }
        conn.execute(
            insert(data_snapshots).values(
                id=uuid.uuid4(),
                user_id=owner,
                purpose="report",
                items=body,
                hash=dim.digest(body),
                created_at=dt.datetime.now(dt.UTC),
            )
        )
        fresh = dim.load_inputs(conn, owner, "688018.SH", DATE, dt.datetime.now(dt.UTC))
        assert fresh["frame"]["features"]["f.rsi14"] is None


def test_legacy_projection_does_not_write_stored_body(produced: Any) -> None:
    engine, client, _, owner, *_ = produced
    with engine.begin() as conn:
        current = build(conn, owner, DATE, dt.datetime.now(dt.UTC))
        body = copy.deepcopy(
            conn.execute(
                select(daily_reports.c.body).where(daily_reports.c.id == current)
            ).scalar_one()
        )
        for row in body["stocks"]:
            row.pop("analysis_snapshot_id")
            row.pop("dimensions")
        conn.execute(
            insert(daily_reports).values(
                id=uuid.uuid4(),
                user_id=owner,
                trade_date=DATE,
                revision=100,
                status="partial",
                body=body,
                generated_at=dt.datetime.now(dt.UTC),
            )
        )
    projected = client.get("/api/v1/daily-reports/" + str(DATE)).json()
    assert all(
        r["dimensions"] is None and r["analysis_snapshot_id"] is None for r in projected["stocks"]
    )
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(daily_reports.c.body).where(
                    daily_reports.c.user_id == owner, daily_reports.c.revision == 100
                )
            ).scalar_one()
            == body
        )


def test_model_rejects_missing_duplicate_dimensions_and_dangling_refs(produced: Any) -> None:
    engine, _, _, owner, *_ = produced
    with engine.begin() as conn:
        identifier = build(conn, owner, DATE, dt.datetime.now(dt.UTC))
        raw = conn.execute(
            select(daily_reports.c.body).where(daily_reports.c.id == identifier)
        ).scalar_one()
    for mode in ["duplicate", "missing", "dangling", "removed"]:
        body = copy.deepcopy(raw)
        stock = body["stocks"][0]
        if mode == "duplicate":
            stock["dimensions"][1] = stock["dimensions"][0]
        elif mode == "missing":
            stock["dimensions"].pop()
        elif mode == "removed":
            stock["change_from_previous"] = "removed"
        else:
            stock["dimensions"][0]["feature_refs"][0]["evidence_ids"] = ["688018.SH:nonexistent"]
        with pytest.raises(ValidationError):
            DailyReport.model_validate(body)


def test_foreign_and_unowned_global_caches_never_fill_dimensions(produced: Any) -> None:
    engine, _, _, owner, other, *_ = produced
    source(produced[:6])
    with engine.begin() as conn:
        conn.execute(
            cache_values(
                code="688018.SH",
                trade_date=DATE,
                feature_set_version=FEATURE_SET_VERSION,
                computed_at=dt.datetime(2026, 10, 30, 18, tzinfo=dim.BEIJING),
                values={"f.close_qfq": "999", "f.amount": "888", "f.market_regime": "range"},
            )
        )
        conn.execute(
            insert(announcements).values(
                id=uuid.uuid4(),
                code="688018.SH",
                title="全局来源不能给另一用户补齐",
                url="https://example.org/not-owned",
                published_at=dt.datetime(2026, 10, 30, 8, tzinfo=dim.BEIJING),
                first_seen_at=dt.datetime(2026, 10, 30, 8, tzinfo=dim.BEIJING),
            )
        )
        identifier, groups, evidence = dim.build(
            conn, other, None, "688018.SH", DATE, dt.datetime.now(dt.UTC)
        )
        assert all(g["facts"] == [] for g in groups)
        assert all(g["data_status"] == "unavailable" and g["data_as_of"] is None for g in groups)
        assert all(e["value"] is None for e in evidence)
        saved = conn.execute(select(data_snapshots).where(data_snapshots.c.id == identifier)).one()
        assert saved.user_id == other
        assert saved._mapping["items"]["sources"] == []
        assert str(owner) not in str(saved._mapping["items"])


def test_removed_row_null_analysis_and_prior_day_revision_baseline(produced: Any) -> None:
    engine, client, _, owner, *_ = produced
    source(produced[:6])
    with engine.begin() as conn:
        watch = uuid.uuid4()
        conn.execute(
            insert(watchlist_items).values(id=watch, user_id=owner, security_code="688073.SH")
        )
        old = build(conn, owner, DATE - dt.timedelta(days=1), dt.datetime.now(dt.UTC))
        original = conn.execute(
            select(daily_reports.c.body).where(daily_reports.c.id == old)
        ).scalar_one()
        assert len(original["stocks"]) == 2
        conn.execute(
            update(watchlist_items)
            .where(watchlist_items.c.id == watch)
            .values(removed_at=dt.datetime.now(dt.UTC))
        )
        first = build(conn, owner, DATE, dt.datetime.now(dt.UTC))
    body = client.get("/api/v1/daily-reports/" + str(DATE)).json()
    removed = next(r for r in body["stocks"] if r["security_code"] == "688073.SH")
    assert removed["change_from_previous"] == "removed"
    assert removed["dimensions"] is None
    assert removed["analysis_snapshot_id"] is None
    assert client.get("/api/v1/daily-reports").json()["items"][0]["stock_count"] == 1
    source(produced[:6], marker=2)
    with engine.begin() as conn:
        second = build(conn, owner, DATE, dt.datetime.now(dt.UTC))
        assert second != first
        assert (
            conn.execute(select(daily_reports.c.body).where(daily_reports.c.id == old)).scalar_one()
            == original
        )
    newer = client.get("/api/v1/daily-reports/" + str(DATE)).json()
    assert [(s["security_code"], s["change_from_previous"]) for s in newer["stocks"]] == [
        (s["security_code"], s["change_from_previous"]) for s in body["stocks"]
    ]


def test_stale_explicit_upstream_status_and_f50_never_fills_f25(produced: Any) -> None:
    engine, _, _, owner, *_ = produced
    sid = source(produced[:6])
    with engine.begin() as conn:
        body = copy.deepcopy(
            conn.execute(
                select(data_snapshots.c["items"]).where(data_snapshots.c.id == sid)
            ).scalar_one()
        )
        instrument = next(i for i in body["instruments"] if i["security_code"] == "688018.SH")
        instrument["scalars"].extend(
            [
                {
                    "feature_key": "f.market_regime_idx",
                    "value": "range",
                    "unit": "enum",
                    "date": str(DATE),
                    "available_at": str(DATE) + "T17:20:00+08:00",
                    "data_status": "stale",
                },
                {
                    "feature_key": "f.market_regime",
                    "value": "uptrend",
                    "unit": "enum",
                    "date": str(DATE),
                    "available_at": "2026-11-02T17:20:00+08:00",
                },
            ]
        )
        for key in ["f.market_regime_idx", "f.market_regime"]:
            conn.execute(
                pg_insert(feature_catalog)
                .values(feature_key=key, unit="enum", status="declared", source={"synthetic": True})
                .on_conflict_do_update(
                    index_elements=["feature_key"], set_={"unit": "enum", "status": "declared"}
                )
            )
        conn.execute(
            insert(data_snapshots).values(
                id=uuid.uuid4(),
                user_id=owner,
                purpose="report",
                items=body,
                hash=dim.digest(body),
                created_at=dt.datetime.now(dt.UTC),
            )
        )
        _, groups, evidence = dim.build(
            conn, owner, None, "688018.SH", DATE, dt.datetime.now(dt.UTC)
        )
        group = next(g for g in groups if g["dimension"] == "sector_market")
        assert group["data_status"] == "stale"
        assert next(e for e in evidence if e["key"] == "f.market_regime_idx")["value"] == "range"
        assert next(e for e in evidence if e["key"] == "f.market_regime")["value"] is None
        assert all(
            f["status"] == "declared"
            for f in group["feature_refs"]
            if f["feature_key"] in {"f.market_regime", "f.market_regime_idx"}
        )


@pytest.mark.parametrize(
    "case", ["early_daily", "missing_session", "future_announcement", "null_reason"]
)
def test_visibility_and_unknown_boundaries(produced: Any, case: str) -> None:
    engine, _, _, owner, *_ = produced
    sid = source(produced[:6])
    with engine.begin() as conn:
        body = copy.deepcopy(
            conn.execute(
                select(data_snapshots.c["items"]).where(data_snapshots.c.id == sid)
            ).scalar_one()
        )
        instrument = next(i for i in body["instruments"] if i["security_code"] == "688018.SH")
        if case == "early_daily":
            for bar in instrument["bars"]:
                if bar["trade_date"] == str(DATE):
                    bar["first_seen_at"] = str(DATE) + "T17:00:00+08:00"
        elif case == "missing_session":
            body["sessions"] = [s for s in body["sessions"] if s != str(DATE)]
        elif case == "future_announcement":
            instrument["announcements"][0]["first_seen_at"] = "2026-11-02T09:00:00+08:00"
        else:
            instrument["scalars"][0]["basis"]["null_reason"] = "synthetic_missing_component"
        conn.execute(
            insert(data_snapshots).values(
                id=uuid.uuid4(),
                user_id=owner,
                purpose="report",
                items=body,
                hash=dim.digest(body),
                created_at=dt.datetime.now(dt.UTC),
            )
        )
        _, groups, evidence = dim.build(
            conn, owner, None, "688018.SH", DATE, dt.datetime.now(dt.UTC)
        )
        by_key = {e["key"]: e for e in evidence}
        if case in {"early_daily", "missing_session"}:
            assert by_key["f.close_qfq"]["value"] is None
            assert by_key["f.amount"]["value"] is None
        elif case == "future_announcement":
            assert next(g for g in groups if g["dimension"] == "news")["facts"] == []
        else:
            assert by_key["f.np_yoy_latest"]["value"] is None


def test_affected_old_daily_revision_and_pagination(env: Any) -> None:
    from selfchecks.test_tb74_candidates import setup as make_setup
    from selfchecks.test_tb76_daily import (
        test_revision_immutable_building_visibility_signed_pagination,
    )

    setup = make_setup.__wrapped__(env[:5], None)
    test_revision_immutable_building_visibility_signed_pagination(setup)


def test_corrupt_owned_source_is_partial_not_global_fallback(produced: Any) -> None:
    engine, client, _, owner, *_ = produced
    sid = source(produced[:6])
    with engine.begin() as conn:
        payload = conn.execute(
            select(data_snapshots.c["items"]).where(data_snapshots.c.id == sid)
        ).scalar_one()
        conn.execute(
            insert(data_snapshots).values(
                id=uuid.uuid4(),
                user_id=owner,
                purpose="report",
                items=payload,
                hash="synthetic-wrong-hash",
                created_at=dt.datetime.now(dt.UTC),
            )
        )
        identifier = build(conn, owner, DATE, dt.datetime.now(dt.UTC))
        assert identifier
    body = client.get("/api/v1/daily-reports/" + str(DATE)).json()
    assert body["data_status"] == "partial"
    assert any(g["reason"] == "upstream_error" for g in body["gaps"])
    assert all(d["facts"] == [] for s in body["stocks"] for d in s["dimensions"])


@pytest.mark.parametrize(
    "case",
    [
        "placeholder_period",
        "calendar_gap",
        "first_seen_future",
        "availability_too_early",
        "null_basis",
    ],
)
def test_financial_pit_receipt_missing_or_invalid_never_fills(case: str, produced: Any) -> None:
    engine, _, _, owner, *_ = produced
    sid = source(produced[:6])
    with engine.begin() as conn:
        body = copy.deepcopy(
            conn.execute(
                select(data_snapshots.c["items"]).where(data_snapshots.c.id == sid)
            ).scalar_one()
        )
        instrument = next(i for i in body["instruments"] if i["security_code"] == "688018.SH")
        basis = instrument["scalars"][0]["basis"]
        if case == "placeholder_period":
            basis["plrq"] = "2026-06-30"
        elif case == "calendar_gap":
            basis["plrq"] = "2025-12-01"
        elif case == "first_seen_future":
            basis["first_seen_at"] = "2026-11-02T10:00:00+08:00"
        elif case == "availability_too_early":
            basis["available_from"] = "2026-07-01T09:30:00+08:00"
        else:
            instrument["scalars"][0]["basis"] = {}
        conn.execute(
            insert(data_snapshots).values(
                id=uuid.uuid4(),
                user_id=owner,
                purpose="report",
                items=body,
                hash=dim.digest(body),
                created_at=dt.datetime.now(dt.UTC),
            )
        )
        _, groups, evidence = dim.build(
            conn, owner, None, "688018.SH", DATE, dt.datetime.now(dt.UTC)
        )
        assert next(e for e in evidence if e["key"] == "f.np_yoy_latest")["value"] is None
        assert next(g for g in groups if g["dimension"] == "fundamental")["gaps"]


def test_foreign_account_binding_rejected_before_snapshot_writes(produced: Any) -> None:
    from app.common.errors import AppError
    from app.db.tables.accounts import accounts

    engine, _, _, owner, other, *_ = produced
    with engine.begin() as conn:
        account = conn.execute(
            select(accounts.c.id).where(accounts.c.user_id == owner)
        ).scalar_one()
        before = conn.execute(
            select(data_snapshots.c.id).where(data_snapshots.c.user_id == other)
        ).all()
        with pytest.raises(AppError) as error:
            dim.build(conn, other, account, "688018.SH", DATE, dt.datetime.now(dt.UTC))
        assert (
            error.value.status == 404
            if hasattr(error.value, "status")
            else error.value.code.value == "NOT_FOUND"
        )
        after = conn.execute(
            select(data_snapshots.c.id).where(data_snapshots.c.user_id == other)
        ).all()
        assert after == before
