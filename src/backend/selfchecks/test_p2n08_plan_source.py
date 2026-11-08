"""Final slice: actual isolated aia_api SQL sources, never fake coverage approval."""

# ruff: noqa: S101,S108,ANN401
from __future__ import annotations

import datetime as dt
import secrets
import socket
import uuid
from decimal import Decimal
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import event, insert, text, update

from app.config import Settings
from app.db.tables.accounts import import_batches, trades
from app.db.tables.research import action_plans, plan_versions
from app.db.tables.users import audit_logs
from app.feedback.plan_source import load
from app.feedback.plans import assess, select_plan
from app.risk.evaluation import current
from selfchecks import test_p2n08_pause as shared
from selfchecks.test_p2n08_pause import env as env
from selfchecks.test_p2n08_pause import pg as pg

SH = dt.timezone(dt.timedelta(hours=8))
CODE = "688018.SH"


def at(hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(2026, 11, 2, hour, minute, tzinfo=SH)


@pytest.fixture(autouse=True)
def confined(monkeypatch: Any) -> None:
    monkeypatch.setattr(shared, "SOCKET", "/tmp/p2n08-s5-owned/pg")
    original = socket.socket.connect

    def guard(sock: socket.socket, address: Any) -> Any:
        assert sock.family == socket.AF_UNIX
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guard)


def seed(env: Any) -> tuple[Any, ...]:
    ids = tuple(uuid.uuid4() for _ in range(6))
    head, v1, v2, t1, old, replacement = ids
    with env[0].begin() as c:
        c.execute(
            insert(action_plans).values(
                id=head,
                user_id=env[2],
                account_id=env[4],
                security_code=CODE,
                status="active",
                origin="manual",
                created_at=at(9),
            )
        )
        for ident, number, point in ((v1, 1, at(9)), (v2, 2, at(10))):
            c.execute(
                insert(plan_versions).values(
                    id=ident,
                    plan_id=head,
                    version_no=number,
                    action="buy",
                    completeness={"qty": "100", "coverage_complete": True},
                    created_at=point,
                )
            )
        c.execute(
            update(action_plans).where(action_plans.c.id == head).values(current_version_id=v2)
        )
        for ident, qty, executed, created, voided, prior in (
            (t1, 60, at(10), at(10), None, None),
            (old, 60, at(10, 2), at(10, 2), at(10, 10), None),
            (replacement, 40, at(10, 2), at(10, 10), None, old),
        ):
            c.execute(
                insert(trades).values(
                    id=ident,
                    user_id=env[2],
                    account_id=env[4],
                    security_code=CODE,
                    side="buy",
                    quantity=Decimal(qty),
                    price=Decimal(10),
                    source="manual",
                    trade_date=executed.date(),
                    traded_at=executed,
                    created_at=created,
                    voided_at=voided,
                    replaces_trade_id=prior,
                )
            )
    return ids


def test_actual_role_version_cut_correction_and_readonly_evaluation_unknown(env: Any) -> None:
    _head, v1, v2, _t1, old, replacement = seed(env)
    with env[1].connect() as c:
        assert c.execute(text("SELECT current_user")).scalar_one() == "aia_api"
        assert (
            c.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")).scalar_one()
            is False
        )
        early = load(c, env[2], env[4], CODE, at=at(9, 59))
        assert early.facts is not None
        assert [p.id for p in early.facts.plans] == [str(v1)]
        assert early.facts.plans[0].end is None
        assert not early.facts.trades
        prior = load(c, env[2], env[4], CODE, at=at(10, 5))
        assert prior.facts is not None
        assert sum(t.quantity for t in prior.facts.trades if not t.voided) == 120
        selected = select_plan(prior.facts.plans, prior.facts.trades[0], at=at(10, 5))
        assert selected.plan is not None
        assert selected.plan.id == str(v2)
        after = load(c, env[2], env[4], CODE, at=at(10, 15))
        assert after.facts is not None
        assert sum(t.quantity for t in after.facts.trades if not t.voided) == 100
        assert next(t for t in after.facts.trades if t.id == str(old)).voided
        assert next(t for t in after.facts.trades if t.id == str(replacement)).available_at == at(
            10, 10
        )
        assert after.facts.coverage_at is None
        assert not after.facts.coverage_complete
        assert "plan_history_coverage_unproven" in after.gaps
        assert not assess(after.facts, at=at(10, 15), checks=("qty_over_plan",)).flags
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=SecretStr(env[1].url.render_as_string(hide_password=False)),
        app_master_key=SecretStr(secrets.token_urlsafe(32)),
    )
    statements = []

    def capture(
        _conn: Any, _cursor: Any, statement: str, _parameters: Any, _context: Any, _many: Any
    ) -> None:
        statements.append(statement)

    event.listen(env[1], "before_cursor_execute", capture)
    try:
        before = shared.counts(env)
        with env[1].connect() as c:
            value = current(c, env[2], CODE, env[4], settings, at(10, 15))
            again = current(c, env[2], CODE, env[4], settings, at(10, 15))
        assert again == value
        assert shared.counts(env) == before
        rc6 = value["controls"][-1]
        assert rc6["state"] == "unknown"
        assert not rc6["flags"]
        assert "plan_history_coverage_unproven" in {g["key"] for g in rc6["gaps"]}
        assert any(e["key"].startswith("plan_db_version:") for e in value["evidence"])
        assert value["data_as_of"] == at(9)
        assert not any(
            s.lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ")) for s in statements
        )
    finally:
        event.remove(env[1], "before_cursor_execute", capture)


