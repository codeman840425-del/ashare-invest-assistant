"""P2N-01 fact coverage, not strategy votes. Cached/PIT inputs only; no IO providers.

Financial scalar receipts must retain their existing basis, periods, versions and
availability. A bare cached number cannot establish financial PIT, industry
history, F21 units or the F23 frozen classifier. Missing producers stay gaps.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, insert, select
from sqlalchemy.exc import SQLAlchemyError

from app.common.errors import AppError, ErrorCode
from app.db.tables.accounts import accounts
from app.db.tables.market import trading_calendar
from app.db.tables.reviews import data_snapshots
from app.db.tables.strategy import feature_catalog
from app.features.pipeline import FEATURE_SET_VERSION, instant, prepare
from app.replay.baseline import VERSION
from app.reports.models import DailyDimensionAnalysis
from app.schemas.enums import DataProvider, EpistemicType, MarketRegime
from app.signals.models import Evidence

BEIJING = ZoneInfo("Asia/Shanghai")
SCHEMA = "p2n04-analysis-v1"
GROUPS = {
    "technical": ("f.close_qfq", "f.high_qfq", "f.low_qfq", "f.rsi14"),
    "capital": ("f.amount", "f.main_net_20d"),
    "fundamental": (
        "f.np_yoy_latest",
        "f.pe_ttm_pit",
        "f.roe_ttm_pit",
        "f.ocf_to_np_ttm_pit",
        "f.debt_ratio_pit",
        "f.pb_pit",
    ),
    "sentiment": ("f.limit_up_count_20d", "f.is_limit_up_close", "f.is_limit_down_close"),
    "sector_market": ("f.sw_l1", "f.market_regime_idx", "f.market_regime", "f.ind_rs20"),
    "news": ("f.ann_risk_count_10d",),
}


def canonical(value: Any) -> str:  # noqa: ANN401
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def digest(value: Any) -> str:  # noqa: ANN401
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def missing(
    key: str, issue: str = "source_unavailable", reason: str = "no_source"
) -> dict[str, str]:
    return {"key": key, "reason": reason, "message": "六维事实缺口：" + issue}


def catalog(conn: Connection) -> dict[str, Any]:
    return {
        r.feature_key: dict(r._mapping)
        for r in conn.execute(
            select(feature_catalog).where(
                feature_catalog.c.feature_key.in_([k for keys in GROUPS.values() for k in keys])
            )
        )
    }


def load_inputs(
    conn: Connection,
    owner: uuid.UUID,
    code: str,
    day: dt.date,
    now: dt.datetime,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cutoff = min(now, dt.datetime.combine(day, dt.time.max, BEIJING))
    if registry is None:
        registry = catalog(conn)
    from app.marketdata.daily_snapshot import OWNED_VERSION

    sources = []
    raw, factors, scalars, sessions = None, [], [], []
    accepted = (VERSION, OWNED_VERSION)
    for row in conn.execute(
        select(data_snapshots)
        .where(
            data_snapshots.c.user_id == owner,
            data_snapshots.c.purpose == "report",
            data_snapshots.c.created_at <= now,
            data_snapshots.c["items"]["schema_version"].astext.in_(accepted),
        )
        .order_by(data_snapshots.c.created_at.desc(), data_snapshots.c.id.desc())
    ):
        body = row._mapping["items"]
        schema = body.get("schema_version")
        if schema not in accepted:
            continue
        if schema == OWNED_VERSION and body.get("trade_date") != day.isoformat():
            continue
        if digest(body) != row.hash:
            raise ValueError("owned_source_hash_conflict")
        raw = next((i for i in body["instruments"] if i["security_code"] == code), None)
        if raw is not None:
            factors, scalars, sessions = (
                raw.get("factors", []),
                raw.get("scalars", []),
                body["sessions"],
            )
            sources.append({"kind": schema, "id": str(row.id), "hash": row.hash})
            break
    no_owned_source = raw is None
    if raw is None:
        # Global market rows carry no licence/owner binding. Never use another
        # user's observations to fill this owner's report; only public calendar
        # and catalog metadata may be shared. Production owned adapter is pending.
        raw = {"bars": [], "price_unit": None, "amount_unit": None}
    # Daily completion is not a wall-clock estimate: both final flag and actual
    # acquisition at/after documented 17:10 are required. No previous close fill.
    raw = dict(
        raw,
        bars=[
            r
            for r in raw["bars"]
            if r.get("is_final") is True
            and instant(r["first_seen_at"]) <= cutoff
            and instant(r["first_seen_at"])
            >= dt.datetime.combine(dt.date.fromisoformat(r["trade_date"]), dt.time(17, 10), BEIJING)
        ],
    )
    frame = None
    frame_error = False
    try:
        frame = (
            {"features": {}, "series": {"f.close_qfq": []}, "data_as_of": None, "visible_dates": []}
            if no_owned_source
            else prepare(raw, sessions, as_of=cutoff, factors=factors, registry=registry)
        )
        closes = frame["series"]["f.close_qfq"]
        # Mapping explicitly excludes the flat-series RSI; do not alter card votes.
        if closes and all(v is not None and v == closes[0] for v in closes):
            frame["features"]["f.rsi14"] = None
    except (ValueError, KeyError, TypeError, ArithmeticError):
        frame_error = True
    return {
        "cutoff": cutoff,
        "registry": registry,
        "raw": raw,
        "frame": frame,
        "frame_error": frame_error,
        "scalars": scalars,
        "cached": None,
        "sources": sources,
        "day": day,
        "now": now,
        "code": code,
    }


def financial_pit(conn: Connection, basis: dict[str, Any], cutoff: dt.datetime) -> bool:
    """Verify the supplied normalized calculation's provenance, not invent a formula."""
    required = {
        "period",
        "plrq",
        "versions",
        "pit_basis",
        "calc_version",
        "first_seen_at",
        "available_from",
    }
    if not required <= basis.keys() or not all(basis[k] for k in required):
        return False
    period, plrq = dt.date.fromisoformat(basis["period"]), dt.date.fromisoformat(basis["plrq"])
    if plrq <= period:
        return False
    rows = list(
        conn.execute(
            select(trading_calendar)
            .where(
                trading_calendar.c.date >= plrq,
                trading_calendar.c.date <= cutoff.astimezone(BEIJING).date(),
            )
            .order_by(trading_calendar.c.date)
        )
    )
    if not rows or rows[0].date != plrq:
        return False
    next_day = next((r.date for r in rows if r.date > plrq and r.is_open), None)
    if next_day is None or any(
        rows[i].date != rows[0].date + dt.timedelta(days=i) for i in range(len(rows))
    ):
        return False
    minimum = dt.datetime.combine(next_day, dt.time(9, 30), BEIJING)
    return (
        minimum <= instant(basis["available_from"]) <= cutoff
        and instant(basis["first_seen_at"]) <= cutoff
    )


