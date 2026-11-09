"""Private, erasable certificate associations. No credential-derived filenames.

Only the shared gate lease holder binds. The keyed equality tag lives in one
0600 SQLite database (secure_delete, no WAL); UUID state files contain no tag.
Deletion/expiry removes associations, never halt/budget facts. Orphan facts
remain fail-closed until an authorized operator resolves them.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import os
import sqlite3
import stat
import time
import uuid
from collections.abc import Iterator, Mapping
from pathlib import Path

from app.ingest.shared_gate import GateClosedError, _read, _sync_directory, _write

DATABASE = "certificate-bindings.sqlite3"
KEY = "binding-key.json"
TTL = 30 * 86400


@contextlib.contextmanager
def database(root: Path, *, create: bool = False) -> Iterator[sqlite3.Connection | None]:
    path = root / DATABASE
    try:
        if create:
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(fd)
                _sync_directory(root)
        try:
            info = path.lstat()
        except FileNotFoundError:
            yield None
            return
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or (
                os.name != "nt"
                and (stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.geteuid())
            )
        ):
            raise GateClosedError("shared_binding_storage_private_required")
        conn = sqlite3.connect(path, timeout=1, isolation_level=None)
        try:
            conn.execute("PRAGMA secure_delete=ON")
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS certificates "
                "(id TEXT PRIMARY KEY, tag BLOB UNIQUE NOT NULL, expires REAL NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS bindings "
                "(licence TEXT PRIMARY KEY, certificate TEXT NOT NULL, expires REAL NOT NULL)"
            )
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
    except (OSError, sqlite3.Error):
        raise GateClosedError("shared_binding_storage_unavailable") from None


def _identifier(value: object) -> str:
    try:
        if not isinstance(value, str) or uuid.UUID(value).hex != value:
            raise ValueError
    except ValueError:
        raise GateClosedError("shared_certificate_binding_invalid") from None
    return value


def _prune(conn: sqlite3.Connection, now: float) -> None:
    conn.execute("DELETE FROM bindings WHERE expires <= ?", (now,))
    conn.execute(
        "DELETE FROM certificates WHERE expires <= ? OR id NOT IN "
        "(SELECT certificate FROM bindings)",
        (now,),
    )


def bind(root: Path, licence: str, secret: str, now: float) -> str:
    with database(root, create=True) as conn:
        assert conn is not None  # noqa: S101 - create=True
        keyfile = root / KEY
        if not keyfile.exists():
            if conn.execute("SELECT 1 FROM certificates LIMIT 1").fetchone():
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
        tag = hmac.digest(key, b"mairui-binding/v2\0" + secret.encode(), hashlib.sha256)
        _prune(conn, now)
        row = conn.execute("SELECT id FROM certificates WHERE tag = ?", (tag,)).fetchone()
        ident = _identifier(row[0]) if row else uuid.uuid4().hex
        existing = conn.execute(
            "SELECT certificate FROM bindings WHERE licence = ?", (licence,)
        ).fetchone()
        if existing and existing[0] != ident:
            raise GateClosedError("shared_certificate_binding_changed")
        conn.execute(
            "INSERT INTO certificates VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE "
            "SET expires=excluded.expires",
            (ident, tag, now + TTL),
        )
        conn.execute(
            "INSERT INTO bindings VALUES (?, ?, ?) ON CONFLICT(licence) DO UPDATE "
            "SET expires=excluded.expires",
            (licence, ident, now + TTL),
        )
        return ident


def identity(root: Path, licence: str) -> str | None:
    with database(root) as conn:
        if conn is None:
            return None
        _prune(conn, time.time())
        row = conn.execute(
            "SELECT certificate FROM bindings WHERE licence = ?", (licence,)
        ).fetchone()
        return _identifier(row[0]) if row else None


def related(root: Path, licence: str) -> list[uuid.UUID]:
    with database(root) as conn:
        if conn is None:
            return [uuid.UUID(licence)]
        _prune(conn, time.time())
        rows = conn.execute(
            "SELECT licence FROM bindings WHERE certificate = "
            "(SELECT certificate FROM bindings WHERE licence = ?)",
            (licence,),
        )
        return list({uuid.UUID(licence), *(uuid.UUID(row[0]) for row in rows)})


def identifiers(root: Path) -> set[str]:
    with database(root) as conn:
        if conn is None:
            return set()
        _prune(conn, time.time())
        return {_identifier(row[0]) for row in conn.execute("SELECT id FROM certificates")}


def cleanup(root: Path, retained: Mapping[str, float], now: float) -> None:
    """Keep live rows; deleted rows only until their existing bounded cooldown.

    The caller supplies non-secret status metadata, never the DB credential HMAC.
    No state/STOP/halt/request file is removed by this operation.
    """
    with database(root) as conn:
        if conn is None:
            return
        for licence, expires in conn.execute("SELECT licence, expires FROM bindings").fetchall():
            end = min(expires, retained.get(licence, now), now + TTL)
            if end <= now:
                conn.execute("DELETE FROM bindings WHERE licence = ?", (licence,))
            else:
                conn.execute("UPDATE bindings SET expires = ? WHERE licence = ?", (end, licence))
        _prune(conn, now)
