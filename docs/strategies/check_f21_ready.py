"""T-R28：W-01 数据就绪检测（离线、只读，不触发门禁、不写库）。

检测 f.main_net_20d（F21）在行情库的覆盖状态，达到阈值时输出
「W-01 可重跑门禁」信号与建议派单文案。纯只读：只 SELECT，不调用
G1–G7、不改生命周期、不发任何请求、不写任何表。

口径背景（全部来自仓库既有权威，不新创设）：
- F21 当前 status=declared（source_reviews.DECLARED_KEYS）；W-01 v2 的 G2 因它是
  declared 而不通过（plan「T-A14 裁定」③、T-R20 ②）：W-01 data_needs 里
  f.main_net_20d 是 counter，缺失按 dimension_unknown，但 declared 状态使 G2 不 pass。
- F21 是四字段资金流派生（T-R19 ②）：zmbtdcje+zmbddcje−zmstdcje−zmsddcje（买正卖负），
  麦蕊内置因子 factor_id='main_20d_net' 与 F21 不等价（T-B81：12807880 vs 1499643492）。
- 数据就绪的 G2 语义（研究员按 T-R19/T-B81/T-A19 推导，非新裁定，可参数覆盖）：
  T-B81 已有 688018/300364 两股 × 约 20 日四字段证据 → 只够样本级；T-A19 F21 项
  （5 只股 × d 15:40 后 / d+1 开盘前两针对比）才是 verified 门槛的覆盖规模。
  因此默认阈值 = 至少 5 只不同股票、每只在最近 20 个交易日内有效资金流记录 ≥ 15 日。

两张落库点都要看（脚本分别报告，不互相替代）：
1. factor_values：派单指定表；factor_id 默认 'main_20d_net'（麦蕊内置因子，
   只作对照，不等于 F21 派生值）。
2. feature_bars_daily：F21 特征真正被 W-01 消费的落点（唯一特征管线产出，
   values JSONB 里的 'f.main_net_20d' 键）。

用法（在仓库根目录，只读）:
  python docs/strategies/check_f21_ready.py            # 打印 JSON 结果
  python docs/strategies/check_f21_ready.py --factor-id main_20d_net --min-stocks 5 \
      --min-days 15 --window-days 20

不自动触发门禁；本脚本出口码 0=脚本正常跑完（与"是否就绪"无关，就绪与否看 JSON 字段
  signal == "ready"）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

# 默认阈值：语义见模块 docstring，均为研究员推导、可参数覆盖。
DEFAULTS = {
    "factor_id": "main_20d_net",
    "min_stocks": 5,
    "min_days": 15,
    "window_days": 20,
}

SCHEMA = "market"


def _dbi() -> str:
    """只读连接串；不落库、不打印密钥。"""
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("DATABASE_URL 未设置；本脚本只读、不写，但需要目标库（通常是隔离库）。")
    return dsn


def _conn():
    dsn = _dbi()  # 先校验 DATABASE_URL，缺失即退出，不必 import sqlalchemy
    import sqlalchemy  # 延迟 import，纯离线脚本不依赖项目包

    return sqlalchemy.create_engine(dsn).connect()


def _calendar_open_days(conn, window: int) -> list[str]:
    """取最近 N 个交易日（含今日），交易日历优先，缺失时退化为自然日数。"""
    try:
        rows = conn.execute(
            f"select \"date\" from {SCHEMA}.trading_calendar where is_open "
            "order by \"date\" desc limit %s",
            (window,),
        ).fetchall()
        if rows:
            return [str(r[0]) for r in rows]
    except Exception:  # noqa: BLE001 - 交易日历不可用时退化为自然日，脚本照常只读
        pass
    today = date.today()
    return [str(today - timedelta(days=i)) for i in range(window)]


def scan_factor_values(conn, factor_id: str, days: list[str], min_days: int):
    """factor_values：distinct 股票数、每只最近窗口有效行 ≥ min_days 的只数。"""
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
    """feature_bars_daily.values JSONB 里的 f.main_net_20d 键覆盖。"""
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--factor-id", default=DEFAULTS["factor_id"])
    ap.add_argument("--min-stocks", type=int, default=DEFAULTS["min_stocks"])
    ap.add_argument("--min-days", type=int, default=DEFAULTS["min_days"])
    ap.add_argument("--window-days", type=int, default=DEFAULTS["window_days"])
    args = ap.parse_args()

    conn = _conn()
    try:
        days = _calendar_open_days(conn, args.window_days)
        fv = scan_factor_values(conn, args.factor_id, days, args.min_days)
        fb = scan_feature_bars(conn, "f.main_net_20d", days, args.min_days)
    finally:
        conn.close()

    # 就绪判据：F21 派生落点 feature_bars_daily 覆盖 ≥ min_stocks 只、每只 ≥ min_days 日。
    # factor_values 是内置因子对照，不作为就绪主判据（与 F21 不等价）。
    ready = fb["stocks_with_min_days"] >= args.min_stocks

    out = {
        "task": "T-R28",
        "signal": "ready" if ready else "not_ready",
        "thresholds": {"min_stocks": args.min_stocks, "min_days": args.min_days,
                       "window_days": args.window_days, "factor_id": args.factor_id},
        "window": {"first": days[-1], "last": days[0]},
        # F21 派生真正落点（就绪主判据）
        "f21_derived_feature_bars": fb,
        # 麦蕊内置因子对照（factor_id=main_20d_net，与 F21 不等价，只作对照）
        "mairui_builtin_factor_values": fv,
    }
    if ready:
        out["suggested_dispatch"] = (
            "W-01 v2 的 f.main_net_20d 覆盖已达阈值（feature_bars_daily 至少 "
            f"{args.min_stocks} 只、每只 ≥{args.min_days} 日）。建议派单：后端对 W-01 v2 "
            "重跑 G1–G6 门禁（不改变 F21 status 声明，只如实回填 G2 结果），并报架构师 "
            "确认 F21 单位与盘后定稿时间实测是否已由 T-B05 覆盖，再决定 declared→verified_doc。"
        )
    else:
        out["suggested_dispatch"] = (
            f"F21 派生覆盖不足（feature_bars_daily {fb['stocks_with_min_days']}/{args.min_stocks} 只达标），"
            "W-01 暂不可重跑门禁。继续积累或核实 T-B81/T-A19 F21 项实测。"
        )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
