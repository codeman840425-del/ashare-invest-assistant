"""DB-authoritative private bindings: deletion retention and clock are one SQL transaction.

Only a runtime-keyed tag enters ingest_private; API/maintenance cannot SELECT it.
Scope UUID history contains no tag and distinguishes detached from unknown files.
No local-clock expiry and no SQLite cache can outlive the DELETE transaction.
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import hmac
import os
import stat
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.db.tables.licences import user_data_licence_status as licences
from app.ingest.shared_gate import GateClosedError, _read, _write

KEY = "binding-key.json"


@functools.lru_cache(maxsize=4)
def _configured_engine(path: str) -> Engine:
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o022:
            raise GateClosedError("shared_database_reference_invalid")
        raw = os.read(fd, 8193)
        if len(raw) > 8192:
            raise GateClosedError("shared_database_reference_invalid")
        value = raw.decode().strip()
        if not value.startswith("postgresql+psycopg://"):
            raise GateClosedError("shared_database_reference_invalid")
        return create_engine(value, hide_parameters=True, connect_args={"connect_timeout": 2})
    except (OSError, UnicodeError, ValueError):
        raise GateClosedError("shared_database_reference_unavailable") from None
    finally:
        if fd is not None:
            os.close(fd)


def engine_from_environment() -> Engine:
    reference = os.environ.get("MAIRUI_SHARED_DATABASE_URL_FILE", "")
    if reference:
        return _configured_engine(reference)
    # Product ingest reuses its existing role/secret wiring; standalone probes
    # must supply an explicit private reference instead of searching credentials.
    from app.config import get_settings
    from app.db.engine import engine_for

    settings = get_settings()
    if settings.service_name != "ingest" or settings.database_url is None:
        raise GateClosedError("shared_database_clock_required")
    return engine_for(settings.database_url.get_secret_value())


@contextlib.contextmanager
def transaction(engine: Engine | None = None, *, prune: bool = True) -> Iterator[Any]:
    try:
        with (engine or engine_from_environment()).begin() as conn:
            role = conn.execute(
                text(
                    "SELECT current_user AS name,rolsuper OR rolcreatedb OR rolcreaterole "
                    "OR rolreplication OR rolbypassrls AS privileged FROM pg_roles "
                    "WHERE rolname=current_user"
                )
            ).one()
            if role.name != "aia_ingest" or role.privileged:
                raise GateClosedError("shared_database_role_refused")
            # Expiry, including immediate DELETE expiry, uses only PostgreSQL now().
            if prune:
                conn.execute(text("SELECT ingest_private.prune_mairui_gate_bindings()"))
            yield conn
    except SQLAlchemyError:
        raise GateClosedError("shared_database_state_unavailable") from None


def bind(root: Path, licence: str, secret: str, engine: Engine | None = None) -> str:
    ident = uuid.UUID(licence)
    with transaction(engine, prune=False) as conn:
        row = conn.execute(
            select(licences.c.user_id).where(
                licences.c.id == ident,
                licences.c.deleted_at.is_(None),
            )
        ).first()
        if row is None:
            raise GateClosedError("shared_licence_detached")
        # Serialize all tag bindings for this owner with API DELETE/replace/hold.
        # A sender already owns that same control lock only after binding finishes.
        from app.licences.service import lock_control

        lock_control(conn, row.user_id)
        conn.execute(text("SELECT ingest_private.prune_mairui_gate_bindings()"))
        if (
            conn.execute(
                select(licences.c.id).where(
                    licences.c.id == ident,
                    licences.c.deleted_at.is_(None),
                )
            ).first()
            is None
        ):
            raise GateClosedError("shared_licence_detached")
        keyfile = root / KEY
        if not keyfile.exists():
            if conn.execute(
                text("SELECT 1 FROM ingest_private.mairui_gate_bindings LIMIT 1")
            ).first():
                raise GateClosedError("shared_binding_key_missing")
            _write(keyfile, {"key": os.urandom(32).hex()}, exclusive=True)
        info = keyfile.lstat()
        if os.name != "nt" and (stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.geteuid()):
            raise GateClosedError("shared_binding_key_private_required")
        try:
            key = bytes.fromhex(_read(keyfile)["key"])
            if len(key) != 32:
                raise ValueError
        except (ValueError, TypeError, KeyError):
            raise GateClosedError("shared_binding_key_invalid") from None
        tag = hmac.digest(
            key, b"mairui-binding/v3\0" + row.user_id.bytes + secret.encode(), hashlib.sha256
        )
        found = conn.execute(
            text(
                "SELECT scope_id FROM ingest_private.mairui_gate_bindings "
                "WHERE user_id=:owner AND tag=:tag AND (expires_at IS NULL OR expires_at>now()) "
                "ORDER BY licence_id LIMIT 1"
            ),
            {"owner": row.user_id, "tag": tag},
        ).first()
        scope = found.scope_id if found else uuid.uuid4()
        existing = conn.execute(
            text("SELECT scope_id FROM ingest_private.mairui_gate_bindings WHERE licence_id=:id"),
            {"id": ident},
        ).first()
        if existing and existing.scope_id != scope:
            raise GateClosedError("shared_certificate_binding_changed")
        if not found:
            conn.execute(
                text(
                    "INSERT INTO ingest_private.mairui_gate_scopes(id,origin_licence_id) "
                    "VALUES(:scope,:id)"
                ),
                {"scope": scope, "id": ident},
            )
        conn.execute(
            text(
                "INSERT INTO ingest_private.mairui_gate_bindings(licence_id,user_id,scope_id,tag) "
                "VALUES(:id,:owner,:scope,:tag) ON CONFLICT(licence_id) DO NOTHING"
            ),
            {"id": ident, "owner": row.user_id, "scope": scope, "tag": tag},
        )
        conn.execute(
            text("UPDATE ingest_private.mairui_gate_scopes SET detached_at=NULL WHERE id=:id"),
            {"id": scope},
        )
        return scope.hex


@contextlib.contextmanager
def control(licence: str) -> Iterator[None]:
    """Probe sends join the existing API per-user deletion/hold transaction fence."""
    from app.licences.service import lock_control

    with transaction(prune=False) as conn:
        owner = conn.execute(
            select(licences.c.user_id).where(
                licences.c.id == uuid.UUID(licence),
                licences.c.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if owner is None:
            raise GateClosedError("shared_licence_detached")
        lock_control(conn, owner)
        if (
            conn.execute(
                select(licences.c.id).where(
                    licences.c.id == uuid.UUID(licence),
                    licences.c.deleted_at.is_(None),
                )
            ).first()
            is None
        ):
            raise GateClosedError("shared_licence_detached")
        yield


def identity(root: Path, licence: str, engine: Engine | None = None) -> str | None:
    with transaction(engine) as conn:
        row = conn.execute(
            text(
                "SELECT b.scope_id FROM ingest_private.mairui_gate_bindings b "
                "JOIN app.user_data_licence_status l ON l.id=b.licence_id "
                "WHERE b.licence_id=:id AND l.deleted_at IS NULL "
                "AND (b.expires_at IS NULL OR b.expires_at>now())"
            ),
            {"id": uuid.UUID(licence)},
        ).first()
        return row.scope_id.hex if row else None


def related(root: Path, licence: str, engine: Engine | None = None) -> list[uuid.UUID]:
    ident = uuid.UUID(licence)
    with transaction(engine) as conn:
        rows = conn.execute(
            text(
                "SELECT licence_id FROM ingest_private.mairui_gate_bindings WHERE scope_id="
                "(SELECT scope_id FROM ingest_private.mairui_gate_bindings WHERE licence_id=:id)"
            ),
            {"id": ident},
        )
        return list({ident, *(row.licence_id for row in rows)})


def identifiers(root: Path, engine: Engine | None = None, *, active_only: bool = False) -> set[str]:
    with transaction(engine) as conn:
        sql = "SELECT id FROM ingest_private.mairui_gate_scopes"
        if active_only:
            sql += " WHERE detached_at IS NULL"
        return {row.id.hex for row in conn.execute(text(sql))}


def cleanup(root: Path | None = None, *, engine: Engine | None = None) -> None:
    with transaction(engine):
        pass


def live(root: Path, licence: str, engine: Engine | None = None) -> bool:
    with transaction(engine) as conn:
        return (
            conn.execute(
                text(
                    "SELECT l.id FROM app.user_data_licence_status l "
                    "JOIN app.users u ON u.id=l.user_id WHERE l.id=:id AND l.deleted_at IS NULL "
                    "AND u.status='approved' AND l.status<>'paused_by_admin' "
                    "AND NOT EXISTS(SELECT 1 FROM app.user_data_licence_holds h "
                    "WHERE h.user_id=l.user_id)"
                ),
                {"id": uuid.UUID(licence)},
            ).first()
            is not None
        )
