"""Safe metadata for the exact newly created CI template; never read SQL text.

Only PID, state, transaction age and fixed source labels leave the process.
This module performs no session cancellation or termination.
"""
from __future__ import annotations

from owned_unix_resources import now, save
from psycopg import sql

STATES = frozenset({"active", "idle", "idle in transaction", "idle in transaction (aborted)", "disabled"})
APPLICATIONS = {"psql": "psql", "pg_dump": "pg_dump", "pg_restore": "pg_restore",
                "aia_ci_template_lifecycle": "ci_template_lifecycle"}
# Exact backend types from the pinned 2.31.0 worker registrations/default jobs.
# An arbitrary application string or numeric suffix never establishes a worker.
WORKER_TYPES = {"TimescaleDB Background Worker Scheduler": "timescale_scheduler",
                "TimescaleDB Background Worker Launcher": "timescale_launcher",
                "Telemetry Reporter [1]": "timescale_telemetry",
                "Job History Log Retention Policy [3]": "timescale_history_retention"}


def source_label(backend_type, application) -> str:
    if backend_type in WORKER_TYPES:
        return WORKER_TYPES[backend_type]
    if backend_type == "background worker" and application in WORKER_TYPES:
        return WORKER_TYPES[application]
    if application in APPLICATIONS:
        return APPLICATIONS[application]
    return {"client backend": "client_unspecified", "autovacuum worker": "autovacuum",
            "parallel worker": "parallel_worker", "background worker": "worker_unspecified"}.get(backend_type, "unknown")


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
        "SELECT pid, state, EXTRACT(EPOCH FROM clock_timestamp() - xact_start), "
        "backend_type, application_name FROM pg_stat_activity WHERE datid=%s ORDER BY pid",
        (row["oid"],),
    ).fetchall()
    return {"at": now(), "database_oid": row["oid"], "allow_connections": actual[2],
            "session_count": len(sessions), "sessions": [
                {"pid": s[0], "state": s[1] if s[1] in STATES else "unknown",
                 "transaction_age_seconds": max(0.0, round(float(s[2]), 3)) if s[2] is not None else None,
                 "source": source_label(s[3], s[4])} for s in sessions]}


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
