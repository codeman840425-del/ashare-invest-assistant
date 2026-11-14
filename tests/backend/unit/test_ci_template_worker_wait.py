"""Owned CI template lifecycle with fake PG metadata and a virtual clock."""
from __future__ import annotations

import copy
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts/ci"))
    prep = importlib.import_module("prepare_tt50_template")
    owner = {"container_id": "a" * 64, "system_identifier": "synthetic-system",
             "run_id": "11", "attempt": "1", "sha": "b" * 40}
    row = {"name": prep.TEMPLATE, "oid": 77, "owner": "aia",
           "template": "template0", "fresh_empty": True}
    receipt = {"owner": owner, "databases": [row],
               "migration": {"target": "0030", "exit": 0, "method": "upgrade"},
               "template": {"name": prep.TEMPLATE, "version": "0030", "tables": 135}}
    state = SimpleNamespace(
        prep=prep, receipt=receipt, row=row, clock=0.0, sleeps=[], frames=[],
        sql=[], saves=[], allow=True, oid=77, connects=[], stops=0, closed=False,
        acknowledge=True, identity_ok=True, pipe_closed=False, observe=0,
    )
    state.self_session = (301, "idle", None, "client backend", "aia_ci_template_lifecycle")
    state.scheduler = (302, "idle", None, "background worker", "TimescaleDB Background Worker Scheduler")
    state.autovacuum = (303, "active", 0.005, "autovacuum worker", "")
    state.frames = [[state.self_session], [state.self_session], []]

    class Result:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return self.value

        def fetchall(self):
            return self.value

    class Admin:
        def execute(self, statement, params=None):
            rendered = statement if isinstance(statement, str) else statement.as_string()
            state.sql.append((rendered, params))
            if "FROM pg_database" in rendered:
                assert params == (prep.TEMPLATE,)
                return Result((state.oid, "aia", state.allow))
            if "FROM pg_stat_activity" in rendered:
                assert params == (77,)
                state.observe += 1
                frame = state.frames.pop(0) if len(state.frames) > 1 else state.frames[0]
                return Result(frame)
            assert rendered == 'ALTER DATABASE "o61_tmp_0030" ALLOW_CONNECTIONS false'
            state.allow = False
            return Result(None)

    class Fresh:
        pgconn = SimpleNamespace(socket=42)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            state.closed = True

        def execute(self, statement):
            state.sql.append((statement, None))
            if statement.startswith("SELECT current_database()"):
                return Result((prep.TEMPLATE, "aia", 77, "aia", "synthetic-system",
                               "2.31.0" if state.identity_ok else "wrong", 301, "on"))
            if "set_config" in statement:
                return Result(None)
            assert statement == "SELECT _timescaledb_functions.stop_background_workers()"
            assert not state.allow
            state.stops += 1
            return Result((state.acknowledge,))

    class Disconnect:
        def settimeout(self, seconds):
            assert seconds == 5

        def recv(self, size):
            return b""

        def close(self):
            state.pipe_closed = True

    def connect(name):
        state.connects.append(name)
        assert name == prep.TEMPLATE
        return Fresh()

    def sleep(seconds):
        assert 0 < seconds <= 1
        state.sleeps.append(seconds)
        state.clock += seconds

    monkeypatch.setattr(prep, "identity", lambda env: owner)
    monkeypatch.setattr(prep, "connect", connect)
    monkeypatch.setattr(prep, "save", lambda path, value: state.saves.append(copy.deepcopy(value)))
    monkeypatch.setattr(prep, "time", SimpleNamespace(monotonic=lambda: state.clock, sleep=sleep), raising=False)
    monkeypatch.setattr(prep.socket, "fromfd", lambda *args: Disconnect(), raising=False)
    state.run = lambda: prep.stop_template_workers(Admin(), receipt, tmp_path / "receipt.json", {})
    return state


def test_template_autovacuum_finishes_before_stop_and_scheduler_drains_after_close(world):
    own, vacuum, worker = world.self_session, world.autovacuum, world.scheduler
    world.frames = [[own, vacuum, worker], [own, vacuum, worker],
                    [own, vacuum, worker], [own, worker], [worker], []]
    world.run()
    lifecycle = world.receipt["template_worker_lifecycle"]
    assert world.sleeps == [1, 1] and world.stops == 1
    assert lifecycle["acknowledged"] and lifecycle["connection_closed"]
    assert lifecycle["after"]["session_count"] == 0
    assert lifecycle["wait_limit_seconds"] == 120
    assert lifecycle["sessions_terminated_by_script"] == 0
    assert world.connects == ["o61_tmp_0030"] and world.closed and world.pipe_closed
    assert all("terminate_backend" not in sql and "cancel_backend" not in sql for sql, _ in world.sql)


