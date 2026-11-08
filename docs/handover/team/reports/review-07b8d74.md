# 评审 07b8d74（T-B47-R10：整手/零股/单笔上限与 ETF 当日回转规则）

- **结论：通过（附 m）**。可以推送（meta-json 枚举失败是继承来的，和 83a031c 一起推）。
- ETF：`config/market_rules.yaml` 的 `t0_round_trip.data_source: null`，`unknown_category_default_t_plus: 1`，所有 ETF 都按 T+1，**没有无来源的 T+0**，所以不是 M。

## 问题
- m1 `market_rules/lots.py:164-199` 的 `fund_t_plus` 不检查 `data_source`：调用方传入 `etf_category` 或 `t0_override` 时会返回 0。目前还没有调用方；裁定要求以 `data_source` 非空为前提（plan 2.13 新增行）——后端
- m2 `check_qty` 还没有调用方
- m3 `check_qty` 返回的 `details.max_qty` 不在契约 #14 的键里——后端去掉它，或者报给架构师补进契约
- m4 测试员的 market_rules 快照要更新；plan 6.1 的 market_rules 配置块要同步新键（odd_lot_sell_all、单笔上限、t0_round_trip）——后端同步配置块，架构师下次改 plan 时一并合入

## 测试
ruff、mypy、静态检查通过。
