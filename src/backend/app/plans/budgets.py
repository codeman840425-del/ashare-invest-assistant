"""T-A40: owned plan estimates, never infer instance budget usage from holdings."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, select

from app.db.tables.research import action_plans, plan_versions
from app.db.tables.signals import candidate_signals, plan_drafts


class BudgetExhaustedError(Exception):
    def __init__(self, allocations: list[dict[str, Any]]) -> None:
        self.allocations = allocations
        super().__init__("STRATEGY_BUDGET_EXHAUSTED")


class BudgetUnknownError(Exception):
    pass


def allocations(
    conn: Connection, owner: uuid.UUID, instances: Sequence[Any], at: dt.datetime
) -> list[dict[str, Any]]:
    result = []
    for inst in sorted(instances, key=lambda r: str(r.id)):
        if inst.user_id != owner:
            raise BudgetUnknownError("budget_instance_owner")
        item: dict[str, Any] = {
            "instance_id": str(inst.id),
            "budget_amount": str(inst.budget_amount) if inst.budget_amount is not None else None,
            "budget_used": None,
            "plan_ids": [],
            "epistemic_type": "estimate",
        }
        if inst.budget_amount is None:
            result.append(item)
            continue
        used = Decimal(0)
        for plan in conn.execute(
            select(action_plans).where(
                action_plans.c.user_id == owner,
                action_plans.c.status.in_(["active", "triggered"]),
                action_plans.c.created_at <= at,
            )
        ):
            first = conn.execute(
                select(plan_versions).where(
                    plan_versions.c.plan_id == plan.id, plan_versions.c.version_no == 1
                )
            ).one()
            ids = (first.completeness or {}).get("candidate_signal_ids")
            if ids is None and plan.plan_draft_id is not None:
                draft = conn.execute(
                    select(plan_drafts).where(
                        plan_drafts.c.id == plan.plan_draft_id,
                        plan_drafts.c.user_id == owner,
                        plan_drafts.c.snapshot_id == first.snapshot_id,
                    )
                ).one_or_none()
                if draft is not None:
                    ids = draft.signal_ids
            if ids is None and plan.origin == "plan_draft":
                raise BudgetUnknownError("budget_plan_origin")
            belongs = conn.execute(
                select(candidate_signals.c.id).where(
                    candidate_signals.c.id.in_(ids or []),
                    candidate_signals.c.instance_id == inst.id,
                    candidate_signals.c.user_id == owner,
                )
            ).first()
            if not belongs:
                continue
            version = conn.execute(
                select(plan_versions).where(
                    plan_versions.c.id == plan.current_version_id,
                    plan_versions.c.plan_id == plan.id,
                )
            ).one_or_none()
            if version is None or version.created_at > at:
                raise BudgetUnknownError("budget_plan_latest_version")
            if version.action not in {"buy", "add"}:
                continue
            payload = version.completeness or {}
            try:
                if payload.get("qty") is not None and payload.get("price") is not None:
                    amount = Decimal(str(payload["qty"])) * Decimal(str(payload["price"]))
                elif version.size_amount is not None:
                    amount = Decimal(version.size_amount)
                else:
                    raise BudgetUnknownError("budget_plan_amount")
            except ArithmeticError:
                raise BudgetUnknownError("budget_plan_amount") from None
            if not amount.is_finite() or amount < 0:
                raise BudgetUnknownError("budget_plan_amount")
            used += amount
            item["plan_ids"].append(str(plan.id))
        item["plan_ids"].sort()
        item["budget_used"] = str(used)
        result.append(item)
    return result


def remaining(items: list[dict[str, Any]]) -> Decimal | None:
    values = [
        Decimal(r["budget_amount"]) - Decimal(r["budget_used"])
        for r in items
        if r["budget_amount"] is not None
    ]
    if values and min(values) <= 0:
        raise BudgetExhaustedError(items)
    return min(values) if values else None


def refresh_reasons(
    conn: Connection, owner: uuid.UUID, signals: list[Any], at: dt.datetime
) -> None:
    """Only POST draft writes transitions; close/revision may release this estimate."""
    from sqlalchemy import insert, update

    from app.db.tables.signals import non_executable_reasons, reason_status_events
    from app.db.tables.strategy import strategy_instances
    from app.signals.service import transition

    for signal in signals:
        if signal.proposed_action not in {"buy", "add"}:
            continue
        reasons = conn.execute(
            select(non_executable_reasons).where(
                non_executable_reasons.c.signal_id == signal.id,
                non_executable_reasons.c.user_id == owner,
                non_executable_reasons.c.code == "STRATEGY_BUDGET_EXHAUSTED",
                non_executable_reasons.c.status == "active",
            )
        ).all()
        if not reasons:
            continue
        inst = conn.execute(
            select(strategy_instances).where(
                strategy_instances.c.id == signal.instance_id, strategy_instances.c.user_id == owner
            )
        ).all()
        if not inst:
            continue
        try:
            remaining(allocations(conn, owner, inst, at))
        except (BudgetExhaustedError, BudgetUnknownError):
            continue
        for reason in reasons:
            conn.execute(
                update(non_executable_reasons)
                .where(non_executable_reasons.c.id == reason.id)
                .values(status="released", released_at=at, released_by="system")
            )
            conn.execute(
                insert(reason_status_events).values(
                    id=uuid.uuid4(),
                    reason_id=reason.id,
                    from_status="active",
                    to_status="released",
                    at=at,
                )
            )
        other = conn.execute(
            select(non_executable_reasons.c.id).where(
                non_executable_reasons.c.signal_id == signal.id,
                non_executable_reasons.c.status == "active",
            )
        ).first()
        if signal.state == "blocked" and other is None:
            transition(conn, signal, "released", "executability_check", at, {"budget": "rechecked"})


def block(
    conn: Connection,
    owner: uuid.UUID,
    signals: list[Any],
    items: list[dict[str, Any]],
    at: dt.datetime,
) -> list[str]:
    from sqlalchemy import update

    from app.db.tables.signals import non_executable_reasons
    from app.signals.service import add_reason, transition

    result = []
    for signal in signals:
        evidence = [
            {
                "id": "budget:" + r["instance_id"],
                "key": "strategy.budget_remaining",
                "value": str(Decimal(r["budget_amount"]) - Decimal(r["budget_used"])),
                "unit": "CNY",
                "provider": "system",
                "endpoint": "owned_plan_versions",
                "data_as_of": at.isoformat(),
                "fetched_at": at.isoformat(),
                "epistemic_type": "estimate",
            }
            for r in items
            if r["budget_amount"] is not None
        ]
        identifier = add_reason(
            conn,
            signal_id=signal.id,
            user_id=owner,
            snapshot_id=signal.snapshot_id,
            code="STRATEGY_BUDGET_EXHAUSTED",
            at=at,
            evidence=evidence,
            salt=at.isoformat(),
            release={
                "kind": "expr",
                "expr": "strategy_used < budget",
                "at": None,
                "event": None,
                "action": None,
                "check_on": ["holding_change"],
                "human_text": "实例预算已用完；按来源计划重新检查。",
                "machine_checkable": True,
            },
        )
        conn.execute(
            update(non_executable_reasons)
            .where(non_executable_reasons.c.id == identifier)
            .values(epistemic_type="estimate")
        )
        transition(
            conn, signal, "blocked", "executability_check", at, {"reason_ids": [str(identifier)]}
        )
        result.append(str(identifier))
    return result
