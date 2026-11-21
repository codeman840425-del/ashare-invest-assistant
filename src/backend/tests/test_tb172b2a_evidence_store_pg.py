"""登记幂等、修订链、来源隔离：仅独立临时数据库。"""

# ruff: noqa: S101
from collections.abc import Iterator
from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, insert, select

from app.db.tables.horizon import horizon_input_versions as versions
from app.db.tables.realtime import pipeline_runs
from app.db.tables.users import users
from app.features import horizon_evidence_store as store
from tests.test_tb172b1a_horizon_versions_pg import world  # noqa: F401
from tests.test_tb172b2a_evidence_store_offline import BATCH, PAYLOADS, PROOF, U

NOW = datetime(2026, 11, 15, 9, tzinfo=UTC)


@pytest.fixture
def conn(world: SimpleNamespace) -> Iterator[Connection]:  # noqa: F811
    with world.engine.begin() as connection:
        connection.execute(
            insert(users).values(
                id=UUID(U),
                username="synthetic_evidence",
                password_hash="unusable",  # noqa: S106
                role="user",
                status="approved",
            )
        )
        yield connection


def package(kind: str = "calendar", **changes: object) -> dict[str, Any]:
    p = {
        "user_id": UUID(U),
        "licence_id": None,
        "kind": kind,
        "source": "derived" if kind in {"feature", "adjust_factor"} else "fake",
        "scope": "public" if kind in {"feature", "adjust_factor"} else "synthetic",
        "code": "SYN",
        "data_date": date(2026, 11, 15),
        "source_key": "merged_calendar",
        "source_version": "v1",
        "payload": {**PAYLOADS[kind], "persisted_receipt": "synthetic"},
        "first_seen_at": NOW,
        "available_at": NOW,
        "computed_at": NOW if kind in {"feature", "adjust_factor"} else None,
        "dependency_ids": [],
        "transform_version": "v1",
    } | changes
    if kind == "daily_bar" and "payload" not in changes:
        p["payload"].update(
            source=p["source"], source_licence_id=str(p["licence_id"]) if p["licence_id"] else None
        )
    return p


def completion(conn: Connection, bar: UUID, **changes: object) -> dict[str, Any]:
    row = conn.execute(select(versions).where(versions.c.id == bar)).mappings().one()
    proof = {
        **PROOF,
        "version_hash": row["version_hash"],
        "source": row["source"],
        "licence_id": str(row["licence_id"]) if row["licence_id"] else None,
        "persisted_receipt": "synthetic",
        "source_final_receipt": "synthetic fixture",
    }
    return {
        "bar_version_id": bar,
        "is_final": True,
        "available_at": NOW,
        "proof_kind": "synthetic",
        "proof": proof,
    } | changes


