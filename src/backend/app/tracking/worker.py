"""Registered internal worker, no network collector or production scheduler activation."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import create_engine, select

from app.config import Settings
from app.db.tables.realtime import suggestions
from app.db.tables.users import users
from app.replay.baseline import require_isolated
from app.tracking.service import run_one

TASK = "tracking"


def tracking_task(settings: Settings, user_id: str | None = None, as_of: str | None = None) -> int:
    if settings.database_url is None:
        raise ValueError("tracking_database_not_configured")
    engine = create_engine(settings.database_url.get_secret_value(), hide_parameters=True)
    at = dt.datetime.now(dt.UTC)
    try:
        if as_of is not None:
            # Controlled synthetic clocks require the established dedicated DB boundary.
            with engine.connect() as conn:
                require_isolated(conn, app_env=settings.app_env)
            at = dt.datetime.fromisoformat(as_of)
            if at.tzinfo is None:
                raise ValueError("tracking_clock_requires_timezone")
        with engine.connect() as conn:
            query = (
                select(suggestions.c.id, suggestions.c.user_id)
                .join(users, users.c.id == suggestions.c.user_id)
                .where(users.c.status == "approved", suggestions.c.created_at <= at)
            )
            if user_id is not None:
                query = query.where(suggestions.c.user_id == uuid.UUID(user_id))
            work = conn.execute(query).all()
        completed = 0
        for item in work:
            with engine.begin() as conn:
                completed += run_one(conn, item.user_id, item.id, at)
        return completed
    finally:
        engine.dispose()
