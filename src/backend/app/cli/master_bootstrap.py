"""证券主数据首次导入：``python -m app.cli.master_bootstrap``（plan 4.6.5，T-B52）。

拉三所当前名单、终止上市名单、深交所简称变更表与北交所代码对照，写 ``master_runs``
（``trigger='bootstrap'``）并合并。与每日同步的区别：

- 不做"行数比上一份成功快照少 N%"校验（首次没有基线）；其余整份拒收规则照常；
- 深交所简称历史强制按变更表重建；
- **不触发 vendor 对账（reconcile_vendor），也不排任何 worker 任务**（运维补充 ①）。

以 worker 同一数据库角色运行（``DATABASE_URL``）；原始快照写 ``MASTER_SNAPSHOT_PATH``。
输出只有来源、状态、行数与 sha256 前缀。
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections.abc import Sequence

from sqlalchemy import Connection

from app.config import Settings, get_settings
from app.db.engine import engine_for
from app.master import sync
from app.master.sources import DAILY_SOURCES, Fetcher, http_fetcher

BOOTSTRAP_SOURCES: tuple[str, ...] = (*DAILY_SOURCES, "bse_code_map")


def run(
    conn: Connection,
    settings: Settings,
    fetcher: Fetcher,
    *,
    sources: Sequence[str] = BOOTSTRAP_SOURCES,
    now: dt.datetime | None = None,
) -> sync.RunResult:
    now = now or dt.datetime.now(dt.UTC)
    root = sync.resolve_master_root(settings.master_snapshot_path, settings.app_env)
    if root is None:
        raise RuntimeError("MASTER_SNAPSHOT_PATH 未设置")
    fetched = sync.collect(fetcher, sources)
    return sync.apply_run(
        conn,
        fetched,
        settings.business.securities.master,
        trigger="bootstrap",
        trade_date=sync.snapshot_trade_date(now),
        now=now,
        raw_root=root,
        force_rebuild=True,
    )


def main(argv: list[str] | None = None, *, fetcher: Fetcher | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.cli.master_bootstrap")
    ap.add_argument(
        "--sources",
        default=",".join(BOOTSTRAP_SOURCES),
        help="逗号分隔的来源（默认全部）",
    )
    args = ap.parse_args(argv)
    sources = [s for s in args.sources.split(",") if s]
    unknown = [s for s in sources if s not in BOOTSTRAP_SOURCES]
    if unknown:
        print(f"未知来源：{','.join(unknown)}", file=sys.stderr)
        return 2
    settings = get_settings()
    if settings.database_url is None:
        print("DATABASE_URL 未设置", file=sys.stderr)
        return 2
    engine = engine_for(settings.database_url.get_secret_value())
    try:
        with engine.begin() as conn:
            res = run(conn, settings, fetcher or http_fetcher(), sources=sources)
    finally:
        engine.dispose()
    for s in res.snaps.values():
        sha = (s.sha256 or "")[:16]
        print(f"{s.source}\t{s.status}\t{s.reason or ''}\trows={s.row_count}\tsha256={sha}")
    print(f"run={res.run_id} status={res.status}")
    return 0 if res.status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
