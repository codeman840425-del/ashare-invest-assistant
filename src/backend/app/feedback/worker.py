"""Owned RC5 expiry sweep, no acquisition, transport or lifecycle promotion."""

from __future__ import annotations

from sqlalchemy import select

from app.common.errors import AppError, ErrorCode
from app.config import Settings
from app.db.tables.accounts import accounts
from app.db.tables.strategy import strategy_instances as instances
from app.db.tables.users import users
from app.feedback.pause import resume_due

TASK = "risk.rc5_expiry"


def task(settings: Settings) -> int:
    from app.workers.jobs import _engine, _now

    at = _now()
    engine = _engine(settings)
    # A queue message contains no caller-selected owner, deadline or lifecycle.
    # Resolve real due rows, then recheck ownership/state under transaction locks.
    with engine.connect() as conn:
        due = conn.execute(
            select(instances.c.id, instances.c.user_id)
            .join(users, users.c.id == instances.c.user_id)
            .join(accounts, accounts.c.id == instances.c.account_id)
            .where(
                instances.c.status == "paused",
                instances.c.paused_by == "system",
                instances.c.pause_reason_code == "LOSS_STREAK_PAUSE",
                instances.c.paused_until <= at,
                instances.c.created_at <= at,
                users.c.status == "approved",
                accounts.c.user_id == instances.c.user_id,
                accounts.c.archived_at.is_(None),
                accounts.c.created_at <= at,
            )
            .order_by(instances.c.user_id, instances.c.id)
        ).all()
    count = 0
    for row in due:
        try:
            # One instance commits its state/audit/blocked notification together.
            with engine.begin() as conn:
                outcome = resume_due(
                    conn, row.user_id, row.id, settings.business.risk_controls, now=at
                )
            count += int(outcome.changed)
        except AppError as exc:
            if exc.code not in {ErrorCode.NOT_FOUND, ErrorCode.ACCOUNT_NOT_APPROVED}:
                raise
            # Deletion/revocation between selection and row locking is a no-op.
    return count
