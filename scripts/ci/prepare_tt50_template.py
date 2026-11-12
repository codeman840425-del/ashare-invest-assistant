#!/usr/bin/env python3
"""Prepare a real 0030 template and a separate head selfcheck DB on this CI service.

Only freshly created databases are owned. Never stamp, downgrade, adopt existing
names or terminate sessions on the head source. Receipts contain no DSNs or rows.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

import psycopg
from owned_unix_resources import PG_IMAGE, ROOT, check_runner, now, save
from psycopg import sql

TEMPLATE = "o61_tmp_0030"
SELFCHECK = "o67_selfcheck"


def identity(env: dict) -> dict:
    container = os.environ["AIA_CI_PG_SERVICE_ID"]
    if not re.fullmatch(r"[0-9a-f]{64}", container):
        raise RuntimeError("Missing exact job service identity")
    result = subprocess.run(["docker", "inspect", container], capture_output=True, text=True, check=True)
    actual = json.loads(result.stdout)[0]
    if actual["Id"] != container or actual["Config"]["Image"] != PG_IMAGE or not actual["State"]["Running"]:
        raise RuntimeError("Wrong CI PostgreSQL service")
    if os.environ.get("PGHOST") != "127.0.0.1" or os.environ.get("PGUSER") != "aia":
        raise RuntimeError("Only the job's loopback PostgreSQL service is allowed")
    bindings = actual["NetworkSettings"]["Ports"].get("5432/tcp") or []
    if not any(b["HostPort"] == os.environ.get("PGPORT") for b in bindings):
        raise RuntimeError("PostgreSQL endpoint differs from exact job service")
    result = subprocess.run(
        ["docker", "exec", container, "psql", "-U", "aia", "-d", "postgres", "-Atc",
         "SELECT system_identifier FROM pg_control_system()"], capture_output=True, text=True, check=True,
    )
    return {"container_id": container, "system_identifier": result.stdout.strip(),
            "run_id": env["GITHUB_RUN_ID"], "attempt": env["GITHUB_RUN_ATTEMPT"], "sha": env["GITHUB_SHA"]}


def connect(name: str):
    return psycopg.connect(host=os.environ["PGHOST"], port=os.environ["PGPORT"],
                          user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"],
                          dbname=name, autocommit=True)


def database(conn, name: str):
    return conn.execute(
        "SELECT oid, pg_get_userbyid(datdba) FROM pg_database WHERE datname=%s", (name,)
    ).fetchone()


def state(name: str, expected: str) -> dict:
    with connect(name) as conn:
        actual = conn.execute("SELECT current_database(), current_user").fetchone()
        versions = conn.execute("SELECT version_num FROM public.alembic_version").fetchall()
        if actual != (name, os.environ["PGUSER"]) or versions != [(expected,)]:
            raise RuntimeError("Database name, role or migration version differs")
        tables = conn.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema IN ('app','market','ops','evaluation') AND table_type='BASE TABLE'"
        ).fetchone()[0]
        if tables <= 0:
            raise RuntimeError("Migration did not create application tables")
    return {"name": name, "version": expected, "tables": tables}


def create(conn, name: str, source: str, receipt: dict, path: Path) -> dict:
    if database(conn, name) is not None:
        raise RuntimeError("Refusing to adopt an existing database")
    conn.execute(sql.SQL("CREATE DATABASE {} WITH TEMPLATE {} OWNER {}").format(
        sql.Identifier(name), sql.Identifier(source), sql.Identifier(os.environ["PGUSER"])))
    oid, owner = database(conn, name)
    row = {"name": name, "oid": oid, "owner": owner, "template": source, "created_at": now()}
    receipt["databases"].append(row)
    save(path, receipt)
    return row


def drop(conn, row: dict, receipt: dict, path: Path) -> None:
    probe = f"oci1_tpl_probe_{os.environ['GITHUB_RUN_ID']}_{os.environ['GITHUB_RUN_ATTEMPT']}"
    if row["name"] not in {TEMPLATE, SELFCHECK, probe} or row["owner"] != os.environ["PGUSER"]:
        raise RuntimeError("Refusing cleanup outside exact newly owned names")
    if row.get("dropped_at"):
        return
    if database(conn, row["name"]) != (row["oid"], row["owner"]):
        raise RuntimeError("Owned database identity changed; refusing cleanup")
    # FORCE terminates only connections to the exact newly created database.
    conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(row["name"])))
    if database(conn, row["name"]) is not None:
        raise RuntimeError("Owned database still exists after cleanup")
    row["dropped_at"] = now()
    save(path, receipt)


def cleanup(conn, receipt: dict, path: Path) -> None:
    failures = []
    for row in reversed(receipt["databases"]):
        try:
            drop(conn, row, receipt, path)
        except (RuntimeError, OSError, ValueError, KeyError, psycopg.Error, subprocess.SubprocessError) as error:
            failures.append({"name": row["name"], "error_type": type(error).__name__})
    receipt.update(cleanup_failures=failures, state="cleanup_failed" if failures else "cleaned")
    save(path, receipt)
    if failures:
        raise RuntimeError("Template cleanup incomplete")


def stop_template_workers(conn, receipt: dict, path: Path, env: dict) -> None:
    """Use the pinned extension's database-local STOP protocol, never a PID kill.

    2.31.0 sends STOP for MyDatabaseId and waits for that scheduler to stop.
    It disables that database's scheduler entry; it does not stop the launcher
    or other databases. Unknown sessions reject the operation before STOP.
    """
    from template_connections import snapshot, template_row

    row = template_row(receipt)
    if (not row.get("fresh_empty") or receipt.get("migration") != {
        "target": "0030", "exit": 0, "method": "upgrade"
    } or receipt.get("template") != {"name": TEMPLATE, "version": "0030", "tables": 135}):
        raise RuntimeError("Worker stop requires this run's real empty-to-0030 template")
    if receipt["owner"] != identity(env):
        raise RuntimeError("Worker stop service or run identity changed")
    snapshot(conn, row)  # Recheck the exact OID/owner before connecting to it.
    lifecycle = {"mechanism": "timescaledb_database_local_stop", "acknowledged": False,
                 "sessions_terminated_by_script": 0}
    receipt["template_worker_lifecycle"] = lifecycle
    with connect(TEMPLATE) as fresh:
        actual = fresh.execute(
            "SELECT current_database(), current_user, "
            "(SELECT oid FROM pg_database WHERE datname=current_database()), "
            "(SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()), "
            "(SELECT system_identifier::text FROM pg_control_system()), "
            "(SELECT extversion FROM pg_extension WHERE extname='timescaledb'), "
            "pg_backend_pid(), current_setting('is_superuser')"
        ).fetchone()
        expected = (TEMPLATE, row["owner"], row["oid"], row["owner"],
                    receipt["owner"]["system_identifier"], "2.31.0")
        if actual[:6] != expected or actual[7] != "on":
            raise RuntimeError("Worker stop template, role, service or extension identity differs")
        lifecycle["identity_verified"] = True
        fresh.execute("SELECT set_config('application_name', 'aia_ci_template_lifecycle', false)")
        lifecycle["before"] = snapshot(conn, row)
        save(path, receipt)
        allowed = {"timescale_scheduler", "timescale_telemetry", "timescale_history_retention"}
        if any(s["pid"] != actual[6] and s["source"] not in allowed
               for s in lifecycle["before"]["sessions"]):
            raise RuntimeError("Unidentified or non-worker template session; STOP refused")
        # Keep our one verified connection alive, reject all new connections,
        # then ask the extension to stop only its own workers in this database.
        conn.execute(sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS false").format(sql.Identifier(TEMPLATE)))
        if fresh.execute("SELECT _timescaledb_functions.stop_background_workers()").fetchone() != (True,):
            raise RuntimeError("Template worker STOP was not acknowledged")
        lifecycle["acknowledged"] = True
        save(path, receipt)
        # PQfinish sends Terminate but does not wait for the server to close.
        # Retain a duplicate of this exact socket to acknowledge EOF before
        # the zero-session guard. This is protocol shutdown, not a SQL retry.
        disconnect = socket.fromfd(fresh.pgconn.socket, socket.AF_INET, socket.SOCK_STREAM)
    try:
        disconnect.settimeout(5)
        remaining = 65536
        while remaining:
            data = disconnect.recv(min(4096, remaining))
            if not data:
                break
            remaining -= len(data)  # Discard pending notices without exposing them.
        else:
            raise RuntimeError("Template connection did not close within protocol bound")
    finally:
        disconnect.close()
    lifecycle["connection_closed"] = True
    lifecycle["after"] = snapshot(conn, row)
    save(path, receipt)
    # seal() still requires zero sessions and verifies a real clone afterwards.


def prepare(conn, receipt: dict, path: Path, env: dict) -> None:
    source = os.environ.get("AIA_TT50_SOURCE_DB", "aia")
    if source != "aia" or os.environ.get("AIA_SELFCHECK_DB", SELFCHECK) != SELFCHECK:
        raise RuntimeError("Unexpected source or selfcheck name")
    sys.path.insert(0, str(ROOT / "src/backend"))
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import URL

    head = ScriptDirectory.from_config(Config(str(ROOT / "src/backend/alembic.ini"))).get_current_head()
    receipt["source_before"] = state(source, head)
    receipt["source_identity"] = list(database(conn, source))
    # Reserve all names before writing anything. Never reuse a stale head template.
    probe = f"oci1_tpl_probe_{env['GITHUB_RUN_ID']}_{env['GITHUB_RUN_ATTEMPT']}"
    if any(database(conn, n) is not None for n in (TEMPLATE, SELFCHECK, probe)):
        raise RuntimeError("Template, selfcheck or probe already exists")
    row = create(conn, TEMPLATE, "template0", receipt, path)
    with connect(TEMPLATE) as fresh:
        if fresh.execute("SELECT to_regclass('public.alembic_version')").fetchone() != (None,):
            raise RuntimeError("New template is not empty")
    row["fresh_empty"] = True
    save(path, receipt)
    url = URL.create("postgresql+psycopg", username=os.environ["PGUSER"], password=os.environ["PGPASSWORD"],
                     host=os.environ["PGHOST"], port=int(os.environ["PGPORT"]), database=TEMPLATE)
    child_env = dict(os.environ, DATABASE_URL=url.render_as_string(hide_password=False))
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "0030"],
                            cwd=ROOT / "src/backend", env=child_env, capture_output=True, text=True, check=False)
    receipt["migration"] = {"target": "0030", "exit": result.returncode, "method": "upgrade"}
    save(path, receipt)
    if result.returncode:
        raise RuntimeError("Fresh template migration failed; output withheld")
    receipt["template"] = state(TEMPLATE, "0030")
    stop_template_workers(conn, receipt, path, env)
    from template_connections import seal

    seal(conn, receipt, path)
    # Prove a clone of the sealed template is connectable at the original 0030.
    cloned = create(conn, probe, TEMPLATE, receipt, path)
    receipt["clone_probe"] = state(probe, "0030")
    if receipt["clone_probe"]["tables"] != receipt["template"]["tables"]:
        raise RuntimeError("Template clone structure differs")
    drop(conn, cloned, receipt, path)
    # A28-A31 selfchecks use head, independently cloned from the unchanged source.
    create(conn, SELFCHECK, source, receipt, path)
    receipt["selfcheck"] = state(SELFCHECK, head)
    receipt["source_after"] = state(source, head)
    if receipt["source_before"] != receipt["source_after"] or list(database(conn, source)) != receipt["source_identity"]:
        raise RuntimeError("Head source changed during template preparation")
    receipt["state"] = "ready"
    save(path, receipt)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", nargs="?", choices=["prepare", "cleanup"], default="prepare")
    args = parser.parse_args()
    try:
        env = check_runner()
        owner = identity(env)
        path = Path(os.environ["AIA_CI_TEMPLATE_RECEIPT"]).resolve()
        if not path.is_relative_to(Path(env["RUNNER_TEMP"]).resolve()) or path.parent.is_symlink():
            raise RuntimeError("Receipt must be within this runner's temporary directory")
        path.parent.mkdir(parents=True, exist_ok=True)
        with connect("postgres") as conn:
            if str(conn.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0]) != owner["system_identifier"]:
                raise RuntimeError("Connected database is not the exact job service")
            if args.action == "cleanup":
                receipt = json.loads(path.read_text(encoding="utf-8"))
                if receipt["owner"] != owner:
                    raise RuntimeError("Receipt belongs to another service or run")
                cleanup(conn, receipt, path)
            else:
                if path.exists():
                    raise RuntimeError("Refusing to overwrite template receipt")
                receipt = {"schema": "aia-ci-templates-v1", "owner": owner, "databases": [], "state": "preparing"}
                save(path, receipt)
                try:
                    prepare(conn, receipt, path, env)
                except Exception:
                    cleanup(conn, receipt, path)
                    raise
        print(json.dumps({"ci_templates": receipt}, sort_keys=True))
        return 0
    except (RuntimeError, OSError, ValueError, KeyError, psycopg.Error, subprocess.SubprocessError) as error:
        print(f"::error title=tt50-template::{type(error).__name__}; details withheld", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