@pytest.mark.parametrize("phase", ["before_stop", "after_close"])
@pytest.mark.parametrize("worker", ["autovacuum", "scheduler"])
def test_template_known_background_sessions_have_a_shared_120_second_bound(world, phase, worker):
    own = world.self_session
    pending = getattr(world, worker)
    if phase == "before_stop":
        # Scheduler uses the existing acknowledged STOP; only vacuum drains first.
        if worker == "scheduler":
            world.frames = [[own], [own], [own], [pending]]
        else:
            world.frames = [[own, pending]]
    else:
        world.frames = [[own], [own], [own], [pending]]
    with pytest.raises(RuntimeError, match="within 120 seconds"):
        world.run()
    assert world.clock == 120 and len(world.sleeps) == 120
    assert not world.allow
    assert world.stops == (0 if phase == "before_stop" and worker == "autovacuum" else 1)


@pytest.mark.parametrize("phase", ["initial", "waiting", "after_close"])
@pytest.mark.parametrize("backend,application", [
    ("client backend", "psql"),
    ("client backend", "TimescaleDB Background Worker Scheduler"),
    ("background worker", "unrecognized worker"),
])
def test_unknown_clients_and_spoofed_worker_names_are_never_waited_out(world, phase, backend, application):
    own, vacuum = world.self_session, world.autovacuum
    unknown = (999, "idle", None, backend, application)
    if phase == "initial":
        world.frames = [[own, unknown]]
    elif phase == "waiting":
        world.frames = [[own, vacuum], [own, vacuum], [own, unknown]]
    else:
        world.frames = [[own], [own], [own], [unknown]]
    with pytest.raises(RuntimeError, match="Unidentified|non-worker"):
        world.run()
    assert world.sleeps == []
    assert world.stops == (1 if phase == "after_close" else 0)


def test_template_wait_budget_is_not_reset_after_stop(world):
    own, vacuum, worker = world.self_session, world.autovacuum, world.scheduler
    world.frames = [[own, vacuum], [own, vacuum]] + [[own, vacuum]] * 119 + [[own], [worker]]
    with pytest.raises(RuntimeError, match="within 120 seconds"):
        world.run()
    assert world.clock == 120 and len(world.sleeps) == 120 and world.stops == 1


@pytest.mark.parametrize("change", ["source_name", "adopted", "not_fresh", "wrong_migration", "wrong_version", "wrong_oid", "wrong_service", "wrong_extension"])
def test_wait_never_bypasses_template_or_service_identity(world, monkeypatch, change):
    if change == "source_name":
        world.row["name"] = "aia"
    elif change == "adopted":
        world.row["template"] = "aia"
    elif change == "not_fresh":
        world.row["fresh_empty"] = False
    elif change == "wrong_migration":
        world.receipt["migration"]["target"] = "0035"
    elif change == "wrong_version":
        world.receipt["template"]["version"] = "0035"
    elif change == "wrong_oid":
        world.oid = 78
    elif change == "wrong_service":
        monkeypatch.setattr(world.prep, "identity", lambda env: {})
    else:
        world.identity_ok = False
    with pytest.raises(RuntimeError):
        world.run()
    assert world.sleeps == [] and world.stops == 0
    assert not any(sql.startswith("ALTER DATABASE") for sql, _ in world.sql)


def test_no_background_sessions_keeps_existing_stop_without_sleep(world):
    world.run()
    assert world.sleeps == [] and world.stops == 1 and world.pipe_closed
    assert world.receipt["template_worker_lifecycle"]["after"]["session_count"] == 0


def test_stop_acknowledgement_is_still_required(world):
    world.acknowledge = False
    with pytest.raises(RuntimeError, match="not acknowledged"):
        world.run()
    assert world.stops == 1 and world.sleeps == []


def test_template_oid_is_rechecked_on_each_wait_observation(world, monkeypatch):
    own, vacuum = world.self_session, world.autovacuum
    world.frames = [[own, vacuum]]
    def change_oid(seconds):
        world.clock += seconds
        world.oid = 88
    world.prep.time.sleep = change_oid
    with pytest.raises(RuntimeError, match="OID or owner changed"):
        world.run()
    assert world.clock == 1 and world.stops == 0
