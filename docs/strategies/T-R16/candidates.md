# T-R16 四周期候选清单 v1（16 项，每周期 4 项）

初稿来自 DeepSeek（`team/reports/deepseek/T-R16/00_candidates.md`，未核实草稿），本表为研究员逐条复核后的版本。所有阈值均为 hypothesis，不含收益或回测数据；来源都是通用规则组合，没有引用经过核实的外部文献。

“模板”一列的含义：
- **可**：所需特征均已在 feature_spec 注册，规则能用 DSL 白名单写出。
- **仅知识卡**：缺特征、缺算子、缺契约键，或数据未实测，只能 `post_close_stats`，不得宣称已就绪。

波段周期中已经正式交付的 W-01（`sw_ma_trend_pullback`）不计入本表，波段候选为 W-02 到 W-05。

| ID | key | 名称 | 周期 | 核心维度 | 数据状态 | 模板 | 缺口 / 待定 | 首批卡 |
|---|---|---|---|---|---|---|---|---|
| T-01 | t_vwap_revert | 均价偏离回归做T | intraday_t | technical | 分钟覆盖未核实；vwap 类单位待 T003 | 仅知识卡 | t_leg 配对写法；入场条件中 ctx 字段的用法；时刻参数类型 | ✅ T-01_t_vwap_revert.md |
| T-02 | t_spike_fade | 分时急拉回落减仓T | intraday_t | technical | 同 T-01 | 仅知识卡 | 同 T-01；缺日内动能衰竭的算子 | — |
| T-03 | t_open_gap | 开盘缺口回补T | intraday_t | technical | `f.open_qfq` **未注册**；开盘快照延迟未实测 | 仅知识卡 | 新特征申请 | — |
| T-04 | t_boll_revert | 布林外轨回归T | intraday_t | technical | 布林带位置特征（%b）**未注册**；日线布林与盘中价混用口径未定 | 仅知识卡 | 原稿称“只依赖已有特征”不成立，已改正 | — |
| S-01 | st_pullback_ma | 强势股缩量回踩 | short | technical | 日线已实测 | 可 | 回踩低点止损的 qfq 键（待定） | ✅ S-01_st_pullback_ma.md |
| S-02 | st_oversold_rebound | 超跌反弹 | short | technical | f.rsi14、f.volatility_20d 已注册 | 可 | 企稳确认的规则待写 | — |
| S-03 | st_limitup_relay | 涨停接力 | short | sentiment | 封单量、开板次数**未注册** | 仅知识卡 | 次日一字板买不进（`LIMIT_LOCKED`）偏差大 | — |
| S-04 | st_broken_board | 断板反包 | short | technical | f.limit_up_count_20d、f.is_limit_up_close 已注册 | 可 | 与 S-03 互斥 | — |
| W-02 | sw_breakout | 收敛放量突破 | swing | technical | 已注册 | 可 | 突破位的 qfq 键（待定） | ✅ W-02_sw_breakout.md |
| W-03 | sw_main_inflow | 主力净流入 | swing | capital | f.main_net_20d 来源**未实测** | 仅知识卡 | 来源核实 | — |
| W-04 | sw_ind_rotation | 行业相对强度轮动 | swing | sector_market | f.sw_l1、f.ind_rs20 来源待 T003 | 仅知识卡（暂） | 原稿标“可算”，已降级 | — |
| W-05 | sw_earnings_drift | 业绩预告漂移 | swing | fundamental | f.np_yoy_latest 为 declared，PIT 门禁未关 | 仅知识卡 | PIT 可见时点 | — |
| L-01 | lt_value | 低估值+质量护栏 | long | fundamental | F43–F46 为 declared，PIT 门禁未关 | 仅知识卡 | 组合层约束、null 语义 | ✅ L-01_lt_value.md |
| L-02 | lt_quality_growth | 质量成长 | long | fundamental | 同 L-01 | 仅知识卡 | 同 L-01 | — |
| L-03 | lt_dividend | 红利低估 | long | fundamental | 股息率特征**未注册** | 仅知识卡 | 新特征申请 | — |
| L-04 | lt_low_vol | 低波动 | long | technical | f.volatility_20d 已注册 | 可 | 再平衡与组合层契约缺失 | — |

统计：可进入模板 5 项（S-01、S-02、S-04、W-02、L-04；L-04 依赖组合层契约），仅知识卡 11 项。

## 复核改动
- key 统一为 `<周期前缀>_<名称>`，并与首批卡保持一致。
- T-04 的“仅依赖已有特征”不成立，已改为仅知识卡。
- W-04 由“可”降级为仅知识卡（行业特征来源待 T003）。
- L-03 原稿列的特征与红利逻辑无关，已改为缺股息率特征。

## 冲突与 A 股约束（并列展示，不合并）
- T-01 与 T-04 并列；S-03 与 S-04 在同一标的同日互斥；L-01 与 L-02 在选股层去重。
- 所有做T类策略**只能使用 T−1 日及以前形成的可卖底仓**，严禁当日新买入的股份当日卖出，也不得为了做T当日开新仓。
- 停牌和涨跌停按执行层原因处理（`SUSPENDED`、`LIMIT_LOCKED`），不写成 veto。
