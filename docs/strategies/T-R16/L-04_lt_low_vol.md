# L-04 低波动 `lt_low_vol` — 知识卡 v1（T-R16 第二批）

> **当前状态：不可导入**（83a66cd 裁定后，本轮只写知识内容，不补 golden，不实现引擎）。下面的 expr 是设计层规则，**不是**当前可以导入的 schema；标“拟议”的字段、函数、语义在契约中还不存在，不代表现有能力或新的裁定。
> 初稿：DeepSeek（`team/reports/deepseek/T-R16/L-04.md`，未核实草稿），本文为研究员逐条复核后的版本。来源：通用规则组合，无外部来源。阈值均为 hypothesis，不含收益、回测或覆盖率数字。

## 1 身份
key `lt_low_vol`；category `low_vol`；horizons `[long]`；risk_level `normal`。

## 3 假设、反证与维度
- why_it_works（hypothesis）：低波动股票的风险调整后收益长期不差于高波动股票（低波动异象；本卡没有引用核实过的文献）。
- falsified_by：1) 样本外月度截面低波动组的夏普比率不高于全市场；2) 低波动组超额全部来自行业暴露（如银行），行业中性后消失；3) 换手成本扣除后超额 ≤ 0。
- 维度：technical（波动）为 core；sector_market 为 auxiliary（行业分散）；news 由 N-01 系统挂载。

## 4 标的范围
全 A（不含北交所）；上市满 120 日；20 日均额 ≥ `p.min_amount`。

## 5 数据（时点 / 单位 / 复权 / 预热）
| 键 | 频率 | 单位 | 复权 | 可得时点 | 状态 |
|---|---|---|---|---|---|
| f.volatility_20d | 日 | ratio | qfq | T 盘后 | 已注册 |
| f.amount_20d_avg | 日 | CNY | none | T 盘后 | 已注册 |
| f.sw_l1 | — | — | — | — | 来源待 T003（DAT-3），只用于行业分散 |
预热：20 根有效日 K（≥15）；不足时 `insufficient_data`，不产生候选。数据缺失：波动率缺失 → `insufficient_data`。

## 7 规则（设计层定稿；未定的部分标 拟议 / 待定）
| id | role | expr | 说明 |
|---|---|---|---|
| E1 | entry | `rank_pct(f.volatility_20d) <= p.vol_pct` | 全市场截面 |
| F1 | filter | `f.amount_20d_avg >= p.min_amount and f.list_days >= p.min_list_days` |  |
| C1 | counter | `rank_pct(f.volatility_20d) > 0.5` | 波动上升 |
| I1 | invalidation | `f.amount_20d_avg < p.min_amount * 0.6` | 流动性下降 |
| X1 | exit（止损） | `f.close_qfq <= plan.entry_price_qfq * (1 - p.stop_pct)` | 原稿用 `ctx.last_price`，已改 |
| X2 | exit | `rank_pct(f.volatility_20d) > p.vol_exit` |  |
- 原稿 `rank_pct_in(f.sw_l1) <= 0.2` 的参数语义错误（应为 `rank_pct_in(x, group_key)`），行业分散属于组合层（ENG-3、ENG-5）。
- 原稿 `f.is_suspended == 1 for 5 days` 作为失效条件：停牌由 G-01 和执行层处理，已删除。

## 8–10 执行与仓位
每月第一个交易日盘后出 screen，次日开盘模拟成交；等权，单票上限按 RC2；行业上限与 top-N 属于组合层（ENG-3，拟议）。

## 11 验证（本轮不写 golden）
walk-forward 月度截面，`min_n` 为 24；同时报告行业中性前后的结果。

## 14 不可执行原因
`LIMIT_LOCKED`（两个方向）、`SUSPENDED`、`T1_NOT_SELLABLE`、`KEY_DATA_MISSING`、`NEW_LISTING`、`ST_OR_DELISTING`。

## 15–16 环境与节奏
不择时；月度节奏。

## 17 A股约束
T+1：当日买入的股份当日不可卖，触发退出时记 `T1_NOT_SELLABLE`，顺延到可卖日。涨跌停价按 market_rules 计算（主板 10%、创业板和科创板 20%、ST 5%；注册制新股上市前 5 日无涨跌幅限制），一字封板按执行层原因 `LIMIT_LOCKED` 处理（写明 direction），不写成 veto。停牌记 `SUSPENDED`，可交易性、ST、退市整理由 G-01 处理，风险公告由 N-01 处理（均由系统挂载，本卡不重复写）。整手：科创板 ≥ 200 股、超出部分按 1 股递增；其余板块 100 股整数倍；零股须一次性卖出。

## 18 成本与滑点（estimate）
佣金按用户费率，单笔最低 5 元，双边计；印花税仅卖出 0.05%；过户费 0.001%（双边）；滑点 `p.slippage_bp`（estimate）；冲击成本按 plan 2.13 分档（0/5/15/30/60bp），参与率 > 2% 标“容量受限”。

## 20 冲突
与 L-03 红利可能重叠（银行）；去重属于 ENG-3。 一律并列展示，不合并结论。

## 22 参数（hypothesis；slippage_bp 为 estimate）
| 参数 | type | default | min | max | step |
|---|---|---|---|---|---|
| vol_pct | float | 0.3 | 0.1 | 0.5 | 0.05 |
| vol_exit | float | 0.7 | 0.5 | 0.9 | 0.05 |
| stop_pct | float | 0.15 | 0.08 | 0.25 | 0.01 |
| min_amount | float | 50000000.0 | 10000000.0 | 500000000.0 | 10000000.0 |
| min_list_days | int | 120 | 60 | 250 | 10 |
| slippage_bp | float | 10.0 | 0.0 | 50.0 | 1.0 |

## 23 当前不可导入原因与引擎需补能力
- ENG-3 月度调度、top-N、行业分散
- ENG-5 分组截面函数
- DAT-3 行业来源

## 复核记录（相对 DeepSeek 原稿）
1. `rank_pct_in` 参数用法已改正，并移到组合层
2. 口径混用已改正
3. 停牌失效条件已删除
4. 原稿“可进模板”下调：缺组合层