def scalar(
    conn: Connection, data: dict[str, Any], key: str
) -> tuple[Any, str | None, dt.datetime | None, list[dict[str, str]], dict[str, Any]]:
    cutoff, day, registry = data["cutoff"], data["day"], data["registry"]
    if key in {"f.main_net_20d", "f.ind_rs20", "f.sw_l1", "f.ann_risk_count_10d"}:
        # These producers/identity/unit/frozen receipts are not supplied by a bare
        # value; do not silently turn a raw scalar into a validated F21/F23 result.
        return None, None, None, [missing(key, "unit_identity_or_frozen_producer_unverified")], {}
    entry = registry.get(key)
    candidates = []
    for r in data["scalars"]:
        if (
            r["feature_key"] == key
            and instant(r["available_at"]) <= cutoff
            and r.get("date", str(day)) <= str(day)
        ):
            candidates.append(r)
    candidates.sort(key=lambda r: instant(r["available_at"]), reverse=True)
    if not candidates or entry is None or entry["unit"] is None:
        return None, None, None, [missing(key)], {}
    row = candidates[0]
    basis = row.get("basis", {})
    if row["unit"] != entry["unit"]:
        raise ValueError("scalar_unit_mismatch")
    if key in GROUPS["fundamental"] and not financial_pit(conn, basis, cutoff):
        return None, row["unit"], None, [missing(key, "financial_pit_receipt_unavailable")], basis
    if key not in GROUPS["fundamental"] and row.get("date") != str(day):
        return None, row["unit"], None, [missing(key, "no_current_session_value")], basis
    value = row["value"]
    if basis.get("null_reason"):
        return None, row["unit"], None, [missing(key, "upstream_null_reason")], basis
    if value is None:
        return None, row["unit"], None, [missing(key)], basis
    if key in {"f.market_regime", "f.market_regime_idx"}:
        if value not in {v.value for v in MarketRegime}:
            raise ValueError("invalid_regime_enum")
    elif key in {"f.is_limit_up_close", "f.is_limit_down_close"}:
        if type(value) is not bool:
            raise ValueError("invalid_boolean_feature")
    else:
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError("invalid_numeric_feature")
        if key == "f.limit_up_count_20d" and (number < 0 or number != number.to_integral_value()):
            raise ValueError("invalid_count_feature")
    gaps = [missing(key, "source_verification_pending")] if basis.get("verify_pending") else []
    if row.get("data_status") == "stale":
        gaps.append(missing(key, "upstream_marked_stale"))
    at = instant(row["available_at"])
    if key in GROUPS["fundamental"]:
        at = max(at, instant(basis["available_from"]), instant(basis["first_seen_at"]))
    return value, row["unit"], at, gaps, basis


