"""T-B61 真正隔离 PG/Redis/HTTP 端到端：仅注入虚构采集结果，不伪造SQL或API输出。

固定本任务套接字，建立新的 tb61_isolated_<pid> 数据库；worker/HTTP 以 aia_api、
交接以 aia_ingest 连接；只有夹具建库/迁移用隔离库属主。结束删除本人新建测试库。
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import logging
import os
import runpy
import secrets
import sys
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import redis
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, insert, select, text
from sqlalchemy.exc import DBAPIError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.api.v1.admin import router
from app.auth import deps
from app.auth.sessions import SessionStore
from app.common.errors import install_exception_handlers
from app.config import Settings, get_settings
from app.db.base import metadata
from app.db.tables import licences, market, ops, users
from app.db.tables.vendor import DATASETS
from app.db.tables.vendor import master_vendor_batches as batch_table
from app.db.tables.vendor import master_vendor_list_rows as list_rows
from app.ingest.intents import IntentError, VendorIntent, VerifyIntent, parse_intent
from app.ingest.vendor_lists import DatasetResult, VendorRow, process_vendor_intent
from app.master import sync
from app.master.sources import Part, sse_list_url
from app.master.vendor import apply_batch, deadline_for
from app.workers import jobs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket-dir", type=Path, required=True)
    socket = parser.parse_args().socket_dir.resolve()
    if socket != Path(tempfile.gettempdir()) / "tb58-pg3-socket":
        parser.error("只允许既有本人专用隔离PG套接字")
    rsocket = Path(tempfile.gettempdir()) / "tb61-offline-redis-socket" / "redis.sock"
    if not rsocket.is_socket():
        raise RuntimeError("专用无网络Redis未运行")
    dbname = f"tb61_isolated_{os.getpid()}"
    admin = create_engine(
        f"postgresql+psycopg://tb58@/tb58_isolated?host={socket}", isolation_level="AUTOCOMMIT"
    )
    with admin.connect() as conn:
        if conn.execute(
            text("SELECT count(*) FROM pg_database WHERE datname=:name"), {"name": dbname}
        ).scalar():
            raise RuntimeError("同名测试库已存在，拒绝修改")
        conn.execute(text(f"CREATE DATABASE {dbname}"))
        for role in ("aia_api", "aia_ingest"):
            if not conn.execute(
                text("SELECT count(*) FROM pg_roles WHERE rolname=:role"), {"role": role}
            ).scalar():
                conn.execute(
                    text(f"CREATE ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT")
                )
            if conn.execute(
                text(
                    "SELECT rolsuper OR rolcreatedb OR rolcreaterole "
                    "FROM pg_roles WHERE rolname=:role"
                ),
                {"role": role},
            ).scalar():
                raise RuntimeError("角色权限不符合最低权限要求")
    owner = create_engine(f"postgresql+psycopg://tb58@/{dbname}?host={socket}")
    api = create_engine(f"postgresql+psycopg://aia_api@/{dbname}?host={socket}")
    ingest = create_engine(f"postgresql+psycopg://aia_ingest@/{dbname}?host={socket}")
    rds = redis.Redis(unix_socket_path=str(rsocket))
    rds.flushdb()  # 本任务专用容器，不读通用REDIS_URL
    results = []

    def check(ok: object, name: str) -> None:
        results.append(bool(ok))
        print(("PASS " if ok else "FAIL ") + name)
        if not ok:
            raise AssertionError(name)

    logtext = io.StringIO()
    handler = logging.StreamHandler(logtext)
    logging.getLogger().addHandler(handler)
    sentinel = "TB61_FAKE_LICENCE_SENTINEL_NOT_A_REAL_SECRET"
    clock = [dt.datetime(2026, 11, 2, 10, 5, tzinfo=dt.UTC)]
    original_clock, original_fetcher = jobs._now, jobs._master_fetcher
    try:
        needed = {
            market.securities,
            market.master_runs,
            market.master_snapshots,
            market.security_name_history,
            market.security_code_history,
            market.security_risk_flag_history,
            market.security_listing_status_history,
            market.security_search_terms,
            market.security_reconciliation_diffs,
            licences.user_data_licences,
            licences.user_data_licence_holds,
            licences.data_licence_events,
            ops.ingest_request_log,
            ops.ingest_leases,
            users.users,
        }
        while True:
            expanded = needed | {fk.column.table for table in needed for fk in table.foreign_keys}
            if expanded == needed:
                break
            needed = expanded
        with owner.begin() as conn:
            for name in ("app", "market", "ops", "evaluation"):
                conn.execute(text(f"CREATE SCHEMA {name}"))
            conn.execute(text("CREATE EXTENSION pg_trgm"))
            conn.execute(text("CREATE EXTENSION btree_gist"))
            metadata.create_all(conn, tables=list(needed))
            migration = runpy.run_path(
                str(
                    Path(__file__).resolve().parents[1]
                    / "migrations/versions/0020_t_b61_vendor_batches.py"
                )
            )
            with Operations.context(MigrationContext.configure(conn)):
                migration["upgrade"]()
                runpy.run_path(
                    str(
                        Path(__file__).resolve().parents[1]
                        / "migrations/versions/0021_t_b61b_not_set.py"
                    )
                )["upgrade"]()
            view = runpy.run_path(
                str(
                    Path(__file__).resolve().parents[1]
                    / "migrations/versions/0007_t_b45_data_licences.py"
                )
            )["_VIEW_SQL"]
            conn.execute(text(view))
            for role in ("aia_api", "aia_ingest"):
                conn.execute(text(f"GRANT USAGE ON SCHEMA app,market,ops TO {role}"))
                conn.execute(
                    text(
                        f"GRANT SELECT ON app.user_data_licence_status,"
                        f"app.user_data_licence_holds TO {role}"
                    )
                )
            # 按已有worker清单逐表最小授权，不用全schema CRUD掩盖权限缺口。
            privileges = {
                "securities": "SELECT,INSERT,UPDATE",
                "master_runs": "SELECT,INSERT,UPDATE",
                "master_snapshots": "SELECT,INSERT,UPDATE",
                "security_name_history": "SELECT,INSERT,UPDATE,DELETE",
                "security_risk_flag_history": "SELECT,INSERT,UPDATE,DELETE",
                "security_listing_status_history": "SELECT,INSERT,UPDATE",
                "security_code_history": "SELECT,INSERT,DELETE",
                "security_search_terms": "SELECT,INSERT,DELETE",
                "security_reconciliation_diffs": "SELECT,INSERT,UPDATE",
            }
            for name, operations in privileges.items():
                conn.execute(text(f"GRANT {operations} ON market.{name} TO aia_api"))
            conn.execute(
                text(
                    "GRANT SELECT ON app.users,ops.ingest_request_log,"
                    "ops.ingest_leases,ops.data_licence_events TO aia_api"
                )
            )
            conn.execute(
                text("GRANT SELECT,INSERT,UPDATE ON market.master_vendor_batches TO aia_api")
            )
            conn.execute(text("GRANT SELECT,DELETE ON market.master_vendor_list_rows TO aia_api"))
            conn.execute(text("GRANT SELECT ON market.master_vendor_batches TO aia_ingest"))
            conn.execute(
                text(
                    "GRANT UPDATE(status,fetched_at,datasets,error_code) "
                    "ON market.master_vendor_batches TO aia_ingest"
                )
            )
            conn.execute(text("GRANT INSERT ON market.master_vendor_list_rows TO aia_ingest"))
            aid, uid, other = uuid4(), uuid4(), uuid4()
            for user, name, role in [
                (aid, "tb61_admin", "admin"),
                (uid, "tb61_user", "user"),
                (other, "tb61_paused", "user"),
            ]:
                conn.execute(
                    users.users.insert().values(
                        id=user,
                        username=name,
                        password_hash=secrets.token_hex(32),
                        role=role,
                        status="approved",
                    )
                )
            lid, paused = uuid4(), uuid4()
            for ident, user, status in [(lid, uid, "active"), (paused, other, "paused_by_admin")]:
                conn.execute(
                    licences.user_data_licences.insert().values(
                        id=ident,
                        user_id=user,
                        ciphertext=sentinel.encode(),
                        licence_hmac=hashlib.sha256(str(ident).encode()).digest(),
                        seal_key_version=1,
                        tier="diamond",
                        status=status,
                    )
                )
            conn.execute(
                market.securities.insert().values(
                    code="609991.SH",
                    name="虚构已退市",
                    type="stock",
                    exchange="SH",
                    listing_status="delisted",
                    delist_date=dt.date(2026, 10, 30),
                    master_source="exchange",
                )
            )
        settings = Settings(
            _env_file=None,
            app_env="test",
            service_name="worker",
            database_url=str(api.url),
            redis_url=f"unix://{rsocket}",
            master_snapshot_path=tempfile.mkdtemp(prefix="tb61-master-"),
            app_master_key="t" * 40,
        )
        jobs._now = lambda: clock[0]

        def exchange_fixture(source: str) -> list[Part]:
            if source != "sse_list":
                raise RuntimeError("offline_source_unavailable")
            body = json.dumps(
                {
                    "result": [
                        {
                            "A_STOCK_CODE": "609990",
                            "SEC_NAME_CN": "虚构正常股票",
                            "COMPANY_ABBR": "虚构正常股票",
                            "LIST_DATE": "20200102",
                            "STOCK_TYPE": "1",
                        }
                    ]
                }
            ).encode()
            return [Part(sse_list_url("1"), body)]

        jobs._master_fetcher = lambda: exchange_fixture
        store = SessionStore(rds, idle_ttl_s=3600, absolute_ttl_s=86400)
        app = FastAPI()
        install_exception_handlers(app)
        app.include_router(router, prefix="/api/v1")
        app.dependency_overrides.update(
            {
                get_settings: lambda: settings,
                deps.get_engine: lambda: api,
                deps.get_redis: lambda: rds,
                deps.get_session_store: lambda: store,
            }
        )
        http = TestClient(app)
        sid, _ = store.create(str(aid))
        http.cookies.set("sid", sid)

        def batches(run: int | None = None) -> list[dict[str, Any]]:
            with api.connect() as conn:
                q = select(batch_table).order_by(batch_table.c.requested_at, batch_table.c.attempt)
                if run:
                    q = q.where(batch_table.c.master_run_id == run)
                return [dict(x) for x in conn.execute(q).mappings()]

        def collect(
            intent: VendorIntent,
            *,
            stale: bool = True,
            real_ok: bool = True,
            fail: str | None = None,
            conflict: bool = False,
        ) -> list[DatasetResult]:
            check(intent.licence_id == lid, "采集入口只收到本批次自己的作用域，不跨暂停证书回退")
            lists = (
                (
                    VendorRow("609991.SH", "供应商滞后退市简称"),
                    VendorRow("609999.SH", "虚构未知证券"),
                )
                if stale
                else (VendorRow("609990.SH", "虚构正常股票"),)
            )
            return [
                DatasetResult(
                    name,
                    lists
                    if name == "hslt_list"
                    else (
                        (VendorRow("609990.SH", "虚构正常股票", conflict),)
                        if name == "hsrl_real"
                        else ()
                    ),
                    error_code=sentinel
                    if name == fail or (name == "hsrl_real" and not real_ok)
                    else None,
                )
                for name in DATASETS
            ]

        def feed(
            fields: dict[bytes, bytes],
            *,
            stale: bool = True,
            real_ok: bool = True,
            fail: str | None = None,
            conflict: bool = False,
        ) -> str:
            return process_vendor_intent(
                ingest,
                rds,
                fields,
                fetch_results=lambda intent: collect(
                    intent, stale=stale, real_ok=real_ok, fail=fail, conflict=conflict
                ),
                clock=lambda: clock[0],
            )

        verify = parse_intent(
            {"kind": "verify_licence", "licence_id": str(lid), "verification_id": str(uuid4())}
        )
        check(isinstance(verify, VerifyIntent), "原verify_licence意图解析回归不受vendor分支影响")
        stream_cursor = "0-0"

        def take_intents() -> list[dict[bytes, bytes]]:
            nonlocal stream_cursor
            found = rds.xread({"ingest:requests": stream_cursor})
            out = []
            for _, records in found:
                for ident, fields in records:
                    stream_cursor = ident
                    out.append(fields)
            return out

        for day in [2, 3, 4, 5, 6, 9]:
            clock[0] = dt.datetime(2026, 11, day, 10, 5, tzinfo=dt.UTC)
            jobs._push(rds, jobs.SYNC_LISTS, {"trigger": "beat_1800"})
            done = jobs.worker_tick(settings, rds)
            check(
                (jobs.SYNC_LISTS, "ok") in done and (jobs.RECONCILE_VENDOR, "ok") in done,
                "实际SYNC_LISTS提交后链式进入已注册RECONCILE_VENDOR",
            )
            intents = take_intents()
            check(len(intents) == 1, "仅active证书产生P1意图")
            if day == 2:
                try:
                    parse_intent({**intents[0], b"licence": sentinel.encode()})
                except IntentError as exc:
                    check(sentinel not in str(exc), "vendor意图拒绝明文附加字段且错误不回显")
                else:
                    check(False, "携带明文的意图未拒绝")
            check(feed(intents[0]) == "fetched", "ingest真实事务写规范化行并提交fetched")
            if day == 2:
                shuffled = dict(intents[0])
                shuffled[b"datasets"] = json.dumps(list(reversed(DATASETS))).encode()
                check(
                    isinstance(parse_intent(shuffled), VendorIntent), "数据集顺序不作为额外契约约束"
                )
                duplicate = {**intents[0], b"datasets": json.dumps([DATASETS[0]] * 4).encode()}
                try:
                    parse_intent(duplicate)
                except IntentError:
                    check(True, "重复或缺失数据集被拒绝，不用局部列表对账")
                else:
                    check(False, "重复数据集不应通过")
                duplicate_calls: list[int] = []
                check(
                    process_vendor_intent(
                        ingest,
                        rds,
                        intents[0],
                        fetch_results=lambda _, calls=duplicate_calls: calls.append(1),
                        clock=lambda: clock[0],
                    )
                    == "noop"
                    and not duplicate_calls,
                    "重复ingest投递不重新采集或写入",
                )
            with api.connect() as conn:
                check(
                    conn.execute(select(func.count()).select_from(list_rows)).scalar() > 0,
                    "另一aia_api连接能读取ingest已经提交的结果",
                )
            done = jobs.worker_tick(settings, rds)
            check((jobs.RECONCILE_VENDOR_APPLY, "ok") in done, "实际worker apply事务提交")
            if day in {2, 6}:
                current_keys = {
                    a["key"] for a in http.get("/api/v1/admin/ingest/status").json()["alerts"]
                }
                check(
                    "master.vendor_stale_listed" not in current_keys,
                    "首次及第5工作日均不提前出滞后告警",
                )
                if day == 2:
                    check(
                        {"master.vendor_unknown", "master.quote_missing"} <= current_keys,
                        "未知证券及缺行情从首次已提交差异立即告警",
                    )
        with api.connect() as conn:
            diff = (
                conn.execute(
                    select(market.security_reconciliation_diffs).where(
                        market.security_reconciliation_diffs.c.kind == "vendor_stale_listed"
                    )
                )
                .mappings()
                .one()
            )
            check(
                diff["seen_days"] == 6 and diff["status"] == "open",
                "6个实际成功工作日累计，跨周末不虚加",
            )
            check(
                conn.execute(
                    select(market.securities.c.listing_status).where(
                        market.securities.c.code == "609991.SH"
                    )
                ).scalar()
                == "delisted",
                "供应商滞后不改变交易所delisted",
            )
        jobs._push(rds, jobs.SYNC_LISTS, {"trigger": "manual"})
        manual_done = jobs.worker_tick(settings, rds)
        check(
            (jobs.SYNC_LISTS, "ok") in manual_done and (jobs.RECONCILE_VENDOR, "ok") in manual_done,
            "管理员手动SYNC_LISTS成功同样链式进入对账，不限钟点任务",
        )
        manual_intents = take_intents()
        check(
            len(manual_intents) == 1 and feed(manual_intents[0]) == "fetched",
            "手动同步使用实际run_id及自己的作用域交接",
        )
        jobs.worker_tick(settings, rds)
        response = http.get("/api/v1/admin/ingest/status")
        check(response.status_code == 200, "真实会话/管理员权限下HTTP状态接口200")
        check(
            any(a["key"] == "master.vendor_stale_listed" for a in response.json()["alerts"]),
            "已提交差异驱动真实HTTP master.vendor_stale_listed告警",
        )
        page = http.get("/api/v1/admin/securities/reconciliation?limit=1").json()
        check(len(page["items"]) == 1 and page["next_cursor"], "真实HTTP差异接口分页并生成签名游标")
        check(
            http.get(
                "/api/v1/admin/securities/reconciliation",
                params={"limit": 1, "cursor": page["next_cursor"]},
            ).status_code
            == 200,
            "差异游标翻页",
        )
        check(
            http.get("/api/v1/admin/securities/reconciliation?kind=garbage").status_code == 400,
            "非法筛选400",
        )
        latest = [x for x in batches() if x["status"] == "reconciled"][-1]
        with api.begin() as conn:
            check(apply_batch(conn, latest["id"], now=clock[0]) == "noop", "重复apply不再次比对")
        # 三列表任一失败，下一轮新attempt；3次后记final，不使用局部快照比对。
        clock[0] += dt.timedelta(minutes=1)
        with owner.begin() as conn:
            run = conn.execute(
                insert(market.master_runs)
                .values(trigger="manual", status="ok", started_at=clock[0], snapshot_ids=[1])
                .returning(market.master_runs.c.id)
            ).scalar_one()
        for attempt in range(1, 4):
            jobs.reconcile_vendor_task(settings, master_run_id=run)
            intents = take_intents()
            check(len(intents) == 1, "失败重试仍只投递自己的active作用域")
            check(
                feed(intents[0], fail="bj_list") == "failed",
                "三列表任一失败，批次failed，不做局部比对",
            )
            jobs.worker_tick(settings, rds)
            row = [x for x in batches(run) if x["source_licence_id"] == lid][-1]
            check(
                row["attempt"] == attempt and row["status"] == "failed",
                "批次attempt递增且失败不变reconciled",
            )
            if attempt < 3:
                jobs.reconcile_vendor_task(settings, master_run_id=run)
                check(not take_intents(), "失败不足10分钟不提前新建或拉取下一attempt")
            clock[0] += dt.timedelta(minutes=10)
        jobs.reconcile_vendor_task(settings, master_run_id=run)
        with api.connect() as conn:
            stats = conn.execute(
                select(market.master_runs.c.stats).where(market.master_runs.c.id == run)
            ).scalar_one()
        check(
            stats["vendor"][0]["final"] == "failed" and not take_intents(),
            "三次后终止批次重试并提交final failed",
        )
        check(
            any(
                x["source_licence_id"] == paused and x["status"] == "skipped" for x in batches(run)
            ),
            "暂停作用域批次skipped且不借别人的证书",
        )
        # 同作用域较新批次消除差异后，再收到较旧快照，必须superseded。
        clock[0] += dt.timedelta(minutes=1)

        def manual_batch() -> dict[bytes, bytes]:
            with owner.begin() as conn:
                rid = conn.execute(
                    insert(market.master_runs)
                    .values(trigger="manual", status="ok", started_at=clock[0], snapshot_ids=[1])
                    .returning(market.master_runs.c.id)
                ).scalar_one()
            jobs.reconcile_vendor_task(settings, master_run_id=rid)
            return take_intents()[0]

        old = manual_batch()
        check(feed(old) == "fetched", "旧快照已完成但暂不apply")
        rds.delete(jobs.QUEUE_KEY)
        clock[0] += dt.timedelta(minutes=1)
        new = manual_batch()
        check(feed(new, stale=False) == "fetched", "新快照实际完成")
        jobs.worker_tick(settings, rds)
        with api.begin() as conn:
            check(
                apply_batch(conn, UUID(old[b"batch_id"].decode()), now=clock[0]) == "superseded",
                "旧快照不能重开已关闭差异",
            )
        check(
            not any(
                a["key"] == "master.vendor_stale_listed"
                for a in http.get("/api/v1/admin/ingest/status").json()["alerts"]
            ),
            "同类完整对账消失后关闭并撤下告警",
        )
        # 仅hsrl_real失败时三列表继续；不能关闭已有quote_conflict。
        clock[0] += dt.timedelta(minutes=1)
        q = manual_batch()
        feed(q, stale=False, conflict=True)
        jobs.worker_tick(settings, rds)
        clock[0] += dt.timedelta(minutes=1)
        q = manual_batch()
        feed(q, stale=False, real_ok=False)
        jobs.worker_tick(settings, rds)
        with api.connect() as conn:
            check(
                conn.execute(
                    select(func.count())
                    .select_from(market.security_reconciliation_diffs)
                    .where(
                        market.security_reconciliation_diffs.c.kind == "quote_conflict",
                        market.security_reconciliation_diffs.c.status == "open",
                    )
                ).scalar()
                == 1,
                "仅real失败不关quote_conflict且三列表仍提交",
            )
        check(
            not any(
                a["key"] == "master.quote_conflict"
                for a in http.get("/api/v1/admin/ingest/status").json()["alerts"]
            ),
            "quote_conflict不出告警",
        )
        clock[0] += dt.timedelta(minutes=1)
        q = manual_batch()
        bid = UUID(q[b"batch_id"].decode())
        feed(q, stale=False)
        rds.delete(jobs.QUEUE_KEY)
        clock[0] += dt.timedelta(minutes=31)
        jobs.vendor_sweep_task(settings)
        check(rds.llen(jobs.QUEUE_KEY) == 1, "超过30分钟fetched由真实兜底重新投递apply")
        jobs.worker_tick(settings, rds)
        check(
            next(x for x in batches() if x["id"] == bid)["status"] == "reconciled",
            "兜底投递实际提交reconciled",
        )
        q = manual_batch()
        deadline = dt.datetime.fromisoformat(q[b"deadline_at"].decode())
        clock[0] = deadline
        calls = []
        check(
            process_vendor_intent(
                ingest, rds, q, fetch_results=lambda _: calls.append(1), clock=lambda: clock[0]
            )
            == "expired"
            and not calls,
            "逾期意图不调用采集边界，直接expired",
        )
        q = manual_batch()
        bid = UUID(q[b"batch_id"].decode())
        clock[0] = dt.datetime.fromisoformat(q[b"deadline_at"].decode())
        jobs._push(rds, jobs.VENDOR_SWEEP, {})
        check(
            (jobs.VENDOR_SWEEP, "ok") in jobs.worker_tick(settings, rds),
            "兜底任务通过实际TASKS注册执行",
        )
        check(
            next(x for x in batches() if x["id"] == bid)["status"] == "expired",
            "兜底真正把超期requested提交为expired",
        )
        pending_intent = manual_batch()
        pending_id = UUID(pending_intent[b"batch_id"].decode())
        pending_parent = next(x for x in batches() if x["id"] == pending_id)["master_run_id"]
        with owner.begin() as conn:
            conn.execute(
                licences.user_data_licences.update()
                .where(licences.user_data_licences.c.id == lid)
                .values(status="paused_by_admin")
            )
        jobs.reconcile_vendor_task(settings, master_run_id=pending_parent)
        check(
            next(x for x in batches() if x["id"] == pending_id)["status"] == "skipped"
            and not take_intents(),
            "已请求作用域后来暂停则skipped，不重投或换证书",
        )
        with owner.begin() as conn:
            conn.execute(
                licences.user_data_licences.update()
                .where(licences.user_data_licences.c.id == lid)
                .values(status="active")
            )
        with owner.begin() as conn:
            try:
                with Operations.context(MigrationContext.configure(conn)):
                    migration["downgrade"]()
            except RuntimeError:
                check(True, "迁移降级遇非空批次拒绝，不删除证据")
            else:
                check(False, "非空降级应被拒绝")
        # 五键告警：固定中文/阈值/跨时段拒收；同sha快照的两次真实运行引用也可升级。
        with owner.begin() as conn:
            for i in range(9):
                conn.execute(
                    market.security_reconciliation_diffs.insert().values(
                        kind="field_mismatch",
                        source="cninfo",
                        security_code=f"6088{i:02d}.SH",
                        field="name",
                        first_seen_on=dt.date(2026, 11, 9),
                        last_seen_on=dt.date(2026, 11, 9),
                        seen_days=1,
                    )
                )
        check(
            not any(
                x["key"] == "master.field_mismatch"
                for x in http.get("/api/v1/admin/ingest/status").json()["alerts"]
            ),
            "字段不一致9行尚不告警",
        )
        with owner.begin() as conn:
            conn.execute(
                market.security_reconciliation_diffs.insert().values(
                    kind="field_mismatch",
                    source="cninfo",
                    security_code="608899.SH",
                    field="name",
                    first_seen_on=dt.date(2026, 11, 9),
                    last_seen_on=dt.date(2026, 11, 9),
                    seen_days=1,
                )
            )
            rejected_id = conn.execute(
                market.master_snapshots.insert()
                .values(
                    source="sse_list",
                    url="https://exchange.invalid/offline",
                    fetched_at=clock[0],
                    trade_date=clock[0].astimezone(sync.BEIJING).date(),
                    row_count=0,
                    sha256="b" * 64,
                    parse_status="rejected",
                    reject_reason="empty",
                )
                .returning(market.master_snapshots.c.id)
            ).scalar_one()
            # 先取未来完整工作日的两个相邻时段，避免先前合成运行的时间戳干扰。
            evening = dt.datetime(2026, 11, 11, 10, 5, tzinfo=dt.UTC)
            conn.execute(
                market.master_runs.insert().values(
                    trigger="beat_1800",
                    status="failed",
                    started_at=evening,
                    snapshot_ids=[rejected_id],
                )
            )
        alerts = http.get("/api/v1/admin/ingest/status").json()["alerts"]
        check(any(x["key"] == "master.field_mismatch" for x in alerts), "字段不一致10行才告警")
        check(
            any(x["key"] == "master.snapshot_rejected" and x["level"] == "warning" for x in alerts),
            "一轮拒收固定中文warning",
        )
        with owner.begin() as conn:
            conn.execute(
                market.master_runs.insert().values(
                    trigger="beat_0730",
                    status="failed",
                    started_at=evening + dt.timedelta(hours=13, minutes=25),
                    snapshot_ids=[rejected_id],
                )
            )
        alerts = http.get("/api/v1/admin/ingest/status").json()["alerts"]
        check(
            alerts[0]["key"] == "master.snapshot_rejected" and alerts[0]["level"] == "critical",
            "同sha的18:00/次日07:30均拒收升级critical且排序在前",
        )
        http_snapshots = response.text + json.dumps(page) + json.dumps(alerts)
        # 权限负例：真正低权限连接不读密文、不改批次归属、不允许DDL。
        for engine, sql in [
            (api, "SELECT ciphertext FROM app.user_data_licences"),
            (api, "CREATE TABLE market.forbidden_ddl(id int)"),
            (api, "DELETE FROM market.master_vendor_batches"),
            (ingest, "SELECT * FROM market.master_vendor_list_rows"),
            (ingest, "UPDATE market.master_vendor_batches SET source_licence_id=source_licence_id"),
            (ingest, "DELETE FROM market.master_vendor_list_rows"),
        ]:
            try:
                with engine.begin() as conn:
                    conn.execute(text(sql))
            except DBAPIError as exc:
                check(
                    getattr(exc.orig, "sqlstate", None) == "42501",
                    "实际aia_api/aia_ingest权限负例被数据库拒绝",
                )
            else:
                check(False, "权限负例意外放行")
        sid_user, _ = store.create(str(uid))
        http.cookies.set("sid", sid_user)
        check(
            http.get("/api/v1/admin/securities/reconciliation").status_code == 404,
            "真实非管理员会话访问管理接口404",
        )
        http.cookies.clear()
        check(http.get("/api/v1/admin/ingest/status").status_code == 404, "未登录管理接口404")
        with api.connect() as conn:
            public = json.dumps(
                [dict(x) for x in conn.execute(select(batch_table)).mappings()], default=str
            )
        queue = (
            repr(rds.xrange("ingest:requests"))
            + repr(rds.lrange(jobs.QUEUE_KEY, 0, -1))
            + repr(rds.zrange(jobs.DELAYED_KEY, 0, -1))
        )
        check(
            sentinel not in public + queue + logtext.getvalue() + http_snapshots,
            "哨兵证书值不进入批次、队列、日志或HTTP告警",
        )
        with api.connect() as conn:
            check(
                conn.execute(text("SELECT current_user")).scalar() == "aia_api",
                "真实worker/API连接为aia_api，不用属主运行",
            )
        with ingest.connect() as conn:
            check(
                conn.execute(text("SELECT current_user")).scalar() == "aia_ingest",
                "真实ingest交接以aia_ingest运行",
            )
        check(
            jobs.VENDOR_SWEEP in jobs.schedule(settings)
            and jobs.schedule(settings)[jobs.VENDOR_SWEEP] == 900,
            "beat每15分钟兜底已注册",
        )
        check(
            deadline_for(dt.datetime(2026, 11, 2, 10, tzinfo=dt.UTC), "beat_1800")
            == dt.datetime(2026, 11, 2, 23, 30, tzinfo=dt.UTC),
            "18:00批次截止次日07:30北京时间",
        )
        for started, expected in [
            (
                dt.datetime(2026, 11, 6, 11, tzinfo=dt.UTC),
                dt.datetime(2026, 11, 6, 23, 30, tzinfo=dt.UTC),
            ),
            (
                dt.datetime(2026, 11, 7, 0, tzinfo=dt.UTC),
                dt.datetime(2026, 11, 9, 10, tzinfo=dt.UTC),
            ),
            (
                dt.datetime(2026, 11, 8, 22, tzinfo=dt.UTC),
                dt.datetime(2026, 11, 9, 10, tzinfo=dt.UTC),
            ),
        ]:
            check(
                deadline_for(started, "manual") == expected,
                "手动对账截止时间与既有slot_jobs工作日/次日补拉排程一致",
            )
        clock[0] += dt.timedelta(days=15)
        check(
            jobs.purge_snapshots_task(settings) > 0, "真实purge_snapshots任务一并清理14天前批次行"
        )
        with api.connect() as conn:
            check(
                conn.execute(select(func.count()).select_from(list_rows)).scalar() == 0
                and conn.execute(select(func.count()).select_from(batch_table)).scalar() > 0,
                "仅清理规范化行，保留批次状态与差异审计",
            )
        http.close()
    finally:
        jobs._now, jobs._master_fetcher = original_clock, original_fetcher
        logging.getLogger().removeHandler(handler)
        for engine in [*jobs._engines.values(), owner, api, ingest]:
            engine.dispose()
        jobs._engines.clear()
        rds.flushdb()
        rds.close()
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE {dbname} WITH (FORCE)"))
        admin.dispose()
    print(f"{sum(results)} passed, {len(results) - sum(results)} failed")
    return int(not all(results))


if __name__ == "__main__":
    raise SystemExit(main())
