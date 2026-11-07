# W-04 行业相对强度轮动 `sw_ind_rotation` — 知识卡 v1（T-R16 第二批）

> **当前状态：不可导入**（83a66cd 裁定后，本轮只写知识内容，不补 golden，不实现引擎）。下面的 expr 是设计层规则，**不是**当前可以导入的 schema；标“拟议”的字段、函数、语义在契约中还不存在，不代表现有能力或新的裁定。
> 初稿：DeepSeek（`team/reports/deepseek/T-R16/W-04.md`，未核实草稿），本文为研究员逐条复核后的版本。来源：通用规则组合，无外部来源。阈值均为 hypothesis，不含收益、回测或覆盖率数字。

## 1 身份
key `sw_ind_rotation`；category `momentum`；horizons `[swing]`；risk_level `normal`。（行业轮动在 category 枚举中没有对应取值，暂用 momentum，是否新增取值**待定**）

## 3 假设、反证与维度
- why_it_works（hypothesis）：行业相对强度有短期延续性；在强势行业中选择强于行业的个股，可以获得行业和个股两层动量。
- falsified_by：1) 样本外行业 RS 前 20% 组与后 20% 组的 10 日扣费超额没有差异；2) “个股强于行业”这一条件没有增量；3) 行业分类 PIT 变更后结论翻转。
- 维度：sector_market 为 core；technical 为 auxiliary；news 由 N-01 系统挂载。

## 4 标的范围
主板、创业板、科创板；上市满 120 日；20 日均额 ≥ `p.min_amount`。

## 5 数据（时点 / 单位 / 复权 / 预热）
| 键 | 频率 | 单位 | 复权 | 可得时点 | 状态 |
|---|---|---|---|---|---|
| f.ind_rs20 | 日 | pct | — | T 盘后 | 已注册；**指数来源待核实**（DAT-3） |
| f.sw_l1 | — | — | — | — | 来源待 T003（DAT-3） |
| 个股相对所属行业强度（拟议，FEA-7） | 日 | pct | qfq | T 盘后 | 未注册 |
| f.close_qfq | 日 | 元 | qfq@as_of | T 盘后 | 已注册 |
预热：20 根有效日 K（行业 RS 20 日）；不足时 `insufficient_data`，不产生候选。数据缺失：`f.sw_l1` 或 `f.ind_rs20` 缺失 → `insufficient_data`。

## 7 规则（设计层定稿；未定的部分标 拟议 / 待定）
| id | role | expr | 说明 |
|---|---|---|---|
| E1 | entry | `rank_pct(f.ind_rs20) >= p.ind_rank_min` | 行业强度截面分位；在个股截面上算，等价于按个股加权，**待定**是否应在行业截面上计算（ENG-5） |
| E2 | entry（拟议） | `f.stock_vs_ind_rs20 > 0` | 个股强于行业，FEA-7；原稿 `f.momentum_60d > f.ind_rs20 + 0.02` 的窗口（60 对 20）与单位都不一致，已删除 |
| E3 | entry | `f.close_qfq > ma(f.close_qfq, 20)` |  |
| F1 | filter | `f.amount_20d_avg >= p.min_amount and f.list_days >= p.min_list_days` |  |
| C1 | counter | `rank_pct(f.ind_rs20) < 0.5` | 行业强度掉到中位以下 |
| I1 | invalidation | `f.close_qfq < ma(f.close_qfq, 20) for 2 days` |  |
| X1 | exit（止损） | `f.close_qfq <= plan.entry_price_qfq * (1 - p.stop_pct)` |  |
| X2 | exit（跟踪） | `f.close_qfq <= ctx.highest_close_since_entry_qfq * (1 - p.trail_pct)` | ctx 键在 T-R15 中已裁定 |
| X3 | exit | `rank_pct(f.ind_rs20) < p.ind_rank_exit` |  |
| X4 | exit（时间） | `ctx.holding_days >= p.max_hold` |  |

## 8–10 执行与仓位
T 日盘后确认，T+1 开盘模拟入场；同一行业持仓上限属于组合层（ENG-3）。

## 11 验证（本轮不写 golden）
`fixture`、`trigger_stats`、`tracking_sim`；horizon_days [5,10,20]；`min_n=30`；行业分类用 PIT 版本。

## 14 不可执行原因
`LIMIT_LOCKED`（两个方向）、`SUSPENDED`、`T1_NOT_SELLABLE`、`KEY_DATA_MISSING`、`NEW_LISTING`、`ST_OR_DELISTING`。

## 15–16 环境与节奏
适用于 uptrend、range；每日或每周盘后扫描（待定）。

## 17 A股约束
T+1：当日买入的股份当日不可卖，触发退出时记 `T1_NOT_SELLABLE`，顺延到可卖日。涨跌停价按 market_rules 计算（主板 10%、创业板和科创板 20%、ST 5%；注册制新股上市前 5 日无涨跌幅限制），一字封板按执行层原因 `LIMIT_LOCKED` 处理（写明 direction），不写成 veto。停牌记 `SUSPENDED`，可交易性、ST、退市整理由 G-01 处理，风险公告由 N-01 处理（均由系统挂载，本卡不重复写）。整手：科创板 ≥ 200 股、超出部分按 1 股递增；其余板块 100 股整数倍；零股须一次性卖出。

## 18 成本与滑点（estimate）
佣金按用户费率，单笔最低 5 元，双边计；印花税仅卖出 0.05%；过户费 0.001%（双边）；滑点 `p.slippage_bp`（estimate）；冲击成本按 plan 2.13 分档（0/5/15/30/60bp），参与率 > 2% 标“容量受限”。

## 20 冲突
与 W-03 同向时并列；与 S-01 的行业分支共用 DAT-3。 一律并列展示，不合并结论。

## 22 参数（hypothesis；slippage_bp 为 estimate）
| 参数 | type | default | min | max | step |
|---|---|---|---|---|---|
| ind_rank_min | float | 0.8 | 0.6 | 0.95 | 0.05 |
| ind_rank_exit | float | 0.5 | 0.3 | 0.7 | 0.05 |
| stop_pct | float | 0.08 | 0.05 | 0.12 | 0.01 |
| trail_pct | float | 0.1 | 0.05 | 0.15 | 0.01 |
| max_hold | int | 20 | 10 | 40 | 5 |
| min_amount | float | 100000000.0 | 20000000.0 | 500000000.0 | 10000000.0 |
| min_list_days | int | 120 | 60 | 250 | 10 |
| slippage_bp | float | 10.0 | 0.0 | 50.0 | 1.0 |

## 23 当前不可导入原因与引擎需补能力
- DAT-3 `f.sw_l1`、`f.ind_rs20` 来源
- FEA-7 个股相对行业强度（未注册）
- ENG-5 分组截面函数（`rank_pct_in`，plan 已列为新增，实现状态待确认）
- ENG-3 行业上限（组合层）

## 复核记录（相对 DeepSeek 原稿）
1. 原稿 E2 窗口和单位不一致，已改为拟议特征
2. 原稿用 `ctx.last_price` 混用口径，已改正
3. 原稿把风险公告写成退出规则，已交给 N-01
4. 原稿“可算”评级下调：行业来源未核实