def collect(
    conn: Connection, data: dict[str, Any], dimension: str
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    code, day = data["code"], data["day"]
    evidence, facts, refs, gaps, basis_by_key, stamps = [], [], [], [], {}, []
    for key in GROUPS[dimension]:
        basis: dict[str, Any] = {}
        if key in {"f.close_qfq", "f.high_qfq", "f.low_qfq", "f.rsi14", "f.amount"}:
            if data["frame_error"]:
                raise ValueError("daily_frame_invalid")
            frame = data["frame"]
            value = (
                frame["features"].get(key)
                if frame["visible_dates"] and frame["visible_dates"][-1] == str(day)
                else None
            )
            unit = data["registry"].get(key, {}).get("unit")
            if unit is None and key != "f.rsi14":
                unit = data["raw"].get("amount_unit" if key == "f.amount" else "price_unit")
            at = frame["data_as_of"] if value is not None else None
            local_gaps = [] if value is not None else [missing(key, "missing_input_or_warmup")]
            if key != "f.rsi14" and value is not None:
                local_gaps.append(missing(key, "documented_unit_scope_pending_live_verification"))
        else:
            value, unit, at, local_gaps, basis = scalar(conn, data, key)
        identifier = code + ":dimension:" + key
        # Null evidence describes a SYSTEM missing-source assessment, not a fake quote.
        assessment = dt.datetime.combine(day, dt.time.min, BEIJING)
        evidence.append(
            Evidence(
                id=identifier,
                key=key,
                value=None if value is None else str(value),
                unit=unit,
                provider=DataProvider.SYSTEM,
                endpoint="reports:cached-facts:" + code,
                data_as_of=at or assessment,
                fetched_at=at or assessment,
                epistemic_type=EpistemicType.ESTIMATE
                if value is not None
                else EpistemicType.HYPOTHESIS,
            ).model_dump(mode="json")
        )
        refs.append(
            {
                "feature_key": key,
                "status": data["registry"].get(key, {}).get("status"),
                "evidence_ids": [identifier],
            }
        )
        if value is not None:
            facts.append(
                {"text": key + " = " + str(value), "expr": None, "evidence_ids": [identifier]}
            )
            if at is not None:
                stamps.append(at)
        gaps.extend(local_gaps)
        if basis:
            basis_by_key[key] = basis
    if dimension == "news":
        for row in data.get("raw", {}).get("announcements", []):
            published, first_seen = instant(row["published_at"]), instant(row["first_seen_at"])
            if max(published, first_seen) > data["cutoff"]:
                continue
            link = row.get("url")
            if (
                not link
                or urlsplit(link).scheme not in {"http", "https"}
                or urlsplit(link).username
            ):
                continue
            identifier = code + ":announcement:" + str(row.get("id", digest(row)))
            evidence.append(
                Evidence(
                    id=identifier,
                    key="announcement.title",
                    value=row["title"],
                    unit=None,
                    provider=DataProvider.SYSTEM,
                    endpoint=link,
                    data_as_of=published,
                    fetched_at=first_seen,
                    epistemic_type=EpistemicType.FACT,
                ).model_dump(mode="json")
            )
            facts.append(
                {
                    "text": "公告标题：" + row["title"] + "；原文：" + link,
                    "expr": None,
                    "evidence_ids": [identifier],
                }
            )
            stamps.append(max(published, first_seen))
    result = DailyDimensionAnalysis.model_validate(
        {
            "dimension": dimension,
            "facts": facts,
            "feature_refs": refs,
            "data_status": "unavailable"
            if not facts
            else "stale"
            if any(g["message"].endswith("upstream_marked_stale") for g in gaps)
            else "partial"
            if gaps
            else "fresh",
            "data_as_of": max(stamps) if stamps else None,
            "gaps": gaps,
        }
    ).model_dump(mode="json")
    return result, evidence, basis_by_key


def build(
    conn: Connection,
    owner: uuid.UUID,
    account: uuid.UUID | None,
    code: str,
    day: dt.date,
    now: dt.datetime,
) -> tuple[uuid.UUID, list[dict[str, Any]], list[dict[str, Any]]]:
    if (
        account is not None
        and conn.execute(
            select(accounts.c.id).where(accounts.c.id == account, accounts.c.user_id == owner)
        ).scalar_one_or_none()
        is None
    ):
        raise AppError(ErrorCode.NOT_FOUND)
    registry = catalog(conn)
    load_error = None
    try:
        with conn.begin_nested():
            data = load_inputs(conn, owner, code, day, now, registry=registry)
    except (ValueError, KeyError, TypeError, ArithmeticError, SQLAlchemyError) as exc:
        load_error = type(exc).__name__
        data = {
            "code": code,
            "day": day,
            "now": now,
            "cutoff": min(now, dt.datetime.combine(day, dt.time.max, BEIJING)),
            "registry": registry,
            "frame_error": True,
            "frame": None,
            "scalars": [],
            "cached": None,
            "sources": [],
        }
    dimensions, evidence, bases = [], [], {}
    for dimension in GROUPS:
        try:
            with conn.begin_nested():
                result, proof, basis = collect(conn, data, dimension)
        except (ValueError, KeyError, TypeError, ArithmeticError, SQLAlchemyError) as exc:
            result = {
                "dimension": dimension,
                "facts": [],
                "feature_refs": [
                    {
                        "feature_key": key,
                        "status": data["registry"].get(key, {}).get("status"),
                        "evidence_ids": [],
                    }
                    for key in GROUPS[dimension]
                ],
                "data_status": "unavailable",
                "data_as_of": None,
                "gaps": [missing(dimension, type(exc).__name__, "upstream_error")],
            }
            proof, basis = [], {}
            for ref in result["feature_refs"]:
                identifier = code + ":dimension:" + ref["feature_key"]
                at = dt.datetime.combine(day, dt.time.min, BEIJING)
                proof.append(
                    Evidence(
                        id=identifier,
                        key=ref["feature_key"],
                        value=None,
                        unit=None,
                        provider=DataProvider.SYSTEM,
                        endpoint="reports:missing-source",
                        data_as_of=at,
                        fetched_at=at,
                        epistemic_type=EpistemicType.HYPOTHESIS,
                    ).model_dump(mode="json")
                )
                ref["evidence_ids"] = [identifier]
        if load_error:
            result["gaps"].append(missing("source_snapshot", load_error, "upstream_error"))
            if result["data_status"] == "fresh":
                result["data_status"] = "partial"
        dimensions.append(result)
        evidence.extend(proof)
        bases[dimension] = basis
    body = {
        "schema_version": SCHEMA,
        "mapping_version": "P2N-01/7.11.1",
        "algorithm_version": "p2n04-fact-coverage-v1",
        "feature_set_version": FEATURE_SET_VERSION,
        "catalog_fingerprint": digest(
            {
                k: {"status": v["status"], "unit": v["unit"], "source": v["source"]}
                for k, v in data["registry"].items()
            }
        ),
        "user_id": str(owner),
        "account_id": str(account) if account else None,
        "security_code": code,
        "date": str(day),
        "dimensions": dimensions,
        "evidence": evidence,
        "basis": bases,
        "sources": data["sources"],
    }
    fingerprint = digest(body)
    identifier = uuid.uuid5(uuid.NAMESPACE_URL, "p2n04:" + fingerprint)
    prior = conn.execute(select(data_snapshots).where(data_snapshots.c.id == identifier)).first()
    if prior is None:
        conn.execute(
            insert(data_snapshots).values(
                id=identifier,
                user_id=owner,
                purpose="report",
                hash=fingerprint,
                items=json.loads(canonical(body)),
                created_at=now,
            )
        )
    elif (
        prior.user_id != owner
        or prior.hash != fingerprint
        or digest(prior._mapping["items"]) != fingerprint
    ):
        raise ValueError("analysis_snapshot_hash_or_owner_conflict")
    return identifier, dimensions, evidence
