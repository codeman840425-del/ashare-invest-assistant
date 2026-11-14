"""beat → worker 的定时任务（T-B49）：beat 按间隔把任务放进 Redis 队列，worker 取出执行。

项目里没有 Celery；沿用 ``app.workers.runner.run(name, tick, interval_s)`` 的占位框架：

- **beat**（``python -m app.workers.beat``，单副本）每轮对 :func:`schedule` 里每个任务做
  ``SET beat:due:<task> <ts> NX EX <interval>``：设置成功（上一次排程已超过间隔，或首次启动）才
  ``LPUSH`` 一条任务到 :data:`QUEUE_KEY`。到期键放在 Redis 里，beat 重启不会立刻重排，
  也不会因多副本而重复排程。
- **worker**（``python -m app.workers.worker``）每轮最多取 :data:`MAX_JOBS_PER_TICK` 条
  （``RPOP``，先进先出）并执行；未知任务名只记日志后丢弃。任务执行失败只记异常类型，不重试
  （下一次排程会再跑；清理类任务幂等）。
- 队列元素是 JSON ``{"task": <名称>, "enqueued_at": <unix 秒>}``，不含任何用户数据或密钥。

当前任务：

- ``licences.purge_expired_cooldowns``：调用 :func:`app.licences.service.purge_expired_cooldowns`
  删除已到期的证书冷却记录（review-a8e055b M1；取代 deploy 的 cooldown-purge 服务）。间隔
  ``Settings.cooldown_purge_interval_s``（``COOLDOWN_PURGE_INTERVAL_S``，默认 3600，最小 60）。
- ``imports.purge_preview_rows``（T-B56；9e693b2 时名为 ``imports.purge_uncommitted_rows``）：调用
  :func:`app.importing.pipeline.purge_uncommitted_import_rows` 删除 discarded / failed 批次残留的
  预览行（架构师裁定，T-live-83a031c §8）；每条 DELETE ≤ 10 000 行、每块单独提交，每轮最多
  100 块。间隔 ``Settings.import_rows_purge_interval_s``
  （``IMPORT_ROWS_PURGE_INTERVAL_S``，默认 3600，最小 60）。
- ``imports.purge_expired_raw_files``：调用 :func:`app.importing.pipeline.purge_expired_raw_files`
  删除 ``retained_until`` 已到期的加密原始导入文件（评审 bbf58a0 m6，plan §3.5A）。间隔
  ``Settings.import_raw_purge_interval_s``（``IMPORT_RAW_PURGE_INTERVAL_S``，默认 86400，最小 60）。
  删除失败的行保留（``deleted_at`` 仍为空）下一轮重试；worker 以 aia_api 运行，无
  ``ops.pending_file_purges`` 权限（T-B03f m2），故不写该表。
  worker 须挂载与 api 相同的 ``IMPORT_STORAGE_PATH`` 卷。

证券主数据（T-B52，plan 4.6）按**北京时间钟点**排程（:func:`beat_slots`，beat 每轮调用；同一钟点用
``SET beat:slot:<task>:<日期>:<HHMM> NX EX 2d`` 去重，钟点后 15 分钟内有效）：

- T-A22：``master.mairui_risk_snapshot`` 仅交易日北京时间 18:00 排一次；
  T-B90：可信运维授权回执 → DB outbox → ingest 三名单 → apply/PIT；
  缺回执无采集，部署/首次实采仍须核实本人授权。
  旧交易所直拉/07:30 补拉/月度代码表不再由 beat 排程，手动旧抓取同样安全拒绝。


旧主数据任务带 ``args``（``{"trigger": ...}``）与 ``attempt``；执行时持 Redis 锁；失败
时第 1、2 次进 ``jobs:delayed``（10 分钟后由 beat 放回队列），第 3 次仍失败则写一条
``master_runs.status='failed'``。``master.sync_exchange_lists`` 由 beat 触发且成功时，若
``master.reconcile_vendor`` 已注册（T-B53）则接着排它；首次导入（CLI）从不触发。
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any, Final, Self

import redis
from redis.typing import EncodableT
from sqlalchemy import Engine, select

from app.config import Settings
from app.db.engine import engine_for
from app.feedback.worker import TASK as RC5_EXPIRY
from app.feedback.worker import task as rc5_expiry_task
from app.intraday.engine import TASK as INTRADAY_UPDATED
from app.intraday.engine import task as intraday_updated_task
from app.marketdata.daily_bars import DAILY_BARS_FETCH, daily_bars_fetch_task
from app.master.mairui_snapshot import TASK as MAIRUI_SNAPSHOT
from app.plans.worker import TASK as PLAN_CONDITIONS
from app.plans.worker import task as plan_conditions_task
from app.risk.worker import TASK as RC1_CHECKS
from app.risk.worker import task as rc1_checks_task
from app.tracking.worker import TASK as TRACKING
from app.tracking.worker import tracking_task
from app.workers.daily import (
    ANALYZE,
    RECOVER,
    REPORT,
    analysis_task,
    final_failure,
    record_intent,
    recover_task,
    report_task,
)

log = logging.getLogger("app.workers.jobs")

QUEUE_KEY: Final = "jobs:worker"
DUE_PREFIX: Final = "beat:due:"
MAX_JOBS_PER_TICK: Final = 20
#: beat / worker 的轮询间隔（秒）；任务真正的间隔由 SCHEDULE 决定
TICK_S: Final = 15

PURGE_COOLDOWNS: Final = "licences.purge_expired_cooldowns"
#: 任务名按 plan T-B56（契约 #35）；9e693b2 时名为 imports.purge_uncommitted_rows
PURGE_IMPORT_ROWS: Final = "imports.purge_preview_rows"
PURGE_RAW_FILES: Final = "imports.purge_expired_raw_files"

Task = Callable[..., int]  # (settings, **args) -> 处理条数

DELAYED_KEY: Final = "jobs:delayed"
SLOT_PREFIX: Final = "beat:slot:"
LOCK_PREFIX: Final = "lock:"
#: 钟点任务的触发窗口（秒）与去重键寿命
SLOT_WINDOW_S: Final = 15 * 60
SLOT_TTL_S: Final = 2 * 86400
MAX_ATTEMPTS: Final = 3
RETRY_DELAY_S: Final = 600
LOCK_TTL_S: Final = 3600

SYNC_LISTS: Final = "master.sync_exchange_lists"
SYNC_CODE_MAP: Final = "master.sync_bse_code_map"
PURGE_SNAPSHOTS: Final = "master.purge_snapshots"
RECONCILE_VENDOR: Final = "master.reconcile_vendor"
RECONCILE_VENDOR_APPLY: Final = "master.reconcile_vendor_apply"
VENDOR_SWEEP: Final = "master.vendor_batches_sweep"
CODE_MAP_TIME: Final = "18:30"
DAILY_BARS_FETCH_TIME: Final = "17:15"
PURGE_SNAPSHOTS_TIME: Final = "03:30"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class MasterCount(int):
    run_id: int

    def __new__(cls, count: int, run_id: int) -> Self:
        obj = super().__new__(cls, count)
        obj.run_id = run_id
        return obj


def _redis(settings: Settings) -> redis.Redis:
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL 未设置")
    t = settings.health_check_timeout_s
    return redis.Redis.from_url(settings.redis_url, socket_connect_timeout=t, socket_timeout=t)


_engines: dict[str, Engine] = {}


def _engine(settings: Settings) -> Engine:
    if settings.database_url is None:
        raise RuntimeError("DATABASE_URL 未设置")
    url = settings.database_url.get_secret_value()
    eng = _engines.get(url)
    if eng is None:
        eng = _engines[url] = engine_for(url)
    return eng


def purge_expired_cooldowns_task(settings: Settings) -> int:
    from app.licences.service import purge_expired_cooldowns

    with _engine(settings).begin() as conn:
        return purge_expired_cooldowns(conn)


#: 预览行清理每轮最多处理的块数（每块 ≤ 10 000 行、单独提交；剩余的下一轮继续）
PURGE_IMPORT_ROWS_MAX_CHUNKS: Final = 100


def purge_import_rows_task(settings: Settings) -> int:
    from app.importing.pipeline import PREVIEW_PURGE_CHUNK, purge_uncommitted_import_rows

    total = 0
    for _ in range(PURGE_IMPORT_ROWS_MAX_CHUNKS):
        with _engine(settings).begin() as conn:
            n = purge_uncommitted_import_rows(conn, chunk=PREVIEW_PURGE_CHUNK)
        total += n
        if n < PREVIEW_PURGE_CHUNK:
            break
    return total


def purge_raw_files_task(settings: Settings) -> int:
    from app.importing.pipeline import purge_expired_raw_files

    with _engine(settings).begin() as conn:
        return purge_expired_raw_files(conn, settings)


# ---------------------------------------------------------------------------
# 证券主数据（T-B52）
# ---------------------------------------------------------------------------


class MasterSyncFailedError(RuntimeError):
    """本次运行所有来源都失败（``master_runs`` 已记 failed）。"""


def _master_fetcher() -> Any:  # noqa: ANN401  selfcheck 替换为假实现
    from app.master.public_sources import PublicSourceGapError

    raise PublicSourceGapError("official_public_download_not_verified")


def _master_root(settings: Settings) -> Any:  # noqa: ANN401
    from app.master.sync import resolve_master_root

    root = resolve_master_root(settings.master_snapshot_path, settings.app_env)
    if root is None:
        raise RuntimeError("MASTER_SNAPSHOT_PATH 未设置")
    return root


def _master_run(settings: Settings, trigger: str, sources: list[str] | None) -> int:
    from app.master import sync
    from app.master.sources import DAILY_SOURCES

    cfg = settings.business.securities.master
    root = _master_root(settings)
    now = _now()
    td = sync.snapshot_trade_date(now)
    eng = _engine(settings)
    if sources is None:
        sources = list(DAILY_SOURCES)
        if trigger == "beat_0730":
            with eng.connect() as c:
                sources = sync.sources_to_retry(c, td)
            if not sources:
                log.info("master 补拉：上一交易日所有来源均已成功")
                return 0
    fetched = sync.collect(_master_fetcher(), sources)  # 外网抓取放在事务外
    with eng.begin() as conn:
        res = sync.apply_run(
            conn, fetched, cfg, trigger=trigger, trade_date=td, now=now, raw_root=root
        )
    if res.status == "failed":
        raise MasterSyncFailedError(res.status)
    return MasterCount(len(res.snaps), res.run_id)


def mairui_snapshot_task(settings: Settings, trade_date: str) -> int:
    from app.master.sync import BEIJING

    now = _now()
    day = dt.date.fromisoformat(trade_date)
    if now.astimezone(BEIJING).date() != day:
        raise ValueError("snapshot_slot_expired")
    from app.master.daily_delivery import publish_pending, read_grant, request

    grant = read_grant()
    if grant is None:
        log.warning("mairui daily authorization unavailable; no ingest request")
        return 0
    with _engine(settings).begin() as conn:
        bid = request(conn, grant, now)
    rds = _redis(settings)
    try:
        publish_pending(_engine(settings), rds)
    finally:
        rds.close()
    return int(bid is not None)


def mairui_daily_sweep(settings: Settings) -> int:
    from app.master.daily_delivery import publish_pending

    rds = _redis(settings)
    try:
        return publish_pending(_engine(settings), rds)
    finally:
        rds.close()


def mairui_daily_apply(settings: Settings, batch_id: str) -> int:
    import uuid

    from app.master.daily_delivery import apply_batch

    with _engine(settings).begin() as conn:
        return apply_batch(
            conn,
            uuid.UUID(batch_id),
            now=_now(),
            cfg=settings.business.securities.master,
            root=_master_root(settings),
        )


def sync_exchange_lists_task(settings: Settings, trigger: str = "manual") -> int:
    return _master_run(settings, trigger, None)


def sync_bse_code_map_task(settings: Settings, trigger: str = "manual") -> int:
    return _master_run(settings, trigger, ["bse_code_map"])


def purge_snapshots_task(settings: Settings) -> int:
    from app.master.sync import purge_snapshots

    with _engine(settings).begin() as conn:
        from app.master.vendor import purge_batch_rows

        return purge_snapshots(conn, _master_root(settings)) + purge_batch_rows(conn, now=_now())


def _record_master_failure(settings: Settings, args: dict[str, Any], exc: BaseException) -> None:
    if isinstance(exc, MasterSyncFailedError):
        return  # apply_run 已写 failed
    from app.master.sync import record_failed_run, snapshot_trade_date

    td = snapshot_trade_date(dt.datetime.now(dt.UTC))
    with _engine(settings).begin() as conn:
        record_failed_run(conn, str(args.get("trigger", "manual")), td, type(exc).__name__)


def reconcile_vendor_task(
    settings: Settings, trigger: str = "manual", master_run_id: int | None = None
) -> int:
    from app.master.vendor import request_batches

    # 先提交 requested，再投递。投递中断由既有任务重试重新发布同一 requested id。
    with _engine(settings).begin() as conn:
        run_id, intents, pending = request_batches(
            conn, master_run_id=master_run_id, trigger=trigger, now=_now()
        )
    rds = _redis(settings)
    try:
        for intent in intents:
            fields: dict[EncodableT, EncodableT] = {}
            for key, value in intent.items():
                fields[key] = value
            rds.xadd("ingest:requests", fields)
        if pending:
            body = {
                "task": RECONCILE_VENDOR,
                "args": {"trigger": trigger, "master_run_id": run_id},
                "attempt": 1,
            }
            rds.zadd(
                DELAYED_KEY, {json.dumps(body, sort_keys=True): _now().timestamp() + RETRY_DELAY_S}
            )
    finally:
        rds.close()
    return len(intents)


def reconcile_vendor_apply_task(settings: Settings, batch_id: str) -> int:
    from app.master.vendor import apply_batch

    with _engine(settings).begin() as conn:
        result = apply_batch(
            conn,
            uuid.UUID(batch_id),
            now=_now(),
            stale_alert_days=settings.business.securities.master.vendor_stale_alert_days,
        )
    return int(result == "reconciled")


def vendor_sweep_task(settings: Settings) -> int:
    from app.master.vendor import sweep_batches

    with _engine(settings).begin() as conn:
        batches = sweep_batches(conn, now=_now())
    rds = _redis(settings)
    try:
        for bid in batches:
            _push(rds, RECONCILE_VENDOR_APPLY, {"batch_id": str(bid)})
    finally:
        rds.close()
    return len(batches)


def plan_conditions_sweep_task(settings: Settings) -> int:
    from app.db.tables.research import action_plans
    from app.db.tables.users import users
    from app.plans.worker import task

    with _engine(settings).connect() as conn:
        owners = (
            conn.execute(
                select(action_plans.c.user_id)
                .join(users, users.c.id == action_plans.c.user_id)
                .where(
                    action_plans.c.status.in_(["active", "triggered"]), users.c.status == "approved"
                )
                .distinct()
            )
            .scalars()
            .all()
        )
    return sum(task(settings, str(owner), as_of=_now().isoformat()) for owner in owners)


#: 任务名 → 实现
TASKS: Final[dict[str, Task]] = {
    INTRADAY_UPDATED: intraday_updated_task,
    PLAN_CONDITIONS: plan_conditions_task,
    "plans.conditions_sweep": plan_conditions_sweep_task,
    RC1_CHECKS: rc1_checks_task,
    RC5_EXPIRY: rc5_expiry_task,
    TRACKING: tracking_task,
    "master.mairui_daily_sweep": mairui_daily_sweep,
    "master.mairui_daily_apply": mairui_daily_apply,
    MAIRUI_SNAPSHOT: mairui_snapshot_task,
    ANALYZE: analysis_task,
    REPORT: report_task,
    RECOVER: recover_task,
    PURGE_COOLDOWNS: purge_expired_cooldowns_task,
    PURGE_IMPORT_ROWS: purge_import_rows_task,
    PURGE_RAW_FILES: purge_raw_files_task,
    SYNC_LISTS: sync_exchange_lists_task,
    SYNC_CODE_MAP: sync_bse_code_map_task,
    PURGE_SNAPSHOTS: purge_snapshots_task,
    RECONCILE_VENDOR: reconcile_vendor_task,
    RECONCILE_VENDOR_APPLY: reconcile_vendor_apply_task,
    VENDOR_SWEEP: vendor_sweep_task,
    DAILY_BARS_FETCH: daily_bars_fetch_task,
}
#: 失败重试（10 分钟后，共 3 次）且执行时持锁的任务 → 重试用尽时的处理
RETRY_TASKS: Final[dict[str, Callable[[Settings, dict[str, Any], BaseException], None]]] = {
    ANALYZE: final_failure,
    REPORT: final_failure,
    SYNC_LISTS: _record_master_failure,
    SYNC_CODE_MAP: _record_master_failure,
    RECONCILE_VENDOR: _record_master_failure,
    RECONCILE_VENDOR_APPLY: _record_master_failure,
    VENDOR_SWEEP: _record_master_failure,
}
LOCKED_TASKS: Final = frozenset(
    {
        MAIRUI_SNAPSHOT,
        TRACKING,
        ANALYZE,
        REPORT,
        RECOVER,
        SYNC_LISTS,
        SYNC_CODE_MAP,
        PURGE_SNAPSHOTS,
        RECONCILE_VENDOR,
        VENDOR_SWEEP,
        DAILY_BARS_FETCH,
    }
)


def schedule(settings: Settings) -> dict[str, int]:
    """任务名 → 间隔秒数（beat 排程表；间隔来自配置）。"""
    return {
        RC1_CHECKS: settings.business.realtime.intervals.quote_interval_s,
        RC5_EXPIRY: settings.business.realtime.intervals.quote_interval_s,
        "plans.conditions_sweep": settings.business.realtime.intervals.quote_interval_s,
        "master.mairui_daily_sweep": 60,
        PURGE_COOLDOWNS: settings.cooldown_purge_interval_s,
        PURGE_IMPORT_ROWS: settings.import_rows_purge_interval_s,
        PURGE_RAW_FILES: settings.import_raw_purge_interval_s,
        VENDOR_SWEEP: 900,
        RECOVER: 300,
    }


def beat_tick(settings: Settings, client: redis.Redis | None = None) -> list[str]:
    """排程到期的任务，返回本轮放进队列的任务名。"""
    r = client or _redis(settings)
    now = int(time.time())
    queued: list[str] = []
    try:
        for task, interval in schedule(settings).items():
            if r.set(DUE_PREFIX + task, now, nx=True, ex=interval):
                r.lpush(QUEUE_KEY, json.dumps({"task": task, "enqueued_at": now}))
                queued.append(task)
                log.info("beat 排程 %s（间隔 %ss）", task, interval)
    finally:
        if client is None:
            r.close()
    return queued


def _hhmm(v: str) -> dt.time:
    h, m = v.split(":")
    return dt.time(int(h), int(m))


def _first_weekday_of_month(d: dt.date) -> bool:
    first = d.replace(day=1)
    while first.weekday() >= 5:
        first += dt.timedelta(days=1)
    return d == first


def slot_jobs(settings: Settings, now: dt.datetime) -> list[tuple[str, str, dict[str, Any]]]:
    """当前北京时间落在哪些钟点窗口：``[(任务名, HHMM, args)]``。"""
    from app.master.sync import BEIJING

    bj = now.astimezone(BEIJING)
    # T-A22 supersedes legacy direct official pulls (including 07:30 retry).
    plan: list[tuple[str, str, dict[str, Any], bool]] = [
        (PURGE_SNAPSHOTS, PURGE_SNAPSHOTS_TIME, {}, True),
    ]
    start1715 = dt.datetime.combine(bj.date(), _hhmm(DAILY_BARS_FETCH_TIME), BEIJING)
    if start1715 <= bj < start1715 + dt.timedelta(seconds=SLOT_WINDOW_S):
        from app.reports.service import covered

        with _engine(settings).connect() as conn:
            is_open = covered(conn, bj.date())
        plan.append(
            (DAILY_BARS_FETCH, DAILY_BARS_FETCH_TIME, {"trade_date": str(bj.date())}, is_open)
        )
    start1800 = dt.datetime.combine(bj.date(), dt.time(18), BEIJING)
    if start1800 <= bj < start1800 + dt.timedelta(seconds=SLOT_WINDOW_S):
        from app.reports.service import covered

        with _engine(settings).connect() as conn:
            is_open = covered(conn, bj.date())
        plan.append((MAIRUI_SNAPSHOT, "18:00", {"trade_date": str(bj.date())}, is_open))
    if any(
        dt.datetime.combine(bj.date(), _hhmm(h), BEIJING)
        <= bj
        < dt.datetime.combine(bj.date(), _hhmm(h), BEIJING) + dt.timedelta(seconds=SLOT_WINDOW_S)
        for h in ("17:30",)
    ):
        from app.reports.service import covered

        with _engine(settings).connect() as conn:
            is_open = covered(conn, bj.date())
        plan.extend(
            [
                (ANALYZE, "17:30", {"trade_date": str(bj.date())}, is_open),
                (REPORT, "17:30", {"trade_date": str(bj.date())}, is_open),
            ]
        )
    out = []
    for task, hhmm, args, on_day in plan:
        start = dt.datetime.combine(bj.date(), _hhmm(hhmm), BEIJING)
        if on_day and start <= bj < start + dt.timedelta(seconds=SLOT_WINDOW_S):
            out.append((task, f"{bj.date():%Y%m%d}:{hhmm.replace(':', '')}", args))
    return out


def _push(r: redis.Redis, task: str, args: dict[str, Any] | None = None, attempt: int = 1) -> None:
    body: dict[str, Any] = {"task": task, "enqueued_at": int(time.time())}
    if args:
        body["args"] = args
    if attempt > 1:
        body["attempt"] = attempt
    r.lpush(QUEUE_KEY, json.dumps(body, sort_keys=True))


def beat_slots(
    settings: Settings, client: redis.Redis | None = None, now: dt.datetime | None = None
) -> list[str]:
    """钟点任务（北京时间）与到期的重试；返回本轮放进队列的任务名。"""
    r = client or _redis(settings)
    now = now or dt.datetime.now(dt.UTC)
    queued: list[str] = []
    try:
        slots = slot_jobs(settings, now)
        # §9.1：两份恢复意图均先持久化，REPORT 只由 analyze 完成后推送。
        for task, _, args in slots:
            if task in {ANALYZE, REPORT}:
                record_intent(settings, task, str(args["trade_date"]))
        for task, slot, args in slots:
            if task == REPORT:
                continue
            if task == MAIRUI_SNAPSHOT:
                from app.master.daily_delivery import read_grant, request

                grant = read_grant()
                if grant is None:
                    continue
                # Durable intent BEFORE the Redis slot flag: a beat crash after
                # SET NX but before LPUSH cannot lose this day's delivery.
                with _engine(settings).begin() as conn:
                    if request(conn, grant, now) is None:
                        continue
            if r.set(f"{SLOT_PREFIX}{task}:{slot}", 1, nx=True, ex=SLOT_TTL_S):
                _push(r, task, args)
                queued.append(task)
                log.info("beat 钟点排程 %s %s", task, slot)
        due: list[bytes] = r.zrangebyscore(DELAYED_KEY, 0, now.timestamp())  # type: ignore[assignment]
        for raw in due:
            if r.zrem(DELAYED_KEY, raw):  # 多副本时只有一个能移走
                r.lpush(QUEUE_KEY, raw)
                queued.append(str(json.loads(raw).get("task", "")))
    finally:
        if client is None:
            r.close()
    return queued


def worker_tick(settings: Settings, client: redis.Redis | None = None) -> list[tuple[str, str]]:
    """执行队列里的任务，返回 ``[(任务名, ok / failed / unknown / bad_payload)]``。"""
    r = client or _redis(settings)
    done: list[tuple[str, str]] = []
    try:
        for _ in range(MAX_JOBS_PER_TICK):
            raw = r.rpop(QUEUE_KEY)
            if raw is None:
                break
            try:
                body = json.loads(raw)  # type: ignore[arg-type]
                task = str(body["task"])
                args = dict(body.get("args") or {})
                attempt = int(body.get("attempt", 1))
            except (ValueError, KeyError, TypeError, AttributeError):
                log.warning("worker 丢弃无法解析的任务")
                done.append(("", "bad_payload"))
                continue
            fn = TASKS.get(task)
            if fn is None:
                log.warning("worker 丢弃未知任务 %s", task[:64])
                done.append((task[:64], "unknown"))
                continue
            lock = f"{LOCK_PREFIX}{task}"
            token = uuid.uuid4().hex
            if task in LOCKED_TASKS and not r.set(lock, token, nx=True, ex=LOCK_TTL_S):
                log.info("worker 任务 %s 正在别处运行，跳过", task)
                done.append((task, "locked"))
                continue
            try:
                n = fn(settings, **args)
                if task == DAILY_BARS_FETCH:
                    from app.ingest.daily_bars_schedule import delay, delayed_until

                    stamp = dt.datetime.now(dt.UTC)
                    with _engine(settings).connect() as conn:
                        until = delayed_until(
                            conn, stamp, args.get("batch_kind", "daily"),
                            args.get("window_trading_days"),
                        )
                    if until is not None:
                        delay(r, args, until)
                        done.append((task, "delayed"))
                        continue
            except Exception as exc:  # noqa: BLE001  只记类型，不输出连接串或参数
                log.warning("worker 任务 %s 失败：%s", task, type(exc).__name__)
                done.append((task, "failed"))
                _after_failure(settings, r, task, args, attempt, exc)
                if task == ANALYZE:
                    _push(r, REPORT, {k: args[k] for k in ("trade_date", "user_id") if k in args})
                continue
            finally:
                if task in LOCKED_TASKS and r.get(lock) == token.encode():
                    r.delete(lock)
            log.info("worker 任务 %s 完成：%s", task, n)
            done.append((task, "ok"))
            if task == ANALYZE:
                _push(r, REPORT, {k: args[k] for k in ("trade_date", "user_id") if k in args})
                _push(r, TRACKING, {"user_id": args.get("user_id")})
            if task == SYNC_LISTS and RECONCILE_VENDOR in TASKS:
                # T-B53；首次导入（CLI）从不走这里
                _push(
                    r,
                    RECONCILE_VENDOR,
                    {"trigger": args.get("trigger", "manual"), "master_run_id": n.run_id}
                    if isinstance(n, MasterCount)
                    else {"trigger": args.get("trigger", "manual")},
                )
    finally:
        if client is None:
            r.close()
    return done


def _after_failure(
    settings: Settings,
    r: redis.Redis,
    task: str,
    args: dict[str, Any],
    attempt: int,
    exc: BaseException,
) -> None:
    final = RETRY_TASKS.get(task)
    if final is None:
        return
    if attempt < MAX_ATTEMPTS:
        body = {"task": task, "args": args, "attempt": attempt + 1, "enqueued_at": int(time.time())}
        r.zadd(DELAYED_KEY, {json.dumps(body, sort_keys=True): time.time() + RETRY_DELAY_S})
        log.info("worker 任务 %s 第 %s 次失败，%ss 后重试", task, attempt, RETRY_DELAY_S)
        return
    try:
        final(settings, args, exc)
    except Exception as e2:  # noqa: BLE001
        log.warning("worker 任务 %s 记录失败运行出错：%s", task, type(e2).__name__)
