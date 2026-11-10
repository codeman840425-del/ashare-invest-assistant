# A28-negative
"""A28 反例夹具：只在子进程运行，允许静态引用 egress 私有注册表（S2 例外）。"""

from __future__ import annotations

# A28-negative
import dataclasses
import os
import sys
import threading
from types import SimpleNamespace


def _deny(code: str) -> None:
    raise SystemExit(f"DENIED:{code}")


def main() -> int:
    # A28-negative — touch private registries only here
    os.environ.pop("MAIRUI_LICENCE", None)
    os.environ["MAIRUI_LICENCE"] = ""
    case = sys.argv[1]
    from app.ingest import egress as eg  # A28-negative

    # Import helpers from the official harness via run-time path set by parent.
    import tests.backend.unit.test_ta87_m1_a1_a24_t_t50 as h  # type: ignore

    tr = h.FakeTransport(responses=[(200, {"ok": True})])
    with h._temp_db("a28") as (eng, _n, _u):
        import uuid
        from pathlib import Path

        uid, lid = uuid.uuid4(), uuid.uuid4()
        h._seed_licence(eng, uid, lid)
        core = h._make_core(eng)
        tmp = Path(os.environ.get("A28_TMP", "/tmp"))
        if case == "inject_registry":
            # A28-negative: copy nonce, stuff fake into _ISSUED_LEASES / _LEASE_LOCK_CONN
            with eg.single_egress(eng) as real:
                nonce = getattr(real, "_nonce", "") or "copied"
                fake_conn = SimpleNamespace(closed=False)
                forged = eg.EgressLease(held=True, _nonce=nonce)  # type: ignore[call-arg]
                # T-A90 M-a：覆盖同一 nonce 槽位（不是另开无关键）
                eg._ISSUED_LEASES[nonce] = forged  # A28-negative
                eg._LEASE_LOCK_CONN[nonce] = fake_conn  # A28-negative
                try:
                    h._call_mairui(
                        eg,
                        engine=eng,
                        core=core,
                        lid=lid,
                        uid=uid,
                        transport=tr,
                        lease=forged,
                        tmp_path=tmp,
                    )
                except eg.EgressDenied as exc:
                    print("DENIED", exc.code, "calls", len(tr.calls))
                    return 0 if exc.code == "single_egress_not_held" and not tr.calls else 4
                print("ALLOWED", "calls", len(tr.calls))
                return 4
        if case == "replace_mac_or_thread":
            with eg.single_egress(eng) as real:
                fields = getattr(real, "__dataclass_fields__", {})
                if "mac" not in fields and "thread_id" not in fields:
                    print("MISSING_MAC_OR_THREAD_FIELDS", list(fields))
                    return 4  # M-a 未实现 HMAC/线程绑定 → 红
                try:
                    kwargs = {}
                    if "thread_id" in fields:
                        kwargs["thread_id"] = -1
                    if "mac" in fields:
                        kwargs["mac"] = bytes(32)
                    clone = dataclasses.replace(real, **kwargs)
                except Exception as exc:  # noqa: BLE001
                    print("REPLACE_FAIL", type(exc).__name__)
                    return 4
                try:
                    h._call_mairui(
                        eg,
                        engine=eng,
                        core=core,
                        lid=lid,
                        uid=uid,
                        transport=tr,
                        lease=clone,
                        tmp_path=tmp,
                    )
                except eg.EgressDenied as exc:
                    print("DENIED", exc.code, "calls", len(tr.calls))
                    return 0 if exc.code == "single_egress_not_held" and not tr.calls else 4
                print("ALLOWED", "calls", len(tr.calls))
                return 4
        if case == "other_thread":
            box: dict[str, object] = {}

            def _use(lease: object) -> None:
                try:
                    h._call_mairui(
                        eg,
                        engine=eng,
                        core=core,
                        lid=lid,
                        uid=uid,
                        transport=tr,
                        lease=lease,
                        tmp_path=tmp,
                    )
                    box["allowed"] = True
                except eg.EgressDenied as exc:
                    box["code"] = exc.code

            with eg.single_egress(eng) as real:
                t = threading.Thread(target=_use, args=(real,))
                t.start()
                t.join(8)
            print("BOX", box, "calls", len(tr.calls))
            if box.get("code") == "single_egress_not_held" and not tr.calls:
                print("DENIED", box["code"], "calls", 0)
                return 0
            print("ALLOWED_OR_FAIL", box)
            return 4
        if case == "unlock_still_in_registry":
            from sqlalchemy import text

            with eg.single_egress(eng) as real:
                nonce = getattr(real, "_nonce", "")
                conn = eg._LEASE_LOCK_CONN.get(nonce)  # A28-negative
                if conn is not None and hasattr(conn, "execute"):
                    conn.execute(text("SELECT pg_advisory_unlock(hashtext('ingest:single-egress'))"))
                    try:
                        conn.commit()
                    except Exception:
                        pass
                try:
                    h._call_mairui(
                        eg,
                        engine=eng,
                        core=core,
                        lid=lid,
                        uid=uid,
                        transport=tr,
                        lease=real,
                        tmp_path=tmp,
                    )
                except eg.EgressDenied as exc:
                    print("DENIED", exc.code, "calls", len(tr.calls))
                    return 0 if exc.code == "single_egress_not_held" and not tr.calls else 4
                print("ALLOWED", "calls", len(tr.calls))
                return 4
        print("UNKNOWN_CASE")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
