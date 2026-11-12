"""Safe metadata for the exact newly created CI template; never read SQL text.

Unknown application names/types are hashed, not emitted. This module performs no
session cancellation, termination or changes outside the recorded template.
"""
from __future__ import annotations

import hashlib

from owned_unix_resources import now, save
from psycopg import sql

BACKEND_TYPES = frozenset({"client backend", "background worker", "parallel worker", "autovacuum worker"})
STATES = frozenset({"active", "idle", "idle in transaction", "idle in transaction (aborted)", "disabled"})
APPLICATIONS = frozenset({"", "psql", "pg_dump", "pg_restore", "TimescaleDB Background Worker Scheduler", "TimescaleDB Background Worker Launcher"})


def label(value, allowed: frozenset) -> dict:
    if value is None:
        return {"known": None}
    text = str(value)
    if text in allowed:
        return {"known": text}
    return {"known": "other", "sha256": hashlib.sha256(text.encode()).hexdigest()[:16]}


def template_row(receipt: dict) -> dict:
    rows = [r for r in receipt["databases"] if r["name"] == "o61_tmp_0030" and not r.get("dropped_at")]
    if len(rows) != 1 or rows[0]["template"] != "template0" or rows[0]["owner"] != "aia":
        raise RuntimeError("Not the exact fresh owned template")
    return rows[0]


def snapshot(conn, row: dict) -> dict:
    actual = conn.execute(
        "SELECT oid, pg_get_userbyid(datdba), datallowconn FROM pg_database WHERE datname=%s",
        (row["name"],),
    ).fetchone()
    if actual is None or actual[:2] != (row["oid"], row["owner"]):
        raise RuntimeError("Template OID or owner changed")
    # No query, query_id, client address/hostname/port, credentials or SQL rows.
    sessions = conn.execute(
        "SELECT pid, leader_pid, backend_type, application_name, state, "
        "usename = %s, backend_start, xact_start IS NOT NULL "
        "FROM pg_stat_activity WHERE datid=%s ORDER BY pid",
        (row["owner"], row["oid"]),
    ).fetchall()
    return {"at": now(), "database_oid": row["oid"], "allow_connections": actual[2],
            "session_count": len(sessions), "sessions": [
                {"pid": s[0], "leader_pid": s[1], "backend_type": label(s[2], BACKEND_TYPES),
                 "application": label(s[3], APPLICATIONS), "state": label(s[4], STATES),
                 "is_owner_role": bool(s[5]), "backend_start": s[6].isoformat() if s[6] else None,
                 "in_transaction": bool(s[7])} for s in sessions]}


def seal(conn, receipt: dict, path) -> None:
    row = template_row(receipt)
    before = snapshot(conn, row)
    # Standard PostgreSQL template lifecycle: prohibit new direct sessions and
    # validate through a separate clone. Existing sessions are never blind-killed.
    conn.execute(sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS false").format(sql.Identifier(row["name"])))
    after = snapshot(conn, row)
    receipt["template_connection_lifecycle"] = {"before": before, "after": after,
                                                "sessions_terminated": 0}
    save(path, receipt)
    if after["allow_connections"]:
        raise RuntimeError("Template still allows direct connections")
    if after["session_count"]:
        raise RuntimeError("Existing template sessions require diagnosis; no termination attempted")
