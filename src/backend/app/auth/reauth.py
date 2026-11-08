"""T-A20 request-local reauthentication. No cached approval, plaintext persistence or retry."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import redis
from pydantic import SecretStr
from sqlalchemy import Connection, Engine, select

from app.auth import abuse, service
from app.auth.deps import AuthContext
from app.auth.passwords import PasswordPolicy
from app.auth.sessions import SessionStore
from app.common.errors import AppError, ErrorCode
from app.config import Settings
from app.db.tables.users import users


@contextmanager
def transaction(
    engine: Engine,
    auth: AuthContext,
    store: SessionStore,
    password: SecretStr | None,
    passwords: PasswordPolicy,
    rds: redis.Redis,
    settings: Settings,
    sid: str | None,
) -> Iterator[Connection]:
    # Serialize credential changes/lockout and the protected write on the same user
    # row. A failed password commits *only* its failure counters/audit; business
    # errors roll back all successful reauthentication and state-change writes.
    with engine.connect() as conn, conn.begin() as tx:
        user = conn.execute(
            select(users).where(users.c.id == auth.user_id).with_for_update()
        ).first()
        session = store.get(sid)
        if (
            session is None
            or session.origin != "password_login"
            or session.user_id != str(auth.user_id)
        ):
            raise AppError(ErrorCode.HUMAN_SESSION_REQUIRED)
        if (
            user is None
            or user.deleted_at is not None
            or user.status != "approved"
            or user.role != "admin"
        ):
            raise AppError(ErrorCode.NOT_FOUND)
        retry = abuse.locked_retry_after(user, user.username, rds, service.now_utc())
        if retry is not None:
            abuse.record_attempt(
                conn,
                username=user.username,
                user_id=user.id,
                ip_hash=None,
                success=False,
                failure_reason="reauth_locked",
            )
            tx.commit()
            raise AppError(ErrorCode.ACCOUNT_LOCKED, details={"retry_after_s": retry})
        if not passwords.verify(
            user.password_hash, password.get_secret_value() if password else ""
        ):
            abuse.record_failure(
                conn, settings.auth_abuse, user_id=user.id, username=user.username, rds=rds
            )
            abuse.record_attempt(
                conn,
                username=user.username,
                user_id=user.id,
                ip_hash=None,
                success=False,
                failure_reason="reauth_failed",
            )
            service.audit(
                conn,
                action="auth.reauth_failed",
                actor_id=user.id,
                actor_role=user.role,
                target_type="user",
                target_id=str(user.id),
            )
            tx.commit()
            raise AppError(ErrorCode.REAUTH_FAILED)
        abuse.reset_failures(conn, user=user, username=user.username, rds=rds)
        yield conn
