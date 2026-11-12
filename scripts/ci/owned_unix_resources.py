#!/usr/bin/env python3
"""Create fresh Unix-only services exclusively on a GitHub ephemeral runner.

The receipt records real inspect identities; it never impersonates T-O33 resources.
No existing database, container or directory is adopted. Evidence is retained.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import time

PG_IMAGE = "timescale/timescaledb:2.31.0-pg16@sha256:322ae364eca3321cf2a48f1ef31213b87843413b3cf8feeebf54e999a26bb731"
REDIS_IMAGE = "redis:7.4.12-alpine3.21@sha256:8da19c7399dca900c6822a1cf30f9d2285585e2c4b457ff4095b0f4500054d3f"
PG_SOCKET = Path("/tmp/tb70-tb91-owned-socket")
REDIS_SOCKET = Path("/tmp/tb91-owned-redis")
ALIASES = {Path("/tmp/tb70-pg-socket"): PG_SOCKET, Path("/tmp/tb70-redis-socket"): REDIS_SOCKET}
ROOT = Path(__file__).resolve().parents[2]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def check_runner() -> dict[str, str]:
    required = ["GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA", "RUNNER_TEMP", "GITHUB_WORKSPACE"]
    if sys.platform != "linux" or os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise RuntimeError("Only an ephemeral GitHub-hosted Linux runner is allowed")
    env = {k: os.environ[k] for k in required}
    if not re.fullmatch(r"\d+", env["GITHUB_RUN_ID"]) or not re.fullmatch(r"\d+", env["GITHUB_RUN_ATTEMPT"]):
        raise RuntimeError("Invalid run identity")
    if not re.fullmatch(r"[0-9a-f]{40}", env["GITHUB_SHA"]) or Path(env["GITHUB_WORKSPACE"]).resolve() != ROOT:
        raise RuntimeError("Wrong checkout identity")
    return env


def save(path: Path, value: dict) -> None:
    tmp = path.with_suffix(".writing")
    tmp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def command(argv: list[str], receipt: dict, *, check: bool = True, timeout: int = 90) -> subprocess.CompletedProcess:
    started = now()
    result = subprocess.run(argv, text=True, capture_output=True, timeout=timeout)
    receipt["commands"].append({"argv": argv, "started_at": started, "completed_at": now(), "exit": result.returncode})
    if check and result.returncode:
        raise RuntimeError(f"{argv[0]} operation failed with exit {result.returncode}")
    return result


def inspect(container: str, receipt: dict) -> dict:
    if not re.fullmatch(r"[0-9a-f]{64}", container):
        raise RuntimeError("Only an exact recorded container ID is accepted")
    raw = json.loads(command(["docker", "inspect", container], receipt).stdout)[0]
    # Deliberately exclude Config.Env, raw logs and any daemon-wide inventory.
    return {"Id": raw["Id"], "Name": raw["Name"], "image_id": raw["Image"], "image": raw["Config"]["Image"],
            "labels": raw["Config"]["Labels"], "network": raw["HostConfig"]["NetworkMode"],
            "ports": raw["HostConfig"]["PortBindings"], "running": raw["State"]["Running"],
            "mounts": [{k: m.get(k) for k in ("Type", "Source", "Destination", "RW")} for m in raw["Mounts"]]}


def validate_identity(actual: dict, expected: dict, owner: dict, *, running: bool = True) -> None:
    if actual["Id"] != expected["Id"] or actual["Name"] != "/" + expected["name"] or actual["image"] != expected["image"]:
        raise RuntimeError("Container identity or pinned image differs")
    if actual["network"] != "none" or actual["ports"] or (running and not actual["running"]):
        raise RuntimeError("Service must be running, network-none, without published ports")
    if any(actual["labels"].get(k) != v for k, v in owner.items()):
        raise RuntimeError("Container belongs to a different run")
    binds = [m for m in actual["mounts"] if m["Type"] == "bind"]
    if len(binds) != 1 or binds[0]["Source"] != expected["socket"] or binds[0]["Destination"] != expected["destination"] or not binds[0]["RW"]:
        raise RuntimeError("Unexpected service bind mount")


def load_receipt(path: Path, env: dict) -> dict:
    path = path.resolve()
    if not path.is_relative_to(Path(env["RUNNER_TEMP"]).resolve()):
        raise RuntimeError("Receipt must be in this runner's private temporary directory")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt["run_id"] != env["GITHUB_RUN_ID"] or receipt["attempt"] != env["GITHUB_RUN_ATTEMPT"] or receipt["sha"] != env["GITHUB_SHA"]:
        raise RuntimeError("Receipt belongs to another workflow invocation")
    return receipt


def cleanup(path: Path, receipt: dict) -> None:
    failures = []
    for row in reversed(receipt["containers"]):
        if row.get("removed_at"):
            continue
        try:
            actual = inspect(row["Id"], receipt)
            validate_identity(actual, row, receipt["owner"], running=False)
            command(["docker", "stop", "--time", "20", row["Id"]], receipt)
            stopped = inspect(row["Id"], receipt)
            if stopped["running"]:
                raise RuntimeError("Owned container did not stop")
            row["stopped_inspect"] = stopped
            # No -v: all data is in this run's tmpfs, never a user volume.
            command(["docker", "rm", row["Id"]], receipt)
            row["removed_at"] = now()
        except Exception as error:
            failures.append({"Id": row["Id"], "error_type": type(error).__name__, "message": str(error)})
    receipt.update(cleanup_at=now(), cleanup_failures=failures, state="cleanup_failed" if failures else "cleaned")
    save(path, receipt)
    # This schema contains selected inspect fields and command metadata only;
    # never Config.Env, application logs, SQL rows or browser session context.
    print(json.dumps({"owned_resource_receipt": receipt}, sort_keys=True))
    if failures:
        raise RuntimeError("Owned resource cleanup incomplete; see receipt")


def initialize_roles(conn, receipt: dict, path: Path) -> None:
    # Original role definitions, exclusively on the newly owned PG, without
    # passwords, database grants or cluster settings from the rest of the file.
    grants = (ROOT / "deploy/db/roles/grants.sql").read_text(encoding="utf-8")
    roles_sql = grants[grants.index("DO $roles$"):grants.index("-- 口令：")].strip()
    expected = {"aia_api": True, "aia_ingest": True, "aia_maint": False}
    if conn.execute("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)", (list(expected),)).fetchall():
        raise RuntimeError("Refuse to adopt pre-existing application roles")
    conn.execute(roles_sql)
    rows = conn.execute(
        "SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
        "rolreplication, rolbypassrls, rolinherit FROM pg_roles WHERE rolname = ANY(%s)", (list(expected),),
    ).fetchall()
    if {r[0]: tuple(r[1:]) for r in rows} != {
        name: (True, False, False, False, False, False, inherit) for name, inherit in expected.items()
    }:
        raise RuntimeError("Fresh application role attributes differ from grants.sql")
    if conn.execute(
        "SELECT count(*) FROM pg_auth_members WHERE roleid IN "
        "(SELECT oid FROM pg_roles WHERE rolname = ANY(%s)) OR member IN "
        "(SELECT oid FROM pg_roles WHERE rolname = ANY(%s))", (list(expected), list(expected)),
    ).fetchone() != (0,):
        raise RuntimeError("Fresh application roles must have no memberships")
    receipt["initialized_roles"] = {
        "names": sorted(expected), "container_id": receipt["containers"][0]["Id"],
        "source": "deploy/db/roles/grants.sql", "sql_sha256": hashlib.sha256(roles_sql.encode()).hexdigest(),
        "attributes_verified": True, "memberships": 0, "initialized_at": now(),
    }
    save(path, receipt)


def apply(path: Path, env: dict) -> None:
    path = path.resolve()
    if not path.is_relative_to(Path(env["RUNNER_TEMP"]).resolve()) or path.exists():
        raise RuntimeError("A new receipt under RUNNER_TEMP is required")
    artifacts = path.parent / "artifacts"
    if os.path.lexists(artifacts):
        raise RuntimeError("Refuse to adopt an existing artifacts directory")
    if os.environ.get("P2N10_ARTIFACTS") != str(artifacts):
        raise RuntimeError("P2N10_ARTIFACTS must match this receipt's artifacts directory")
    # Fixed test paths must not already exist, including dangling links.
    for p in [PG_SOCKET, REDIS_SOCKET, *ALIASES]:
        if os.path.lexists(p):
            raise RuntimeError(f"Refuse to adopt existing path: {p}")
    token = secrets.token_hex(12)
    owner = {"aia.task": "O-CI1-RES", "aia.run": env["GITHUB_RUN_ID"], "aia.attempt": env["GITHUB_RUN_ATTEMPT"], "aia.owner": token}
    receipt = {"schema": "aia-ci-unix-resources-v1", "run_id": env["GITHUB_RUN_ID"], "attempt": env["GITHUB_RUN_ATTEMPT"], "sha": env["GITHUB_SHA"],
               "owner": owner, "created_at": now(), "state": "creating", "containers": [], "commands": [], "paths": [],
               "artifacts_root": str(artifacts), "artifact_paths": []}
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    save(path, receipt)
    try:
        artifacts.mkdir(mode=0o700)
        (artifacts / "p2n10").mkdir(mode=0o700)
        (artifacts / "p2n10/runtime").mkdir(mode=0o700)
        for p in [artifacts, artifacts / "p2n10", artifacts / "p2n10/runtime"]:
            receipt["artifact_paths"].append({"path": str(p), "inode": p.stat().st_ino})
        save(path, receipt)
        for p in [PG_SOCKET, REDIS_SOCKET]:
            p.mkdir(mode=0o777)
            p.chmod(0o777)  # Only a new socket dir on the dedicated ephemeral host.
            receipt["paths"].append({"path": str(p), "inode": p.stat().st_ino})
        for alias, target in ALIASES.items():
            alias.symlink_to(target, target_is_directory=True)
            receipt["paths"].append({"path": str(alias), "target": str(target), "inode": alias.lstat().st_ino})
        for kind, image, sock, destination, args in [
            ("pg", PG_IMAGE, PG_SOCKET, "/var/run/postgresql", ["postgres", "-c", "listen_addresses=", "-c", "unix_socket_permissions=0777"]),
            ("redis", REDIS_IMAGE, REDIS_SOCKET, "/run/aia-ci-redis", ["redis-server", "--port", "0", "--unixsocket", "/run/aia-ci-redis/redis.sock", "--unixsocketperm", "777", "--save", "", "--appendonly", "no"]),
        ]:
            name = "aia-ci-unix-" + kind + "-" + env["GITHUB_RUN_ID"] + "-" + token[:8]
            argv = ["docker", "create", "--name", name, "--network", "none", "--cpus", "2", "--memory", "2g", "--pids-limit", "256"]
            for k, v in owner.items():
                argv += ["--label", k + "=" + v]
            argv += ["--mount", f"type=bind,source={sock},destination={destination}"]
            if kind == "pg":
                argv += ["--tmpfs", "/var/lib/postgresql/data:rw,size=2147483648", "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "-e", "PGDATA=/var/lib/postgresql/data/pgdata"]
            else:
                argv += ["--tmpfs", "/data:rw,size=268435456"]
            argv += [image, *args]
            ident = command(argv, receipt).stdout.strip()
            row = {"Id": ident, "name": name, "kind": kind, "image": image, "socket": str(sock), "destination": destination}
            receipt["containers"].append(row)
            save(path, receipt)  # Persist exact newly created IDs before start.
            validate_identity(inspect(ident, receipt), row, owner, running=False)
            command(["docker", "start", ident], receipt)
            row["start_inspect"] = inspect(ident, receipt)
            validate_identity(row["start_inspect"], row, owner)
        deadline = time.monotonic() + 75
        while True:
            ready = all((p.is_socket() for p in [PG_SOCKET / ".s.PGSQL.5432", REDIS_SOCKET / "redis.sock"]))
            if ready:
                pg = receipt["containers"][0]
                if command(["docker", "exec", pg["Id"], "pg_isready", "-U", "postgres"], receipt, check=False).returncode == 0:
                    break
            if time.monotonic() >= deadline:
                raise RuntimeError("Fresh Unix services did not become ready within 75s")
            time.sleep(1)
        redis_service = receipt["containers"][1]
        pong = command(["docker", "exec", redis_service["Id"], "redis-cli", "-s", "/run/aia-ci-redis/redis.sock", "PING"], receipt)
        if pong.stdout.strip() != "PONG":
            raise RuntimeError("Dedicated Redis did not answer its Unix socket")
        sys.path.insert(0, str(ROOT / "src/backend"))
        import psycopg
        from psycopg import sql
        from alembic import command as alembic_command
        from alembic.config import Config
        from argparse import Namespace
        url = "postgresql+psycopg://postgres@/tb70_replay?host=/tmp/tb70-pg-socket"
        with psycopg.connect(dbname="postgres", user="postgres", host=str(PG_SOCKET), autocommit=True) as conn:
            if conn.execute("SHOW listen_addresses").fetchone() != ("",):
                raise RuntimeError("Dedicated PostgreSQL must have TCP disabled")
            initialize_roles(conn, receipt, path)
            conn.execute(sql.SQL("CREATE DATABASE {} ").format(sql.Identifier("tb70_replay")))
        receipt["created_databases"] = [{"name": "tb70_replay", "container_id": receipt["containers"][0]["Id"], "created_at": now(), "fresh_empty": True}]
        save(path, receipt)
        cfg = Config(str(ROOT / "src/backend/alembic.ini"))
        cfg.set_main_option("script_location", str(ROOT / "src/backend/migrations"))
        cfg.cmd_opts = Namespace(x=["url=" + url])
        alembic_command.upgrade(cfg, "head")
        with psycopg.connect(dbname="tb70_replay", user="postgres", host=str(PG_SOCKET)) as conn:
            receipt["version"] = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            receipt["current_database"] = conn.execute("SELECT current_database()").fetchone()[0]
        from alembic.script import ScriptDirectory
        from sqlalchemy import create_engine
        from app.replay.baseline import require_isolated
        if receipt["version"] != ScriptDirectory.from_config(cfg).get_current_head():
            raise RuntimeError("Fresh database did not reach the checkout's unique migration head")
        engine = create_engine(url)
        try:
            with engine.connect() as conn:
                require_isolated(conn, app_env="test")
        finally:
            engine.dispose()
        receipt["require_isolated_passed"] = True
        receipt.update(state="ready", ready_at=now())
        receipt["resources"] = [inspect(row["Id"], receipt) for row in receipt["containers"]]
        save(path, receipt)
        print(json.dumps({"receipt": str(path), "state": "ready", "run_id": receipt["run_id"], "version": receipt["version"]}))
    except BaseException:
        receipt["state"] = "failed"
        save(path, receipt)
        cleanup(path, receipt)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "apply", "check", "cleanup"])
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if args.action == "plan":
        print(json.dumps({"task": "O-CI1-RES", "images": [PG_IMAGE, REDIS_IMAGE], "network": "none", "published_ports": [], "sockets": [str(PG_SOCKET), str(REDIS_SOCKET)], "adopts_existing": False, "legacy_identity_compatible": False}, indent=2))
        return 0
    env = check_runner()
    if args.receipt is None:
        parser.error("--receipt is required for runner actions")
    if args.action == "apply":
        apply(args.receipt, env)
    else:
        receipt = load_receipt(args.receipt, env)
        if args.action == "check":
            if receipt["state"] != "ready":
                raise RuntimeError("Resources were not prepared successfully")
            for row in receipt["containers"]:
                validate_identity(inspect(row["Id"], receipt), row, receipt["owner"])
            for p in [PG_SOCKET / ".s.PGSQL.5432", REDIS_SOCKET / "redis.sock"]:
                if not stat.S_ISSOCK(p.stat().st_mode):
                    raise RuntimeError("Owned Unix socket missing")
        else:
            cleanup(args.receipt, receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