def test_owned_close_audit_and_import_commit_provenance_not_coverage(env: Any) -> None:
    head, _v1, v2, *_ = seed(env)
    with env[0].begin() as c:
        c.execute(
            update(action_plans)
            .where(action_plans.c.id == head)
            .values(status="done", updated_at=at(19))
        )
        c.execute(
            insert(audit_logs).values(
                actor_id=env[2],
                actor_role="user",
                action="plan.closed",
                target_type="action_plan",
                target_id=str(head),
                detail={"status": "done"},
                at=at(16, 30),
            )
        )
        batch = uuid.uuid4()
        c.execute(
            insert(import_batches).values(
                id=batch,
                user_id=env[2],
                account_id=env[4],
                status="committed",
                kind="trades",
                created_at=at(10),
                committed_at=at(17),
                summary={"coverage_complete": True, "through": at(17).isoformat()},
            )
        )
        c.execute(
            insert(trades).values(
                user_id=env[2],
                account_id=env[4],
                security_code=CODE,
                side="buy",
                quantity=Decimal(999),
                price=Decimal(10),
                source="import",
                import_batch_id=batch,
                trade_date=at(10).date(),
                traded_at=at(10),
                created_at=at(10),
            )
        )
        c.execute(
            insert(trades).values(
                user_id=env[3],
                account_id=env[4],
                security_code=CODE,
                side="buy",
                quantity=Decimal(999),
                price=Decimal(10),
                source="manual",
                trade_date=at(10).date(),
                traded_at=at(10),
                created_at=at(10),
            )
        )
    with env[1].connect() as c:
        earlier = load(c, env[2], env[4], CODE, at=at(16))
        assert earlier.facts is not None
        assert next(p for p in earlier.facts.plans if p.id == str(v2)).end is None
        assert all(t.quantity != 999 for t in earlier.facts.trades)
        closed = load(c, env[2], env[4], CODE, at=at(17, 1))
        assert closed.facts is not None
        assert next(p for p in closed.facts.plans if p.id == str(v2)).end == at(16, 30)
        assert sum(t.quantity == 999 for t in closed.facts.trades) == 1
        assert not closed.facts.coverage_complete
        assert load(c, env[3], env[4], CODE, at=at(17, 1)).facts is None
        assert not load(c, env[3], env[4], CODE, at=at(17, 1)).evidence
    with env[0].begin() as c:
        # An invented status/updated_at is not an immutable closure boundary.
        other_head = uuid.uuid4()
        c.execute(
            insert(action_plans).values(
                id=other_head,
                user_id=env[2],
                account_id=env[4],
                security_code=CODE,
                status="done",
                origin="manual",
                created_at=at(9),
            )
        )
        c.execute(
            insert(plan_versions).values(
                plan_id=other_head,
                version_no=1,
                action="buy",
                completeness={"qty": "100"},
                created_at=at(9),
            )
        )
    with env[1].connect() as c:
        assert "plan_closed_boundary_unproven" in load(c, env[2], env[4], CODE, at=at(17, 1)).gaps
