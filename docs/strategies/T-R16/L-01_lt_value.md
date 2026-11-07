# L-01 低估值+质量护栏 `lt_value` — 知识卡 v1（T-R16 首批）

> **当前状态：不可导入**（83a66cd 裁定：本批不补卡/golden，实现 MVP 后再议；文中做T配对、null 与组合约束、新特征等“待定”项一律暂停）。下文“可进入模板”仅表示未来潜力。

> **标签：仅知识卡**（PIT 切换门禁尚未关闭，**不得宣称已就绪**）。F43–F46 已在 feature_spec 登记，但 PIT 的可见时点和截面覆盖率（§7A 的 S1/S2 验收）**未通过实测**，状态为 declared；门禁关闭前只能 `post_close_stats`，不产生候选。初稿来自 DeepSeek（`team/reports/deepseek/T-R16/L-01.md`，未核实草稿），本文为复核后版本。阈值均为 hypothesis；来源：通用规则组合，无外部来源；不含收益数字。

## 1 身份
key `lt_value`；category `value`；horizons `[long]`（月度再平衡，持有 ≥ 3 个月）。

## 3 假设与维度
- why_it_works（hypothesis）：在同一行业内，估值处于低分位、同时 ROE 与现金流质量达标的股票，被错杀的概率高于价值陷阱，长期均值回归带来超额收益。
- falsified_by：① PIT 门禁关闭后，样本外滚动 12 个月的月度组合扣费超额中位数 ≤ 0；② 低估值组与中性估值组的未来 6 个月 ROE 变化无差异（说明质量护栏无效）；③ 组合中个股因 N-01 或 ST 退出的比例高于全市场基准。
- 维度：fundamental 为 core；sector_market 为 auxiliary（同行业分组）；news 为 veto（N-01，系统挂载）；technical 不参与。

## 5 数据（PIT，按 feature_spec v1.1.11）
| 键 | 单位 | 状态 |
|---|---|---|
| f.pe_ttm_pit_ind_pct（F43） | 0–1 | declared，PIT 未实测 |
| f.pb_pit_ind_pct（§7A） | 0–1 | declared，口径按 plan 2.12.1 |
| f.roe_ttm_pit（F44） | pct（8 = 8%） | declared |
| f.ocf_to_np_ttm_pit（F45） | 比值 | declared；归母净利润 ≤ 0 时为 null |
| f.debt_ratio_pit（F46） | 比值；银行和保险为 null | declared |
| f.sw_l1（F26） | — | 来源待 T003 |
原稿使用的 `f.debt_ratio_pit_ind_pct` **未注册**，已删除；如需要，作为新特征申请（**待定**）。

## 7 规则
| id | role | expr |
|---|---|---|
| E1 | entry | `f.pe_ttm_pit_ind_pct <= p.val_pct and f.pb_pit_ind_pct <= p.val_pct` |
| E2 | entry | `f.roe_ttm_pit >= p.roe_min` |
| E3 | entry | `f.ocf_to_np_ttm_pit >= p.ocf_min` |
| F1 | filter | `f.list_days >= 250` |
| F2 | filter | `f.debt_ratio_pit <= p.debt_max`（银行和保险为 null 时**待定**：须放行而不是判为缺失，DSL 的 null 语义需要架构师确认） |
| C1 | counter | `f.roe_ttm_pit < p.roe_min`（质量跌破，提示价值陷阱） |
| I1 | invalidation | `f.pe_ttm_pit_ind_pct > 0.5 or f.pb_pit_ind_pct > 0.5`（估值回到中性） |
| X1 | exit（止损） | `f.close_qfq <= ctx.cost_price_qfq * (1 - p.stop_pct)` |
| X2 | exit | `f.roe_ttm_pit < p.roe_exit or f.ocf_to_np_ttm_pit < p.ocf_exit` |
| X3 | exit | `f.pe_ttm_pit_ind_pct > p.exit_val_pct` |
- 原稿的改动：
  - 原稿 X3 用 `ctx.last_price` 与 qfq 成本比较，口径混用 → 改为 `f.close_qfq`。
  - 原稿 `N01_veto()`、`H01_state`、`count_holding*()`、`in_top30_screen` 都不在 DSL 白名单内：N-01 和 H-01 由系统挂载；行业 ≤ 5 只、组合 ≤ 30 只属于组合层的约束，不是卡内规则，**待定**（组合构造契约缺失）。
  - 原稿 X5 把停牌和跌停挂起写成规则 → 改为执行层原因。
- 财报季切换：只用公告日（`f.*_visible_at` / basis）≤ as_of 的报告期，不得用报告期末日对齐。

## 8–10 执行与仓位
每月第一个交易日盘后出 screen，次日开盘模拟成交；等权，单票上限按 RC2 执行。

## 11 验证
门禁关闭前只做 `fixture` 和 `post_close_stats`；关闭后做 walk-forward（训练 36 个月 / 测试 12 个月，月度滚动），`min_n` 为 24 个月度截面，基准用中证全指；年度换手和容量须一并报告。

## 14 不可执行原因
`KEY_DATA_MISSING`（PIT 字段为 null 或门禁未关闭）、`SUSPENDED`、`LIMIT_LOCKED`（sell 方向写 `direction=sell`）、`T1_NOT_SELLABLE`、`ST_OR_DELISTING`。

## 15–17 环境 / 节奏 / A股约束
不依赖 G-02 择时，`downtrend` 时只提示、不否决（hypothesis）。月度节奏。T+1、涨跌停、整手（科创板 ≥ 200 股、按 1 股递增）按 market_rules 处理。

## 18 成本（estimate）
佣金按用户费率，单笔最低 5 元；印花税仅卖出 0.05%；过户费 0.001%；`slippage_bp` 10；冲击成本按 plan 2.13 分档。

## 20 冲突
与 H-01 的 exit 并列展示；与短线、波段卡在同一标的上方向相反时并列展示，不合并。

## 22 参数（hypothesis）
| 参数 | type | default | min | max | step |
|---|---|---|---|---|---|
| val_pct | float | 0.3 | 0.1 | 0.5 | 0.05 |
| roe_min | float | 8.0 | 5.0 | 15.0 | 1.0 |
| ocf_min | float | 0.8 | 0.5 | 1.2 | 0.1 |
| debt_max | float | 0.7 | 0.5 | 0.9 | 0.05 |
| roe_exit | float | 6.0 | 3.0 | 10.0 | 1.0 |
| ocf_exit | float | 0.6 | 0.3 | 1.0 | 0.1 |
| exit_val_pct | float | 0.7 | 0.5 | 0.9 | 0.05 |
| stop_pct | float | 0.15 | 0.10 | 0.30 | 0.05 |

## 复核记录
key 与 name 已改正；删除未注册特征 1 个；删除非白名单函数 5 个；修正口径混用 1 处；组合层约束与 null 语义列为待定。
