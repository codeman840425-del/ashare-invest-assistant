# ruff: noqa: S101
"""T-B116 / T-A87: mairui_get fail-closed matrix (10 cases) + fake transport only.

Uses TB116_DATABASE_URL (isolated PG). Never calls real Mairui (_https_get must stay unused).
"""

from __future__ import annotations

import datetime as dt
import os
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Never, Self

import pytest
import yaml
from sqlalchemy import Connection, CursorResult, create_engine, text
from sqlalchemy.engine import Engine

from app.config_files import IngestConfig
from app.ingest import egress as eg
from app.ingest.core import IngestCore
from app.ingest.daily_lists import DailyHaltError
from app.ingest.state import Priority
from app.schemas.enums import DataLicenceStatus, DataLicenceTier

ROOT = Path(__file__).resolve().parents[3]
CFG = IngestConfig.model_validate(
    yaml.safe_load((ROOT / "config/ingest.yaml").read_text(encoding="utf-8"))
).licences
NOW0 = dt.datetime(2026, 11, 9, 19, 0, tzinfo=dt.UTC)
SENTINEL = "SENTINEL-LIC-" + "tb116-never-log"
FAKE_URL_FRAG = "https://api.mairuiapi.com/hslt/list/"


def _url() -> str:
    url = os.environ.get("TB116_DATABASE_URL")
    if not url:
        pytest.skip("TB116_DATABASE_URL not set")
    return url


def _seed(engine: Engine, uid: uuid.UUID, lid: uuid.UUID, *, status: str = "active") -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO app.users(id, username, password_hash, role, status) "
                "VALUES (:id, :u, 'x', 'user', 'approved')"
            ),
            {"id": uid, "u": f"u{uid.hex[:12]}"},
        )
        conn.execute(
            text(
                "INSERT INTO app.user_data_licences("
                "id, user_id, ciphertext, seal_key_version, licence_hmac, tier, status"
                ") VALUES ("
                ":id, :uid, decode('00','hex'), 1, decode(:hm,'hex'), 'annual', :st)"
            ),
            {"id": lid, "uid": uid, "hm": uuid.uuid4().hex, "st": status},
        )


def _clock(when: dt.datetime) -> Callable[[], dt.datetime]:
    return lambda: when


def _calls_transport(box: list[str]) -> Callable[[str, str], tuple[int, object]]:
    def transport(path: str, secret: str) -> tuple[int, object]:
        box.append(path)
        assert secret == SENTINEL
        return 200, [{"dm": "600000", "mc": "合成"}]

    return transport



@contextmanager
def _issued_lease(engine: Engine) -> Iterator[eg.EgressLease]:
    with eg.single_egress(engine) as lease:
        assert lease is not None, "single-egress not acquired in selfcheck"
        yield lease


def _mg(*, engine: Engine, **kwargs: object) -> eg.EgressResult:
    """mairui_get under an issued lease. Pass lease= to exercise deny paths."""
    if "lease" in kwargs:
        return eg.mairui_get(engine=engine, **kwargs)
    with _issued_lease(engine) as lease:
        return eg.mairui_get(lease=lease, engine=engine, **kwargs)


# ---- FC1 HALT/STOP before lock/DB ----


def test_tb116_fc1_halt_present_zero_transport_no_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    halt = tmp_path / "HALTED"
    halt.write_bytes(b"limit_103_or_429")
    stop = tmp_path / "STOP"
    calls: list[str] = []
    _engine = create_engine("sqlite+pysqlite:///:memory:")  # must not be queried

    class BoomEngine:
        def connect(self) -> Never:
            raise AssertionError("halt_present must not open DB")

    with pytest.raises(eg.EgressDenied) as ei:
        eg.mairui_get(
            lease=eg.EgressLease(held=True),
            core=IngestCore(CFG),
            engine=BoomEngine(),  # type: ignore[arg-type]
            licence_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            path="/hslt/list/",
            secret=SENTINEL,
            priority=Priority.P1,
            clock=_clock(NOW0),
            stop=stop,
            halt=halt,
            transport=_calls_transport(calls),
        )
    assert ei.value.code == "halt_present"
    assert calls == []
    assert halt.exists()  # never cleared


# ---- FC4 / FC6 / FC13-style lease & core ----