def test_registration_idempotency(conn: Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    p = package()
    first = store.register_version(conn, **p)
    assert store.register_version(conn, **p) == first
    digest = conn.scalar(select(versions.c.version_hash).where(versions.c.id == first))
    assert digest == store.canon_sha256({**p, "supersedes_id": None})
    monkeypatch.setattr(store, "canon_sha256", lambda obj: digest)
    with pytest.raises(store.EvidenceConflict):
        store.register_version(conn, **(p | {"source_version": "changed"}))


@pytest.mark.parametrize("case", ["same", "licence", "key", "missing"])
def test_revision_chain(conn: Connection, case: str) -> None:
    p = package(source="merged_calendar", scope="per_licence", licence_id=uuid4())
    old = store.register_version(conn, **p)
    p |= {"source_version": "v2", "supersedes_id": old}
    if case == "licence":
        p["licence_id"] = uuid4()
    elif case == "key":
        p["source_key"] = "other"
    elif case == "missing":
        p["supersedes_id"] = uuid4()
    with nullcontext() if case == "same" else pytest.raises(store.EvidenceRejected):
        assert store.register_version(conn, **p) != old


@pytest.mark.parametrize("case", ["user", "licence", "missing", "duplicate", "self"])
def test_source_isolation(conn: Connection, case: str, monkeypatch: pytest.MonkeyPatch) -> None:
    p = package(source="merged_calendar", scope="per_licence", licence_id=uuid4())
    dep = store.register_version(conn, **p)
    p["dependency_ids"] = [dep]
    if case == "user":
        p["user_id"] = UUID(int=1724)
    elif case == "licence":
        p["licence_id"] = uuid4()
    elif case == "missing":
        p["dependency_ids"] = [uuid4()]
    elif case == "duplicate":
        p["dependency_ids"] = [dep, dep]
    else:
        monkeypatch.setattr(store, "uuid4", lambda: dep)
    with pytest.raises(store.EvidenceRejected):
        store.register_version(conn, **p)


@pytest.mark.parametrize(
    ("target", "key"),
    [("payload", k) for k in ("code", "trade_date", "source", "source_licence_id", "adj_type")]
    + [("proof", k) for k in PROOF],
)
def test_daily_bar_outer_binding(conn: Connection, target: str, key: str) -> None:
    p = package("daily_bar")
    if target == "proof":
        p = completion(conn, store.register_version(conn, **p))
    bad = "2026-11-14" if key == "trade_date" else "b" * 64
    p[target][key] = str(uuid4()) if key.endswith("id") else bad
    with nullcontext() if key == "sha256" else pytest.raises(store.EvidenceRejected, match=key):
        if target == "payload":
            store.register_version(conn, **p)
        else:
            store.register_completion(conn, **p)


@pytest.mark.parametrize("kinds", [[], ["daily_bar"], ["ex_rights"], ["calendar"]])
def test_adjust_factor_dependencies(conn: Connection, kinds: list[str]) -> None:
    deps = [store.register_version(conn, **package(kind)) for kind in kinds]
    with pytest.raises(store.EvidenceRejected, match="dependency"):
        store.register_version(conn, **package("adjust_factor", dependency_ids=deps))


@pytest.mark.parametrize(
    ("kind", "unknown"),
    [
        ("adjust_factor", "known"),
        ("adjust_factor", "dependency"),
        ("feature", "known"),
        ("feature", "dependency"),
        ("feature", "evidence"),
    ],
)
@pytest.mark.parametrize("hours", [-1, 4])
def test_derived_available_at(conn: Connection, kind: str, unknown: str, hours: int) -> None:
    event = store.register_version(
        conn, **package("ex_rights", available_at=None if unknown == "dependency" else NOW)
    )
    bar = store.register_version(conn, **package("daily_bar"))
    computed = NOW + timedelta(hours=hours)
    visible = NOW + timedelta(hours=3 if kind == "feature" else 0)
    p = package(kind, computed_at=computed, dependency_ids=[event, bar], available_at=None)
    if kind == "feature":
        evidence = store.register_completion(
            conn,
            **completion(
                conn,
                bar,
                available_at=None if unknown == "evidence" else visible,
                is_final=None if unknown == "evidence" else True,
            ),
        )
        p["payload"].update(dependency_ids=[str(event), str(bar)], evidence_ids=[str(evidence)])
    expected = None if unknown != "known" else max(computed, visible)
    result = store.register_version(conn, **p)
    assert conn.scalar(select(versions.c.available_at).where(versions.c.id == result)) == expected
    with pytest.raises(store.EvidenceRejected, match="derived_available_at"):
        store.register_version(conn, **(p | {"available_at": NOW + timedelta(hours=2)}))
    if kind == "feature":
        p["dependency_ids"] = [event]
        p["payload"]["dependency_ids"] = [str(event)]
        with pytest.raises(store.EvidenceRejected, match=r"evidence.*dependency"):
            store.register_version(conn, **p)


COMPLETION_CASES = (
    "kind scope historical pipeline members run_date valid synthetic missing_run "
    "no_batches empty_batches owner_id licence_id step"
)


@pytest.mark.parametrize("case", COMPLETION_CASES.split())
def test_completion_gates_and_idempotency(conn: Connection, case: str) -> None:
    p = package() if case == "kind" else package("daily_bar")
    if case != "synthetic" and case != "kind":
        p = package("daily_bar", source="mairui", scope="per_licence", licence_id=uuid4())
    bar = store.register_version(conn, **p)
    c = completion(conn, bar)
    if case != "scope":
        c["proof_kind"] = "synthetic" if case == "synthetic" else "source_final_receipt"
    if case not in {"kind", "synthetic", "historical"}:
        run = uuid4()
        conn.execute(
            insert(pipeline_runs).values(
                id=run, kind="daily_batch", run_date=p["data_date"], status="ok"
            )
        )
        c["pipeline_run_id"] = None if case == "missing_run" else run
        c["proof"]["batches"] = [{**BATCH, "run_id": U if case == "pipeline" else str(run)}]
        if case in BATCH:
            bad = [] if case == "members" else "2026-11-14" if case == "run_date" else str(uuid4())
            c["proof"]["batches"][0][case] = bad
        if case == "no_batches":
            del c["proof"]["batches"]
        if case == "empty_batches":
            c["proof"]["batches"] = []
    with (
        nullcontext()
        if case in {"valid", "synthetic", "historical", "missing_run"}
        else pytest.raises(store.EvidenceRejected)
    ):
        first = store.register_completion(conn, **c)
        assert store.register_completion(conn, **c) == first
