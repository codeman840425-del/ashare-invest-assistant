# T-R15b 补 epistemic 参数认知类型（策略研究员，2026-11-07）
依据：reports/T-B71.md 第 7–16 行；plan 2.5.14 B 节（epistemic 至少标出 hypothesis 与各阈值类型）。
改动：H-01 新增 params_schema.reclaim_days: hypothesis；W-01 新增 params_schema.ma_fast: hypothesis、params_schema.ma_slow: hypothesis。理由：20/60 均线周期和 2 日确认都是经验设定，无实证依据，不是 fact，也不是由数据估算的 estimate。其余未改动。
校验：两张卡的 params_schema 全部参数都有 epistemic 条目（缺失 0）；check_T-R15 PASS；T-R15_golden.json 未变（md5 89ad2c50…，golden 期望不变）。
已由架构师本地提交 d783fdf（密钥扫描 0 阻断）；原待提交（仓库内 4 个，逐文件暂存，不含 docs/strategies/T-R16/）：
 docs/strategies/cards/hold_risk_monitor.md
 docs/strategies/cards/sw_ma_trend_pullback.md
 docs/strategies/golden/hold_risk_monitor.card.tmpl
 docs/strategies/golden/sw_ma_trend_pullback.card.tmpl
T-R16 暂停：DeepSeek 已完成 5 次调用，草稿保存在 reports/deepseek/T-R16/；docs/strategies/T-R16/ 下只有 candidates.md 初版，未完成，暂不提交。