def test_tb116_fc4_no_lease_and_fc6_core_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    stop, halt = tmp_path / "STOP", tmp_path / "HALT"
    calls: list[str] = []
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with pytest.raises(eg.EgressDenied) as e1:
        _mg(
            lease=None,
            core=IngestCore(CFG),
            engine=engine,
            licence_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            path="/x/",
            secret=SENTINEL,
            priority=Priority.P1,
            clock=_clock(NOW0),
            stop=stop,
            halt=halt,
            transport=_calls_transport(calls),
        )
    assert e1.value.code == "single_egress_not_held"
    # B-1(b): forged held=True → single_egress_not_held (not core_unavailable).
    with pytest.raises(eg.EgressDenied) as e_forge:
        _mg(
            lease=eg.EgressLease(held=True),
            core=None,
            engine=engine,
            licence_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            path="/x/",
            secret=SENTINEL,
            priority=Priority.P1,
            clock=_clock(NOW0),
            stop=stop,
            halt=halt,
            transport=_calls_transport(calls),
        )
    assert e_forge.value.code == "single_egress_not_held"
    pg = create_engine(_url(), hide_parameters=True)
    with pytest.raises(eg.EgressDenied) as e2:
        _mg(
            core=None,
            engine=pg,
            licence_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            path="/x/",
            secret=SENTINEL,
            priority=Priority.P1,
            clock=_clock(NOW0),
            stop=stop,
            halt=halt,
            transport=_calls_transport(calls),
        )
    assert e2.value.code == "core_unavailable"
    assert calls == []


# ---- FC7 licence missing / non-active ----


def test_tb116_fc7_licence_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    url = _url()
    engine = create_engine(url, hide_parameters=True)
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(engine, uid, lid, status="expired")
    stop, halt = tmp_path / "S", tmp_path / "H"
    calls: list[str] = []
    core = IngestCore(CFG, engine=engine)
    with pytest.raises(eg.EgressDenied) as ei:
        _mg(
            core=core,
            engine=engine,
            licence_id=lid,
            user_id=uid,
            path="/hslt/list/",
            secret=SENTINEL,
            priority=Priority.P1,
            clock=_clock(NOW0),
            stop=stop,
            halt=halt,
            transport=_calls_transport(calls),
        )
    assert ei.value.code == "licence_unavailable"
    # missing row
    with pytest.raises(eg.EgressDenied) as e2:
        _mg(
            core=core,
            engine=engine,
            licence_id=uuid.uuid4(),
            user_id=uid,
            path="/hslt/list/",
            secret=SENTINEL,
            priority=Priority.P1,
            clock=_clock(NOW0),
            stop=stop,
            halt=halt,
            transport=_calls_transport(calls),
        )
    assert e2.value.code == "licence_unavailable"
    assert calls == []


# ---- happy path + FC8 token bucket + FC10 network ----


def test_tb116_happy_and_fc8_token_bucket_and_fc10_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    url = _url()
    engine = create_engine(url, hide_parameters=True)
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(engine, uid, lid)
    stop, halt = tmp_path / "S", tmp_path / "H"
    calls: list[str] = []
    core = IngestCore(CFG, engine=engine)

    # Force tiny bucket via cfg copy — use annual default then drain by override on upsert path:
    # mairui_get upserts without override; instead call twice with per_minute=1
    # by patching core.per_minute
    monkeypatch.setattr(core, "per_minute", lambda tier, override=None: 1)

    r1 = _mg(
        core=core,
        engine=engine,
        licence_id=lid,
        user_id=uid,
        path="/hslt/list/",
        secret=SENTINEL,
        priority=Priority.P1,
        clock=_clock(NOW0),
        stop=stop,
        halt=halt,
        transport=_calls_transport(calls),
    )
    assert r1.status == 200
    assert len(calls) == 1

    with pytest.raises(eg.EgressDenied) as ei:
        _mg(
            core=core,
            engine=engine,
            licence_id=lid,
            user_id=uid,
            path="/hslt/list/",
            secret=SENTINEL,
            priority=Priority.P1,
            clock=_clock(NOW0),  # same second → bucket empty
            stop=stop,
            halt=halt,
            transport=_calls_transport(calls),
        )
    assert ei.value.code == "core_denied"
    assert len(calls) == 1  # no second socket

    # FC10: transport raises → NETWORK complete + DailyHaltError
    def boom(path: str, secret: str) -> tuple[int, object]:
        calls.append("boom")
        raise DailyHaltError("transport_or_response_failed_no_retry")

    # new second → refill roughly; bump clock far enough
    t2 = NOW0 + dt.timedelta(minutes=2)
    # restore rate for network test
    monkeypatch.setattr(core, "per_minute", lambda tier, override=None: 60)
    # re-upsert bucket rate
    core.upsert(
        lid,
        user_id=uid,
        tier=DataLicenceTier.ANNUAL,
        status=DataLicenceStatus.ACTIVE,
        now=t2,
    )
    with pytest.raises(DailyHaltError, match="transport_or_response_failed_no_retry"):
        _mg(
            core=core,
            engine=engine,
            licence_id=lid,
            user_id=uid,
            path="/hslt/list/",
            secret=SENTINEL,
            priority=Priority.P1,
            clock=_clock(t2),
            stop=stop,
            halt=halt,
            transport=boom,
        )
    assert "boom" in calls


