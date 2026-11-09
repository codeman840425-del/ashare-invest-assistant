"""T-R28/T-R31：W-01 数据就绪检测（离线逻辑 + 隔离库只读；不触发门禁、不写库）。

检测 f.main_net_20d（F21）在行情库的覆盖状态，达到锁定阈值时输出
「W-01 可重跑门禁」信号与建议派单文案。纯只读：只 SELECT，不调用
G1–G7、不改生命周期、不发任何请求、不写任何表。

T-R31：阈值写死于 docs/strategies/T-R28/f21_ready_thresholds.json，
启动时校验同目录 .sha256；拒绝 CLI/环境变量覆盖。F21 保持 declared。

口径背景（全部来自仓库既有权威，不新创设）：
- F21 当前 status=declared；本脚本不升级。
- 阈值语义：T-A19 F21 项覆盖规模（5 只股 × 最近 20 交易日有效记录 ≥15 日）。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
THRESHOLDS_PATH = HERE / "T-R28" / "f21_ready_thresholds.json"
THRESHOLDS_HASH_PATH = HERE / "T-R28" / "f21_ready_thresholds.sha256"
SCHEMA = "market"

# Env keys that must NOT override thresholds (presence → hard fail).
FORBIDDEN_ENV = (
    "F21_READY_MIN_STOCKS",
    "F21_READY_MIN_DAYS",
    "F21_READY_WINDOW_DAYS",
    "F21_READY_FACTOR_ID",
    "F21_READY_THRESHOLDS_JSON",
)


def _canonical_thresholds_bytes(raw: dict) -> bytes:
    return json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def load_locked_thresholds() -> dict:
    if not THRESHOLDS_PATH.is_file() or not THRESHOLDS_HASH_PATH.is_file():
        raise SystemExit("missing locked thresholds file or sha256 sidecar")
    raw = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))
    expected = THRESHOLDS_HASH_PATH.read_text(encoding="utf-8").strip().split()[0]
    got = hashlib.sha256(_canonical_thresholds_bytes(raw)).hexdigest()
    if got != expected:
        raise SystemExit(f"thresholds hash mismatch: got={got} expected={expected}")
    required = {"factor_id", "feature_key", "min_stocks", "min_days", "window_days"}
    if not required <= set(raw):
        raise SystemExit(f"thresholds missing keys: {required - set(raw)}")
    return raw


def reject_override_attempts(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    banned_flags = (
        "--min-stocks",
        "--min-days",
        "--window-days",
        "--factor-id",
        "--thresholds",
        "--thresholds-json",
    )
    for a in argv:
        key = a.split("=", 1)[0]
        if key in banned_flags:
            raise SystemExit(f"threshold override rejected: {key}")
    for k in FORBIDDEN_ENV:
        if os.environ.get(k):
            raise SystemExit(f"threshold override rejected via env: {k}")


def decide_ready(feature_bars: dict, thresholds: dict) -> bool:
    """Pure readiness predicate; feature_bars from scan_feature_bars."""
    return int(feature_bars["stocks_with_min_days"]) >= int(thresholds["min_stocks"])


def _dbi() -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("DATABASE_URL 未设置；本脚本只读、不写，但需要目标库（通常是隔离库）。")
    return dsn


def _conn():
    dsn = _dbi()
    import sqlalchemy

    return sqlalchemy.create_engine(dsn).connect()


def _calendar_open_days(conn, window: int) -> list[str]:
    try:
        rows = conn.execute(
            f'select "date" from {SCHEMA}.trading_calendar where is_open '
            'order by "date" desc limit %s',
            (window,),
        ).fetchall()
        if rows:
            return [str(r[0]) for r in rows]
    except Exception:  # noqa: BLE001
        pass
    today = date.today()
    return [str(today - timedelta(days=i)) for i in range(window)]


def scan_factor_values(conn, factor_id: str, days: list[str], min_days: int):
    rows = conn.execute(
        f"select code, count(*) as n from {SCHEMA}.factor_values "
        "where factor_id = %s and trade_date >= %s and value is not null "
        "group by code",
        (factor_id, days[-1]),
    ).fetchall()
    total = [dict(code=r[0], days=r[1]) for r in rows]
    qualified = [d for d in total if d["days"] >= min_days]
    return {
        "factor_id": factor_id,
        "distinct_stocks": len(total),
        "stocks_with_min_days": len(qualified),
        "rows": total,
    }


def scan_feature_bars(conn, feature_key: str, days: list[str], min_days: int):
    rows = conn.execute(
        f"select code, count(*) as n from {SCHEMA}.feature_bars_daily "
        "where trade_date >= %s "
        f"and values ? %s "
        "group by code",
        (days[-1], feature_key),
    ).fetchall()
    total = [dict(code=r[0], days=r[1]) for r in rows]
    qualified = [d for d in total if d["days"] >= min_days]
    return {
        "feature_key": feature_key,
        "distinct_stocks": len(total),
        "stocks_with_min_days": len(qualified),
        "rows": total,
    }


def build_report(thresholds: dict, days: list[str], fv: dict, fb: dict) -> dict:
    ready = decide_ready(fb, thresholds)
    out = {
        "task": "T-R28",
        "signal": "ready" if ready else "not_ready",
        "f21_status": "declared",
        "thresholds": {
            "min_stocks": thresholds["min_stocks"],
            "min_days": thresholds["min_days"],
            "window_days": thresholds["window_days"],
            "factor_id": thresholds["factor_id"],
            "feature_key": thresholds["feature_key"],
            "locked": True,
        },
        "window": {"first": days[-1], "last": days[0]},
        "f21_derived_feature_bars": fb,
        "mairui_builtin_factor_values": fv,
    }
    if ready:
        out["suggested_dispatch"] = (
            "W-01 v2 的 f.main_net_20d 覆盖已达锁定阈值（feature_bars_daily）。"
            "建议派单：后端对 W-01 v2 重跑 G1–G6（不改变 F21 declared），报架构师确认后再议 verified_doc。"
        )
    else:
        out["suggested_dispatch"] = (
            f"F21 派生覆盖不足（feature_bars_daily {fb['stocks_with_min_days']}/"
            f"{thresholds['min_stocks']} 只达标），W-01 暂不可重跑门禁。F21 保持 declared。"
        )
    return out


def main() -> int:
    reject_override_attempts()
    thresholds = load_locked_thresholds()
    conn = _conn()
    try:
        days = _calendar_open_days(conn, int(thresholds["window_days"]))
        fv = scan_factor_values(
            conn, thresholds["factor_id"], days, int(thresholds["min_days"])
        )
        fb = scan_feature_bars(
            conn, thresholds["feature_key"], days, int(thresholds["min_days"])
        )
    finally:
        conn.close()
    print(json.dumps(build_report(thresholds, days, fv, fb), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
