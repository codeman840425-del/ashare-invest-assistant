"""Read-only owned RC6 DB projection; no invented complete-history watermark."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import Connection, select

from app.db.tables.accounts import accounts, import_batches, trades
from app.db.tables.research import action_plans, plan_versions
from app.db.tables.users import audit_logs, users
from app.feedback.core import timestamp
from app.feedback.plans import Facts, Plan, Trade, _evidence
from app.signals.models import Evidence


@dataclass(frozen=True)
class Loaded:
    facts: Facts | None
    evidence: tuple[Evidence, ...] = ()
    gaps: tuple[str, ...] = ()


def load(
    conn: Connection, owner: uuid.UUID, account: uuid.UUID | None, code: str, *, at: dt.datetime
) -> Loaded:
    timestamp(at)
    if (
        account is None
        or conn.execute(
            select(accounts.c.id)
            .join(users, users.c.id == accounts.c.user_id)
            .where(
                accounts.c.id == account,
                accounts.c.user_id == owner,
                accounts.c.archived_at.is_(None),
                accounts.c.created_at <= at,
                users.c.status == "approved",
            )
        ).first()
        is None
    ):
        return Loaded(None, gaps=("plan_account_scope_unknown",))
    gaps = {"plan_history_coverage_unproven"}
    projected: list[Plan] = []
    evidence: list[Evidence] = []
    heads = conn.execute(
        select(action_plans.c.id, action_plans.c.status).where(
            action_plans.c.user_id == owner,
            action_plans.c.account_id == account,
            action_plans.c.security_code == code,
            action_plans.c.created_at <= at,
        )
    ).all()
    for head in heads:
        versions = conn.execute(
            select(
                plan_versions.c.id,
                plan_versions.c.version_no,
                plan_versions.c.action,
                plan_versions.c.created_at,
                plan_versions.c.completeness["qty"].astext.label("qty"),
            )
            .where(plan_versions.c.plan_id == head.id, plan_versions.c.created_at <= at)
            .order_by(plan_versions.c.version_no)
        ).all()
        closed = (
            conn.execute(
                select(audit_logs.c.at)
                .where(
                    audit_logs.c.target_type == "action_plan",
                    audit_logs.c.target_id == str(head.id),
                    audit_logs.c.actor_id == owner,
                    audit_logs.c.action == "plan.closed",
                )
                .order_by(audit_logs.c.at)
            )
            .scalars()
            .all()
        )
        visible_closed = [t for t in closed if t <= at]
        if head.status not in {"active", "triggered"} and not closed:
            gaps.add("plan_closed_boundary_unproven")
            continue
        if [r.version_no for r in versions] != list(range(1, len(versions) + 1)):
            gaps.add("plan_version_sequence_incomplete")
            continue
        for index, v in enumerate(versions):
            endings = visible_closed[:1]
            if index + 1 < len(versions):
                endings = [*endings, versions[index + 1].created_at]
            end = min(endings) if endings else None
            if end is not None and end <= v.created_at:
                gaps.add("plan_empty_or_unresolved_interval")
                continue
            try:
                qty = Decimal(v.qty) if v.qty is not None else None
                if qty is not None and (not qty.is_finite() or qty < 0):
                    raise ValueError("invalid_qty")
            except (InvalidOperation, ValueError):
                qty = None
                gaps.add("planned_quantity_invalid")
            side = (
                "buy"
                if v.action in {"buy", "add"}
                else "sell"
                if v.action in {"sell", "reduce"}
                else v.action
            )
            projected.append(
                Plan(
                    str(v.id), owner, account, code, side, qty, v.created_at, end, v.created_at, end
                )
            )
            evidence.append(
                _evidence("db_version:" + str(v.id), str(v.qty), v.created_at, v.created_at)
            )
            if end is not None:
                evidence.append(_evidence("db_end:" + str(v.id), end.isoformat(), end, end))
    # Explicit columns only: never read shareholder hashes, raw rows or amounts.
    rows = conn.execute(
        select(
            trades.c.id,
            trades.c.side,
            trades.c.quantity,
            trades.c.traded_at,
            trades.c.trade_date,
            trades.c.created_at,
            trades.c.voided_at,
            trades.c.import_batch_id,
        ).where(
            trades.c.user_id == owner,
            trades.c.account_id == account,
            trades.c.security_code == code,
            trades.c.created_at <= at,
        )
    ).all()
    projected_trades: list[Trade] = []
    for row in rows:
        known = row.created_at
        if row.import_batch_id is not None:
            batch = conn.execute(
                select(import_batches.c.committed_at).where(
                    import_batches.c.id == row.import_batch_id,
                    import_batches.c.user_id == owner,
                    import_batches.c.account_id == account,
                )
            ).first()
            if batch is None or batch.committed_at is None:
                gaps.add("plan_trade_commit_unproven")
                continue
            known = max(known, batch.committed_at)
        if known > at:
            continue
        executed = row.traded_at or row.trade_date
        from app.feedback.plans import execution

        if execution(executed) > at:
            continue
        voided = row.voided_at is not None and row.voided_at <= at
        if voided:
            known = max(known, row.voided_at)
        projected_trades.append(
            Trade(
                str(row.id), owner, account, code, row.side, row.quantity, executed, known, voided
            )
        )
        evidence.append(
            _evidence(
                "db_trade:" + str(row.id),
                "voided" if voided else str(row.quantity),
                execution(executed),
                known,
            )
        )
    # No existing contract/table proves full plan+trade coverage through `at`.
    # Committed import rows, balances or a nonempty DB are not such proof.
    return Loaded(
        Facts(owner, account, code, tuple(projected), tuple(projected_trades), None, False),
        tuple(evidence),
        tuple(sorted(gaps)),
    )