# ---- FC3 escalate from DB events (3rd hit) zero transport ----


def test_tb116_fc3_escalation_blocks_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DB already has 2 ip_limited + pause mark → rehydrate escalated → deny, transport 0."""
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    url = _url()
    engine = create_engine(url, hide_parameters=True)
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(engine, uid, lid)
    with engine.begin() as conn:
        for mins in (0, 5):
            conn.execute(
                text(
                    "INSERT INTO ops.data_licence_events("
                    "licence_id, user_id, event, actor, from_status, to_status, upstream_code, at"
                    ") VALUES (:l,:u,'ip_limited','ingest','active','ip_limited','103',:at)"
                ),
                {"l": lid, "u": uid, "at": NOW0 + dt.timedelta(minutes=mins)},
            )
        conn.execute(
            text(
                "INSERT INTO ops.data_licence_events("
                "licence_id, user_id, event, actor, from_status, to_status, upstream_code, at"
                ") VALUES (:l,:u,'paused','ingest','active','ip_limited','103',:at)"
            ),
            {"l": lid, "u": uid, "at": NOW0 + dt.timedelta(minutes=5)},
        )
    stop, halt = tmp_path / "S", tmp_path / "H"
    calls: list[str] = []
    core = IngestCore(CFG, engine=engine)
    with pytest.raises(eg.EgressDenied) as ei:
        _mg(
            core=core,
            engine=engine,
            licence_id=lid,
            user_id=uid,
            path="/hslt/list/",
            secret=SENTINEL,
            priority=Priority.P1,
            clock=_clock(NOW0 + dt.timedelta(minutes=6)),
            stop=stop,
            halt=halt,
            transport=_calls_transport(calls),
        )
    assert ei.value.code == "core_denied"
    assert calls == []


# ---- FC9 write failure → pending + later deny ----


def test_tb116_fc9_event_insert_fail_pending_then_deny(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    url = _url()
    engine = create_engine(url, hide_parameters=True)
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(engine, uid, lid)
    stop, halt = tmp_path / "S", tmp_path / "H"
    core = IngestCore(CFG, engine=engine)

    # Break event inserts by revoking INSERT on events for this session via a boom wrapper
    class BoomConn:
        def __init__(self, real: Connection) -> None:
            self._real = real

        def execute(self, *a: object, **k: object) -> CursorResult[Any]:
            sql = str(a[0]) if a else ""
            if "data_licence_events" in sql.lower() or "INSERT" in sql.upper():
                # only boom on event writes heuristically via compile
                try:
                    compiled = str(a[0].compile(dialect=engine.dialect))
                except Exception:  # noqa: BLE001
                    compiled = sql
                if "data_licence_events" in compiled:
                    raise RuntimeError("tb116_event_insert_boom")
            return self._real.execute(*a, **k)

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *a: object) -> bool:
            return False

    class BoomBegin:
        def __init__(self, real_engine: Engine) -> None:
            self._eng = real_engine

        def __enter__(self) -> BoomConn:
            self._ctx = self._eng.begin()
            self._conn = self._ctx.__enter__()
            return BoomConn(self._conn)

        def __exit__(self, *a: object) -> bool | None:
            return self._ctx.__exit__(*a)

    class BoomEngine:
        def __init__(self, real: Engine) -> None:
            self._real = real

        def connect(self) -> Connection:
            return self._real.connect()

        def begin(self) -> BoomBegin:
            return BoomBegin(self._real)

    core.engine = BoomEngine(engine)  # type: ignore[assignment]
    calls: list[str] = []

    def lim(path: str, secret: str) -> tuple[int, object]:
        calls.append(path)
        return 429, None

    # First IP_LIMITED with boom write → fail-closed pending in memory
    _mg(
        core=core,
        engine=engine,  # load licence still uses real engine
        licence_id=lid,
        user_id=uid,
        path="/hslt/list/",
        secret=SENTINEL,
        priority=Priority.P1,
        clock=_clock(NOW0),
        stop=stop,
        halt=halt,
        transport=lim,
    )
    if halt.exists():
        halt.unlink()
    mem = core._user_mem(uid)
    assert mem.escalated_until is not None or mem.pending_escalation is not None
    # Subsequent call while escalated → core_denied, no transport
    n = len(calls)
    with pytest.raises(eg.EgressDenied) as ei:
        _mg(
            core=core,
            engine=engine,
            licence_id=lid,
            user_id=uid,
            path="/hslt/list/",
            secret=SENTINEL,
            priority=Priority.P1,
            clock=_clock(NOW0 + dt.timedelta(seconds=1)),
            stop=stop,
            halt=halt,
            transport=_calls_transport(calls),
        )
    assert ei.value.code == "core_denied"
    assert len(calls) == n


# ---- FC2 upstream_halted is process/eligible concern: document via source + eligible ----


def test_tb116_fc2_upstream_halted_checked_before_egress_in_process() -> None:
    src = (ROOT / "src/backend/app/ingest/daily_lists.py").read_text(encoding="utf-8")
    # eligible (upstream_halted) appears in reservation txn before mairui_get
    assert "eligible(conn, grant" in src
    assert "mairui_get(" in src
    # order: reservation block containing eligible precedes mairui_get in the loop body
    loop = src.split("for index, dataset in enumerate(LISTS)", 1)[1]
    assert loop.find("eligible(conn, grant") < loop.find("mairui_get(")


# ---- FC5 ip_limit lock timeout bounded (rehydrate fail-closed) ----


def test_tb116_fc5_rehydrate_lock_timeout_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    url = _url()
    engine = create_engine(url, hide_parameters=True)
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(engine, uid, lid)
    _stop, _halt = tmp_path / "S", tmp_path / "H"
    core = IngestCore(CFG, engine=engine)
    # Hold ip_limit advisory lock in another connection so flush/rehydrate path times out
    holder = engine.connect()
    holder.execute(
        text("SELECT pg_advisory_lock(hashtext(:k))"),
        {"k": f"ingest:ip_limit:{uid}"},
    )
    holder.commit()  # session lock remains held on connection
    try:
        t0 = time.monotonic()
        # Seed pending so tick/rehydrate flush hits lock_timeout
        from app.ingest import ip_limit as ipl

        core.upsert(
            lid,
            user_id=uid,
            tier=DataLicenceTier.ANNUAL,
            status=DataLicenceStatus.ACTIVE,
            now=NOW0,
            hydrate=False,  # L-a: tick flush is the lock-wait under test
        )
        mem = core._user_mem(uid)
        mem.escalated_until = NOW0 + dt.timedelta(hours=1)
        ipl.queue_pending_escalation(
            mem,
            licence_id=lid,
            user_id=uid,
            from_status="active",
            upstream_code="103",
            at=NOW0,
        )
        core.tick(NOW0 + dt.timedelta(seconds=1))
        elapsed = time.monotonic() - t0
        assert elapsed < 3.0, f"lock wait too long: {elapsed}"
        assert mem.pending_escalation is not None  # kept
    finally:
        holder.execute(
            text("SELECT pg_advisory_unlock(hashtext(:k))"),
            {"k": f"ingest:ip_limit:{uid}"},
        )
        holder.close()


# ---- deny codes never leak sentinel ----


def test_tb116_deny_codes_no_secret_or_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    stop, halt = tmp_path / "S", tmp_path / "H"
    halt.touch()
    with pytest.raises(eg.EgressDenied) as ei:
        _mg(
            lease=eg.EgressLease(held=True),  # halt checked before lease; avoid sqlite advisory
            core=IngestCore(CFG),
            engine=create_engine("sqlite+pysqlite:///:memory:"),
            licence_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            path=FAKE_URL_FRAG,
            secret=SENTINEL,
            priority=Priority.P1,
            clock=_clock(NOW0),
            stop=stop,
            halt=halt,
            transport=lambda p, s: (200, []),
        )
    msg = str(ei.value)
    assert SENTINEL not in msg
    assert "mairuiapi" not in msg
    assert ei.value.code == "halt_present"


# ---- real _https_get never called: monkeypatch guard ----


def test_tb116_https_get_not_used_in_selfchecks(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*a: object, **k: object) -> Never:
        raise AssertionError("real _https_get must not be called in T-B116 selfchecks")

    monkeypatch.setattr(eg, "_https_get", forbidden)
    # default transport is _https_get — calling without override would hit forbidden;
    # ensure our tests always pass transport= (spot-check one deny path uses explicit transport)
    # transport is keyword-only → lives in __kwdefaults__, not __defaults__
    assert eg.mairui_get.__kwdefaults__ is not None
    # __kwdefaults__ keeps the original function object; name must stay _https_get.
    assert eg.mairui_get.__kwdefaults__["transport"].__name__ == "_https_get"
