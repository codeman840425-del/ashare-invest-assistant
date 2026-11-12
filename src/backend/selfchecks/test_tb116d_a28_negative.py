# A28-negative
# ruff: noqa: S101, ANN001, N817, I001
"""A28 negative fixtures. Run only as a subprocess (``python thisfile.py``), not under pytest."""

from __future__ import annotations

import dataclasses
import datetime as dt
import os
import sys
import threading
import uuid
from pathlib import Path

import yaml
from sqlalchemy import create_engine, text

from app.config_files import IngestConfig
from app.ingest import egress as eg
from app.ingest.core import IngestCore
from app.ingest.state import Priority

ROOT = Path(__file__).resolve().parents[3]
CFG = IngestConfig.model_validate(
    yaml.safe_load((ROOT / "config/ingest.yaml").read_text(encoding="utf-8"))
).licences
NOW0 = dt.datetime(2026, 11, 9, 19, 30, tzinfo=dt.UTC)
FAKE_LIC = "FAKE-" + "tb116d" + "-a28"


def _url() -> str:
    u = os.environ.get("TB116D_DATABASE_URL") or os.environ.get("TB116B_DATABASE_URL")
    if not u:
        raise SystemExit("no TB116D_DATABASE_URL")
    return u


def _seed(eng, uid, lid) -> None:
    with eng.begin() as conn:
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
                ") VALUES (:id, :uid, decode('00','hex'), 1, decode(:hm,'hex'), 'annual', 'active')"
            ),
            {"id": lid, "uid": uid, "hm": uuid.uuid4().hex},
        )


def _call(lease, core, eng, lid, uid, halt: Path, calls: list) -> None:
    def transport(path: str, secret: str) -> tuple[int, object]:
        calls.append(path)
        return 200, {"ok": True}

    eg.mairui_get(
        lease=lease,
        core=core,
        engine=eng,
        licence_id=lid,
        user_id=uid,
        path="/hslt/list/",
        secret=FAKE_LIC,
        priority=Priority.P1,
        clock=lambda: NOW0,
        stop=halt.parent / "S",
        halt=halt,
        transport=transport,
    )


def main() -> None:
    from pathlib import Path as P
    import tempfile

    url = _url()
    eng = create_engine(url, hide_parameters=True)
    tmp = P(tempfile.mkdtemp(prefix="tb116d-a28-"))
    halt = tmp / "H"
    failures: list[str] = []

    def expect_denied(label: str, fn) -> None:
        calls: list[str] = []
        try:
            fn(calls)
        except eg.EgressDenied as exc:
            if exc.code != "single_egress_not_held":
                failures.append(f"{label}: code={exc.code}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{label}: {type(exc).__name__}: {exc}")
        else:
            failures.append(f"{label}: DID NOT RAISE")
        if calls:
            failures.append(f"{label}: transport={calls}")

    # ① stuff registry with a fake entry while a real lease is held
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(eng, uid, lid)
    core = IngestCore(CFG, engine=eng)
    with eg.single_egress(eng) as lease:
        assert lease is not None
        fake = eg.EgressLease(
            held=True, nonce="deadbeef", thread_id=lease.thread_id, lock_pid=1, mac=b"x"
        )
        # A28-negative
        eg._ISSUED_LEASES[fake.nonce] = fake
        # A28-negative
        eg._LEASE_LOCK_CONN[fake.nonce] = object()
        expect_denied("stuff", lambda calls: _call(fake, core, eng, lid, uid, halt, calls))

        # ② dataclasses.replace of mac / thread_id
        bad_mac = dataclasses.replace(lease, mac=b"\x00" * 32)
        expect_denied("bad_mac", lambda calls: _call(bad_mac, core, eng, lid, uid, halt, calls))
        bad_tid = dataclasses.replace(lease, thread_id=lease.thread_id + 1)
        expect_denied("bad_tid", lambda calls: _call(bad_tid, core, eng, lid, uid, halt, calls))

        # ③ another thread uses the real lease
        box: dict[str, object] = {}

        def in_other(calls: list) -> None:
            err_holder: list = []

            def run() -> None:
                try:
                    _call(lease, core, eng, lid, uid, halt, calls)
                    err_holder.append("NO_RAISE")
                except eg.EgressDenied as exc:
                    err_holder.append(exc.code)
                except Exception as exc:  # noqa: BLE001
                    err_holder.append(f"{type(exc).__name__}:{exc}")

            th = threading.Thread(target=run)
            th.start()
            th.join(5)
            box["r"] = err_holder
            if err_holder != ["single_egress_not_held"]:
                raise AssertionError(f"other thread: {err_holder}")

        calls3: list[str] = []
        in_other(calls3)
        if box.get("r") != ["single_egress_not_held"] or calls3:
            failures.append(f"other_thread: {box} calls={calls3}")

        # ④ unlock session advisory lock but objects remain
        # A28-negative
        lock = eg._LEASE_LOCK_CONN[lease.nonce]
        lock.execute(text("SELECT pg_advisory_unlock(hashtext('ingest:single-egress'))"))
        lock.commit()
        expect_denied("unlocked", lambda calls: _call(lease, core, eng, lid, uid, halt, calls))

    if failures:
        print("FAIL")
        for f in failures:
            print(f)
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
