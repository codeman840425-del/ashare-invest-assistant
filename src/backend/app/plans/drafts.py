"""Draft authorization order and explicit user confirmation, never automatic approval."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Body
from sqlalchemy import Connection, Row, insert, select, update

from app.auth.deps import AuthDep, EngineDep, SettingsDep
from app.common.errors import AppError
from app.common.errors import ErrorCode as E
from app.common.pagination import Page
from app.config_files import MarketRuleSegment
from app.db.tables.accounts import accounts
from app.db.tables.market import securities
from app.db.tables.reviews import data_snapshots
from app.db.tables.signals import (
    candidate_signals,
    non_executable_reasons,
    plan_draft_confirmations,
    plan_drafts,
)
from app.db.tables.strategy import market_rule_versions, strategy_instances, strategy_versions
from app.market_rules.lots import check_qty
from app.plans import service as s
from app.plans.api import Paging, page, statuses
from app.plans.models import Confirm, Confirmed, DraftInput, PlanDraft, PlanInput
from app.signals.service import transition as signal_transition

router = APIRouter(tags=["plan-drafts"])


def candidates(conn: Connection, owner: uuid.UUID, ids: list[uuid.UUID]) -> list[Row[Any]]:
    rows = conn.execute(
        select(candidate_signals)
        .where(candidate_signals.c.user_id == owner, candidate_signals.c.id.in_(ids))
        .order_by(candidate_signals.c.id)
        .with_for_update()
    ).all()
    if len(rows) != len(set(ids)):
        s.invalid("signal_ids", "not_found")
    if len({(r.security_code, r.proposed_action, r.t_leg) for r in rows}) != 1:
        s.invalid("signal_ids", "mismatch")
    # Run each complete stage across all rows before moving to the next stage.
    for r in rows:
        instance = conn.execute(
            select(strategy_instances).where(
                strategy_instances.c.id == r.instance_id, strategy_instances.c.user_id == owner
            )
        ).first()
        actual = (
            (instance.derived_strategy_version_id or instance.strategy_version_id)
            if instance
            else None
        )
        life = conn.execute(
            select(strategy_versions.c.lifecycle)
            .where(strategy_versions.c.id == actual)
            .with_for_update()
        ).scalar_one_or_none()
        stored = conn.execute(
            select(strategy_versions.c.lifecycle)
            .where(strategy_versions.c.id == r.strategy_version_id)
            .with_for_update()
        ).scalar_one_or_none()
        if life not in {"published", "observing"} or stored not in {"published", "observing"}:
            raise AppError(E.STRATEGY_VERSION_NOT_RUNNABLE, details={"lifecycle": life or stored})
    for r in rows:
        if r.valid_until is not None and r.valid_until <= dt.datetime.now(dt.UTC):
            s.transition("expired", "drafted", [])
        if r.state not in {"open", "released", "drafted", "blocked"}:
            s.transition(r.state, "drafted", [])
    reasons = (
        conn.execute(
            select(non_executable_reasons.c.id)
            .where(
                non_executable_reasons.c.signal_id.in_(ids),
                non_executable_reasons.c.status == "active",
            )
            .order_by(non_executable_reasons.c.id)
        )
        .scalars()
        .all()
    )
    if reasons or any(r.state == "blocked" for r in rows):
        raise AppError(E.SIGNAL_NOT_EXECUTABLE, details={"reason_ids": [str(x) for x in reasons]})
    if any(
        not any(
            ref.get("role") in {"entry", "exit", "weakening"} and ref.get("passed") is True
            for ref in (r.rule_refs or [])
        )
        for r in rows
    ):
        raise AppError(E.PLAN_REQUIRES_EXPLAINABLE_SIGNAL)
    return list(rows)


@router.post("/plan-drafts", status_code=201, response_model=PlanDraft)
def generate(body: DraftInput, auth: AuthDep, engine: EngineDep) -> dict[str, Any]:
    with engine.begin() as conn:
        s.owner_lock(conn, auth.user_id)
        candidates(conn, auth.user_id, body.signal_ids)
        # Do not invent strategy budget, slippage, fee buffer, per-trade loss or
        # judgement checklist values. None is an executable production adapter yet.
        raise AppError(
            E.UPSTREAM_UNAVAILABLE,
            details={"gaps": ["draft_sizing_inputs_and_slippage_fee_checklist_adapter_missing"]},
        )


def own(conn: Connection, owner: uuid.UUID, identifier: uuid.UUID, lock: bool = False) -> Row[Any]:
    q = select(plan_drafts).where(plan_drafts.c.user_id == owner, plan_drafts.c.id == identifier)
    row = conn.execute(q.with_for_update() if lock else q).first()
    if row is None:
        raise AppError(E.NOT_FOUND)
    return row


def output(conn: Connection, d: Row[Any]) -> dict[str, Any]:
    name = conn.execute(
        select(securities.c.name).where(securities.c.code == d.security_code)
    ).scalar_one_or_none()
    return {
        "id": str(d.id),
        "status": d.status,
        "signal_ids": [str(x) for x in d.signal_ids],
        "security_code": d.security_code,
        "name": name or d.security_code,
        "action": d.action,
        "qty_range": d.qty_range,
        "price_range": d.price_range,
        "stops": d.stops,
        "max_loss_amount": str(d.max_loss_amount) if d.max_loss_amount is not None else None,
        "max_loss_pct": str(d.max_loss_pct) if d.max_loss_pct is not None else None,
        "fee_estimate": d.fee_estimate,
        "user_context_snapshot": d.user_context_snapshot,
        "risk_flags": d.risk_flags or [],
        "judgment_checklist": d.judgment_checklist or [],
        "valid_until": d.expires_at,
        "market_rule_version_id": str(d.market_rule_version_id)
        if d.market_rule_version_id
        else None,
        "created_at": d.created_at,
    }


@router.get("/plan-drafts/{identifier}", response_model=PlanDraft)
def detail(identifier: uuid.UUID, auth: AuthDep, engine: EngineDep) -> dict[str, Any]:
    with engine.connect() as conn:
        return output(conn, own(conn, auth.user_id, identifier))


@router.post("/plan-drafts/{identifier}/discard", response_model=PlanDraft)
def discard(
    identifier: uuid.UUID,
    auth: AuthDep,
    engine: EngineDep,
    ignored: dict[str, Any] = Body(default={}),  # noqa: B008
) -> dict[str, Any]:
    with engine.begin() as conn:
        s.owner_lock(conn, auth.user_id)
        d = own(conn, auth.user_id, identifier, True)
        if d.status == "discarded":
            return output(conn, d)
        if d.status != "pending":
            s.transition(d.status, "discarded", [])
        conn.execute(
            update(plan_drafts)
            .where(plan_drafts.c.id == identifier)
            .values(status="discarded", status_changed_at=dt.datetime.now(dt.UTC))
        )
        s.audit(conn, auth.user_id, "plan_draft.discarded", identifier)
        return output(conn, own(conn, auth.user_id, identifier))


@router.post("/plan-drafts/{identifier}/confirm", status_code=201, response_model=Confirmed)
def confirm(
    identifier: uuid.UUID, body: Confirm, auth: AuthDep, engine: EngineDep
) -> dict[str, Any]:
    from app.aggregates.service import select_account
    from app.api.v1.portfolio import _account

    with engine.begin() as conn:
        s.owner_lock(conn, auth.user_id)
        d = own(conn, auth.user_id, identifier, True)
        prior = conn.execute(
            select(plan_draft_confirmations).where(
                plan_draft_confirmations.c.draft_id == identifier,
                plan_draft_confirmations.c.user_id == auth.user_id,
            )
        ).first()
        if prior:
            expected = (
                prior.checklist_answers,
                prior.risk_ack,
                prior.chosen_qty,
                prior.chosen_price,
                prior.deviation,
            )
            actual = (
                [x.model_dump(mode="json") for x in body.checklist_answers],
                body.risk_ack,
                Decimal(body.chosen_qty),
                Decimal(body.chosen_price),
                {"ack": body.deviation_ack},
            )
            if expected != actual:
                raise AppError(E.IDEMPOTENCY_CONFLICT)
            return {"plan_id": str(prior.plan_id), "plan_version_no": 1}
        now = dt.datetime.now(dt.UTC)
        if d.status in {"stale", "expired"} or d.expires_at <= now:
            raise AppError(
                E.PLAN_DRAFT_STALE,
                details={"status": d.status if d.status != "pending" else "expired"},
            )
        if d.status != "pending":
            s.transition(d.status, "confirmed", [])
        validated_signals = candidates(conn, auth.user_id, d.signal_ids)
        for signal in validated_signals:
            if signal.state != "drafted":
                s.transition(signal.state, "confirmed", [])
        answers = {a.id: a for a in body.checklist_answers}
        if len(answers) != len(body.checklist_answers) or set(answers) - {
            q["id"] for q in d.judgment_checklist
        }:
            s.invalid("checklist_answers")
        missing = [
            q["id"] for q in d.judgment_checklist if q["required"] and q["id"] not in answers
        ]
        if missing:
            raise AppError(E.CHECKLIST_INCOMPLETE, details={"missing": missing})
        if not body.risk_ack:
            raise AppError(E.RISK_ACK_REQUIRED)
        source = conn.execute(
            select(data_snapshots).where(
                data_snapshots.c.id == d.snapshot_id,
                data_snapshots.c.user_id == auth.user_id,
                data_snapshots.c.created_at <= now,
            )
        ).first()
        rules = conn.execute(
            select(market_rule_versions.c.rules).where(
                market_rule_versions.c.id == d.market_rule_version_id
            )
        ).scalar_one_or_none()
        if source is None or rules is None:
            raise AppError(E.PLAN_DRAFT_STALE, details={"status": "stale"})
        ctx = source.items.get("plan_draft_context")
        if not ctx or source.items.get("schema_version") != "p2n07-draft-input-v1":
            raise AppError(E.PLAN_DRAFT_STALE, details={"status": "stale"})
        import hashlib

        from app.workers.assembly import canonical

        if hashlib.sha256(canonical(source.items).encode()).hexdigest() != source.hash:
            raise AppError(E.PLAN_DRAFT_STALE, details={"status": "stale"})
        account_id = select_account(conn, auth.user_id, None)
        if ctx.get("account_id") != (str(account_id) if account_id else None) or account_id is None:
            raise AppError(E.PLAN_DRAFT_STALE, details={"status": "stale"})
        conn.execute(
            select(accounts.c.id)
            .where(accounts.c.id == account_id, accounts.c.user_id == auth.user_id)
            .with_for_update()
        ).one()
        account = _account(
            conn, account_id, now.astimezone(dt.timezone(dt.timedelta(hours=8))).date()
        )
        pos = account.positions.get(d.security_code)
        current = {
            "holding_qty": str(pos.qty if pos else 0),
            "sellable_qty": str(pos.sellable if pos else 0),
            "cash": str(account.cash) if account.cash is not None else None,
        }
        try:
            changed = any(
                current[k] is None
                or Decimal(str(d.user_context_snapshot.get(k))) != Decimal(str(current[k]))
                for k in current
            )
        except (ValueError, TypeError, ArithmeticError, AttributeError):
            changed = True
        if changed:
            raise AppError(E.PLAN_DRAFT_STALE, details={"status": "stale"})
        security = conn.execute(
            select(securities).where(securities.c.code == d.security_code)
        ).one()
        segment = MarketRuleSegment.model_validate(rules)
        issue = check_qty(
            segment,
            board=security.board,
            security_type=security.type,
            side="buy" if d.action in {"buy", "add"} else "sell",
            qty=Decimal(body.chosen_qty),
            sellable_qty=Decimal(str(current["sellable_qty"])),
        )
        if issue:
            raise AppError(E.VALIDATION_ERROR, details={"fields": [issue]})
        if d.action in {"buy", "add"} and Decimal(body.chosen_qty) * Decimal(
            body.chosen_price
        ) + Decimal(d.fee_estimate["amount"]) > Decimal(str(account.cash)):
            s.invalid("chosen_qty", "insufficient_cash")
        if d.action in {"buy", "add"} and (
            ctx.get("quantity_cap") is None
            or Decimal(body.chosen_qty) > Decimal(ctx["quantity_cap"])
        ):
            s.invalid("chosen_qty", "quantity_cap_unavailable_or_exceeded")
        fields = []
        if (
            not Decimal(d.qty_range["min"])
            <= Decimal(body.chosen_qty)
            <= Decimal(d.qty_range["max"])
        ):
            fields.append("chosen_qty")
        if (
            not Decimal(d.price_range["low"])
            <= Decimal(body.chosen_price)
            <= Decimal(d.price_range["high"])
        ):
            fields.append("chosen_price")
        if fields and not body.deviation_ack:
            raise AppError(E.DEVIATION_ACK_REQUIRED, details={"fields": fields})
        full_answers = [
            {
                "id": q["id"],
                "question": q["question"],
                "answer": answers[q["id"]].answer,
                "note": answers[q["id"]].note,
            }
            for q in d.judgment_checklist
            if q["id"] in answers
        ]
        plan = s.create(
            conn,
            auth.user_id,
            PlanInput(
                security_code=d.security_code,
                account_id=account_id,
                action=d.action,
                qty=body.chosen_qty,
                price=body.chosen_price,
                stops=d.stops,
                rationale="用户确认计划草案",
                max_loss_amount=str(d.max_loss_amount) if d.max_loss_amount is not None else None,
            ),
            draft=d,
            answers=full_answers,
        )
        conn.execute(
            insert(plan_draft_confirmations).values(
                draft_id=d.id,
                user_id=auth.user_id,
                checklist_answers=[a.model_dump(mode="json") for a in body.checklist_answers],
                risk_ack=True,
                chosen_qty=body.chosen_qty,
                chosen_price=body.chosen_price,
                deviation={"ack": body.deviation_ack},
                plan_id=uuid.UUID(plan["id"]),
            )
        )
        conn.execute(
            update(plan_drafts)
            .where(plan_drafts.c.id == d.id)
            .values(status="confirmed", status_changed_at=now)
        )
        for signal in validated_signals:
            signal_transition(
                conn,
                signal,
                "confirmed",
                "user",
                now,
                {"plan_id": plan["id"], "plan_draft_id": str(identifier)},
            )
        s.audit(conn, auth.user_id, "plan_draft.confirmed", identifier, {"plan_id": plan["id"]})
        return {"plan_id": plan["id"], "plan_version_no": 1}


@router.get("/plan-drafts", response_model=Page[PlanDraft])
def listing(
    auth: AuthDep,
    engine: EngineDep,
    cfg: SettingsDep,
    pp: Paging,
    status: str = "all",
    security_code: str | None = None,
    signal_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    wanted = statuses(status, {"pending", "confirmed", "discarded", "expired", "stale"})
    with engine.connect() as conn:
        q = select(plan_drafts).where(plan_drafts.c.user_id == auth.user_id)
        if wanted:
            q = q.where(plan_drafts.c.status.in_(wanted))
        if security_code is not None:
            q = q.where(plan_drafts.c.security_code == security_code)
        if signal_id is not None:
            q = q.where(plan_drafts.c.signal_ids.any(signal_id))
        scope = f"plan-drafts:{auth.user_id}:{status}:{security_code}:{signal_id}"
        p = page(conn, plan_drafts, q, pp, cfg, scope, plan_drafts.c.created_at)
        return {"items": [output(conn, d) for d in p.items], "next_cursor": p.next_cursor}
